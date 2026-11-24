"""Automatic keyword highlighting and emoji for captions.

Every serious short-form tool (OpusClip, Submagic, CapCut) bolds/colours the
word that carries the meaning and drops in an emoji. It is the single most
visible difference between "subtitles" and "edited captions".

Everything here is local and deterministic: no API, no per-word cost.

Two jobs:
1. `highlight_words()` marks the words worth accenting inside a cue.
2. `cue_emoji()` picks one emoji for a cue, and `emoji_assets()` rasterises
   colour emoji to PNG so they can be composited into the video. libass cannot
   draw colour emoji, so the renderer overlays these images instead.
"""
from __future__ import annotations

import re
from collections import Counter

from .transcribe import tokenize

# Words whose meaning is worth accenting: stakes, emotion, and strong claims.
EMPHASIS = set("""
never always nobody everybody everyone everything nothing nobody money rich broke
million billion thousand percent free fake real truth lie scam secret mistake
worst best biggest craziest insane crazy wild unbelievable impossible disaster
failed failure won lost win lose quit fired hired banned suspended arrested exposed
caught betrayed cheated stole stolen killed died dead alive survived destroyed
love hate scared afraid terrified cry crying hurt painful broken heart proud
rich poor expensive cheap profit loss debt ruined homeless job career business
boss manager fired promoted salary income tax rent buying selling price
fast slow huge tiny massive dangerous illegal legal banned viral famous rich
yesterday tomorrow today now forever finally suddenly
""".split())

# Two- and three-word phrases that carry the meaning as a unit. Single-word
# matching misses the most common case in speech ("feel bad", "lost my job"),
# which left the captions looking unedited.
EMPHASIS_PHRASES = [
    "feel bad", "feels bad", "lost my job", "lost it", "lost everything",
    "no way", "oh my god", "what the hell", "for real", "i swear",
    "never again", "one hundred percent", "right now", "all my money",
    "my whole life", "the truth", "sold out", "gave up", "walked away",
    "turned down", "blew up", "went viral", "messed up", "fucked up",
    "freaked out", "passed out", "knocked out", "broke down",
    "big deal", "life changing", "game changer", "at the end",
]

# Interjections/laughter that deserve a reaction emoji rather than a colour.
REACTION = set("""
haha lol lmao funny hilarious kidding joke laughed laughing dead dying
wow whoa damn god jesus shit wow wait what no yes yay
""".split())

# Emotion -> emoji. Ordered: first match in a cue wins, strongest first.
EMOJI_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(haha|lol|lmao|hilarious|funny|joking|kidding|laughed|laughing)\b", re.I), "😂"),
    (re.compile(r"\b(cry|cried|crying|tears|sad|devastated|heartbroken)\b", re.I), "😢"),
    (re.compile(r"\b(love|loved|adorable|beautiful|amazing)\b", re.I), "❤️"),
    (re.compile(r"\b(scared|afraid|terrified|horrified|fear)\b", re.I), "😱"),
    (re.compile(r"\b(money|rich|million|billion|profit|salary|income|cash|dollars?|paid|paycheck)\b", re.I), "💰"),
    (re.compile(r"\b(broke|debt|lost|losing|lose|ruined|bankrupt)\b", re.I), "💸"),
    (re.compile(r"\b(fired|quit|lost my job|unemployed|laid off)\b", re.I), "🚪"),
    (re.compile(r"\b(won|win|winning|victory|champion|first place)\b", re.I), "🏆"),
    (re.compile(r"\b(crazy|insane|wild|unbelievable|impossible|craziest|nuts|mind blown)\b", re.I), "🤯"),
    (re.compile(r"\b(secret|the truth|lying|lied|lie to|scam|fake|exposed|betray\w*)\b", re.I), "🤫"),
    (re.compile(r"\b(dead|died|dying|killed|murder)\b", re.I), "💀"),
    (re.compile(r"\b(fire|burning|flame|lit)\b", re.I), "🔥"),
    (re.compile(r"\b(warning|danger|dangerous|careful|illegal|banned)\b", re.I), "⚠️"),
    (re.compile(r"\b(career|business|boss|manager|office|meeting|interview|salary|promotion)\b", re.I), "💼"),
    (re.compile(r"\b(game|gaming|played|player|gamer|stream)\b", re.I), "🎮"),
    (re.compile(r"\b(food|eat|eating|hungry|meal|pizza|burger)\b", re.I), "🍔"),
    (re.compile(r"\b(car|cars|driving|drove|truck|lambo|ferrari|parking lot)\b", re.I), "🚗"),
    (re.compile(r"\b(clock|o'?clock|late again|running late|too early)\b", re.I), "⏰"),
    (re.compile(r"\b(phone|text|call|message|dm)\b", re.I), "📱"),
    (re.compile(r"\b(school|college|teacher|student|exam|graduat)\w*\b", re.I), "🎓"),
    (re.compile(r"\b(oh my god|what the hell|what the fuck|no way|whoa|wow)\b", re.I), "😳"),
    (re.compile(r"\b(hold on|listen to me|stop right there)\b", re.I), "✋"),
    (re.compile(r"\b(help|please|need you)\b", re.I), "🙏"),
    (re.compile(r"\b(feel bad|feels bad|so bad|terrible|awful|horrible|sucks)\b", re.I), "😞"),
    (re.compile(r"\b(tired|exhausted|sleepy|no sleep)\b", re.I), "😴"),
    (re.compile(r"\b(nervous|anxious|stress\w*|worried|panic)\b", re.I), "😬"),
    (re.compile(r"\b(proud|grateful|thank god|blessed|lucky)\b", re.I), "🙏"),
    (re.compile(r"\b(angry|mad|pissed|furious|rage)\b", re.I), "😡"),
    (re.compile(r"\b(fight|punch|attack|war|beat him|beat me)\b", re.I), "💥"),
    (re.compile(r"\b(gym|workout|strong|muscle|training)\b", re.I), "💪"),
]

# Never put an emoji on these: they carry no reaction and would look random.
NO_EMOJI = set("""
the a an and but or so if when while because of to in on at for with from by
is are was were be been being am do does did has have had will would can could
should may might must not no yes i you he she it we they me him her us them
that this these those there here what which who whom whose how why where
""".split())


def highlight_words(words: list[dict], limit: int = 2) -> list[bool]:
    """Flag which words in a cue deserve the accent colour.

    Chosen by meaning, not position: a stake word ("lost", "million") beats a
    long word, which beats nothing. Returns one bool per word so the renderer and
    the editor preview can style the exact same words.
    """
    out = [False] * len(words)
    if not words:
        return out

    scores: list[tuple[float, int]] = []
    for i, w in enumerate(words):
        raw = (w.get("word") or "").strip()
        core = re.sub(r"[^A-Za-z0-9'%.-]", "", raw).lower()
        if not core or core in NO_EMOJI:
            continue
        score = 0.0
        if core in EMPHASIS or core.rstrip("s") in EMPHASIS:
            score += 3.0
        if core in REACTION:
            score += 1.2
        if re.fullmatch(r"\d[\d,.]*%?", core):
            score += 2.4           # numbers are concrete and scan fast
        if len(core) >= 7:
            score += 0.6
        if raw.isupper() and len(core) > 2:
            score += 0.5
        if raw.endswith("!"):
            score += 0.4
        if score > 0:
            scores.append((score, i))

    scores.sort(key=lambda x: (-x[0], x[1]))
    for _, i in scores[:limit]:
        out[i] = True

    # Phrase emphasis: mark every word of a meaningful phrase, not just one.
    words_flat = [(w.get("word") or "") for w in words]
    for phrase in EMPHASIS_PHRASES:
        parts = phrase.split()
        for start in range(len(words_flat) - len(parts) + 1):
            window = [core_word(words_flat[start + k]) for k in range(len(parts))]
            if window == parts:
                for k in range(len(parts)):
                    out[start + k] = True
                break
    return out


def core_word(raw: str) -> str:
    return re.sub(r"[^a-z']", "", (raw or "").lower())


def cue_emoji(text: str, min_words: int = 1) -> str | None:
    """Pick at most one emoji for a caption line, or None.

    One emoji per cue keeps captions readable; stacking several is the fastest
    way to make a clip look spammy. A cue that is mostly filler gets nothing:
    a random glyph on "you want to know" looks worse than no emoji at all.
    """
    t = (text or "").strip()
    if not t:
        return None
    # Count only meaningful words: "that is so funny" is one real word, and
    # that one word is the whole point of the line.
    toks = [x.lower() for x in tokenize(t) if x.lower() not in NO_EMOJI]
    if len(toks) < min_words:
        return None
    hits: Counter = Counter()
    first_pos: dict[str, int] = {}
    for pattern, emoji in EMOJI_RULES:
        m = pattern.search(t)
        if m:
            hits[emoji] += 1
            first_pos.setdefault(emoji, m.start())
    if not hits:
        return None
    # Prefer the earliest, most specific match.
    return min(hits, key=lambda e: (first_pos[e], -hits[e]))


EMOJI_SIZE_CACHE: dict[tuple[str, int], object] = {}


def emoji_assets(work_dir, items: list[dict], size: int) -> list[dict]:
    """Rasterise colour emoji to transparent PNGs inside `work_dir`.

    libass cannot draw colour emoji, so the render graph overlays these images.
    `items` are dicts with `key`, `emoji`, `x`, `y` where x/y are 0-1 fractions
    of the output frame. Unsupported glyphs are dropped silently.
    """
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont

    work = Path(work_dir)
    font_path = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
    made: list[dict] = []
    try:
        # Noto Color Emoji only ships a bitmap strike at a fixed size; load at
        # that size then scale down, which keeps it sharp.
        font = ImageFont.truetype(font_path, 109)
    except Exception:
        return made

    for n, item in enumerate(items):
        emoji = (item.get("emoji") or "").strip()
        if not emoji:
            continue
        key = (emoji, size)
        path = work / f"emoji_{n}.png"
        if key in EMOJI_SIZE_CACHE:
            cached = EMOJI_SIZE_CACHE[key]
            try:
                cached.save(path)  # type: ignore[union-attr]
                made.append({**item, "path": path})
                continue
            except Exception:
                pass
        try:
            canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            draw.text((8, 8), emoji, font=font, embedded_color=True)
            bbox = canvas.getbbox()
            img = canvas.crop(bbox) if bbox else canvas
            img = img.resize((max(size, 8), max(size, 8)), Image.LANCZOS)
            img.save(path)
            EMOJI_SIZE_CACHE[key] = img
            made.append({**item, "path": path})
        except Exception:
            continue
    return made


def cue_text(cue: dict) -> str:
    return " ".join((w.get("word") or "") for w in cue.get("words") or []).strip()


def keywords(text: str, limit: int = 6) -> list[str]:
    """Content words worth surfacing as keywords/hashtags for a clip."""
    counts = Counter(
        t for t in tokenize(text or "")
        if len(t) > 3 and t not in NO_EMOJI and t.isalpha()
    )
    return [w for w, _ in counts.most_common(limit)]


def _cue_of_word(cues: list[dict]) -> list[dict]:
    """Flatten words to absolute time with the cue each belongs to."""
    flat: list[dict] = []
    for ci, cue in enumerate(cues):
        for w in cue.get("words") or []:
            flat.append({"ci": ci, "start": float(w.get("start", 0)),
                         "end": float(w.get("end", 0)), "word": w.get("word") or ""})
    return flat


# Matches must *start* at the word being examined, so the emoji is anchored to
# the cue that actually contains the trigger word.
_ANCHORED = [(re.compile(r"^(?:" + pat.pattern + r")", pat.flags), emo)
             for pat, emo in EMOJI_RULES]


def plan_emoji(cues: list[dict], min_spacing: float = 2.8, max_gap: float = 7.5,
               max_items: int = 16) -> list[dict]:
    """Choose where emoji appear across a whole clip.

    Word-chunk captions are only ~3 words long ("you talk you"), so matching a
    cue on its own finds almost nothing, while a window match would put the
    emoji on whichever cue the *window* started in ("them." instead of
    "I feel bad,"). This scans every word with a 3-word look-ahead, only accepts
    matches that begin on that word, and places the emoji on the cue holding it.

    Spacing rules keep it readable: no repeat back to back, at least
    `min_spacing` apart, and — only when the clip is genuinely emotional — the
    dominant emoji fills stretches longer than `max_gap` so a long clip never
    goes flat. A clip with no emotional content gets no emoji at all.
    """
    if not cues:
        return []

    flat = _cue_of_word(cues)
    found: list[tuple[int, float, str]] = []   # (cue index, time, emoji)
    for i in range(len(flat)):
        phrase = " ".join(w["word"] for w in flat[i:i + 3]).strip()
        if not phrase:
            continue
        core = re.sub(r"[^a-z' ]", "", phrase.lower()).strip()
        if not core:
            continue
        for pattern, emoji in _ANCHORED:
            if pattern.match(core):
                found.append((flat[i]["ci"], flat[i]["start"], emoji))
                break

    plan: list[dict] = []
    used: set[int] = set()
    last_g = ""
    last_t = -999.0
    for ci, t, glyph in found:
        if ci in used or glyph == last_g or t - last_t < min_spacing:
            continue
        plan.append({"index": ci, "emoji": glyph})
        used.add(ci)
        last_g, last_t = glyph, t
        if len(plan) >= max_items:
            return plan

    if not plan:
        return plan

    # Long stretches without an emoji read as flat. Fill with the emoji the
    # clip already uses most, so the choice still matches its tone.
    tally = Counter(item["emoji"] for item in plan)
    dominant = tally.most_common(1)[0][0]
    # Start from the clip's first cue, not minus infinity, or cue zero always
    # looks like it follows a long silence and gets filled.
    prev_t = float(cues[0]["start"])
    for ci, cue in enumerate(cues):
        start = float(cue["start"])
        if ci in used:
            prev_t = start
            continue
        # Filler cues ("okay", "hey") make any emoji look random, so a filled
        # cue needs real words in it, not just a gap to fill.
        words = [w for w in cue.get("words") or []
                 if re.sub(r"[^a-z']", "", (w.get("word") or "").lower())
                 and re.sub(r"[^a-z']", "", (w.get("word") or "").lower()) not in NO_EMOJI]
        if len(words) < 2:
            continue
        if cue["end"] - cue["start"] < 0.6 or start - prev_t < max_gap:
            continue
        plan.append({"index": ci, "emoji": dominant})
        used.add(ci)
        prev_t = start
        if len(plan) >= max_items:
            break
    plan.sort(key=lambda x: x["index"])
    return plan
