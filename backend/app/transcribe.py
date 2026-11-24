from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from .config import CACHE, WHISPER_DIR, WHISPER_MODEL

_model_lock = threading.Lock()
_model = None
_model_name = None


def get_model(name: str | None = None):
    global _model, _model_name
    name = name or WHISPER_MODEL
    with _model_lock:
        if _model is None or _model_name != name:
            from faster_whisper import WhisperModel

            _model = WhisperModel(name, device="cpu", compute_type="int8", download_root=WHISPER_DIR)
            _model_name = name
        return _model


def transcribe(wav: Path, duration: float, cache_key: str, progress=None, model_name: str | None = None) -> dict:
    """Transcribe with word timestamps. Cached by audio content hash."""
    cache_file = CACHE / f"{cache_key}.transcript.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            if data.get("segments"):
                if progress:
                    progress(1.0, "Loaded cached transcript")
                return data
        except Exception:
            pass

    model = get_model(model_name)
    if progress:
        progress(0.05, "Loading speech recognition model")
    segments_iter, info = model.transcribe(
        str(wav),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 450},
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    segments: list[dict] = []
    for seg in segments_iter:
        words = []
        for w in (seg.words or []):
            words.append({
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
                "word": (w.word or "").strip(),
                "prob": round(float(getattr(w, "probability", 0.0) or 0.0), 3),
            })
        text = (seg.text or "").strip()
        if not text:
            continue
        segments.append({
            "id": len(segments),
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
            "words": words,
        })
        if progress and duration:
            progress(min(0.95, 0.05 + (float(seg.end) / duration) * 0.9),
                     f"Transcribing audio · {int(float(seg.end))}s of {int(duration)}s")

    data = {
        "language": getattr(info, "language", None) or "en",
        "language_probability": round(float(getattr(info, "language_probability", 0) or 0), 3),
        "segments": segments,
        "model": model_name or WHISPER_MODEL,
    }
    cache_file.write_text(json.dumps(data))
    if progress:
        progress(1.0, f"Transcript ready · {len(segments)} segments")
    return data


WORD_RE = re.compile(r"[A-Za-z0-9']+")
STOPWORDS = set("""a an the and or but if then than that this these those i you he she it we they me him her us them
my your his its our their is am are was were be been being do does did doing have has had having will would can could
should may might must shall to of in on at by for with about into through during before after above below from up down
out off over under again further once here there when where why how all any both each few more most other some such no
nor not only own same so too very just now also like well really got get go going gone yeah okay um uh oh
""".split())


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "")]


def content_tokens(text: str) -> list[str]:
    return [w for w in tokenize(text) if w not in STOPWORDS and len(w) > 2]
