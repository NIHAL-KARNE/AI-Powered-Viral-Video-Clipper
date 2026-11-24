from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from .transcribe import content_tokens, tokenize

HOOK = set("""what why how when who imagine listen wait stop actually honestly seriously
surprising shocking unbelievable crazy insane nobody everyone most people truth secret mistake
problem question biggest best worst never always first last did know remember""".split())
SURPRISE = set("""actually surprised surprising shock shocked unbelievable crazy insane wild
never suddenly wait whoa wow unexpected twist turns out literally plot""".split())
CONTROVERSY = set("""wrong hate disagree controversial unpopular overrated scam lie lies
argue debate stupid terrible awful against banned illegal refuse problem fail""".split())
EMOTION = set("""love loved cried cry scared afraid happy angry hurt amazing beautiful terrible
heart proud grateful sad shocked excited painful emotional trauma fear hope lonely lost""".split())
STORY = set("""story happened one day then after suddenly ended ended turned realized remember
years months later finally start began felt""".split())
INSIGHT = set("""because reason lesson learn learned mistake advice tip secret strategy
framework rule principle means important key value better best""".split())
LAUGH = set("""haha lol funny joke laughed laughing hilarious kidding""".split())
FILLER = set("""um uh like actually basically literally you know i mean sort of kinda right okay""".split())
REVEAL = set("""but however although except instead until unless because therefore so""".split())

CATEGORIES = {
    "revelation": "Unexpected revelation",
    "funny": "Funny moment",
    "controversial": "Controversial take",
    "emotional": "Emotional story",
    "insight": "Insight & advice",
    "high_energy": "High-energy moment",
    "story": "Storytelling",
    "fact": "Interesting fact",
}


def _split_sentences(segments: list[dict]) -> list[dict]:
    """Split Whisper segments into sentence units on terminal punctuation."""
    units: list[dict] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            text = seg["text"].strip()
            if text:
                units.append({"start": seg["start"], "end": seg["end"], "text": text, "words": []})
            continue
        buf: list[dict] = []
        for w in words:
            buf.append(w)
            raw = w["word"]
            if re.search(r"[.!?][\"')\]]*$", raw) and len(buf) >= 3:
                text = " ".join(x["word"] for x in buf).strip()
                if text:
                    units.append({
                        "start": round(buf[0]["start"], 3),
                        "end": round(buf[-1]["end"], 3),
                        "text": text,
                        "words": [dict(x) for x in buf],
                    })
                buf = []
        if buf:
            text = " ".join(x["word"] for x in buf).strip()
            if text:
                units.append({
                    "start": round(buf[0]["start"], 3),
                    "end": round(buf[-1]["end"], 3),
                    "text": text,
                    "words": [dict(x) for x in buf],
                })
    # merge tiny fragments into neighbours
    merged: list[dict] = []
    for u in units:
        if merged and (u["end"] - u["start"] < 0.55 or len(tokenize(u["text"])) <= 2):
            prev = merged[-1]
            prev["end"] = u["end"]
            prev["text"] = f"{prev['text']} {u['text']}".strip()
            prev["words"].extend(u["words"])
        else:
            merged.append(u)
    return [u for u in merged if u["end"] > u["start"]]


def audio_features(wav_path) -> dict:
    """RMS energy, spectral centroid and silence map at 100ms resolution."""
    from .media import read_wav

    samples, sr = read_wav(wav_path)
    if len(samples) == 0:
        return {"hop": 0.1, "rms": np.zeros(1, dtype=np.float32), "centroid": np.zeros(1, dtype=np.float32), "sr": sr}
    hop = max(int(sr * 0.1), 1)
    n = len(samples) // hop
    trimmed = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(trimmed ** 2, axis=1)).astype(np.float32)
    window = np.hanning(hop).astype(np.float32)
    spec = np.abs(np.fft.rfft(trimmed * window, axis=1)).astype(np.float32)
    freqs = np.fft.rfftfreq(hop, 1 / sr).astype(np.float32)
    mag = spec.sum(axis=1) + 1e-9
    centroid = ((spec * freqs).sum(axis=1) / mag).astype(np.float32)
    return {"hop": hop / sr, "rms": rms, "centroid": centroid, "sr": sr}


def _window_audio(feats: dict, start: float, end: float) -> dict:
    hop = feats["hop"]
    rms, centroid = feats["rms"], feats["centroid"]
    i0 = max(int(start / hop), 0)
    i1 = min(int(end / hop) + 1, len(rms))
    if i1 <= i0:
        return {"loudness": 0.0, "dyn": 0.0, "silence": 0.0, "pitch_var": 0.0, "peak": 0.0}
    seg = rms[i0:i1]
    c = centroid[i0:i1]
    med = float(np.median(rms)) + 1e-6
    loudness = float(np.clip(np.percentile(seg, 85) / 0.16, 0, 1))
    dyn = float(np.clip(np.std(seg) / med, 0, 2))
    silence = float(np.mean(seg < max(med * 0.28, 0.004)))
    pitch_var = float(np.clip(np.std(c) / (np.mean(c) + 1e-6), 0, 1.5))
    peak = float(np.clip(np.percentile(seg, 99) / 0.30, 0, 1))
    return {"loudness": loudness, "dyn": dyn, "silence": silence, "pitch_var": pitch_var, "peak": peak}


def enrich_units(units: list[dict], feats: dict, frames: dict) -> list[dict]:
    frame_list = frames.get("frames") or []
    for u in units:
        toks = tokenize(u["text"])
        content = [t for t in toks if t not in FILLER]
        dur = max(u["end"] - u["start"], 0.01)
        u["tokens"] = toks
        u["content"] = content
        u["wps"] = round(len(content) / dur, 2)
        u["audio"] = _window_audio(feats, u["start"], u["end"])
        # visual activity for this sentence
        if frame_list:
            near = [f for f in frame_list if u["start"] - 1 <= f["t"] <= u["end"] + 1]
            if near:
                u["visual_motion"] = round(float(np.mean([f["motion"] for f in near])), 3)
                faces = [f for f in near if f.get("faces")]
                u["face_ratio"] = round(len(faces) / len(near), 2)
                u["brightness"] = round(float(np.mean([f["brightness"] for f in near])), 3)
            else:
                u["visual_motion"], u["face_ratio"], u["brightness"] = 0.0, 0.0, 0.5
        else:
            u["visual_motion"], u["face_ratio"], u["brightness"] = 0.0, 0.0, 0.5
        u["exclaim"] = u["text"].count("!")
        u["question"] = u["text"].count("?")
        u["numbers"] = len(re.findall(r"\b\d[\d,.]*%?\b", u["text"]))
        u["caps"] = sum(1 for w in re.findall(r"\b[A-Z]{3,}\b", u["text"]))
        u["filler_ratio"] = round(sum(1 for t in toks if t in FILLER) / max(len(toks), 1), 2)
    return units


def _lex(text_tokens: list[str], vocab: set[str]) -> int:
    return sum(1 for t in text_tokens if t in vocab)


def document_stats(units: list[dict]) -> dict:
    all_tokens = [t for u in units for t in u["content"]]
    counts = Counter(all_tokens)
    top = [w for w, _ in counts.most_common(40)]
    rarity = {}
    total = max(len(all_tokens), 1)
    for w, c in counts.items():
        rarity[w] = 1 - (c / total)
    return {"counts": counts, "top": set(top), "rarity": rarity}


def score_window(units: list[dict], start_idx: int, end_idx: int, duration: float,
                 stats: dict, total_units: int) -> dict:
    window = units[start_idx:end_idx + 1]
    text = " ".join(u["text"] for u in window)
    toks = [t for u in window for t in u["tokens"]]
    content = [t for u in window for t in u["content"]]
    content_set = set(content)
    first = window[0]
    last = window[-1]
    total_sec = max(last["end"] - first["start"], 0.01)

    # --- hook strength (first sentence / first ~4s) ---
    hook_units = [u for u in window if u["start"] - first["start"] < 4.5] or [first]
    hook_text = " ".join(u["text"] for u in hook_units)
    hook_toks = [t for t in tokenize(hook_text) if t not in FILLER]
    hook = 26.0
    hook += min(_lex(hook_toks, HOOK) * 7.0, 26)
    hook += min(len(re.findall(r"\?", hook_text)) * 10, 16)
    hook += min(len(re.findall(r"\b\d[\d,.]*%?\b", hook_text)) * 7, 14)
    hook += 12 if re.search(r"\b(you|your|we|our)\b", hook_text, re.I) else 0
    hook += 8 if re.match(r"^(so|and|but|because|the|this|it|that)\b", first["text"], re.I) is None else -4
    hook += min(first["exclaim"] * 5, 10)
    hook = float(np.clip(hook, 0, 100))

    # --- emotional intensity ---
    emo = _lex(toks, EMOTION)
    emotional = 28.0
    emotional += min(emo * 8, 26)
    emotional += min(sum(u["exclaim"] for u in window) * 5, 12)
    emotional += min(_lex(toks, LAUGH) * 12, 18)
    emotional += min(sum(u["audio"]["dyn"] for u in window) / len(window) * 14, 20)
    emotional += min(sum(u["audio"]["peak"] for u in window) / len(window) * 14, 12)
    emotional += 8 if any(u["question"] for u in window) else 0
    emotional = float(np.clip(emotional, 0, 100))

    # --- novelty / surprise ---
    novelty = 26.0
    novelty += min(_lex(toks, SURPRISE) * 9, 24)
    novelty += min(sum(u["numbers"] for u in window) * 5, 15)
    novelty += min(len(content_set) / max(len(content), 1) * 22, 22)
    rare_score = float(np.mean([stats["rarity"].get(t, 0.8) for t in content])) if content else 0.5
    novelty += rare_score * 16
    novelty = float(np.clip(novelty, 0, 100))

    # --- audience relevance (topic density + universal topics) ---
    relevance = 30.0
    top_hits = sum(1 for t in content if t in stats["top"])
    relevance += min(top_hits / max(len(content), 1) * 45, 40)
    relevance += 10 if any(t in {"money", "business", "life", "love", "health", "people", "work", "mind", "time", "world"} for t in content) else 0
    relevance += min(len(content) / 40 * 12, 12)
    relevance = float(np.clip(relevance, 0, 100))

    # --- standalone context ---
    standalone = 58.0
    if re.match(r"^(and|but|so|because|which|that|then|also|or|it|this|they|he|she)\b", first["text"], re.I):
        standalone -= 18
    if not re.search(r"[.!?][\"')\]]*$", last["text"]):
        standalone -= 10
    if re.search(r"[.!?][\"')\]]*$", first["text"]):
        standalone += 6
    if duration < 18:
        standalone -= 6
    if duration > 75:
        standalone -= 4
    standalone += min(len(content_set) / 18 * 12, 12)
    standalone += 5 if 22 <= duration <= 60 else 0
    standalone = float(np.clip(standalone, 0, 100))

    # --- storytelling ---
    story = 28.0
    story += min(_lex(toks, STORY) * 8, 26)
    story += min(_lex(toks, REVEAL) * 4, 14)
    story += 10 if re.search(r"\b(when|after|before|once|until)\b", text, re.I) else 0
    story += 8 if re.search(r"\b(i|we|he|she)\b", text, re.I) else 0
    story += 8 if _lex(toks, INSIGHT) else 0
    story = float(np.clip(story, 0, 100))

    # --- retention: pacing, energy arc, punchline ---
    wps = len(content) / total_sec
    silence = float(np.mean([u["audio"]["silence"] for u in window]))
    energies = [u["audio"]["loudness"] for u in window]
    arc = (float(np.mean(energies[-max(len(energies) // 3, 1):])) -
           float(np.mean(energies[:max(len(energies) // 3, 1)]))) if len(energies) > 1 else 0.0
    retention = 34.0
    retention += max(0.0, min((wps - 1.8) / 2.0, 1.0)) * 22
    retention -= min(silence * 40, 16)
    retention += max(0.0, min(arc * 60, 16))
    retention += 10 if re.search(r"[.!?][\"')\]]*$", last["text"]) else 0
    retention += min(_lex(tokenize(last["text"]), SURPRISE | EMOTION | INSIGHT) * 6, 14)
    retention -= min(sum(1 for u in window if u["filler_ratio"] > 0.2) * 4, 12)
    retention = float(np.clip(retention, 0, 100))

    # --- visual/audio liveliness ---
    visual = float(np.mean([u["visual_motion"] for u in window])) if window else 0
    faces = float(np.mean([u["face_ratio"] for u in window])) if window else 0
    energy = float(np.clip(visual * 160 + faces * 30, 0, 100))

    weights = {
        "hook": 0.22, "emotion": 0.18, "novelty": 0.15,
        "relevance": 0.11, "standalone": 0.13, "story": 0.11, "retention": 0.10,
    }
    parts = {
        "hook": hook, "emotion": emotional, "novelty": novelty, "relevance": relevance,
        "standalone": standalone, "story": story, "retention": retention,
    }
    base = sum(parts[k] * w for k, w in weights.items())
    base += energy * 0.04
    base -= min(first["filler_ratio"] * 12, 6)
    score = float(np.clip(base, 0, 99))

    # --- category ---
    counts = {
        "revelation": _lex(toks, SURPRISE) * 1.3 + sum(u["numbers"] for u in window) * 0.8,
        "funny": _lex(toks, LAUGH) * 1.8 + sum(u["exclaim"] for u in window) * 0.8,
        "controversial": _lex(toks, CONTROVERSY) * 1.4,
        "emotional": _lex(toks, EMOTION) * 1.1 + float(np.mean([u["audio"]["dyn"] for u in window])) * 2,
        "insight": _lex(toks, INSIGHT) * 1.2,
        "high_energy": float(np.mean([u["audio"]["loudness"] for u in window])) * 2 + energy * 0.01,
        "story": _lex(toks, STORY) * 1.1,
        "fact": sum(u["numbers"] for u in window) * 1.2,
    }
    category = max(counts, key=counts.get) if max(counts.values()) > 0 else "story"
    if category == "fact" and counts["revelation"] >= counts["fact"]:
        category = "revelation"
    if category == "story" and counts["high_energy"] > counts["story"] * 1.3:
        category = "high_energy"

    reasons = _reasons(parts, first, window, energy, silence, wps)
    return {
        "score": round(score, 1),
        "components": {k: round(v, 1) for k, v in parts.items()},
        "energy": round(energy, 1),
        "category": category,
        "category_label": CATEGORIES.get(category, "Highlight"),
        "reasons": reasons,
        "start_unit": start_idx,
        "end_unit": end_idx,
        "start": round(first["start"], 3),
        "end": round(last["end"], 3),
        "duration": round(total_sec, 2),
        "text": text.strip(),
        "words": [w for u in window for w in u["words"]],
        "speaker": "Speaker 1",
        "audio_stats": {
            "silence": round(silence, 3),
            "wps": round(wps, 2),
            "loudness": round(float(np.mean([u["audio"]["loudness"] for u in window])), 3),
        },
        "visual_stats": {"motion": round(visual, 3), "face_ratio": round(faces, 2)},
    }


def _reasons(parts, first, window, energy, silence, wps) -> list[str]:
    ordered = sorted(parts.items(), key=lambda kv: -kv[1])
    labels = {
        "hook": "A strong opening line grabs attention immediately",
        "emotion": "High emotional intensity and vocal dynamics",
        "novelty": "Surprising or unexpected information",
        "relevance": "Topic is broadly relevant to short-form audiences",
        "standalone": "Makes sense without extra context",
        "story": "Contains a clear narrative arc",
        "retention": "Fast pacing keeps viewers watching",
    }
    out = [labels[k] for k, v in ordered[:3] if v >= 45]
    if silence < 0.12:
        out.append("Almost no dead air — continuous, watchable delivery")
    if 2.0 <= wps <= 4.2:
        out.append(f"Conversational pace of {wps:.1f} words/sec")
    if energy > 45:
        out.append("Visual activity keeps the frame interesting")
    if not out:
        out.append("Coherent, self-contained moment with a clear beginning and end")
    return out[:4]


def build_candidates(units: list[dict], stats: dict, targets: list[float],
                     min_dur: float, max_dur: float, total_units: int) -> list[dict]:
    """Sentence-aligned candidate windows, scored with full model."""
    candidates: list[dict] = []
    for i in range(total_units):
        acc_start = units[i]["start"]
        for target in targets:
            j = i
            while j < total_units and (units[j]["end"] - acc_start) < target:
                j += 1
            if j >= total_units:
                continue
            dur = units[j]["end"] - units[i]["start"]
            if dur < min_dur or dur > max_dur:
                continue
            cand = score_window(units, i, j, dur, stats, total_units)
            if cand["duration"] < min_dur or cand["duration"] > max_dur:
                continue
            candidates.append(cand)
    return candidates


def pick_diverse(candidates: list[dict], max_clips: int, overlap_ratio: float = 0.45) -> list[dict]:
    """Greedy by score with time-overlap suppression and category spread."""
    pool = sorted(candidates, key=lambda c: -c["score"])
    picked: list[dict] = []
    for cand in pool:
        if len(picked) >= max_clips:
            break
        clash = False
        for p in picked:
            overlap = min(p["end"], cand["end"]) - max(p["start"], cand["start"])
            if overlap > 0 and overlap / min(p["duration"], cand["duration"]) > overlap_ratio:
                clash = True
                break
        if clash:
            continue
        if picked and cand["score"] < picked[-1]["score"] - 32:
            break
        picked.append(cand)
    return picked


def rescale_scores(clips: list[dict]) -> list[dict]:
    """Map raw model output onto a readable 40-96 band without inventing rank order."""
    if not clips:
        return clips
    values = [c["score"] for c in clips]
    lo, hi = min(values), max(values)
    for c in clips:
        if hi - lo < 0.5:
            c["score"] = round(min(96, max(40, c["score"] + 8)), 1)
        else:
            norm = (c["score"] - lo) / (hi - lo)
            c["score"] = round(40 + norm * 52, 1)
    return clips


def make_titles(text: str, category: str) -> dict:
    """Extractive title suggestions + hashtags. No invented claims."""
    from .transcribe import content_tokens

    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sentences = [s for s in raw_sentences if len(tokenize(s)) >= 3] or [text]
    kw = Counter(content_tokens(text))
    keys = [w for w, _ in kw.most_common(8)]
    cat_label = CATEGORIES.get(category, "Highlight")
    first = sentences[0]
    title_candidates: list[str] = []

    def shorten(s: str, limit: int = 68) -> str:
        s = re.sub(r"\s+", " ", s).strip(" .,;:-")
        if len(s) <= limit:
            return s
        cut = s[:limit]
        return cut.rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"

    title_candidates.append(shorten(first))
    if len(sentences) > 1:
        title_candidates.append(shorten(sentences[-1]))
    if keys:
        title_candidates.append(shorten(f"The truth about {keys[0]}"))
    if len(keys) > 1:
        title_candidates.append(shorten(f"{keys[0].title()} vs {keys[1].title()}: what happened next"))
    title_candidates.append(shorten(f"{cat_label}: {first}"))
    if len(sentences) > 2:
        title_candidates.append(shorten(sentences[len(sentences) // 2]))

    seen, titles = set(), []
    for t in title_candidates:
        norm = t.lower()
        if norm and norm not in seen and len(t) > 8:
            seen.add(norm)
            titles.append(t)
        if len(titles) >= 5:
            break

    hashtags = [f"#{re.sub(r'[^a-z0-9]', '', k)}" for k in keys[:5] if len(k) > 3]
    if len(hashtags) < 3:
        hashtags += ["#shorts", "#reels", "#fyp"]
    hashtags = list(dict.fromkeys(hashtags))[:6]

    hook = first
    if len(tokenize(hook)) > 16:
        hook = " ".join(hook.split()[:16]).rstrip(" ,;:") + "…"

    description = re.sub(r"\s+", " ", text).strip()
    if len(description) > 220:
        description = description[:217].rsplit(" ", 1)[0] + "…"

    return {
        "titles": titles,
        "hook": hook,
        "hashtags": hashtags,
        "description": description,
        "keywords": keys[:8],
    }
