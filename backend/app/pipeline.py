from __future__ import annotations

import hashlib
import json
import time
import traceback
from pathlib import Path

from . import analysis, media, selection
from .titles import generate_metadata
from .config import CACHE, THUMBS
from .db import get_settings, new_id, set_job, update
from .media import MediaError
from .transcribe import transcribe

ANALYSIS_VERSION = 7
# (min, max, unused target list kept for backwards compatibility)
DURATION_OPTIONS = {
    "short": (15, 30, []),
    "medium": (25, 45, []),
    "long": (40, 60, []),
    "extended": (55, 90, []),
    "any": (18, 55, []),
}


def log(project_id: str, message: str) -> None:
    update(lambda db: db.setdefault("logs", {}).setdefault(project_id, []).append(
        {"t": time.time(), "msg": message}
    ))


def _clean_aspects(aspects: list[str] | None) -> list[str]:
    """Keep only ratios the renderer knows, de-duplicated, in a stable order."""
    from .render import ASPECTS
    out: list[str] = []
    for a in aspects or []:
        if a in ASPECTS and a not in out:
            out.append(a)
    return out or ["9:16"]


def analyze_project(project_id: str, job_id: str, preset: str = "any", max_clips: int | None = None,
                    aspects: list[str] | None = None) -> None:
    started = time.time()

    def progress(frac: float, stage: str, label: str | None = None) -> None:
        set_job(job_id, progress=round(frac, 4), stage=stage, label=label or stage, status="running")
        update(lambda db: db["projects"][project_id].update({
            "progress": round(frac, 4), "stage": stage, "stage_label": label or stage, "status": "processing"
        }) if project_id in db.get("projects", {}) else None)

    try:
        db = update(lambda d: d)
        project = db["projects"].get(project_id)
        if not project:
            raise RuntimeError("Project not found")
        src = Path(project["file_path"])
        if not src.exists():
            raise RuntimeError("The source video file is missing from storage.")

        progress(0.02, "probe", "Reading video metadata")
        info = media.probe(src)
        duration = info["duration"]
        update(lambda d: d["projects"][project_id].update({"meta": info}) if project_id in d["projects"] else None)

        conf = DURATION_OPTIONS.get(preset, DURATION_OPTIONS["any"])
        min_dur, max_dur, targets = conf
        limit = max_clips or get_settings().get("max_clips", 10)
        limit = max(3, min(int(limit), 20))
        # Ratios are applied after analysis, so cached moments can be reused for a
        # different set of ratios without re-transcribing or re-scoring.
        ratios = _clean_aspects(aspects or get_settings().get("default_aspects"))

        # Cache key covers content + analysis params
        cache_key = f"{project['media_hash'][:32]}-v{ANALYSIS_VERSION}-{preset}-{limit}"
        cache_file = CACHE / f"{cache_key}.analysis.json"
        cached = None
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
            except Exception:
                cached = None

        if cached:
            progress(0.7, "cached", "Reusing cached transcript & analysis")
            transcript = cached.get("transcript") or {"segments": []}
            moments = cached["clips"]
            clips = _expand_aspects(project_id, moments, ratios)
            progress(0.95, "finalize", f"Preparing {len(clips)} clip previews")
            _finalize(project_id, job_id, src, info, transcript, clips, started, cached=True)
            return

        progress(0.05, "audio", "Extracting audio track")
        wav = CACHE / f"{project['media_hash'][:32]}.wav"
        if not wav.exists():
            media.extract_audio(src, wav)

        def ensure_wav() -> Path:
            """Re-extract if the cached audio vanished (cleaned cache, failed write).

            Besides being missing, a truncated file would fail deep inside the
            signal analysis with a confusing error, so check the size too.
            """
            expected = int(duration * 16000 * 2)  # 16 kHz mono s16
            try:
                ok = wav.exists() and wav.stat().st_size >= expected * 0.6
            except OSError:
                ok = False
            if not ok:
                wav.unlink(missing_ok=True)
                media.extract_audio(src, wav)
            return wav

        def tr_progress(frac, label):
            progress(0.08 + frac * 0.52, "transcribe", label)

        transcript = transcribe(ensure_wav(), duration, project["media_hash"][:32], progress=tr_progress,
                                model_name=get_settings().get("whisper_model"))
        if not transcript.get("segments"):
            raise RuntimeError("No speech was detected in this video. Highlight detection needs spoken audio.")

        progress(0.62, "visual", "Detecting scenes, faces and motion")
        # Same sampling rate the renderer uses, so analysis and every later
        # render share one cached face scan.
        # select_clips expects the whole analysis dict (frames, scenes), not just
        # the frame list.
        frames = media.cached_frames(src, duration, sample_every=0.5,
                                     media_hash=project.get("media_hash"))
        progress(0.70, "audio-signals", "Measuring energy, pace and emotion")
        feats = analysis.audio_features(ensure_wav())

        if max_dur > duration:
            max_dur = max(min_dur + 1, min(max_dur, duration))
        progress(0.76, "score", "Finding complete moments on sentence boundaries")
        picked = selection.select_clips(
            transcript["segments"], feats, frames, duration, min_dur, max_dur, limit
        )
        if not picked:
            raise RuntimeError(
                "No complete spoken moment fit this clip length. Try a longer length preset or a video with more continuous speech."
            )

        enriched = []
        for c in picked:
            meta = generate_metadata(c["text"], c.get("sentences"), c["category"], c["category_label"])
            clip_id = new_id("clip_")
            c.update({
                "id": clip_id,
                "project_id": project_id,
                "created_at": time.time(),
                **meta,
                "titles": meta["titles"],
                "selected_title": meta["titles"][0] if meta["titles"] else "",
                "caption_style": "bold-pop",
                "crop_mode": "face-track",
                "trim_start": 0.0,
                "trim_end": 0.0,
                "volume": 1.0,
                "denoise": True,
                "smart_cuts": True,
                "zoom": True,
                "music": "none",
                "music_volume": 0.12,
                "watermark": "",
                "overlays": [],
                "headline": meta["titles"][0] if meta["titles"] else "",
                "headline_enabled": True,
                "headline_seconds": 4.0,
                "progress_bar": True,
                "accent_color": "#a78bfa",
                "remove_fillers": False,
                "caption_font": "",
                "crop_x": 0.5,
                "crop_y": 0.45,
                "crop_zoom": 1.0,
                "dual_auto": True,
                "track_motion": True,
                "status": "ready",
            })
            c["thumbnail"] = None
            enriched.append(c)

        # optional LLM refinement
        if get_settings().get("llm_enabled"):
            try:
                from .llm import refine_clips
                progress(0.84, "llm", "Refining titles with language model")
                enriched = refine_clips(enriched, transcript["segments"])
                enriched = analysis.rescale_scores(sorted(enriched, key=lambda c: -c.get("llm_boost", c["score"])))
            except Exception as exc:  # keep local results on API failure
                log(project_id, f"LLM refinement skipped: {exc}")

        cache_file.write_text(json.dumps({
            "transcript": transcript,
            "clips": enriched,
            "version": ANALYSIS_VERSION,
            "created_at": time.time(),
        }))
        clips = _expand_aspects(project_id, enriched, ratios)
        _finalize(project_id, job_id, src, info, transcript, clips, started, cached=False)

    except Exception as exc:
        message = str(exc) if isinstance(exc, (MediaError, RuntimeError)) else f"Analysis failed: {exc}"
        set_job(job_id, status="error", error=message, progress=0)
        update(lambda d: d["projects"][project_id].update({"status": "error", "error": message})
               if project_id in d.get("projects", {}) else None)
        log(project_id, f"ERROR: {message}")
        print(traceback.format_exc())


def _expand_aspects(project_id: str, moments: list[dict], ratios: list[str]) -> list[dict]:
    """One clip per moment per ratio, so each ratio is a real, editable clip."""
    clips: list[dict] = []
    for index, base in enumerate(moments):
        # Stable ids: the same moment + ratio keeps its id on re-analysis, so
        # trims, captions, overlays and exports survive a settings change.
        stem = f"{float(base.get('start', 0)):.2f}-{float(base.get('end', 0)):.2f}"
        base_id = base.get("id") or f"clip_{hashlib.sha1(stem.encode()).hexdigest()[:10]}"
        for i, aspect in enumerate(ratios):
            c = dict(base)
            c.update({
                "id": f"{base_id}-{aspect.replace(':', '')}",
                "project_id": project_id,
                "aspect": aspect,
                "moment_index": index,
                "ratio_count": len(ratios),
                "ratio_index": i,
                # thumbs are shared per moment, so they are filled in _finalize
                "thumbnail": None,
                "edits": {},
            })
            clips.append(c)
    return clips


def _finalize(project_id, job_id, src: Path, info: dict, transcript: dict, clips: list[dict],
              started: float, cached: bool) -> None:
    def progress(frac, stage, label):
        set_job(job_id, progress=round(frac, 4), stage=stage, label=label)
        update(lambda d: d["projects"][project_id].update({"progress": round(frac, 4), "stage": stage,
                                                          "stage_label": label}) if project_id in d["projects"] else None)

    progress(0.90, "thumbnails", "Generating clip previews")
    moment_thumbs: dict[int, str | None] = {}
    done = 0
    for clip in clips:
        mid_index = int(clip.get("moment_index", 0))
        if mid_index not in moment_thumbs:
            thumb_name = f"{project_id}-m{mid_index}.jpg"
            thumb_path = THUMBS / thumb_name
            mid = clip["start"] + min(max(clip["duration"] * 0.35, 1.0), clip["duration"] - 0.3)
            ok = True if thumb_path.exists() else media.make_thumb(src, thumb_path, mid)
            moment_thumbs[mid_index] = f"/media/thumbs/{thumb_name}" if ok else None
            done += 1
            progress(0.90 + done / max(len(moment_thumbs) + 2, 1) * 0.08, "thumbnails",
                     f"Preparing preview {done}")
        clip["thumbnail"] = moment_thumbs[mid_index]
        clip.setdefault("edits", {})

    new_ids = {c["id"] for c in clips}

    def save(d):
        # Re-running with a different set of ratios replaces this project's
        # clips; drop the old copies so they don't linger in storage.
        stale = [cid for cid, c in d.get("clips", {}).items()
                 if c.get("project_id") == project_id and cid not in new_ids]
        for cid in stale:
            gone = d["clips"].pop(cid, None)
            if gone and gone.get("export_path"):
                Path(gone["export_path"]).unlink(missing_ok=True)
        for clip in clips:
            existing = d["clips"].get(clip["id"], {})
            merged = {**clip, **{k: v for k, v in existing.items() if k in (
                "selected_title", "caption_style", "aspect", "crop_mode", "trim_start", "trim_end",
                "volume", "denoise", "smart_cuts", "zoom", "music", "music_volume", "watermark",
                "overlays", "edits", "titles", "hashtags", "description", "hook", "status",
                "export_path", "exported_at", "caption_preset", "title_source")}}
            d["clips"][clip["id"]] = merged
        p = d["projects"][project_id]
        p.update({
            "status": "ready",
            "stage": "done",
            "stage_label": "Analysis complete",
            "progress": 1.0,
            "clip_ids": [c["id"] for c in clips],
            "transcript_segments": len(transcript.get("segments", [])),
            "transcript_language": transcript.get("language"),
            "analysis_seconds": round(time.time() - started, 1),
            "analyzed_at": time.time(),
            "cached_result": cached,
        })
        p.pop("error", None)

    update(save)
    set_job(job_id, status="done", progress=1.0, stage="done", label="Analysis complete",
            finished_at=time.time())
    log(project_id, f"Analysis complete · {len(clips)} clips in {round(time.time() - started, 1)}s")
