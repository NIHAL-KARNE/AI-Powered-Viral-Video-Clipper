"""Sentence-boundary aware clip selection.

The old approach cut windows at fixed durations, which produced clips starting
mid-sentence ("up because we're going to get back") and running far too long for
short-form. This module rebuilds selection around *speech units*:

1. Flatten words into sentence groups with punctuation-aware boundaries.
2. Group sentences into "beat" units (a complete thought).
3. Build candidate clips that always start at a sentence start and end at a
   sentence end, within a target duration band.
4. Score each candidate, then greedily pick non-overlapping, category-diverse clips.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .analysis import (
    CONTROVERSY,
    EMOTION,
    FILLER,
    HOOK,
    INSIGHT,
    LAUGH,
    REVEAL,
    STORY,
    SURPRISE,
    score_window,
)
from .titles import BARE_QUESTION  # noqa: F401  (re-exported for title logic reuse)
from .transcribe import content_tokens, tokenize

SENT_END = re.compile(r"[.!?][\"')\]]*$")


def _words(segments: list[dict]) -> list[dict]:
    out: list[dict] = []
    for seg in segments:
        for w in seg.get("words") or []:
            word = (w.get("word") or "").strip()
            if not word:
                continue
            out.append({
                "start": float(w["start"]),
                "end": float(w["end"]),
                "word": word,
                "prob": float(w.get("prob", 1.0)),
            })
    return out


def sentence_units(segments: list[dict], duration: float) -> list[dict]:
    """Split into sentences. Hard break on punctuation, soft break on a long pause."""
    words = _words(segments)
    if not words:
        return []
    sentences: list[dict] = []
    buf: list[dict] = []

    def flush() -> None:
        if not buf:
            return
        text = " ".join(x["word"] for x in buf).strip()
        if text:
            sentences.append({
                "start": round(buf[0]["start"], 3),
                "end": round(buf[-1]["end"], 3),
                "text": text,
                "words": [dict(x) for x in buf],
            })
        buf.clear()

    for i, w in enumerate(words):
        buf.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 99.0
        ends = bool(SENT_END.search(w["word"]))
        # A sentence has to be at least 3 words unless it ends a long pause.
        if ends and len(buf) >= 3:
            flush()
        elif gap > 1.4 and len(buf) >= 3:
            flush()
        elif nxt is None:
            flush()
    flush()

    # Merge fragments that are too short to be a usable hook.
    merged: list[dict] = []
    for s in sentences:
        if merged and (len(tokenize(s["text"])) <= 2 and s["end"] - s["start"] < 1.2):
            prev = merged[-1]
            prev["end"] = s["end"]
            prev["text"] = f"{prev['text']} {s['text']}".strip()
            prev["words"].extend(s["words"])
        elif merged and (s["start"] - merged[-1]["end"]) < 0.28 and len(tokenize(merged[-1]["text"])) < 5:
            prev = merged[-1]
            prev["end"] = s["end"]
            prev["text"] = f"{prev['text']} {s['text']}".strip()
            prev["words"].extend(s["words"])
        else:
            merged.append(s)
    for idx, s in enumerate(merged):
        s["idx"] = idx
        s["tokens"] = tokenize(s["text"])
        s["content"] = [t for t in s["tokens"] if t not in FILLER]
        s["dur"] = round(max(s["end"] - s["start"], 0.01), 2)
        s["question"] = "?" in s["text"]
        s["exclaim"] = s["text"].count("!")
    return merged


def sentence_features(sentences: list[dict], feats: dict, frames: dict) -> list[dict]:
    """Attach audio/visual/language features used for boundary choice and scoring."""
    from .analysis import _window_audio

    frame_list = frames.get("frames") or []
    all_content = [t for s in sentences for t in s["content"]]
    counts = Counter(all_content)
    total = max(len(all_content), 1)
    for s in sentences:
        s["audio"] = _window_audio(feats, s["start"], s["end"])
        near = [f for f in frame_list if s["start"] - 0.8 <= f["t"] <= s["end"] + 0.8]
        # Only count real detections; a held position is an inference, not a face.
        s["faces"] = round(
            sum(1 for f in near if any(not x.get("held") for x in (f.get("faces") or []))) / len(near), 2
        ) if near else 0.0
        s["motion"] = round(sum(f.get("motion", 0) for f in near) / len(near), 3) if near else 0.0
        s["rarity"] = round(sum(1 - counts[t] / total for t in s["content"]) / max(len(s["content"]), 1), 3)
        s["wps"] = round(len(s["content"]) / max(s["dur"], 0.01), 2)
        s["filler"] = round(sum(1 for t in s["tokens"] if t in FILLER) / max(len(s["tokens"]), 1), 2)
        # signal words, used to decide which sentence is the "payoff" of a beat
        s["punch"] = (
            sum(1 for t in s["tokens"] if t in SURPRISE) * 1.6
            + sum(1 for t in s["tokens"] if t in LAUGH) * 1.4
            + sum(1 for t in s["tokens"] if t in EMOTION) * 1.0
            + sum(1 for t in s["tokens"] if t in CONTROVERSY) * 1.0
            + sum(1 for t in s["tokens"] if t in INSIGHT) * 0.8
            + s["exclaim"] * 0.8
            + (0.6 if s["question"] else 0)
        )
        s["hook"] = (
            sum(1 for t in s["tokens"] if t in HOOK) * 1.5
            + (1.2 if s["question"] else 0)
            + (0.5 if re.match(r"^(what|why|how|when|who|imagine|listen|stop)\b", s["text"], re.I) else 0)
            + (0.4 if re.search(r"\byou\b|\byour\b", s["text"], re.I) else 0)
        )
    return sentences


def _window_text(sentences: list[dict], a: int, b: int) -> str:
    return " ".join(s["text"] for s in sentences[a:b + 1]).strip()


BARE_INTERJECTION = re.compile(
    r"^(what|huh|hey|oh|wow|whoa|wait|yeah|yes|no|okay|ok|damn|god|jesus|shit|fuck|"
    r"what\?|huh\?|oh my god|oh my gosh)[\s!?.,]*$", re.I)

FILLER_OPENER = re.compile(r"^(oh|yeah|um|uh|ah|well|okay|ok|right|huh|so yeah|like)\b[\s,]*", re.I)


def _strong_opener(sentences: list[dict], i: int) -> bool:
    """A clip must not open on a bare interjection or a filler-led fragment."""
    s = sentences[i]
    text = s["text"].strip()
    if BARE_INTERJECTION.match(text):
        return False
    # Need real content, not just "What? What? Everyone..."
    if len(s["content"]) < 2 and len(s["tokens"]) < 4:
        return False
    if FILLER_OPENER.match(text) and len(s["content"]) < 4:
        return False
    return True


def _repetitive_end(sentences: list[dict], b: int) -> bool:
    """Reject endings that are the same short phrase repeated (weak payoff)."""
    s = sentences[b]
    toks = [t.lower() for t in tokenize(s["text"])]
    if len(toks) < 6:
        return True
    if len(set(toks)) <= max(2, len(toks) // 3):
        return True
    # trailing 3 words repeated elsewhere at the very end
    if len(toks) >= 6 and toks[-3:] == toks[-6:-3]:
        return True
    return False


def tighten_span(sentences: list[dict], a: int, b: int, min_dur: float) -> tuple[int, int]:
    """Trim weak leading/trailing sentences so the clip opens and closes on value."""
    changed = True
    while changed and b > a:
        changed = False
        # drop a weak opener if the next sentence is a better hook and we keep enough length
        if not _strong_opener(sentences, a):
            if sentences[b]["end"] - sentences[a + 1]["start"] >= min_dur:
                a += 1
                changed = True
                continue
        # drop a weak / repetitive ending
        if b > a and (_repetitive_end(sentences, b) or sentences[b]["punch"] < 0.15):
            if sentences[b - 1]["end"] - sentences[a]["start"] >= min_dur:
                b -= 1
                changed = True
    return a, b


BROKEN_OPENER = re.compile(
    r"^(is|are|was|were|am|be|been|being|has|have|had|do|does|did|will|would|can|could|"
    r"should|may|might|must)\b",
    re.I,
)


def _complete_start(sentences: list[dict], i: int) -> bool:
    s = sentences[i]
    if i == 0:
        # The video may simply start mid-sentence ("is on doing in this game").
        # A continuation word at the very start is unavoidable there, but a bare
        # verb or copula still means the line is broken, not just open-ended.
        return not BROKEN_OPENER.match(s["text"])
    # Reject openers that depend on the previous sentence.
    return not re.match(
        r"^(and|but|so|because|which|that|then|also|or|it|this|they|he|she|however|although|"
        r"though|while|if|when|as|to|of|at|in|for|with|from|on|his|her|their|its|my|our|your|"
        # A bare verb or copula means we cut into the middle of a sentence
        # ("is on doing in this game").
        r"is|are|was|were|am|be|been|being|has|have|had|do|does|did|will|would|can|could|"
        r"should|may|might|must)\b",
        s["text"], re.I,
    )


def _complete_end(sentences: list[dict], j: int) -> bool:
    s = sentences[j]
    if SENT_END.search(s["text"]):
        return True
    # No punctuation: acceptable only if the next sentence starts a new thought
    # and this one is not obviously hanging mid-clause.
    if re.search(r"(,|:)$", s["text"]):
        return False
    return not re.search(
        r"\b(and|but|because|which|that|so|or|if|when|with|to|the|a|an|of|in|on|for|is|are|was|were|"
        r"i|you|we|they|he|she|it)\W*$",
        s["text"], re.I,
    )


def build_beats(sentences: list[dict], max_beat: float = 16.0) -> list[dict]:
    """Merge sentences into beats — a complete thought with a payoff sentence."""
    beats: list[dict] = []
    i = 0
    n = len(sentences)
    while i < n:
        start = sentences[i]["start"]
        best_end = None
        for j in range(i, min(i + 5, n)):
            span = sentences[j]["end"] - start
            if span > max_beat and j > i:
                break
            if _complete_end(sentences, j) or j == n - 1:
                best_end = j
                # Prefer the earliest ending that carries a payoff.
                if sentences[j]["punch"] > 0.7 or not _complete_end(sentences, j):
                    best_end = j
                    break
        if best_end is None:
            best_end = min(i + 1, n - 1)
        beats.append({"a": i, "b": best_end})
        i = best_end + 1
    return beats



# ---------------------------------------------------------------- viral structure
# What separates clips that travel on Shorts/Reels from merely good moments:
# a cold open on the strongest line, a payoff at least every ~18s, no dead air,
# and an ending that hands attention back to the start.
PAYOFF_GAP = 18.0


def _viral_structure(sentences: list[dict], a: int, b: int) -> dict:
    """Score the *shape* of a clip, not just its content.

    Returns 0-100 plus flags the reasons/titles can use, so the editor can show
    why a clip was picked.
    """
    window = sentences[a:b + 1]
    if not window:
        return {"viral": 0.0, "cold_open": False, "loops": False, "dead_air": 0.0}
    first, last = window[0], window[-1]
    dur = max(last["end"] - first["start"], 0.01)

    viral = 42.0

    # 1. Cold open: the opening line itself has to be the hook. A clip whose
    #    best line is buried 10 seconds in loses most viewers before it lands.
    qualities = [_line_hook_strength(s) for s in window]
    best_idx = max(range(len(window)), key=lambda i: qualities[i])
    cold_open = best_idx == 0
    if cold_open:
        viral += 14
    else:
        # Partial credit if the hook is very near the top.
        lead = sentences[best_idx]["start"] - first["start"]
        if lead <= 2.5:
            viral += 8
        elif lead <= 5.0:
            viral += 3
        else:
            viral -= 8

    # 2. Payoff cadence: a laugh, turn or strong claim at least every ~18s.
    payoffs = [s for s in window if s.get("punch", 0) >= 0.7 or _line_hook_strength(s) >= 2.5]
    gaps: list[float] = []
    prev_t = first["start"]
    for s in payoffs:
        gaps.append(s["start"] - prev_t)
        prev_t = s["start"]
    gaps.append(last["end"] - prev_t)
    worst_gap = max(gaps) if gaps else dur
    if worst_gap <= PAYOFF_GAP:
        viral += 10
    elif worst_gap <= PAYOFF_GAP * 1.6:
        viral += 3
    else:
        viral -= 9

    # 3. Dead air: silence and slow stretches kill completion rate.
    silence = sum(1 for s in window if s["audio"]["silence"] > 0.35) / len(window)
    slow = sum(1 for s in window if s["wps"] < 1.2) / len(window)
    dead_air = round(min(silence * 0.7 + slow * 0.3, 1.0), 2)
    viral -= dead_air * 16

    # 4. Loop-friendly ending: a short, punchy close feels like it restarts.
    ends_clean = bool(SENT_END.search(last["text"])) or bool(last["text"].strip().endswith(("!", "?")))
    loops = ends_clean and len(last["tokens"]) <= 12 and last["punch"] >= 0.5
    if loops:
        viral += 7
    elif not ends_clean:
        viral -= 5

    # 5. Momentum: energy should not collapse in the final third.
    energies = [s["audio"]["loudness"] for s in window]
    third = max(len(energies) // 3, 1)
    if sum(energies[-third:]) / third >= sum(energies[:third]) / third - 0.02:
        viral += 5
    else:
        viral -= 4

    # 6. Repetition: stutters and repeated chants ("Big Team! Big Team!") look
    #    broken once captioned, so they lose to clips with real progression.
    toks = [t.lower() for s in window for t in s.get("tokens", [])]
    if len(toks) >= 8:
        uniq = len(set(toks)) / len(toks)
        if uniq < 0.45:
            viral -= 18
        elif uniq < 0.6:
            viral -= 9

    # 7. Length: 15-45s is the completion-rate sweet spot on Shorts/Reels.
    if 14 <= dur <= 42:
        viral += 4
    elif dur > 70:
        viral -= 7

    return {
        "viral": round(max(0.0, min(100.0, viral)), 1),
        "cold_open": cold_open,
        "loops": loops,
        "dead_air": dead_air,
    }


def _line_hook_strength(s: dict) -> float:
    """How strongly a single line can stop a scroll, in its own right."""
    strength = 0.0
    strength += min(s.get("hook", 0.0) * 1.1, 3.0)
    strength += min(s.get("punch", 0.0) * 0.9, 2.6)
    strength += 1.2 if s.get("question") else 0.0
    strength += 0.9 if re.search(r"\b\d[\d,.]*\b", s["text"]) else 0.0
    strength += 0.8 if re.search(r"\b(you|your|nobody|everybody|never|always)\b", s["text"], re.I) else 0.0
    if BARE_INTERJECTION.match(s["text"]):
        strength -= 2.0
    return max(0.0, strength)


def _score_components(sentences: list[dict], a: int, b: int,
                      ideal: float = 32.0) -> dict:
    """Component scores for a sentence window (0-100 each)."""
    window = sentences[a:b + 1]
    text = " ".join(s["text"] for s in window)
    toks = [t for s in window for t in s["tokens"]]
    content = [t for s in window for t in s["content"]]
    content_set = set(content)
    first, last = window[0], window[-1]
    dur = max(last["end"] - first["start"], 0.01)

    # Hook: strength of the first sentence as an opener.
    hook = 20.0
    hook += min(first["hook"] * 9, 40)
    hook += min(len(content_set) / max(len(content), 1) * 14, 14)
    hook += 8 if re.search(r"\b\d[\d,.]*%?\b", first["text"]) else 0
    hook += 6 if len(first["tokens"]) >= 4 else -8
    if not _complete_start(sentences, a):
        hook -= 16
    hook += min(first["audio"]["loudness"] * 12, 12)
    # A filler-led or interjection-heavy opening wastes the first 2 seconds.
    if FILLER_OPENER.match(first["text"]):
        hook -= 12
    if BARE_INTERJECTION.match(first["text"]):
        hook -= 22
    hook = max(0.0, min(100.0, hook))

    # Emotional intensity: words + vocal dynamics + exclamations.
    emo = 18.0
    emo += min(sum(1 for t in toks if t in EMOTION) * 7, 24)
    emo += min(sum(1 for t in toks if t in LAUGH) * 11, 20)
    emo += min(sum(s["exclaim"] for s in window) * 4, 12)
    emo += min(sum(s["audio"]["dyn"] for s in window) / len(window) * 16, 16)
    emo += min(sum(s["audio"]["peak"] for s in window) / len(window) * 10, 10)
    emo += 6 if any(s["question"] for s in window) else 0
    emo = max(0.0, min(100.0, emo))

    # Novelty + surprise.
    novelty = 18.0
    novelty += min(sum(1 for t in toks if t in SURPRISE) * 8, 26)
    novelty += min(sum(len(re.findall(r"\b\d[\d,.]*%?\b", s["text"])) for s in window) * 4, 12)
    novelty += min(len(content_set) / max(len(content), 1) * 22, 22)
    novelty += (sum(s["rarity"] for s in window) / len(window)) * 14
    novelty = max(0.0, min(100.0, novelty))

    # Audience relevance: recurring topic terms + everyday themes.
    counts = Counter(t for s in sentences for t in s["content"])
    top = {w for w, _ in counts.most_common(30)}
    relevance = 26.0
    relevance += min(sum(1 for t in content if t in top) / max(len(content), 1) * 38, 38)
    if any(t in {"money", "life", "love", "people", "work", "time", "world", "game", "funny", "crazy"} for t in content):
        relevance += 10
    relevance += min(len(content) / 35 * 12, 12)
    relevance = max(0.0, min(100.0, relevance))

    # Standalone: complete start/end, enough words, not dependent on prior context.
    standalone = 46.0
    standalone += 18 if _complete_start(sentences, a) else -22
    standalone += 16 if _complete_end(sentences, b) else -12
    standalone += min(sum(len(s["tokens"]) for s in window) / 22 * 16, 16)
    standalone -= min(sum(s["filler"] for s in window) / len(window) * 14, 14)
    standalone = max(0.0, min(100.0, standalone))

    # Storytelling: narrative markers + reveal words.
    story = 22.0
    story += min(sum(1 for t in toks if t in STORY) * 6, 24)
    story += min(sum(1 for t in toks if t in REVEAL) * 3, 12)
    story += 8 if re.search(r"\b(when|after|before|once|until|then)\b", text, re.I) else 0
    story += min(len(window) * 3, 15)
    story = max(0.0, min(100.0, story))

    # Retention: conversational pace, low dead air, rising energy.
    silence = sum(1 for w in window if w["audio"]["silence"] > 0) / len(window)
    energies = [s["audio"]["loudness"] for s in window]
    third = max(len(energies) // 3, 1)
    arc = (sum(energies[-third:]) / third) - (sum(energies[:third]) / third)
    retention = 26.0
    retention += max(0.0, min((sum(s["wps"] for s in window) / len(window) - 1.6) / 1.8, 1.0)) * 20
    retention -= min(silence * 26, 14)
    retention += max(0.0, min(arc * 70, 16))
    retention += 8 if SENT_END.search(last["text"]) else 0
    retention += min(last["punch"] * 7, 18)
    retention = max(0.0, min(100.0, retention))

    visual = max(0.0, min(100.0, (sum(s["motion"] for s in window) / len(window)) * 150
                             + (sum(s["faces"] for s in window) / len(window)) * 28))

    # Duration fit: reward landing near the requested band's midpoint.
    fit = max(0.0, 1.0 - abs(dur - ideal) / (ideal + 12))
    return {
        "hook": hook, "emotion": emo, "novelty": novelty, "relevance": relevance,
        "standalone": standalone, "story": story, "retention": retention,
        "energy": visual, "fit": fit * 100, "dur": dur,
    }


WEIGHTS = {
    "hook": 0.24, "emotion": 0.17, "novelty": 0.13, "relevance": 0.09,
    "standalone": 0.16, "story": 0.08, "retention": 0.13,
}


def _categorise(sentences: list[dict], a: int, b: int) -> tuple[str, str]:
    window = sentences[a:b + 1]
    toks = [t for s in window for t in s["tokens"]]
    counts = {
        "revelation": sum(1 for t in toks if t in SURPRISE) * 1.4 + sum(s["punch"] for s in window) * 0.3,
        "funny": sum(1 for t in toks if t in LAUGH) * 1.9 + sum(s["exclaim"] for s in window) * 0.6,
        "controversial": sum(1 for t in toks if t in CONTROVERSY) * 1.5,
        "emotional": sum(1 for t in toks if t in EMOTION) * 1.1
                     + (sum(s["audio"]["dyn"] for s in window) / len(window)) * 1.4,
        "insight": sum(1 for t in toks if t in INSIGHT) * 1.25,
        "high_energy": (sum(s["audio"]["loudness"] for s in window) / len(window)) * 2.0
                        + (sum(s["motion"] for s in window) / len(window)) * 0.6,
        "story": sum(1 for t in toks if t in STORY) * 1.1,
    }
    cat = max(counts, key=counts.get) if max(counts.values()) > 0 else "story"
    labels = {
        "revelation": "Unexpected revelation", "funny": "Funny moment",
        "controversial": "Controversial take", "emotional": "Emotional moment",
        "insight": "Insight & advice", "high_energy": "High-energy moment",
        "story": "Storytelling",
    }
    return cat, labels.get(cat, "Highlight")


HANGING = re.compile(
    r"\b(and|but|because|so|or|if|when|with|to|the|a|an|of|in|on|for|that|which|is|are|was|were)\W*$",
    re.I)


def _usable_sentence(s: dict) -> bool:
    """Loose check for clip substance: has content and doesn't hang mid-clause.

    Deliberately weaker than the title filter — natural speech rarely produces
    polished sentences, but a clip can still work if each line carries meaning.
    """
    text = s["text"].strip()
    content = s["content"]
    if len(content) < 2 and len(s["tokens"]) < 4:
        return False
    if BARE_INTERJECTION.match(text):
        return False
    if HANGING.search(text) and not SENT_END.search(text):
        return False
    return True


def _payoff_strength(sentences: list[dict], a: int, b: int) -> float:
    """How well a clip lands its ending — short-form lives or dies on the last line.

    A clip that ends on a bare "yeah" or a repeated phrase wastes the payoff slot.
    """
    last = sentences[b]
    prev = sentences[b - 1] if b > a else last
    score = 0.0
    score += min(last["punch"] * 0.9, 3.2)          # surprise/laugh/emotion words
    score += 0.8 if SENT_END.search(last["text"]) else 0.0
    score += 0.5 if last["hook"] > 0.8 else 0.0     # ends on a quotable line
    score += 0.6 if len(last["content"]) >= 4 else -0.6
    # Contrast: a calmer setup resolving into a loud payoff reads as a punchline.
    if last["audio"]["loudness"] > prev["audio"]["loudness"] + 0.05:
        score += 0.7
    if last["audio"]["dyn"] > 0.16:
        score += 0.4
    if _repetitive_end(sentences, b):
        score -= 1.2
    if last["filler"] > 0.5:
        score -= 0.8
    return score


def _topic_signature(sentences: list[dict], a: int, b: int, top_n: int = 8) -> set[str]:
    """Distinctive words in a clip, used to stop two clips telling the same story."""
    words = [t for s in sentences[a:b + 1] for t in s["content"]]
    counts = Counter(words)
    return {w for w, _ in counts.most_common(top_n) if len(w) > 3}


def _topic_overlap(sig: set[str], picked_sigs: list[set[str]]) -> float:
    if not sig or not picked_sigs:
        return 0.0
    worst = 0.0
    for other in picked_sigs:
        if not other:
            continue
        j = len(sig & other) / max(min(len(sig), len(other)), 1)
        worst = max(worst, j)
    return worst


def _substance_ratio(sentences: list[dict], a: int, b: int) -> float:
    """Share of sentences that carry actual content (used to down-rank noise)."""
    window = sentences[a:b + 1]
    ok = sum(1 for s in window if _usable_sentence(s))
    return ok / max(len(window), 1)


def _reasons(comp: dict, sentences: list[dict], a: int, b: int,
             viral: dict | None = None) -> list[str]:
    labels = {
        "hook": "Opens with a line that stops the scroll",
        "emotion": "Strong emotional charge in voice and wording",
        "novelty": "Unexpected or fresh information",
        "relevance": "Broadly relatable topic",
        "standalone": "Complete thought — works without the rest of the video",
        "story": "Clear narrative with a setup and payoff",
        "retention": "Tight pacing with a punchline at the end",
    }
    ranked = sorted(WEIGHTS, key=lambda k: -comp[k] * WEIGHTS[k])
    out = [labels[k] for k in ranked[:3] if comp[k] >= 42]
    viral = viral or {}
    if viral.get("cold_open"):
        out.insert(0, "Opens on the strongest line — no wasted first second")
    if viral.get("loops"):
        out.append("Ends on a punchy line, so it loops cleanly")
    if (viral.get("dead_air") or 0) <= 0.15:
        out.append("Almost no dead air — tight pacing throughout")
    if comp["standalone"] >= 70:
        out.append("Starts and ends on a full sentence")
    if comp["dur"] <= 45:
        out.append(f"Fits the {round(comp['dur'])}s short-form sweet spot")
    return out[:4]


def _append_pick(out: list[dict], sentences: list[dict], a: int, b: int,
                 cat: str, label: str, cand: dict) -> None:
    comp = cand["comp"]
    words = [w for s in sentences[a:b + 1] for w in s["words"]]
    start = sentences[a]["start"]
    end = sentences[b]["end"]
    out.append({
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 2),
        "text": _window_text(sentences, a, b),
        "words": words,
        "score": round(cand["score"], 1),
        "components": {k: round(comp[k], 1) for k in WEIGHTS},
        "energy": round(comp["energy"], 1),
        "category": cat,
        "category_label": label,
        "reasons": _reasons(comp, sentences, a, b, cand.get("viral")),
        "sentence_start": a,
        "sentence_end": b,
        "sentences": [s["text"] for s in sentences[a:b + 1]],
        "viral": cand.get("viral") or _viral_structure(sentences, a, b),
        "audio_stats": {
            "silence": round(sum(1 for s in sentences[a:b + 1] if s["audio"]["silence"] > 0.3) / (b - a + 1), 2),
            "wps": round(sum(s["wps"] for s in sentences[a:b + 1]) / (b - a + 1), 2),
            "loudness": round(sum(s["audio"]["loudness"] for s in sentences[a:b + 1]) / (b - a + 1), 3),
        },
        "visual_stats": {
            "motion": round(sum(s["motion"] for s in sentences[a:b + 1]) / (b - a + 1), 3),
            "face_ratio": round(sum(s["faces"] for s in sentences[a:b + 1]) / (b - a + 1), 2),
        },
    })


def select_clips(segments: list[dict], feats: dict, frames: dict, duration: float,
                 target_min: float, target_max: float, max_clips: int) -> list[dict]:
    """Return final clips that always begin and end on a sentence boundary."""
    sentences = sentence_units(segments, duration)
    if len(sentences) < 2:
        return []
    sentences = sentence_features(sentences, feats, frames)
    beats = build_beats(sentences)

    ideal = (target_min + target_max) / 2
    candidates: list[dict] = []
    n = len(sentences)

    def consider(a: int, b: int) -> None:
        """Score one span; helpers decide whether it's usable."""
        if a >= b or b >= n:
            return
        dur = sentences[b]["end"] - sentences[a]["start"]
        if dur < target_min * 0.97 or dur > target_max * 1.04:
            return
        if not _complete_start(sentences, a) or not _complete_end(sentences, b):
            return
        ta, tb = tighten_span(sentences, a, b, target_min * 0.7)
        if (not _complete_start(sentences, ta) or not _complete_end(sentences, tb)
                or not _strong_opener(sentences, ta)):
            return
        comp = _score_components(sentences, ta, tb, ideal)
        if comp["dur"] < target_min * 0.97 or comp["dur"] > target_max:
            return
        ratio = _substance_ratio(sentences, ta, tb)
        if ratio < 0.55:
            return
        base = sum(comp[k] * w for k, w in WEIGHTS.items())
        base *= 0.72 + 0.28 * ratio
        base += comp["energy"] * 0.03
        base += (comp["fit"] - 50) * 0.16
        base += _payoff_strength(sentences, ta, tb) * 2.1
        # Viral shape matters as much as content: a great line buried mid-clip
        # under dead air still gets scrolled past.
        viral = _viral_structure(sentences, ta, tb)
        base += (viral["viral"] - 50) * 0.42
        candidates.append({
            "a": ta, "b": tb, "score": max(0.0, min(99.0, base)),
            "comp": comp, "viral": viral,
        })

    # Start at every sentence that reads as a fresh thought, not only at beat
    # edges — real conversations put a strong opener mid-beat all the time.
    for a in range(n):
        if not _complete_start(sentences, a) or not _strong_opener(sentences, a):
            continue
        for b in range(a + 1, min(a + 12, n)):
            dur = sentences[b]["end"] - sentences[a]["start"]
            if dur < target_min * 0.97:
                continue
            if dur > target_max * 1.04:
                break
            consider(a, b)

    # Beat-aligned spans are still useful: they tend to be the cleanest narratively.
    for bi in range(len(beats)):
        a = beats[bi]["a"]
        if not _complete_start(sentences, a):
            if bi + 1 < len(beats):
                a = beats[bi + 1]["a"]
            else:
                continue
        for bj in range(bi, min(bi + 6, len(beats))):
            consider(a, beats[bj]["b"])

    if not candidates:
        return []

    # Deduplicate identical spans, keeping the highest score.
    by_span: dict[tuple[int, int], dict] = {}
    for c in candidates:
        key = (c["a"], c["b"])
        if key not in by_span or c["score"] > by_span[key]["score"]:
            by_span[key] = c
    pool = sorted(by_span.values(), key=lambda c: -c["score"])

    picked: list[dict] = []
    category_counts: Counter = Counter()
    picked_sigs: list[set[str]] = []

    def span_free(a: int, b: int, overlap_limit: float) -> bool:
        start, end = sentences[a]["start"], sentences[b]["end"]
        for p in picked:
            overlap = min(p["end"], end) - max(p["start"], start)
            if overlap > 0 and overlap / min(p["duration"], end - start) > overlap_limit:
                return False
        return True

    # Pass 1: strict. Pass 2 (short videos / few survivors): looser, so a good
    # 40-second clip doesn't monopolise an 85-second source.
    passes = [
        {"overlap": 0.24, "topic": 0.62, "cat_cap": 2, "cat_until": 0.6},
        {"overlap": 0.34, "topic": 0.80, "cat_cap": 3, "cat_until": 0.85},
        {"overlap": 0.45, "topic": 0.95, "cat_cap": 9, "cat_until": 1.0},
    ]
    for pcfg in passes:
        for cand in pool:
            if len(picked) >= max_clips:
                break
            a, b = cand["a"], cand["b"]
            if not span_free(a, b, pcfg["overlap"]):
                continue
            cat, label = _categorise(sentences, a, b)
            if pcfg["cat_cap"] and category_counts[cat] >= pcfg["cat_cap"] and len(picked) < max_clips * pcfg["cat_until"]:
                continue
            sig = _topic_signature(sentences, a, b)
            if _topic_overlap(sig, picked_sigs) > pcfg["topic"]:
                continue
            category_counts[cat] += 1
            picked_sigs.append(sig)
            _append_pick(picked, sentences, a, b, cat, label, cand)
        # Only relax further if this pass didn't fill the requested count.
        if len(picked) >= max_clips:
            break
        if len(picked) >= max(1, (max_clips * 2) // 3):
            # we have most of the clips; don't force weak extras
            if duration > 240:
                break

    if not picked:
        return []

    # Spread: if everything landed in one third of the video, swap the weakest
    # pick for the best candidate from an empty third so the feed isn't repetitive.
    if duration > 0 and len(picked) > 1:
        thirds = [0, 0, 0]
        for c in picked:
            thirds[min(int(c["start"] / max(duration, 0.1) * 3), 2)] += 1
        if max(thirds) == len(picked) and len(picked) < max_clips:
            used = {(c["sentence_start"], c["sentence_end"]) for c in picked}
            for cand in pool:
                if (cand["a"], cand["b"]) in used:
                    continue
                st = sentences[cand["a"]]["start"]
                if min(int(st / max(duration, 0.1) * 3), 2) == thirds.index(max(thirds)):
                    continue
                if not span_free(cand["a"], cand["b"], passes[-1]["overlap"]):
                    continue
                cat, label = _categorise(sentences, cand["a"], cand["b"])
                _append_pick(picked, sentences, cand["a"], cand["b"], cat, label, cand)
                break

    picked.sort(key=lambda c: -c["score"])
    # Rescale into a readable band while preserving order.
    if len(picked) > 1:
        vals = [c["score"] for c in picked]
        lo, hi = min(vals), max(vals)
        for c in picked:
            if hi - lo < 0.5:
                c["score"] = round(min(96, max(45, c["score"] + 6)), 1)
            else:
                c["score"] = round(45 + ((c["score"] - lo) / (hi - lo)) * 50, 1)
    return picked
