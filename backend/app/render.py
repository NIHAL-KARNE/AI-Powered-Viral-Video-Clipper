from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import emphasis
from .config import CLIPS, EXPORTS
from .media import MediaError, probe, run

# The inset window starts closer than the whole shot: a facecam crop at 1.0x is
# the entire frame shrunk, which reads as "nothing happened".
INSET_DEFAULT_ZOOM = 1.8
# Hard ceiling for any zoom, so a stray patch cannot crop to a few pixels.
MAX_ZOOM = 8.0

ASPECTS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
    "4:5": (1080, 1350),
}

# The accent colour each style uses for the one word that carries the meaning.
# Kept next to the style so the editor preview and the export agree.
KEYWORD_COLOURS = {
    "bold-pop": "&H004DE1FF",   # #FFE14D warm yellow
    "clean": "&H004DE1FF",
    "karaoke": "&H004DE1FF",
    "editorial": "&H004DE1FF",
    "neon": "&H00FFFFFF",
}


def _keyword_ass(style_name: str, accent: str | None) -> str:
    """Colour for accented keywords.

    Deliberately fixed per style rather than following the user's accent: the
    spoken word already uses the accent, so a keyword in the same colour would
    merge into it. A warm highlight against accent-tinted text reads as two
    distinct layers, which is what edited captions look like.
    """
    return KEYWORD_COLOURS.get(style_name, "&H004DE1FF")


CAPTION_STYLES = {
    "bold-pop":   {"font": "Inter", "size": 104, "primary": "&H00FFFFFF", "outline": "&H00000000",
                   "bold": -1, "outline_w": 5, "shadow": 0, "border": 1, "uppercase": True, "words": True},
    "clean":      {"font": "Inter", "size": 74, "primary": "&H00FFFFFF", "outline": "&H99000000",
                   "bold": 0, "outline_w": 3, "shadow": 0, "border": 1, "uppercase": False, "words": False},
    "karaoke":    {"font": "Inter", "size": 92, "primary": "&H00FFFFFF", "highlight": "&H0000E5FF",
                   "outline": "&H00101010", "bold": -1, "outline_w": 4, "border": 1, "uppercase": True, "words": True},
    "editorial":  {"font": "DejaVu Serif", "size": 70, "primary": "&H00FFFFFF", "outline": "&H66000000",
                   "bold": 0, "outline_w": 2, "border": 1, "uppercase": False, "words": False},
    "neon":       {"font": "Inter", "size": 96, "primary": "&H00FFF3B0", "outline": "&H00B02CC9",
                   "bold": -1, "outline_w": 5, "border": 1, "uppercase": True, "words": True},
}

MUSIC_MOODS = {
    "none": None,
    "upbeat": (196.0, "sine"),
    "chill": (130.8, "triangle"),
    "dramatic": (98.0, "sawtooth"),
    "lofi": (164.8, "sine"),
}


# drawtext's `font=` selector only picks the Regular face, which made exported
# text look far lighter than the editor's bold preview. Point at real faces.
_FONT_DIR = Path("/usr/share/fonts/opentype/inter")
_FONTS = {
    "extrabold": _FONT_DIR / "Inter-ExtraBold.otf",
    "bold": _FONT_DIR / "Inter-Bold.otf",
    "semibold": _FONT_DIR / "Inter-SemiBold.otf",
    "regular": _FONT_DIR / "Inter-Regular.otf",
}


def _font_arg(weight: str = "extrabold", family: str | None = None) -> str:
    """drawtext font option for a weight, with a safe fallback."""
    if family:
        return f"font='{family}'"
    face = _FONTS.get(weight) or _FONTS["extrabold"]
    if face.exists():
        return f"fontfile='{face.as_posix()}'"
    return "font='Inter'"


def _drawtext_escape(text: str) -> str:
    """Escape text for a drawtext argument inside a filtergraph."""
    return (text.replace("\\", "")
                .replace("'", "\u2019")
                .replace(":", "\\:")
                .replace("%", "\\%")
                .replace(",", "\\,")
                .replace(";", "\\;")
                .replace("[", "\\[")
                .replace("]", "\\]"))


def _wrap_overlay(text: str, max_chars: int) -> str:
    """Break an overlay into rows at word boundaries.

    drawtext does no wrapping of its own, so without this a long line runs off
    the edge of the frame. Rows are balanced so the block reads as a block
    rather than one full line plus a stub.
    """
    words = str(text or "").split()
    if not words:
        return ""
    if len(" ".join(words)) <= max_chars:
        return " ".join(words)
    rows: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join([*current, word])
        if current and len(trial) > max_chars:
            rows.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        rows.append(" ".join(current))
    if len(rows) > 1 and len(rows[-1]) < max_chars * 0.45 and len(rows[-2].split()) > 1:
        moved = rows[-2].split()[-1]
        rows[-2] = " ".join(rows[-2].split()[:-1])
        rows[-1] = f"{moved} {rows[-1]}"
    return "\n".join(rows)


def _overlay_columns(overlays: list[dict], oh: int) -> dict[int, tuple[str, str]]:
    """Per-overlay x/y expressions, stacked so overlays never sit on top of each other.

    Overlays sharing a band stack downward in their own order. Overlays that
    carry explicit x/y (the editor's drag handle) keep the position set by the
    user; those coordinates are the text block's top-left corner as a fraction
    of the frame.
    """
    bands = {"top": 0.06, "center": 0.40, "bottom": 0.66}
    used = dict(bands)
    placed: dict[int, tuple[str, str]] = {}
    for idx, ov in enumerate(overlays):
        size_px = max(int(round(float(ov.get("size", 54)) * oh / 1920)), 12)
        rows = str(ov.get("text") or "").count("\n") + 1
        height = (size_px * 1.22 * rows) / max(oh, 1)
        if ov.get("x") is not None and ov.get("y") is not None:
            try:
                fx = min(max(float(ov["x"]), 0.0), 1.0)
                fy = min(max(float(ov["y"]), 0.0), 1.0)
                placed[idx] = (f"(W-text_w)*{fx:.4f}", f"(H-text_h)*{fy:.4f}")
                continue
            except (TypeError, ValueError):
                pass
        pos = str(ov.get("position", "top"))
        if pos not in bands:
            pos = "top"
        y = used[pos]
        if y + height > 0.97:
            y = max(0.02, 0.97 - height)
        used[pos] = y + height + 0.02
        placed[idx] = ("(W-text_w)/2", f"H*{y:.4f}")
    return placed


def _ts(seconds: float) -> str:
    seconds = max(seconds, 0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:01d}:{m:02d}:{s:05.2f}"


def _ass_time(seconds: float) -> str:
    seconds = max(seconds, 0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                .replace("\n", "\\N"))


# ---------------------------------------------------------------- caption chunks
# Three-word chunks flash by too fast to read and split phrases in half
# ("I" / "feel bad"). 4-5 words per cue is what short-form editors actually use:
# long enough to hold a thought, short enough to read at a glance.
CAPTION_WORDS_DEFAULT = 5
CAPTION_MAX_DUR = 2.8

# Ending a cue on one of these leaves the viewer hanging mid-phrase.
DANGLING = {
    "the", "a", "an", "to", "of", "and", "but", "or", "for", "with", "in", "on",
    "at", "my", "your", "his", "her", "their", "its", "our", "is", "are", "was",
    "were", "be", "been", "that", "which", "who", "as", "than", "so", "if",
}

HARD_END = re.compile(r"[.!?][\"')\]]*$")
SOFT_END = re.compile(r"[,;:—–-][\"')\]]*$")


def caption_chunks(words: list[dict], max_words: int = CAPTION_WORDS_DEFAULT,
                   max_dur: float = CAPTION_MAX_DUR) -> list[list[dict]]:
    """Group words into readable caption cues.

    Breaks at sentence punctuation first, then commas once a cue is long enough
    to stand on its own, then at `max_words`. Never ends a cue on a function
    word, so a line does not finish on "the" or "and".
    """
    max_words = max(2, min(int(max_words or CAPTION_WORDS_DEFAULT), 7))
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        cur.append(w)
        word = (w.get("word") or "").strip()
        dur = float(cur[-1].get("end", 0)) - float(cur[0].get("start", 0))
        hard = bool(HARD_END.search(word))
        soft = bool(SOFT_END.search(word))
        long_enough = len(cur) >= max(3, max_words - 1)
        if not hard:
            if not (len(cur) >= max_words or (soft and long_enough) or (dur >= max_dur and len(cur) >= 3)):
                continue
            # Do not leave a stray article/preposition dangling at the end.
            core = re.sub(r"[^a-z']", "", word.lower())
            if core in DANGLING and len(cur) > 2:
                moved = cur.pop()
                chunks.append(cur)
                cur = [moved]
                continue
        chunks.append(cur)
        cur = []
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


def word_captions(words: list[dict], clip_start: float, clip_end: float, style_name: str,
                  offset: float = 0.0, max_words: int | None = None) -> list[dict]:
    """Build caption cues from words, keeping shot-relative timing."""
    style = CAPTION_STYLES.get(style_name, CAPTION_STYLES["bold-pop"])
    words = [w for w in words if clip_start - 0.3 <= w["start"] <= clip_end + 0.3]
    if not words:
        return []
    cues: list[dict] = []
    if style.get("words"):
        # Animated word styles: 4-5 word cues, broken on punctuation.
        for chunk in caption_chunks(words, max_words or CAPTION_WORDS_DEFAULT):
            t0 = chunk[0]["start"] - clip_start + offset
            t1 = chunk[-1]["end"] - clip_start + offset
            cues.append({"start": t0, "end": max(t1, t0 + 0.36), "words": chunk, "active": None})
        # expand each cue into per-word highlight cues for karaoke feel
        if style_name == "karaoke":
            expanded = []
            for cue in cues:
                for i, w in enumerate(cue["words"]):
                    expanded.append({
                        "start": w["start"] - clip_start + offset,
                        "end": max(w["end"] - clip_start + offset, w["start"] - clip_start + offset + 0.12),
                        "words": cue["words"],
                        "active": i,
                    })
            cues = expanded
    else:
        # sentence chunking of ~7 words
        chunk = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= 7 or re.search(r"[.!?]$", w["word"]):
                t0 = chunk[0]["start"] - clip_start + offset
                t1 = chunk[-1]["end"] - clip_start + offset
                cues.append({"start": t0, "end": max(t1, t0 + 0.4), "words": chunk, "active": None})
                chunk = []
        if chunk:
            t0 = chunk[0]["start"] - clip_start + offset
            t1 = chunk[-1]["end"] - clip_start + offset
            cues.append({"start": t0, "end": max(t1, t0 + 0.4), "words": chunk, "active": None})
    return cues


def _hex_to_ass(color: str | None, fallback: str) -> str:
    """#RRGGBB / #RGB -> &H00BBGGRR (ASS is BGR)."""
    if not color:
        return fallback
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return fallback
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return fallback
    return f"&H00{b:02X}{g:02X}{r:02X}"


def build_ass(cues: list[dict], style_name: str, out_path: Path, width: int, height: int,
              position: str = "bottom", base_size: int | None = None,
              accent: str | None = None, font: str | None = None,
              keywords_enabled: bool = True) -> Path:
    style = dict(CAPTION_STYLES.get(style_name, CAPTION_STYLES["bold-pop"]))
    if accent:
        style["highlight"] = _hex_to_ass(accent, style.get("highlight", "&H0000E5FF"))
        # Only the accent styles (karaoke, neon) tint their text with the accent.
        # Every other style keeps white text, which is what the preview shows;
        # tinting all of them made rendered captions come out violet.
        if style_name in ("karaoke", "neon"):
            style["primary"] = _hex_to_ass(accent, style["primary"])
            style["outline"] = "&H00000000"
    if font:
        style["font"] = font
    else:
        # Match the editor's weights with real faces instead of synthetic bold.
        if style_name in ("bold-pop", "karaoke", "neon"):
            style["font"] = "Inter ExtraBold"
            style["bold"] = 0
        elif style_name == "clean":
            style["font"] = "Inter SemiBold"
            style["bold"] = 0
    # base_size arrives as a percentage (the editor's 70-140% slider), not
    # pixels: 100% means the style's own size.
    pct = float(base_size) if base_size else 100.0
    size = style["size"] * (pct / 100.0)
    # scale caption size with output height
    size = int(size * (height / 1920))
    size = max(size, 28)
    # Alignment must change with the position. A bottom-anchored style (2) with
    # a large MarginV puts "top" captions at the bottom of the frame, which is
    # why top and centre looked identical to the export's bottom setting.
    align, margin_frac = {
        "top": (8, 0.085),      # 8 = top-centre; MarginV is distance from the top
        "center": (5, 0.0),     # 5 = middle-centre
        "bottom": (2, 0.15),    # 2 = bottom-centre; MarginV is distance from the bottom
    }.get(position, (2, 0.15))
    margin_v = int(height * margin_frac)
    # WrapStyle 0 = smart wrapping at the margin, so long lines break onto a
    # second row instead of running off the frame (2 = no wrapping at all).
    margin_x = max(int(width * 0.07), 24)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style['font']},{size},{style['primary']},{style.get('highlight', style['primary'])},{style['outline']},&H80000000,{style['bold']},0,0,0,100,100,0,0,{style['border']},{style['outline_w']},0,{align},{margin_x},{margin_x},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    upper = bool(style.get("uppercase"))
    hl = style.get("highlight", "&H0000E5FF")
    kw = _keyword_ass(style_name, accent)
    lines = [header]
    for cue in cues:
        if cue["end"] - cue["start"] < 0.05:
            continue
        tokens = [(w["word"].upper() if upper else w["word"]) for w in cue["words"]]
        # Which words carry the meaning. Computed here so keyword colouring and
        # the emoji overlays always agree on the same words.
        flags = emphasis.highlight_words(cue["words"]) if keywords_enabled else [False] * len(tokens)
        parts = []
        for i, raw in enumerate(tokens):
            if cue["active"] is not None and i == cue["active"]:
                # The spoken word: accent + weight, as before.
                parts.append(r"{\c" + hl + r"&\b1}" + _esc(raw) + r"{\rCap}")
            elif flags[i] and i != cue["active"]:
                # A meaning-carrying word in the same cue keeps the accent even
                # while another word is being spoken, which is what makes the
                # caption scan like an edited one.
                parts.append(r"{\c" + kw + r"&}" + _esc(raw) + r"{\rCap}")
            else:
                parts.append(_esc(raw))
        text = " ".join(parts)
        _dur = max(cue["end"] - cue["start"], 0.1)
        lines.append(
            f"Dialogue: 1,{_ass_time(cue['start'])},{_ass_time(cue['end'])},Cap,,0,0,0,,{{\\fad(50,30)}}{text}\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def _silence_intervals(path: Path, start: float, end: float, noise_db: int = -32,
                       min_dur: float = 0.42) -> list[tuple[float, float]]:
    proc = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.1):.3f}",
        "-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
        "-f", "null", "-",
    ], capture_output=True, text=True)
    log = proc.stderr or ""
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", log)]
    intervals = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else (end - start)
        if e > s:
            intervals.append((s, e))
    return intervals


def filler_ranges(words: list[dict], start: float, end: float,
                  extra: list[str] | None = None) -> list[tuple[float, float]]:
    """Intervals occupied by filler words, used to tighten rambling speech."""
    fillers = set(extra or ["um", "uh", "erm", "hmm", "mmm", "ah", "uhh", "umm", "like", "you know"])
    out = []
    for w in words:
        raw = (w.get("word") or "").strip().strip(".,!?;:").lower()
        if raw in fillers and start <= w.get("start", -1) and w.get("end", 0) <= end:
            out.append((max(float(w["start"]) - start, 0.0), min(float(w["end"]) - start, end - start)))
    return out


def compute_cuts(path: Path, start: float, end: float,
                 fillers: list[tuple[float, float]] | None = None) -> tuple[list[tuple[float, float]], float]:
    """Remove long dead air and optional filler words. Returns (keep_ranges, removed_total)."""
    sil = _silence_intervals(path, start, end)
    if fillers:
        # Treat filler words as extra "silence" so the existing keep-range logic cuts them.
        total = end - start
        for (a, b) in fillers:
            if b - a >= 0.10 and a > 0.35 and b < total - 0.25:
                sil.append((a, b))
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    removed = 0.0
    total = end - start
    for (s, e) in sil:
        if e - s < 0.55 or s < 0.4:
            continue
        cut_s = max(s + 0.22, cursor)
        if cut_s - cursor > 0.35:
            keep.append((cursor, cut_s))
        cursor = min(e, total)
        removed += max(0.0, cursor - cut_s)
    if total - cursor > 0.35:
        keep.append((cursor, total))
    if not keep:
        keep = [(0.0, total)]
        removed = 0.0
    # merge tiny fragments
    merged = []
    for r in keep:
        if merged and r[0] - merged[-1][1] < 0.2:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    merged = [r for r in merged if r[1] - r[0] > 0.25]
    if not merged:
        return [(0.0, total)], 0.0
    return merged, removed


def _rounded_inset_assets(work: Path, iw: int, ih: int, radius_pct: float,
                          border_px: int, border_color: str,
                          shadow: bool) -> dict[str, Path]:
    """Build the images that give the inset rounded, antialiased edges.

    FFmpeg's drawbox can only draw square corners, and its corner pixels are
    hard-edged. Rendering the shapes with PIL at 4x and downscaling with Lanczos
    gives clean curves, and a soft drop shadow separates the window from a busy
    background.

    Returns paths for whichever pieces are needed:
      mask  – white rounded rect on black, used with `alphamerge`
      ring  – the coloured outline, drawn over the masked video
      shadow – black rounded rect, pre-blurred
    """
    from PIL import Image, ImageDraw, ImageFilter

    ss = 4  # supersample factor
    out: dict[str, Path] = {}

    radius = int(round(min(iw, ih) * min(max(radius_pct, 0.0), 50.0) / 100.0))
    # PIL refuses a radius larger than half the shorter side.
    radius = max(0, min(radius, min(iw, ih) // 2 - 1))

    mask = Image.new("L", (iw * ss, ih * ss), 0)
    draw = ImageDraw.Draw(mask)
    if radius > 0:
        draw.rounded_rectangle([0, 0, iw * ss - 1, ih * ss - 1],
                               radius=radius * ss, fill=255)
    else:
        draw.rectangle([0, 0, iw * ss - 1, ih * ss - 1], fill=255)
    mask = mask.resize((iw, ih), Image.LANCZOS)
    mask_path = work / "inset-mask.png"
    mask.save(mask_path)
    out["mask"] = mask_path

    if border_px > 0:
        # The ring is drawn *inside* the rounded shape so the corners stay
        # smooth: an outline centred on the edge would bleed outside the mask.
        bw = max(1, int(border_px))
        ring = Image.new("RGBA", (iw * ss, ih * ss), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rgb = _hex_rgb(border_color)
        if radius > 0:
            rd.rounded_rectangle([0, 0, iw * ss - 1, ih * ss - 1],
                                 radius=radius * ss, outline=rgb + (255,), width=bw * ss)
        else:
            rd.rectangle([0, 0, iw * ss - 1, ih * ss - 1],
                         outline=rgb + (255,), width=bw * ss)
        # Keep the ring inside the mask: everything outside the rounded rect is
        # transparent anyway, so nothing spills over the background.
        ring = ring.resize((iw, ih), Image.LANCZOS)
        ring_path = work / "inset-ring.png"
        ring.save(ring_path)
        out["ring"] = ring_path

    if shadow:
        pad = max(int(round(min(iw, ih) * 0.09)), 10)
        blur = max(pad // 2, 6)
        sh = Image.new("RGBA", ((iw + pad * 2) * ss, (ih + pad * 2) * ss), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        box = [pad * ss, pad * ss, (pad + iw) * ss - 1, (pad + ih) * ss - 1]
        # Strong enough to separate the window from a busy background, offset
        # downward so it reads as the window sitting above the picture.
        a = 190
        if radius > 0:
            sd.rounded_rectangle(box, radius=radius * ss, fill=(0, 0, 0, a))
        else:
            sd.rectangle(box, fill=(0, 0, 0, a))
        # Blur after downscaling keeps it cheap and still smooth.
        sh = sh.resize((iw + pad * 2, ih + pad * 2), Image.LANCZOS)
        sh = sh.filter(ImageFilter.GaussianBlur(blur))
        sh_path = work / "inset-shadow.png"
        sh.save(sh_path)
        out["shadow"] = sh_path
        out["shadow_pad"] = pad  # type: ignore[assignment]

    return out


def _filter_path(path) -> str:
    """Path safe to embed inside a filtergraph (colons and quotes escaped)."""
    p = str(path).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


def _hex_rgb(value: str) -> tuple[int, int, int]:
    """'#aabbcc' or 'aabbcc' -> (170, 187, 204); falls back to white."""
    v = (value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        return (255, 255, 255)
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def crop_rect(meta: dict, target_aspect: float, cx: float, cy: float,
              zoom: float = 1.0) -> tuple[int, int, int, int]:
    """Largest rect of `target_aspect` centred on (cx, cy), divided by zoom.

    cx/cy are 0-1 normalised positions in the source frame; zoom > 1 crops tighter.
    The rect is clamped inside the source and kept even-sized for encoders.
    """
    w, h = int(meta["width"]), int(meta["height"])
    zoom = min(max(float(zoom or 1.0), 1.0), MAX_ZOOM)
    if w / h > target_aspect:
        ch = float(h)
        cw = h * target_aspect
    else:
        cw = float(w)
        ch = w / target_aspect
    cw = min(cw / zoom, w)
    ch = min(ch / zoom, h)
    cw = max(2, int(round(cw / 2)) * 2)
    ch = max(2, int(round(ch / 2)) * 2)
    cx = min(max(float(cx if cx is not None else 0.5), 0.0), 1.0)
    cy = min(max(float(cy if cy is not None else 0.5), 0.0), 1.0)
    x = int(round(cx * w - cw / 2))
    y = int(round(cy * h - ch / 2))
    x = max(0, min(x, w - cw))
    y = max(0, min(y, h - ch))
    x -= x % 2
    y -= y % 2
    return cw, ch, x, y


def _auto_focus(frames: list[dict], clip_start: float, clip_end: float,
                pick: str = "first") -> tuple[float, float, int]:
    """Face-derived focus point, plus how many faces were seen on average."""
    near = [f for f in frames if clip_start - 1 <= f.get("t", 0) <= clip_end + 1 and f.get("faces")]
    if not near:
        return 0.5, 0.45, 0
    xs, ys, counts = [], [], []
    for f in near:
        faces = f["faces"]
        counts.append(len(faces))
        face = faces[0] if pick == "first" else max(faces, key=lambda x: x.get("area", 0))
        xs.append(float(face["x"]))
        ys.append(float(face["y"]))
    xs.sort()
    ys.sort()
    return xs[len(xs) // 2], ys[len(ys) // 2], round(sum(counts) / len(counts))


def _dual_focus(frames: list[dict], clip_start: float, clip_end: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Two crop centres for the split layout.

    With two faces in frame we follow them (left face -> top panel, right -> bottom).
    With one face we use a left/right split so the panel still shows content.
    """
    near = [f for f in frames if clip_start - 1 <= f.get("t", 0) <= clip_end + 1 and f.get("faces")]
    if not near:
        return (0.28, 0.45), (0.72, 0.45)
    lefts, rights = [], []
    for f in near:
        faces = sorted(f["faces"], key=lambda x: x["x"])
        if len(faces) >= 2:
            lefts.append(faces[0])
            rights.append(faces[-1])
        else:
            # Single subject: keep one panel on the face, the other on the other half.
            face = faces[0]
            if face["x"] <= 0.5:
                lefts.append(face)
                rights.append({"x": min(face["x"] + 0.45, 0.85), "y": face["y"]})
            else:
                rights.append(face)
                lefts.append({"x": max(face["x"] - 0.45, 0.15), "y": face["y"]})
    def med(items, key):
        vals = sorted(float(i[key]) for i in items)
        return vals[len(vals) // 2] if vals else 0.5
    return (med(lefts, "x"), med(lefts, "y")), (med(rights, "x"), med(rights, "y"))


def _focus_for(meta, frames, start, end, mode, cx, cy, zoom):
    """Resolve the actual crop centre/zoom used for a single-panel layout."""
    if mode == "manual":
        return float(cx if cx is not None else 0.5), float(cy if cy is not None else 0.5), float(zoom or 1.0)
    if mode == "center":
        return 0.5, 0.5, float(zoom or 1.0)
    ax, ay, _faces = _auto_focus(frames, start, end)
    return ax, ay, max(float(zoom or 1.0), 1.0)


def _clamp_centre(meta: dict, target_aspect: float, zoom: float, cx: float, cy: float) -> tuple[float, float]:
    """Clamp a normalised centre so the crop rect stays fully inside the source."""
    w, h = float(meta["width"]), float(meta["height"])
    if w / h > target_aspect:
        cw, ch = h * target_aspect / zoom, h / zoom
    else:
        cw, ch = w / zoom, w / target_aspect / zoom
    hx, hy = cw / w / 2, ch / h / 2
    return min(max(cx, hx), 1 - hx), min(max(cy, hy), 1 - hy)


def _aim(meta: dict, target_aspect: float, zoom: float, fx: float, fy: float) -> tuple[float, float]:
    """Crop centre that puts a face where a person frames it: slightly above centre.

    Also clamps the centre so the crop stays inside the source. The editor
    preview consumes this same path, so the framing it shows is the framing the
    export gets.
    """
    w, h = float(meta["width"]), float(meta["height"])
    if w / h > target_aspect:
        ch = h / zoom
    else:
        ch = w / target_aspect / zoom
    aim_y = fy + 0.07 * (ch / h)
    return _clamp_centre(meta, target_aspect, zoom, fx, aim_y)


def _smooth_path(points: list[tuple[float, float, float]], window: int = 3) -> list[tuple[float, float, float]]:
    """Median-ish smoothing of a (t, x, y) path so the camera glides instead of jittering."""
    if len(points) <= 2:
        return points
    out = []
    for i, (t, x, y) in enumerate(points):
        lo, hi = max(0, i - window // 2), min(len(points), i + window // 2 + 1)
        xs = sorted(p[1] for p in points[lo:hi])
        ys = sorted(p[2] for p in points[lo:hi])
        out.append((t, xs[len(xs) // 2], ys[len(ys) // 2]))
    return out


def _lerp_expr(times: list[float], values: list[float], digits: int = 1, tvar: str = "t") -> str:
    """Build an ffmpeg expression that linearly interpolates values over time.

    `times` are seconds from the start of the trimmed clip, `values` are in
    output pixels. Nested if() keeps it self-contained (no extra filters).
    """
    if not times:
        return "0"
    if len(times) == 1:
        return f"{values[0]:.{digits}f}"
    expr = f"{values[-1]:.{digits}f}"
    for i in range(len(times) - 2, -1, -1):
        dt = max(times[i + 1] - times[i], 0.001)
        rise = values[i + 1] - values[i]
        seg = f"{values[i]:.{digits}f}+({rise:.{digits}f})*(({tvar}-{times[i]:.3f})/{dt:.3f})"
        expr = f"if(lt({tvar},{times[i + 1]:.3f}),{seg},{expr})"
    return expr


def _subject_track(frames: list[dict], start: float, end: float) -> list[tuple[float, float, float]]:
    """Group detections into per-person tracks and return the main subject's path.

    Two things matter here, and both were wrong before:

    * Assignment is **global per frame**. Picking the nearest track face by face
      lets a stray detection grab the established track and push the real person
      onto a brand-new one, which splits a single subject into two tracks.
      Instead every (track, face) pair is scored for the frame and the closest
      pairs are assigned first, so each face gets the track it clearly belongs to.
    * Tracks are **merged** afterwards when one ends where another begins: a
      brief miss (occlusion, a turned head) breaks a track in two, and the two
      halves are still the same person.

    Tracks are then scored by coverage and screen area, with coverage weighted
    more heavily — the subject is the face present through the whole clip, not a
    large face that flashes past once.
    """
    near = [f for f in frames if start - 0.6 <= f.get("t", 0) <= end + 0.6]
    if not near:
        return []

    # (time, x, y, area) points, one list per candidate identity.
    tracks: list[list[tuple[float, float, float, float]]] = []

    for f in near:
        t = float(f.get("t", 0))
        faces = [x for x in (f.get("faces") or []) if not x.get("held")]
        if not faces:
            continue
        pairs: list[tuple[float, int, int]] = []
        for fi, face in enumerate(faces):
            fx, fy = float(face["x"]), float(face["y"])
            for ti, track in enumerate(tracks):
                lt, lx, ly, _la = track[-1]
                gap = t - lt
                # People do not teleport, but a fast pan or a cut can move a face
                # a long way in a second, so the budget grows with the gap.
                if gap > 4.0 or gap <= 0:
                    continue
                d = ((fx - lx) ** 2 + (fy - ly) ** 2) ** 0.5
                # Cap the distance: past ~half the frame it is a scene change,
                # not the same person moving, and following it would make the
                # crop snap across the picture.
                if d <= min(0.12 + 0.3 * gap, 0.5):
                    pairs.append((d, fi, ti))
        pairs.sort()
        used_faces: set[int] = set()
        used_tracks: set[int] = set()
        for _d, fi, ti in pairs:
            if fi in used_faces or ti in used_tracks:
                continue
            face = faces[fi]
            tracks[ti].append((t, float(face["x"]), float(face["y"]),
                               float(face.get("area") or 0.0)))
            used_faces.add(fi)
            used_tracks.add(ti)
        # Anything unmatched starts a new identity.
        for fi, face in enumerate(faces):
            if fi in used_faces:
                continue
            tracks.append([(t, float(face["x"]), float(face["y"]),
                            float(face.get("area") or 0.0))])

    # --- merge tracks that are the same person across a short gap -----------
    tracks.sort(key=lambda tr: tr[0][0])
    merged = True
    while merged:
        merged = False
        for i in range(len(tracks)):
            for j in range(len(tracks)):
                if i == j:
                    continue
                a, b = tracks[i], tracks[j]
                if a[-1][0] <= b[0][0]:
                    gap = b[0][0] - a[-1][0]
                elif b[-1][0] <= a[0][0]:
                    gap = a[0][0] - b[-1][0]
                else:
                    continue  # overlapping in time: two different people
                if gap > 2.5:
                    continue
                d = ((a[-1][1] - b[0][1]) ** 2 + (a[-1][2] - b[0][2]) ** 2) ** 0.5 if a[-1][0] <= b[0][0] \
                    else ((b[-1][1] - a[0][1]) ** 2 + (b[-1][2] - a[0][2]) ** 2) ** 0.5
                if d > 0.08 + 0.12 * gap:
                    continue
                first, second = (a, b) if a[0][0] <= b[0][0] else (b, a)
                first.extend(second)
                first.sort(key=lambda p: p[0])
                tracks.pop(j if j > i else i)
                merged = True
                break
            if merged:
                break

    total = max(len(near), 1)

    def score(track: list[tuple[float, float, float, float]]) -> tuple[float, float]:
        coverage = len(track) / total
        mean_area = sum(p[3] for p in track) / max(len(track), 1)
        # Coverage first: a facecam face is present all clip and should win over
        # a bigger face that only appears briefly.
        return (coverage ** 1.5 * (mean_area + 1e-6), coverage)

    if not tracks:
        return []
    keep = [tr for tr in tracks if len(tr) >= 3] or tracks
    best_track = max(keep, key=score)
    return [(p[0], p[1], p[2]) for p in sorted(best_track, key=lambda p: p[0])]


def _track_path(meta: dict, frames: list[dict], start: float, end: float,
                target_aspect: float, zoom: float) -> tuple[list[float], list[float], list[float]]:
    """Camera path that follows one subject across the clip.

    Returns normalised (times, xs, ys) where times are clip-relative seconds.

    The subject is chosen from continuous tracks rather than per-frame picks, so
    the camera does not hop between two people, and gaps hold the last known
    position instead of drifting to the centre.
    """
    span = max(end - start, 0.1)
    track = _subject_track(frames, start, end)
    if not track:
        return [0.0, span], [0.5, 0.5], [0.45, 0.45]

    raw: list[tuple[float, float, float]] = []
    i = 0
    last = (track[0][1], track[0][2])
    # Walk the clip in ~0.5s steps, using the track where it has a sighting.
    steps = max(int(round(span / 0.5)), 2)
    for k in range(steps + 1):
        t = round(min(k * span / steps, span), 3)
        src_t = start + t
        while i + 1 < len(track) and track[i + 1][0] <= src_t:
            i += 1
        if abs(track[i][0] - src_t) <= 0.9:
            last = (track[i][1], track[i][2])
        elif i + 1 < len(track) and abs(track[i + 1][0] - src_t) <= 0.9:
            last = (track[i + 1][1], track[i + 1][2])
        cx, cy = _aim(meta, target_aspect, zoom, last[0], last[1])
        raw.append((t, cx, cy))
    if raw[0][0] > 0:
        raw.insert(0, (0.0, raw[0][1], raw[0][2]))
    if raw[-1][0] < span:
        raw.append((span, raw[-1][1], raw[-1][2]))

    smooth = _smooth_path(raw, window=5)
    thin: list[tuple[float, float, float]] = []
    for p in smooth:
        if not thin or p[0] - thin[-1][0] >= 1.0 or p is smooth[-1]:
            thin.append(p)
    if len(thin) < 2:
        thin = [smooth[0], smooth[-1]]
    return [p[0] for p in thin], [p[1] for p in thin], [p[2] for p in thin]


def _keyframe_chain(meta: dict, aspect: str, start: float, end: float, keyframes: list[dict],
                    opts: dict, fps: float = 30.0) -> list[str] | None:
    """Animated camera path driven by user keyframes (position + zoom over time).

    Each keyframe is {t (clip-relative seconds), x, y, zoom}; values interpolate
    linearly between neighbours and hold beyond the ends.

    The frame is cropped once to the largest window of the output aspect (centred
    on the average keyframe position), then zoompan pans and zooms inside it. Two
    details matter and are easy to get wrong:

    * zoompan must run at the same frame rate as the graph, otherwise it buffers
      frames internally and the output stalls or comes out blank.
    * a centre near the edge of the source cannot be reached at high zoom, so
      positions are clamped exactly the way the editor preview clamps them.
    """
    span = max(end - start, 0.1)
    ow, oh = ASPECTS[aspect]
    target_aspect = ow / oh
    marks: list[tuple[float, float, float]] = []
    for kf in keyframes or []:
        try:
            t = float(kf.get("t", 0))
            x = float(kf.get("x", 0.5))
            y = float(kf.get("y", 0.45))
            z = float(kf.get("zoom", 1.0))
        except (TypeError, ValueError):
            continue
        marks.append((min(max(t, 0.0), span), min(max(x, 0.0), 1.0),
                      min(max(y, 0.0), 1.0), max(z, 1.0)))
    if len(marks) < 2:
        return None
    marks.sort(key=lambda m: m[0])
    if marks[0][0] > 0:
        marks.insert(0, (0.0, marks[0][1], marks[0][2], marks[0][3]))
    if marks[-1][0] < span:
        marks.append((span, marks[-1][1], marks[-1][2], marks[-1][3]))
    cleaned: list[tuple[float, float, float, float]] = []
    for m in marks:
        if cleaned and abs(m[0] - cleaned[-1][0]) < 0.05:
            cleaned[-1] = m
        else:
            cleaned.append(m)
    marks = cleaned
    if len(marks) < 2:
        return None

    # Base window: largest output-aspect crop of the source, positioned near the
    # average keyframe so as much of the path as possible stays reachable.
    base_w, base_h, _bx, _by = crop_rect(meta, target_aspect, 0.5, 0.5, 1.0)
    sw, sh = float(meta["width"]), float(meta["height"])
    mean_x = sum(m[1] for m in marks) / len(marks)
    mean_y = sum(m[2] for m in marks) / len(marks)
    base_x = int(round(min(max(mean_x * sw - base_w / 2, 0), sw - base_w)))
    base_y = int(round(min(max(mean_y * sh - base_h / 2, 0), sh - base_h)))

    times = [m[0] for m in marks]
    # Where each keyframe's centre sits inside the base window (0-1), clamped so
    # the zoomed window stays inside the picture.
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for _t, x, y, z in marks:
        hx = 1 / (2 * z)
        xs.append(min(max((x * sw - base_x) / base_w, hx), 1 - hx))
        ys.append(min(max((y * sh - base_y) / base_h, hx * (base_w / base_h)), 1 - hx * (base_w / base_h)))
        zs.append(z)

    cxs = _lerp_expr(times, xs, digits=5, tvar="in_time")
    cys = _lerp_expr(times, ys, digits=5, tvar="in_time")
    zexpr = _lerp_expr(times, zs, digits=4, tvar="in_time")
    xexpr = f"min(max(({cxs})*iw-iw/(2*({zexpr})),0),iw-iw/({zexpr}))"
    yexpr = f"min(max(({cys})*ih-ih/(2*({zexpr})),0),ih-ih/({zexpr}))"

    chain = (
        f"[vcut]crop={base_w}:{base_h}:{base_x}:{base_y},"
        f"fps={fps:.3f},"
        f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1"
        f":s={ow}x{oh}:fps={fps:.3f},"
        f"scale={ow}:{oh},setsar=1[vframed]"
    )
    return [chain]


def _build_video_frames(meta: dict, aspect: str, frames: list[dict], start: float, end: float,
                        opts: dict) -> tuple[list[str], str, str]:
    """Compose the crop/stack graph.

    Returns (filter_chains, input_label_used, output_size). The caller supplies the
    base video label as [vcut]; chains consume and produce [vframed].
    """
    w, h = int(meta["width"]), int(meta["height"])
    ow, oh = ASPECTS[aspect]
    mode = opts.get("crop_mode") or "face-track"
    zoom = float(opts.get("crop_zoom") or 1.0)

    if mode == "dual":
        half_h = oh // 2
        panel_aspect = ow / half_h
        # `.get(k, default)` returns None when the caller passed the key with a
        # None value, which is exactly what the render endpoint does for clips
        # that were never hand-framed. Use `or` so those fall back.
        top_cx = float(opts.get("dual_top_x") if opts.get("dual_top_x") is not None else 0.28)
        top_cy = float(opts.get("dual_top_y") if opts.get("dual_top_y") is not None else 0.45)
        bot_cx = float(opts.get("dual_bottom_x") if opts.get("dual_bottom_x") is not None else 0.72)
        bot_cy = float(opts.get("dual_bottom_y") if opts.get("dual_bottom_y") is not None else 0.45)
        if opts.get("dual_auto", True):
            (ax, ay), (bx, by) = _dual_focus(frames, start, end)
            if opts.get("dual_top_x") is None:
                top_cx, top_cy = ax, ay
            if opts.get("dual_bottom_x") is None:
                bot_cx, bot_cy = bx, by
        tz = float(opts.get("dual_top_zoom") or 1.0)
        bz = float(opts.get("dual_bottom_zoom") or 1.0)
        tw, th, tx, ty = crop_rect(meta, panel_aspect, top_cx, top_cy, max(tz, 1.0))
        bw, bh, bx_, by_ = crop_rect(meta, panel_aspect, bot_cx, bot_cy, max(bz, 1.0))
        chains = [
            f"[vcut]split=2[da][db]",
            f"[da]crop={tw}:{th}:{tx}:{ty},scale={ow}:{half_h}:flags=bilinear,setsar=1[vtop]",
            f"[db]crop={bw}:{bh}:{bx_}:{by_},scale={ow}:{half_h}:flags=bilinear,setsar=1[vbot]",
            "[vtop][vbot]vstack=inputs=2[vframed]",
        ]
        return chains, "[vframed]", f"{ow}:{oh}"

    if mode == "inset":
        # Background takes the whole shot; the inset is a second, user-chosen
        # rectangle of the same source placed on top. This is the facecam-over-
        # gameplay layout: gameplay stays readable behind, the face sits in a
        # corner window.
        bg_fit = str(opts.get("inset_bg_fit") or "cover")
        bg_cx = float(opts.get("inset_bg_x") if opts.get("inset_bg_x") is not None else 0.5)
        bg_cy = float(opts.get("inset_bg_y") if opts.get("inset_bg_y") is not None else 0.5)
        bg_z = max(float(opts.get("inset_bg_zoom") or 1.0), 1.0)

        shape = str(opts.get("inset_shape") or "16:9")
        try:
            sh_num, sh_den = [float(v) for v in shape.split(":")]
            inset_aspect = sh_num / sh_den
        except Exception:
            inset_aspect = 16 / 9

        size = min(max(float(opts.get("inset_size") if opts.get("inset_size") is not None else 0.3), 0.12), 0.7)
        iw = int(round(ow * size))
        ih = int(round(iw / inset_aspect))
        if ih > int(oh * 0.9):
            ih = int(oh * 0.9)
            iw = int(round(ih * inset_aspect))
        iw -= iw % 2
        ih -= ih % 2

        in_cx = float(opts.get("inset_x") if opts.get("inset_x") is not None else 0.5)
        in_cy = float(opts.get("inset_y") if opts.get("inset_y") is not None else 0.5)
        in_z = max(float(opts.get("inset_zoom") or INSET_DEFAULT_ZOOM), 1.0)
        cw, ch, cx_, cy_ = crop_rect(meta, inset_aspect, in_cx, in_cy, in_z)

        # Where the window sits inside the output frame.
        pos_x = min(max(float(opts.get("inset_pos_x") if opts.get("inset_pos_x") is not None else 0.78), 0), 1)
        pos_y = min(max(float(opts.get("inset_pos_y") if opts.get("inset_pos_y") is not None else 0.8), 0), 1)
        ox = int(round(pos_x * ow - iw / 2))
        oy = int(round(pos_y * oh - ih / 2))
        ox = max(0, min(ox, ow - iw))
        oy = max(0, min(oy, oh - ih))
        ox -= ox % 2
        oy -= oy % 2

        work = opts.get("work")
        radius_pct = min(max(float(opts.get("inset_radius") if opts.get("inset_radius") is not None else 4.0), 0.0), 50.0)
        # `opts` carries explicit None values for clips that never set these, and
        # `bool(None)` is False — which silently disabled the outline. Absent or
        # None must both mean "on".
        border_on = opts.get("inset_border") is not False
        # Width is specified for a 1080-wide frame so it scales with the output.
        border_px = int(round(max(float(opts.get("inset_border_width") if opts.get("inset_border_width") is not None else 5), 0) * ow / 1080))
        if not border_on:
            border_px = 0
        border_color = str(opts.get("inset_border_color") or "#ffffff")
        want_shadow = opts.get("inset_shadow") is not False

        assets: dict = {}
        if work is not None and (radius_pct > 0 or border_px > 0 or want_shadow):
            assets = _rounded_inset_assets(Path(work), iw, ih, radius_pct,
                                           border_px, border_color, want_shadow)

        bg_chains: list[str]
        if bg_fit == "blur":
            bg_chains = [
                "[vcut]split=2[bga][ina]",
                f"[bga]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},"
                f"boxblur=32:2,eq=brightness=-0.10[bgv]",
            ]
        else:
            bcw, bch, bx_, by_ = crop_rect(meta, ow / oh, bg_cx, bg_cy, bg_z)
            bg_chains = [
                "[vcut]split=2[bga][ina]",
                f"[bga]crop={bcw}:{bch}:{bx_}:{by_},scale={ow}:{oh}:flags=bilinear,setsar=1[bgv]",
            ]

        crop_chain = f"[ina]crop={cw}:{ch}:{cx_}:{cy_},scale={iw}:{ih}:flags=bilinear,setsar=1"
        chain = list(bg_chains)
        pad = int(assets.get("shadow_pad") or 0)

        # 1) soft drop shadow behind the window
        if "shadow" in assets:
            sh_path = _filter_path(assets["shadow"])
            chain.append(f"movie='{sh_path}',format=rgba[simg]")
            chain.append(
                f"[bgv][simg]overlay={max(ox - pad, 0)}:{max(oy - pad, 0)}:format=auto:"
                f"eof_action=repeat[bgsh]"
            )
            cur = "[bgsh]"
        else:
            cur = "[bgv]"

        # 2) the crop itself, clipped to a rounded, antialiased mask
        if "mask" in assets:
            mask_path = _filter_path(assets["mask"])
            chain.append(f"{crop_chain}[inx]")
            chain.append(f"movie='{mask_path}',format=gray[msk]")
            chain.append("[inx][msk]alphamerge,format=rgba[iround]")
            chain.append(f"{cur}[iround]overlay={ox}:{oy}:format=auto:eof_action=repeat[vwin]")
            cur = "[vwin]"
        else:
            # Square fallback: still exact, just no curve.
            chain.append(f"{crop_chain}[iround]")
            chain.append(f"{cur}[iround]overlay={ox}:{oy}:format=auto:eof_action=repeat[vwin]")
            cur = "[vwin]"

        # 3) the outline, drawn inside the rounded shape
        if "ring" in assets:
            ring_path = _filter_path(assets["ring"])
            chain.append(f"movie='{ring_path}',format=rgba[rimg]")
            chain.append(f"{cur}[rimg]overlay={ox}:{oy}:format=auto:eof_action=repeat[vring]")
            cur = "[vring]"

        chain.append(f"{cur}scale={ow}:{oh},setsar=1[vframed]")
        return chain, "[vframed]", f"{ow}:{oh}"

    if mode == "pad" or (mode != "dual" and (w / h) < (ow / oh) * 0.82):
        # Full-frame mode letterboxes the whole shot, which leaves a lot of the
        # 9:16 frame empty on a 16:9 source. `crop_zoom` scales the contained
        # video up and centre-crops the excess, so the subject fills more of the
        # frame without the whole shot being cut away.
        pad_zoom = min(max(float(opts.get("crop_zoom") or 1.0), 1.0), 4.0)
        fw, fh = int(round(ow * pad_zoom)), int(round(oh * pad_zoom))
        if pad_zoom > 1.001:
            # Scale until the picture covers the enlarged box, then centre-crop
            # back to the frame. `increase` is required: `decrease` can leave an
            # axis smaller than the crop box and crop then fails outright.
            fg = (f"[fg]scale={fw}:{fh}:force_original_aspect_ratio=increase,"
                  f"crop={ow}:{oh}[fgv]")
        else:
            fg = f"[fg]scale={ow}:{oh}:force_original_aspect_ratio=decrease[fgv]"
        chains = [
            f"[vcut]split=2[bg][fg]",
            f"[bg]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},"
            f"boxblur=40:2,eq=brightness=-0.12[bgv]",
            fg,
            f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2:format=auto,scale={ow}:{oh},setsar=1[vframed]",
        ]
        return chains, "[vframed]", f"{ow}:{oh}"

    target_aspect = ow / oh
    if mode != "pad":
        kf_chain = _keyframe_chain(meta, aspect, start, end, opts.get("keyframes") or [], opts,
                                   fps=float(opts.get("fps") or 30.0))
        if kf_chain:
            return kf_chain, "[vframed]", f"{ow}:{oh}"

    tracked = bool(opts.get("track_motion", True)) and mode == "face-track"

    if tracked:
        times, xs, ys = _track_path(meta, frames, start, end, target_aspect, max(zoom, 1.0))
        cw, ch, _x, _y = crop_rect(meta, target_aspect, 0.5, 0.5, max(zoom, 1.0))
        # Convert normalised centres to pixel offsets, then interpolate over time.
        px = [min(max(c * meta["width"] - cw / 2, 0), meta["width"] - cw) for c in xs]
        py = [min(max(c * meta["height"] - ch / 2, 0), meta["height"] - ch) for c in ys]
        xexpr = _lerp_expr(times, px)
        yexpr = _lerp_expr(times, py)
        chain = (
            f"[vcut]crop={cw}:{ch}:x='{xexpr}':y='{yexpr}',"
            f"scale={ow}:{oh}:flags=bilinear,setsar=1[vframed]"
        )
        return [chain], "[vframed]", f"{ow}:{oh}"

    cx, cy, z = _focus_for(meta, frames, start, end, mode,
                           opts.get("crop_x"), opts.get("crop_y"), zoom)
    cw, ch, x, y = crop_rect(meta, target_aspect, cx, cy, z)
    chain = f"[vcut]crop={cw}:{ch}:{x}:{y},scale={ow}:{oh}:flags=bilinear,setsar=1[vframed]"
    return [chain], "[vframed]", f"{ow}:{oh}"


def _music_track(dest: Path, duration: float, mood: str) -> Path | None:
    spec = MUSIC_MOODS.get(mood)
    if not spec:
        return None
    freq, _wave = spec
    fade_out = max(duration - 1.2, 0)
    # Procedural royalty-free ambient bed: root + fifth, slow tremolo, fades
    af2 = (
        f"sine=frequency={freq}:duration={duration:.3f}[b1];"
        f"sine=frequency={freq * 1.5:.3f}:duration={duration:.3f}[b2];"
        f"[b1][b2]amix=inputs=2:weights=1 0.45,volume=0.30,"
        f"tremolo=f={88 if mood == 'upbeat' else 52}:d=0.4,"
        f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out:.2f}:d=1.2[out]"
    )
    run(["ffmpeg", "-y", "-v", "error", "-filter_complex", af2, "-map", "[out]", "-t",
         f"{duration:.3f}", "-ar", "44100", "-ac", "2", str(dest)], timeout=120)
    return dest


def render_clip(project: dict, clip: dict, options: dict, out_name: str | None = None,
                progress=None) -> dict:
    """Render one clip to a real MP4 with captions, crop, cuts and audio processing."""
    src = Path(project["file_path"])
    meta = project.get("meta") or probe(src)
    clip_start = float(clip["start"])
    clip_end = float(clip["end"])

    trim_start = max(float(options.get("trim_start", 0) or 0), 0)
    trim_end = max(float(options.get("trim_end", 0) or 0), 0)
    start = clip_start + trim_start
    end = clip_end - trim_end
    if end - start < 1.0:
        raise MediaError("Clip is too short after trimming. Leave at least 1 second.")
    aspect = options.get("aspect") or clip.get("aspect") or "9:16"
    if aspect not in ASPECTS:
        aspect = "9:16"
    crop_mode = options.get("crop_mode") or "face-track"
    style_name = options.get("caption_style") or "bold-pop"
    if style_name not in CAPTION_STYLES:
        style_name = "bold-pop"
    position = options.get("caption_position") or "bottom"
    font_size = options.get("caption_size")
    smart = bool(options.get("smart_cuts"))
    denoise = bool(options.get("denoise", True))
    zoom = bool(options.get("zoom"))
    volume = float(options.get("volume", 1.0) or 1.0)
    music = options.get("music") or "none"
    music_volume = float(options.get("music_volume", 0.12) or 0)
    watermark = (options.get("watermark") or "").strip()
    watermark_size = min(max(float(options.get("watermark_size") or 100), 50.0), 220.0)
    captions_enabled = options.get("captions_enabled") is not False
    # Words per caption cue. The editor exposes this as a slider; None keeps the
    # style's readable default (5).
    caption_words = options.get("caption_words")
    # On by default: the endpoint sends every key, unset ones as None.
    keywords_enabled = options.get("keywords_enabled") is not False
    emoji_enabled = options.get("emoji_enabled") is not False
    overlays = options.get("overlays") or []
    headline = str(options.get("headline") or "").strip()
    headline_on = bool(options.get("headline_enabled", True)) and bool(headline)
    progress_bar = bool(options.get("progress_bar"))
    accent = options.get("accent_color") or None
    remove_fillers = bool(options.get("remove_fillers"))
    font_choice = options.get("caption_font") or None
    # Keyframes are stored clip-relative; the graph starts at the trim point.
    keyframes = [
        {**kf, "t": float(kf.get("t", 0)) - trim_start}
        for kf in (options.get("keyframes") or [])
        if isinstance(kf, dict)
    ]

    out_dir = CLIPS
    out_dir.mkdir(parents=True, exist_ok=True)
    final_name = out_name or f"{clip['id']}-{int(time.time())}.mp4"
    out_path = out_dir / final_name

    frames = []
    try:
        from .media import cached_frames
        frames = (cached_frames(src, meta["duration"], sample_every=0.5,
                                media_hash=project.get("media_hash")).get("frames") or [])
    except Exception:
        frames = []

    # --- smart cuts: build keep-ranges relative to the full source ---
    keep_abs: list[tuple[float, float]] = [(start, end)]
    removed = 0.0
    if smart:
        fill = filler_ranges(clip.get("words") or [], start, end) if remove_fillers else None
        keep_rel, removed = compute_cuts(src, start, end, fill)
        keep_abs = [(start + a, start + b) for a, b in keep_rel]
        if not keep_abs:
            keep_abs = [(start, end)]

    # timeline mapping: source time -> output time
    def to_out(t: float) -> float:
        acc = 0.0
        for (a, b) in keep_abs:
            if t <= a:
                return acc
            if t <= b:
                return acc + (t - a)
            acc += b - a
        return acc

    out_duration = sum(b - a for a, b in keep_abs)

    # --- captions ---
    work = Path(tempfile.mkdtemp(prefix="cliprender-", dir=str(EXPORTS)))
    try:
        words = clip.get("words") or []
        cues = []
        if words:
            # rebuild cues with shot-relative timing and post-cut remap
            raw = word_captions(words, start, end, style_name,
                                max_words=caption_words) if captions_enabled else []
            for cue in raw:
                # convert output-time cue back to source for remap
                src_t0 = start + cue["start"]
                src_t1 = start + cue["end"]
                if not any(a <= src_t0 <= b + 0.4 for a, b in keep_abs):
                    continue
                cue2 = dict(cue)
                cue2["start"] = to_out(src_t0)
                cue2["end"] = max(to_out(src_t1), cue2["start"] + 0.18)
                cues.append(cue2)

        ow, oh = ASPECTS[aspect]
        ass_path = work / "captions.ass"
        if cues:
            build_ass(cues, style_name, ass_path, ow, oh, position,
                      int(font_size) if font_size else None,
                      accent=accent, font=font_choice,
                      keywords_enabled=keywords_enabled)

        fps = min(max(meta.get("fps") or 30, 24), 60)
        frame_chains, framed_label, size = _build_video_frames(
            meta, aspect, frames, start, end, {
                "crop_mode": crop_mode,
                "crop_x": options.get("crop_x"),
                "crop_y": options.get("crop_y"),
                "crop_zoom": options.get("crop_zoom"),
                "dual_top_x": options.get("dual_top_x"),
                "dual_top_y": options.get("dual_top_y"),
                "dual_top_zoom": options.get("dual_top_zoom"),
                "dual_bottom_x": options.get("dual_bottom_x"),
                "dual_bottom_y": options.get("dual_bottom_y"),
                "dual_bottom_zoom": options.get("dual_bottom_zoom"),
                "dual_auto": options.get("dual_auto", True),
                "inset_x": options.get("inset_x"), "inset_y": options.get("inset_y"),
                "inset_zoom": options.get("inset_zoom"), "inset_size": options.get("inset_size"),
                "inset_shape": options.get("inset_shape"),
                "inset_pos_x": options.get("inset_pos_x"), "inset_pos_y": options.get("inset_pos_y"),
                "inset_bg_fit": options.get("inset_bg_fit"),
                "inset_bg_x": options.get("inset_bg_x"), "inset_bg_y": options.get("inset_bg_y"),
                "inset_bg_zoom": options.get("inset_bg_zoom"),
                "inset_border": options.get("inset_border", True),
                "inset_border_color": options.get("inset_border_color"),
                "inset_border_width": options.get("inset_border_width"),
                "inset_radius": options.get("inset_radius"),
                "inset_shadow": options.get("inset_shadow", True),
                "work": work,
                "track_motion": options.get("track_motion", True),
                "keyframes": keyframes,
                "fps": fps,
            })

        # --- filter graph ---
        vf_parts: list[str] = []
        if smart and len(keep_abs) > 1:
            # select+asetpts style: trim per range with concat
            n = len(keep_abs)
            chains = []
            for i, (a, b) in enumerate(keep_abs):
                chains.append(f"[0:v]trim=start={a - start:.3f}:end={b - start:.3f},setpts=PTS-STARTPTS[v{i}]")
            concat_inputs = "".join(f"[v{i}]" for i in range(n))
            chains.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vcut]")
            v_src = "[vcut]"
            vf_parts.extend(chains)
        else:
            vf_parts.append(f"[0:v]trim=start=0:end={out_duration:.3f},setpts=PTS-STARTPTS[vcut]")
            v_src = "[vcut]"

        # frame composition (crop / dual stack / blur pad)
        chains = [c.replace("[vcut]", v_src, 1) if i == 0 else c for i, c in enumerate(frame_chains)]
        vf_parts.extend(chains)
        # No colour grade here: the editor preview shows the source as-is, and
        # a hidden contrast/saturation bump made every export look different
        # from what was on screen. Only the format conversion is needed.
        vf_parts.append(f"{framed_label}fps={fps},format=yuv420p[vbase]")
        v_cur = "[vbase]"
        if zoom:
            # slow subtle zoom-in, centred; zoompan keeps output size stable
            vf_parts.append(
                f"{v_cur}zoompan=z='min(zoom+0.0006,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={size.replace(':', 'x')}:fps={fps}[vzoom]"
            )
            v_cur = "[vzoom]"
        if cues:
            vf_parts.append(f"{v_cur}subtitles='{ass_path.as_posix()}':fontsdir='/usr/share/fonts'[vcap]")
            v_cur = "[vcap]"
        if cues and emoji_enabled:
            # Colour emoji cannot be drawn by libass, so each cue's emoji is a
            # transparent PNG composited above the caption block. One per cue,
            # and never the same emoji twice in a row (that strobed on screen).
            emoji_size = max(int(round(0.085 * oh * (float(font_size or 100) / 100.0))), 32)
            items: list[dict] = [
                {"emoji": item["emoji"],
                 "start": cues[item["index"]]["start"],
                 "end": cues[item["index"]]["end"]}
                for item in emphasis.plan_emoji(cues)[:16]
            ]
            # Sit the emoji beside the caption band, not on top of the words:
            # bottom captions get it above-right, centre gets it right, top gets
            # it above the block. Clamped so it never leaves the frame.
            if position == "center":
                ex, ey = 0.78, 0.34
            elif position == "top":
                ex, ey = 0.80, 0.20
            else:
                ex, ey = 0.76, 0.685
            x_px = int(ow * ex)
            y_px = int(oh * ey)
            x_px = max(0, min(x_px, ow - emoji_size))
            y_px = max(0, min(y_px, oh - emoji_size))
            for idx, item in enumerate(emphasis.emoji_assets(work, items, emoji_size)):
                a = max(float(item["start"]), 0.0)
                b = max(float(item["end"]), a + 0.2)
                # A soft pop-in: overlay has no scale animation, so fade is done
                # by the caption fad timing; keep the emoji static and crisp.
                vf_parts.append(
                    f"movie='{Path(item['path']).as_posix()}',format=rgba,"
                    f"scale={emoji_size}:{emoji_size}[em{idx}]"
                )
                vf_parts.append(
                    f"{v_cur}[em{idx}]overlay=x={x_px}:y={y_px}:"
                    f"enable='between(t,{a:.3f},{b:.3f})'[ve{idx}]"
                )
                v_cur = f"[ve{idx}]"
        # overlays: wrapped to the frame width, stacked per band, or placed where
        # the user dragged them.
        live = [ov for ov in overlays[:6] if str(ov.get("text") or "").strip()]
        wrapped: list[dict] = []
        for ov in live:
            size_px = max(int(round(float(ov.get("size", 54)) * oh / 1920)), 12)
            # ~0.62 em average glyph width for a bold sans at this size.
            max_chars = max(int((ow * 0.86) / (size_px * 0.62)), 8)
            wrapped.append({**ov, "text": _wrap_overlay(str(ov.get("text")), max_chars)})
        columns = _overlay_columns(wrapped, oh)
        for idx, ov in enumerate(wrapped):
            # Write the text to its own file: drawtext renders real newlines from
            # a file, whereas inline text has to be escaped and loses them.
            text_file = work / f"overlay-{idx}.txt"
            text_file.write_text(ov["text"], encoding="utf-8")
            size_px = max(int(round(float(ov.get("size", 54)) * oh / 1920)), 12)
            color = str(ov.get("color") or "#ffffff")
            if not color.startswith("#"):
                color = {"white": "#ffffff", "black": "#000000", "yellow": "#ffe066"}.get(color, "#ffffff")
            color = color.replace("#", "0x")
            x_expr, y_expr = columns.get(idx, ("(W-text_w)/2", "H*0.06"))
            start_t = max(float(ov.get("start", 0) or 0), 0)
            end_t = max(float(ov.get("end", out_duration) or out_duration), start_t + 0.1)
            vf_parts.append(
                f"{v_cur}drawtext=textfile='{text_file.as_posix()}':{_font_arg('extrabold')}"
                f":fontcolor={color}:fontsize={size_px}"
                f":line_spacing={max(int(size_px * 0.14), 2)}:borderw=3:bordercolor=black@0.6"
                f":text_align=center:x='{x_expr}':y='{y_expr}'"
                f":enable='between(t,{start_t:.2f},{end_t:.2f})'[vo{idx}]"
            )
            v_cur = f"[vo{idx}]"
        if headline_on:
            # The preview wraps the headline inside the frame and centres the
            # block, so the export must wrap too: one long unwrapped line ran
            # past both edges and started higher up the frame.
            h_size = max(int(58 * oh / 1920), 12)
            show_for = min(max(float(options.get("headline_seconds", 4) or 4), 1.0), out_duration)
            accent_hex = (accent or "#ffffff").replace("#", "0x")
            h_max = max(int((ow * 0.88) / (h_size * 0.58)), 8)
            h_rows = _wrap_overlay(headline, h_max)
            head_file = work / "headline.txt"
            head_file.write_text(h_rows, encoding="utf-8")
            n_rows = h_rows.count("\n") + 1
            head_y = 0.055
            vf_parts.append(
                f"{v_cur}drawtext=textfile='{head_file.as_posix()}':{_font_arg('extrabold')}"
                f":fontcolor=white:fontsize={h_size}"
                f":line_spacing={max(int(h_size * 0.14), 2)}:borderw=4:bordercolor=black@0.55"
                f":text_align=center:x=(W-text_w)/2:y=H*{head_y}:"
                f"enable='between(t,0.15,{show_for:.2f})'[vhead]"
            )
            v_cur = "[vhead]"
            # Thin accent underline directly under the block, wherever it ends.
            block_h = int(h_size * 1.14 * n_rows)
            vf_parts.append(
                f"{v_cur}drawbox=x=(iw-{int(120 * ow / 1080)})/2:"
                f"y=ih*{head_y}+{block_h + max(int(h_size * 0.3), 8)}:"
                f"w={int(120 * ow / 1080)}:h={max(int(6 * oh / 1920), 3)}:color={accent_hex}@0.95:t=fill:"
                f"enable='between(t,0.15,{show_for:.2f})'[vheadline]"
            )
            v_cur = "[vheadline]"
        if progress_bar and out_duration > 0.5:
            # Single animated overlay instead of 60 chained drawbox filters:
            # smooth per-frame motion and much faster to render.
            bar_h = max(int(20 * oh / 1920), 10)
            accent_hex = (accent or "#8b5cf6").replace("#", "0x")
            vf_parts.append(
                f"{v_cur}drawbox=x=0:y=ih-{bar_h}:w=iw:h={bar_h}:color=black@0.35:t=fill[vpgbg]"
            )
            vf_parts.append(
                f"color=c={accent_hex}@0.95:s={ow}x{bar_h}:r={fps}:d={out_duration:.3f}[vpgbar]"
            )
            vf_parts.append(
                f"[vpgbg][vpgbar]overlay=x='-w+(t/{out_duration:.3f})*w':y=H-{bar_h}:shortest=1[vpg]"
            )
            v_cur = "[vpg]"
        if watermark:
            safe = watermark.replace("'", "’").replace(":", "\\:")[:40]
            wm_size = max(int(round(36 * (watermark_size / 100.0) * oh / 1920)), 14)
            wm_pad = max(int(round(wm_size * 0.34)), 6)
            wm_mx = max(int(round(36 * ow / 1080)), 16)
            wm_my = max(int(round((68 if progress_bar else 46) * oh / 1920)), 24)
            vf_parts.append(
                f"{v_cur}drawtext=text='{safe}':font='Inter':fontcolor=white@0.92:fontsize={wm_size}"
                f":box=1:boxcolor=black@0.42:boxborderw={wm_pad}"
                f":shadowcolor=black@0.55:shadowx=0:shadowy=2"
                f":x=W-text_w-{wm_mx}:y=H-text_h-{wm_my}[vwm]"
            )
            v_cur = "[vwm]"
        vf_parts.append(f"{v_cur}null[vfinal]")

        # --- audio graph ---
        af_parts: list[str] = []
        if smart and len(keep_abs) > 1:
            n = len(keep_abs)
            for i, (a, b) in enumerate(keep_abs):
                af_parts.append(f"[0:a]atrim=start={a - start:.3f}:end={b - start:.3f},asetpts=PTS-STARTPTS[a{i}]")
            af_parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acut]")
            a_cur = "[acut]"
        else:
            af_parts.append(f"[0:a]atrim=start=0:end={out_duration:.3f},asetpts=PTS-STARTPTS[acut]")
            a_cur = "[acut]"
        chain = []
        if denoise:
            chain.append("afftdn=nf=-24")
        chain.append(f"volume={volume:.2f}")
        chain.append("loudnorm=I=-15:TP=-1.5:LRA=9")
        af_parts.append(f"{a_cur}{','.join(chain)}[abase]")
        a_cur = "[abase]"

        music_file = None
        if music in MUSIC_MOODS and MUSIC_MOODS[music]:
            music_file = work / "music.wav"
            _music_track(music_file, out_duration, music)
            af_parts.append(f"[1:a]volume={max(music_volume, 0):.2f},atrim=0:{out_duration:.3f},asetpts=PTS-STARTPTS[amus]")
            af_parts.append(f"[abase][amus]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.7[amix]")
            a_cur = "[amix]"
        af_parts.append(f"{a_cur}alimiter=limit=0.95[afinal]")

        filter_script = work / "filters.txt"
        filter_script.write_text(";\n".join(vf_parts + af_parts))
        if options.get("debug_filters"):
            import shutil as _sh
            _sh.copy(filter_script, "/tmp/filters_debug.txt")

        cmd = ["ffmpeg", "-y", "-v", "error", "-stats_period", "0.5",
               "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src)]
        if music_file:
            cmd += ["-i", str(music_file)]
        cmd += ["-filter_complex_script", str(filter_script),
                "-map", "[vfinal]", "-map", "[afinal]",
                # CRF keeps quality constant while the cap stops long clips from
                # ballooning. faststart moves the index to the front so players
                # can begin playback before the whole file is downloaded.
                "-c:v", "libx264", "-preset", "superfast", "-crf", "24", "-threads", "0",
                "-maxrate", "6M", "-bufsize", "12M",
                "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
                "-g", str(max(int(fps * 2), 48)),
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-movflags", "+faststart", "-shortest", str(out_path)]

        if progress:
            progress(0.15, "Rendering video")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if proc.returncode != 0 or not out_path.exists():
            raise MediaError((proc.stderr or "FFmpeg render failed")[-900:])
        info = probe(out_path)
        if progress:
            progress(1.0, "Render complete")
        return {
            "path": str(out_path),
            "filename": out_path.name,
            "url": f"/media/clips/{out_path.name}",
            "size": info["size"],
            "duration": info["duration"],
            "width": info["width"],
            "height": info["height"],
            "cut_seconds": round(removed, 2),
            "caption_cues": len(cues),
            "rendered_at": time.time(),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
