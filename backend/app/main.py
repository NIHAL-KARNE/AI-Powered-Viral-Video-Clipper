from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import media, render
from .analysis import CATEGORIES
from .config import (ALLOWED_VIDEO_EXT, CLIPS, DATA, DEFAULT_SETTINGS, EXPORTS, THUMBS,
                     PLATFORM_PRESETS, UPLOADS)
from .db import get_job, get_settings, load_db, new_id, save_settings, set_job, update
from .pipeline import analyze_project

app = FastAPI(title="Viral Clipper", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media/thumbs", StaticFiles(directory=str(THUMBS)), name="thumbs")
app.mount("/media/clips", StaticFiles(directory=str(CLIPS)), name="clips")
app.mount("/media/exports", StaticFiles(directory=str(EXPORTS)), name="exports")

MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
DIRECT_MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
SUPPORTED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "vimeo.com",
                   "www.vimeo.com", "dailymotion.com", "www.dailymotion.com", "twitch.tv",
                   "www.twitch.tv", "clips.twitch.tv"}


# ---------------------------------------------------------------- helpers
def project_public(p: dict, clips_by_id: dict | None = None) -> dict:
    clips_by_id = clips_by_id or {}
    out = {k: v for k, v in p.items() if k not in ("file_path", "media_hash")}
    clip_ids = p.get("clip_ids", [])
    out["clips"] = [clip_public(clips_by_id[c]) for c in clip_ids if c in clips_by_id]
    return out


def clip_public(c: dict) -> dict:
    out = dict(c)
    out.pop("words", None)
    out["word_count"] = len(c.get("words") or [])
    return out


def get_project_or_404(pid: str) -> dict:
    db = load_db()
    p = db["projects"].get(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def start_job(pid: str, preset: str, max_clips: int | None,
              aspects: list[str] | None = None) -> str:
    job_id = new_id("job_")
    set_job(job_id, project_id=pid, status="queued", progress=0, stage="queued",
            label="Queued", kind="analysis")
    t = threading.Thread(target=analyze_project, args=(pid, job_id, preset, max_clips, aspects),
                         daemon=True)
    t.start()
    return job_id


# ---------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    import shutil as sh

    return {
        "ok": True,
        "ffmpeg": bool(sh.which("ffmpeg")),
        "ytdlp": True,
        "whisper_model": get_settings().get("whisper_model"),
        "categories": CATEGORIES,
        "platforms": PLATFORM_PRESETS,
        "caption_styles": list(render.CAPTION_STYLES.keys()),
        "aspects": list(render.ASPECTS.keys()),
        "music": list(render.MUSIC_MOODS.keys()),
    }


@app.get("/api/dashboard")
def dashboard():
    db = load_db()
    projects = sorted(db["projects"].values(), key=lambda p: p.get("created_at", 0), reverse=True)
    clips = list(db["clips"].values())
    ready_clips = [c for c in clips if c.get("status") == "ready"]
    return {
        "projects": [project_public(p, db["clips"]) for p in projects],
        "stats": {
            "videos": len(projects),
            "clips": len(ready_clips),
            "exports": len([c for c in clips if c.get("export_path")]),
            "avg_score": round(sum(c.get("score", 0) for c in ready_clips) / len(ready_clips), 1)
            if ready_clips else 0,
            "processing": len([p for p in projects if p.get("status") in ("processing", "queued")]),
            "minutes_analyzed": round(sum((p.get("meta") or {}).get("duration", 0) for p in projects) / 60, 1),
        },
        "recent_clips": [clip_public(c) for c in sorted(ready_clips, key=lambda c: -c.get("score", 0))[:6]],
    }


# ---------------------------------------------------------------- upload
# Chunked, parallel, resumable uploads: the browser sends up to 4 pieces at a
# time (8 MB each), and the server writes each piece straight to its byte offset
# in a staging file on the same volume as UPLOADS. Finishing is then an instant
# rename instead of copying gigabytes of parts.
CHUNK_DIR = UPLOADS / ".chunks"
CHUNK_DIR.mkdir(parents=True, exist_ok=True)
CHUNK_SIZE = 8 * 1024 * 1024


class UploadInit(BaseModel):
    filename: str
    size: int
    # Whole-file fingerprint from the browser: lets an interrupted upload resume.
    fingerprint: str | None = None


def _chunk_folder(upload_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", upload_id or ""):
        raise HTTPException(400, "Invalid upload id.")
    return CHUNK_DIR / upload_id


def _received_chunks(folder: Path, total: int) -> list[int]:
    """Sorted list of chunk indices already written to disk."""
    done: list[int] = []
    for entry in folder.iterdir():
        name = entry.name
        if name.endswith(".done") and len(name) == 10:
            try:
                idx = int(name[:5])
                if 0 <= idx < total:
                    done.append(idx)
            except ValueError:
                continue
    done.sort()
    return done


def _next_chunk(done: list[int], total: int) -> int:
    """First chunk index that has not been written yet."""
    seen = set(done)
    index = 0
    while index < total and index in seen:
        index += 1
    return index


def _received_bytes(done: list[int], chunk_size: int, total_size: int, total_chunks: int) -> int:
    total = 0
    for idx in done:
        if idx == total_chunks - 1:
            rem = total_size - idx * chunk_size
            total += max(rem, 0)
        else:
            total += chunk_size
    return min(total, total_size)


def _sweep_chunks(max_age_hours: float = 24) -> None:
    """Remove abandoned partial uploads so they don't fill the disk."""
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_hours * 3600
    for folder in CHUNK_DIR.glob("up_*"):
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


@app.post("/api/upload/init")
def upload_init(req: UploadInit):
    _sweep_chunks()
    if not req.filename:
        raise HTTPException(400, "A filename is required.")
    ext = Path(req.filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext or 'unknown'}'. Upload MP4, MOV, MKV, WEBM, AVI or M4V.")
    if req.size <= 0:
        raise HTTPException(400, "The file is empty.")
    if req.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than the 4 GB limit.")

    name = Path(req.filename).name
    total = max(1, -(-req.size // CHUNK_SIZE))

    # Same file, same size, recently interrupted: continue where it stopped
    # instead of sending bytes the server already has.
    if req.fingerprint:
        for meta_file in CHUNK_DIR.glob("*/meta.json"):
            try:
                prev = json.loads(meta_file.read_text())
            except Exception:
                continue
            prev_cs = int(prev.get("chunk_size") or CHUNK_SIZE)
            if (prev.get("fingerprint") == req.fingerprint and prev.get("size") == req.size
                    and (meta_file.parent / "data.bin").exists()
                    and time.time() - float(prev.get("created_at", 0)) < 24 * 3600):
                folder = meta_file.parent
                prev_total = int(prev.get("total", total))
                done = _received_chunks(folder, prev_total)
                nxt = _next_chunk(done, prev_total)
                received = _received_bytes(done, prev_cs, req.size, prev_total)
                return {
                    "upload_id": folder.name, "chunk_size": prev_cs,
                    "total_chunks": prev_total, "next_chunk": nxt,
                    "received_chunks": done, "received": received, "resumed": len(done) > 0,
                }

    upload_id = new_id("up_")
    folder = CHUNK_DIR / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    # Create the staging file upfront so parallel pwrite calls can land at any offset.
    with (folder / "data.bin").open("wb") as fh:
        fh.truncate(req.size)
    (folder / "meta.json").write_text(json.dumps({
        "filename": name, "size": req.size, "total": total, "chunk_size": CHUNK_SIZE,
        "fingerprint": req.fingerprint, "created_at": time.time(),
    }))
    return {
        "upload_id": upload_id, "chunk_size": CHUNK_SIZE, "total_chunks": total,
        "next_chunk": 0, "received_chunks": [], "received": 0, "resumed": False,
    }


@app.get("/api/upload/{upload_id}/status")
def upload_status(upload_id: str):
    """How much of this upload already reached the server (for resume)."""
    folder = _chunk_folder(upload_id)
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        raise HTTPException(404, "Upload not found or expired.")
    meta = json.loads(meta_file.read_text())
    total = int(meta.get("total", 1))
    cs = int(meta.get("chunk_size") or CHUNK_SIZE)
    size = int(meta.get("size") or 0)
    done = _received_chunks(folder, total)
    nxt = _next_chunk(done, total)
    received = _received_bytes(done, cs, size, total)
    return {
        "upload_id": upload_id, "next_chunk": nxt, "received_chunks": done,
        "received": received, "size": size, "total_chunks": total,
        "complete": len(done) >= total,
    }


@app.put("/api/upload/{upload_id}/chunk/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request):
    folder = _chunk_folder(upload_id)
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        raise HTTPException(404, "Upload not found or expired.")
    meta = json.loads(meta_file.read_text())
    total = int(meta.get("total", 1))
    cs = int(meta.get("chunk_size") or CHUNK_SIZE)
    if index < 0 or index >= total:
        raise HTTPException(400, "Chunk index out of range.")
    marker = folder / f"{index:05d}.done"
    if marker.exists():
        return {"ok": True, "index": index, "deduped": True}
    data_path = folder / "data.bin"
    if not data_path.exists():
        raise HTTPException(404, "Upload staging file missing.")

    # Stream directly to the chunk's byte offset in data.bin without buffering
    # the entire chunk in memory or rewriting it at complete time.
    offset = index * cs
    written = 0
    fd = os.open(data_path, os.O_WRONLY)
    try:
        async for piece in request.stream():
            if not piece:
                continue
            os.pwrite(fd, piece, offset + written)
            written += len(piece)
    finally:
        os.close(fd)

    if written == 0:
        raise HTTPException(400, "Empty chunk.")
    marker.touch()
    return {"ok": True, "index": index, "written": written}


@app.post("/api/upload/{upload_id}/complete")
def upload_complete(upload_id: str):
    folder = _chunk_folder(upload_id)
    meta_file = folder / "meta.json"
    if not meta_file.exists():
        raise HTTPException(404, "Upload not found or expired.")
    meta = json.loads(meta_file.read_text())
    name = meta.get("filename") or "video.mp4"
    ext = Path(name).suffix.lower()
    total = int(meta.get("total", 1))
    done = set(_received_chunks(folder, total))
    missing = total - len(done)
    if missing > 0:
        raise HTTPException(409, f"{missing} part(s) still missing. Resume the upload.")

    data_path = folder / "data.bin"
    if not data_path.exists():
        raise HTTPException(404, "Upload staging file missing.")

    pid = new_id("proj_")
    dest = UPLOADS / f"{pid}{ext}"
    # Same volume as UPLOADS: instant rename, zero gigabyte copy.
    os.replace(data_path, dest)
    shutil.rmtree(folder, ignore_errors=True)

    size = dest.stat().st_size
    if size != int(meta.get("size", size)):
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Upload was incomplete. Please try again.")
    return _finish_upload(dest, name, pid)


@app.post("/api/upload")
async def upload_video(request: Request, file: UploadFile):
    name = Path(file.filename or "video.mp4").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext or 'unknown'}'. Upload MP4, MOV, MKV, WEBM, AVI or M4V.")

    pid = new_id("proj_")
    dest = UPLOADS / f"{pid}{ext}"
    size = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "File is larger than the 4 GB limit.")
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file was empty.")

    return _finish_upload(dest, name, pid)


def _finish_upload(dest: Path, name: str, pid: str, media_hash: str | None = None) -> dict:
    """Probe + hash + thumbnail, shared by the single-shot and chunked paths."""
    try:
        info = media.probe(dest)
    except media.MediaError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))

    media_hash = media_hash or media.sha256_file(dest)
    thumb_name = f"{pid}.jpg"
    thumb = THUMBS / thumb_name
    media.make_thumb(dest, thumb, min(info["duration"] * 0.12, 5.0))

    project = {
        "id": pid,
        "title": Path(name).stem[:120] or "Uploaded video",
        "source_type": "upload",
        "source_url": None,
        "file_path": str(dest),
        "media_hash": media_hash,
        "original_filename": name,
        "created_at": time.time(),
        "status": "uploaded",
        "stage": "uploaded",
        "stage_label": "Ready to analyze",
        "progress": 0,
        "meta": info,
        "thumbnail": f"/media/thumbs/{thumb_name}" if thumb.exists() else None,
        "clip_ids": [],
    }
    update(lambda db: db["projects"].__setitem__(pid, project))
    return project_public(project)


# ---------------------------------------------------------------- URL import
class UrlRequest(BaseModel):
    url: str
    title: str | None = None


def validate_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(400, "Paste a video URL first.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        raise HTTPException(400, "That does not look like a valid URL.")
    if host not in SUPPORTED_HOSTS:
        if Path(parsed.path).suffix.lower() in DIRECT_MEDIA_EXT:
            return raw  # direct link to a video file
        raise HTTPException(
            400,
            f"{host} is not a supported host. Use YouTube, Vimeo, Dailymotion, Twitch, "
            "or a direct link to an MP4/MOV/WEBM file. You can also upload the file directly.",
        )
    if "youtube" in host or host == "youtu.be":
        if not (re.search(r"(v=|/shorts/|/live/|youtu\.be/)", parsed.path + "?" + parsed.query)):
            raise HTTPException(400, "That YouTube link does not contain a video ID.")
    return raw


@app.post("/api/import-url")
def import_url(req: UrlRequest):
    url = validate_url(req.url)
    pid = new_id("proj_")
    upload_dir = UPLOADS / pid
    upload_dir.mkdir(parents=True, exist_ok=True)
    job_id = new_id("job_")
    set_job(job_id, project_id=pid, status="running", progress=0.04, stage="download",
            label="Fetching video", kind="download")

    project = {
        "id": pid,
        "title": req.title or "Remote video",
        "source_type": "url",
        "source_url": url,
        "file_path": "",
        "media_hash": "",
        "original_filename": None,
        "created_at": time.time(),
        "status": "processing",
        "stage": "download",
        "stage_label": "Downloading video",
        "progress": 0.02,
        "meta": {},
        "thumbnail": None,
        "clip_ids": [],
    }
    update(lambda db: db["projects"].__setitem__(pid, project))

    def work():
        try:
            def prog(f):
                set_job(job_id, progress=round(f, 3), label="Downloading video")
                update(lambda d: d["projects"][pid].update({"progress": round(f, 3),
                                                           "stage_label": "Downloading video"})
                       if pid in d["projects"] else None)

            cookies = DATA / "cookies.txt"
            path, meta = media.download_remote(
                url, upload_dir, pid, progress=prog,
                cookies_file=str(cookies) if cookies.exists() else None,
            )
            info = media.probe(path)
            media_hash = media.sha256_file(path)
            thumb = THUMBS / f"{pid}.jpg"
            media.make_thumb(path, thumb, min(info["duration"] * 0.12, 5.0))
            title = (meta.get("title") or req.title or "Remote video")[:140]

            def save(d):
                p = d["projects"][pid]
                p.update({
                    "file_path": str(path), "media_hash": media_hash, "meta": info,
                    "title": title, "status": "uploaded", "stage": "uploaded",
                    "stage_label": "Ready to analyze", "progress": 0,
                    "thumbnail": f"/media/thumbs/{pid}.jpg" if thumb.exists() else None,
                    "source_meta": {k: meta.get(k) for k in ("title", "uploader", "duration",
                                                             "thumbnail", "webpage_url")},
                })
            update(save)
            set_job(job_id, status="done", progress=1.0, stage="done", label="Video ready")
        except Exception as exc:
            msg = str(exc)[:500]
            set_job(job_id, status="error", error=msg, label="Download failed")
            update(lambda d: d["projects"][pid].update({"status": "error", "error": msg})
                   if pid in d["projects"] else None)
            shutil.rmtree(upload_dir, ignore_errors=True)

    threading.Thread(target=work, daemon=True).start()
    return {"project": project_public(project), "job_id": job_id}


# ---------------------------------------------------------------- projects
@app.get("/api/projects")
def list_projects():
    db = load_db()
    return [project_public(p, db["clips"]) for p in
            sorted(db["projects"].values(), key=lambda p: p.get("created_at", 0), reverse=True)]


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    db = load_db()
    p = db["projects"].get(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    out = project_public(p, db["clips"])
    job = None
    for j in db["jobs"].values():
        if j.get("project_id") == pid and j.get("kind") in ("analysis", "download"):
            if job is None or j.get("updated_at", 0) > job.get("updated_at", 0):
                job = j
    out["job"] = job
    return out


@app.get("/api/projects/{pid}/video")
def project_video(pid: str):
    p = get_project_or_404(pid)
    path = Path(p["file_path"])
    if not path.exists():
        raise HTTPException(404, "Source video file is missing")
    return FileResponse(path, media_type="video/mp4", filename=p.get("original_filename") or path.name)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    db = load_db()
    p = db["projects"].get(pid)
    if not p:
        raise HTTPException(404, "Project not found")

    def mutate(d):
        for cid in d["projects"][pid].get("clip_ids", []):
            c = d["clips"].pop(cid, None)
            if c:
                for key in ("export_path",):
                    if c.get(key):
                        Path(c[key]).unlink(missing_ok=True)
        d["projects"].pop(pid, None)
    update(mutate)
    if p.get("file_path"):
        Path(p["file_path"]).unlink(missing_ok=True)
    for f in (THUMBS / f"{pid}.jpg",):
        f.unlink(missing_ok=True)
    # Shared per-moment previews for this project.
    for f in THUMBS.glob(f"{pid}-m*.jpg"):
        f.unlink(missing_ok=True)
    shutil.rmtree(UPLOADS / pid, ignore_errors=True)
    return {"ok": True}


class AnalyzeRequest(BaseModel):
    preset: str = "any"
    max_clips: int | None = None
    aspects: list[str] | None = None


@app.post("/api/projects/{pid}/analyze")
def analyze(pid: str, req: AnalyzeRequest):
    p = get_project_or_404(pid)
    if not p.get("file_path") or not Path(p["file_path"]).exists():
        raise HTTPException(400, "This project has no video file available. Re-upload it.")
    if p.get("status") == "processing":
        raise HTTPException(409, "This video is already being analyzed.")
    job_id = start_job(pid, req.preset, req.max_clips, req.aspects)
    return {"job_id": job_id, "status": "started"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/projects/{pid}/transcript")
def transcript(pid: str):
    import json

    from .config import CACHE
    p = get_project_or_404(pid)
    cached = CACHE / f"{(p.get('media_hash') or '')[:32]}.transcript.json"
    if cached.exists():
        return json.loads(cached.read_text())
    raise HTTPException(404, "No transcript cached for this project yet. Run analysis first.")


# ---------------------------------------------------------------- clips
@app.get("/api/clips")
def list_clips(project_id: str | None = None):
    db = load_db()
    clips = [clip_public(c) for c in db["clips"].values()]
    if project_id:
        clips = [c for c in clips if c.get("project_id") == project_id]
    return sorted(clips, key=lambda c: -c.get("score", 0))


@app.get("/api/clips/{cid}")
def get_clip(cid: str):
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    p = db["projects"].get(c["project_id"])
    out = clip_public(c)
    out["transcript_text"] = c.get("text")
    out["project_title"] = (p or {}).get("title")
    meta = ((p or {}).get("meta") or {})
    out["project_duration"] = meta.get("duration")
    out["source_width"] = meta.get("width")
    out["source_height"] = meta.get("height")
    return out


EDITABLE = {
    "selected_title", "caption_style", "aspect", "crop_mode", "start", "end", "trim_start", "trim_end",
    "volume", "denoise", "smart_cuts", "zoom", "music", "music_volume", "watermark", "watermark_size", "captions_enabled",
    "overlays", "hashtags", "description", "hook", "caption_position", "caption_size",
    "status", "title_source", "titles", "keywords",
    "headline", "headline_enabled", "headline_seconds", "progress_bar", "accent_color",
    "remove_fillers", "caption_font", "track_motion",
    "emoji_enabled", "keywords_enabled", "caption_words",
    "crop_x", "crop_y", "crop_zoom", "dual_top_x", "dual_top_y", "dual_top_zoom",
    "dual_bottom_x", "dual_bottom_y", "dual_bottom_zoom", "dual_auto", "frame_preset",
    "inset_x", "inset_y", "inset_zoom", "inset_size", "inset_shape", "inset_pos_x",
    "inset_pos_y", "inset_bg_fit", "inset_bg_x", "inset_bg_y", "inset_bg_zoom",
    "inset_border", "inset_border_color", "inset_border_width", "inset_radius", "inset_shadow",
    "keyframes",
}


class ClipPatch(BaseModel):
    selected_title: str | None = None
    caption_style: str | None = None
    caption_position: str | None = None
    caption_size: int | None = None
    aspect: str | None = None
    crop_mode: str | None = None
    start: float | None = None
    end: float | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    volume: float | None = None
    denoise: bool | None = None
    smart_cuts: bool | None = None
    zoom: bool | None = None
    music: str | None = None
    music_volume: float | None = None
    watermark: str | None = None
    watermark_size: float | None = None
    captions_enabled: bool | None = None
    emoji_enabled: bool | None = None
    keywords_enabled: bool | None = None
    caption_words: int | None = None
    overlays: list[dict] | None = None
    hashtags: list[str] | None = None
    description: str | None = None
    hook: str | None = None
    titles: list[str] | None = None
    keywords: list[str] | None = None
    crop_x: float | None = None
    crop_y: float | None = None
    crop_zoom: float | None = None
    dual_top_x: float | None = None
    dual_top_y: float | None = None
    dual_top_zoom: float | None = None
    dual_bottom_x: float | None = None
    dual_bottom_y: float | None = None
    dual_bottom_zoom: float | None = None
    dual_auto: bool | None = None
    inset_x: float | None = None
    inset_y: float | None = None
    inset_zoom: float | None = None
    inset_size: float | None = None
    inset_shape: str | None = None
    inset_pos_x: float | None = None
    inset_pos_y: float | None = None
    inset_bg_fit: str | None = None
    inset_bg_x: float | None = None
    inset_bg_y: float | None = None
    inset_bg_zoom: float | None = None
    inset_border: bool | None = None
    inset_border_color: str | None = None
    inset_border_width: float | None = None
    inset_radius: float | None = None
    inset_shadow: bool | None = None
    frame_preset: str | None = None
    track_motion: bool | None = None
    keyframes: list[dict] | None = None
    headline: str | None = None
    headline_enabled: bool | None = None
    headline_seconds: float | None = None
    progress_bar: bool | None = None
    accent_color: str | None = None
    remove_fillers: bool | None = None
    caption_font: str | None = None


@app.patch("/api/clips/{cid}")
def patch_clip(cid: str, patch: ClipPatch):
    db = load_db()
    if cid not in db["clips"]:
        raise HTTPException(404, "Clip not found")
    data = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if k in EDITABLE and v is not None}

    # undo history (cap 30)
    def mutate(d):
        c = d["clips"][cid]
        p = d["projects"].get(c["project_id"]) or {}
        proj_dur = float((p.get("meta") or {}).get("duration") or 0)
        old_start = float(c["start"])
        old_end = float(c["end"])

        if "start" in data or "end" in data:
            new_start = float(data.get("start", old_start))
            new_end = float(data.get("end", old_end))
            new_start = max(0.0, new_start)
            if proj_dur > 0:
                new_end = min(proj_dur, new_end)
                new_start = min(new_start, max(proj_dur - 1.0, 0.0))
            if new_end - new_start < 1.0:
                new_end = min(proj_dur, new_start + 1.0) if proj_dur > 0 else new_start + 1.0
            data["start"] = round(new_start, 3)
            data["end"] = round(new_end, 3)

        hist = c.setdefault("history", [])
        hist.append({k: c.get(k) for k in data})
        c["history"] = hist[-30:]
        c.pop("redo", None)
        c.update(data)

        if "start" in data or "end" in data:
            ns = float(c["start"])
            ne = float(c["end"])
            c["duration"] = round(max(ne - ns, 0.1), 3)
            # Keep trims within the updated clip duration
            ts = float(c.get("trim_start") or 0)
            te = float(c.get("trim_end") or 0)
            if ts + te > c["duration"] - 1.0:
                c["trim_start"] = 0.0
                c["trim_end"] = 0.0
            # Pull in transcript words for any newly extended range while keeping existing words
            mh = p.get("media_hash")
            if mh:
                tr_path = DATA / "cache" / f"{mh}.transcript.json"
                if tr_path.exists():
                    try:
                        tr = json.loads(tr_path.read_text())
                        all_words = []
                        for seg in tr.get("segments") or []:
                            all_words.extend(seg.get("words") or [])
                        existing = [
                            w for w in (c.get("words") or [])
                            if ns - 0.1 <= float(w["start"]) <= ne + 0.1
                        ]
                        extra = [
                            w for w in all_words
                            if (ns <= float(w["start"]) < old_start - 0.05)
                            or (old_end + 0.05 < float(w["start"]) <= ne)
                        ]
                        if extra:
                            c["words"] = sorted(existing + extra, key=lambda x: float(x["start"]))
                    except Exception:
                        pass
        c["edited_at"] = time.time()
    update(mutate)
    return clip_public(load_db()["clips"][cid])


@app.post("/api/clips/{cid}/undo")
def undo_clip(cid: str):
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")

    def mutate(d):
        c = d["clips"][cid]
        hist = c.get("history") or []
        if not hist:
            raise HTTPException(400, "Nothing to undo")
        prev = hist.pop()
        redo = c.setdefault("redo", [])
        redo.append({k: c.get(k) for k in prev})
        c.update(prev)
        c["history"] = hist
    try:
        update(mutate)
    except HTTPException:
        raise
    return clip_public(load_db()["clips"][cid])


@app.post("/api/clips/{cid}/redo")
def redo_clip(cid: str):
    db = load_db()
    if cid not in db["clips"]:
        raise HTTPException(404, "Clip not found")

    def mutate(d):
        c = d["clips"][cid]
        redo = c.get("redo") or []
        if not redo:
            raise HTTPException(400, "Nothing to redo")
        nxt = redo.pop()
        c.setdefault("history", []).append({k: c.get(k) for k in nxt})
        c.update(nxt)
    update(mutate)
    return clip_public(load_db()["clips"][cid])


@app.get("/api/clips/{cid}/captions")
def clip_captions(cid: str):
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    cues = render.word_captions(c.get("words") or [], c["start"], c["end"],
                                c.get("caption_style", "bold-pop"),
                                max_words=c.get("caption_words"))
    out = []
    for cue in cues:
        out.append({
            "start": round(cue["start"], 3),
            "end": round(cue["end"], 3),
            "text": " ".join(w["word"] for w in cue["words"]),
        })
    words = []
    for w in c.get("words") or []:
        local = float(w["start"]) - c["start"]
        if -0.2 <= local <= (c["end"] - c["start"]) + 0.5:
            words.append({
                "start": round(max(local, 0), 3),
                "end": round(max(float(w["end"]) - c["start"], 0.01), 3),
                "word": w["word"],
            })
    return {"cues": out, "words": words, "style": c.get("caption_style")}


class CaptionWordIn(BaseModel):
    start: float
    end: float
    word: str


class CaptionsUpdate(BaseModel):
    words: list[CaptionWordIn]


@app.put("/api/clips/{cid}/captions")
def update_clip_captions(cid: str, body: CaptionsUpdate):
    """Replace the clip's spoken words with user-edited captions (clip-local times)."""
    def _apply(db):
        c = db["clips"].get(cid)
        if not c:
            raise HTTPException(404, "Clip not found")
        clip_start = float(c["start"])
        clip_end = float(c["end"])
        duration = max(clip_end - clip_start, 0.1)

        cleaned: list[dict] = []
        for w in body.words:
            text = (w.word or "").strip()
            if not text:
                continue
            st = max(0.0, min(float(w.start), duration))
            en = max(st + 0.04, min(float(w.end), duration + 0.25))
            cleaned.append({
                "start": round(clip_start + st, 3),
                "end": round(clip_start + en, 3),
                "word": text,
            })
        cleaned.sort(key=lambda x: x["start"])

        # Keep any words outside this clip's current trim window untouched.
        outside = [
            w for w in (c.get("words") or [])
            if float(w["start"]) < clip_start - 0.2 or float(w["start"]) > clip_end + 0.5
        ]
        c["words"] = sorted(outside + cleaned, key=lambda x: float(x["start"]))
        c["updated_at"] = time.time()

    update(_apply)
    return clip_captions(cid)


@app.get("/api/clips/{cid}/frame-info")
def clip_frame_info(cid: str):
    """Geometry the editor needs to draw the draggable crop window."""
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    project = db["projects"].get(c["project_id"]) or {}
    meta = project.get("meta") or {}
    if not meta.get("width"):
        raise HTTPException(400, "Source video metadata is unavailable.")
    return {
        "source": {"width": meta["width"], "height": meta["height"], "duration": meta.get("duration", 0)},
        "clip": {"start": c["start"], "end": c["end"], "duration": c["duration"]},
        "crop": {
            "mode": c.get("crop_mode", "face-track"),
            "x": c.get("crop_x", 0.5),
            "y": c.get("crop_y", 0.45),
            "zoom": c.get("crop_zoom", 1.0),
        },
        "dual": {
            "auto": c.get("dual_auto", True),
            "top": {"x": c.get("dual_top_x", 0.28), "y": c.get("dual_top_y", 0.45),
                    "zoom": c.get("dual_top_zoom", 1.0)},
            "bottom": {"x": c.get("dual_bottom_x", 0.72), "y": c.get("dual_bottom_y", 0.45),
                       "zoom": c.get("dual_bottom_zoom", 1.0)},
        },
        "inset": {
            "x": c.get("inset_x", 0.5), "y": c.get("inset_y", 0.5),
            "zoom": c.get("inset_zoom", 1.8),
            "size": c.get("inset_size", 0.3),
            "shape": c.get("inset_shape", "16:9"),
            "pos_x": c.get("inset_pos_x", 0.78), "pos_y": c.get("inset_pos_y", 0.8),
            "bg_fit": c.get("inset_bg_fit", "cover"),
            "bg_x": c.get("inset_bg_x", 0.5), "bg_y": c.get("inset_bg_y", 0.5),
            "bg_zoom": c.get("inset_bg_zoom", 1.0),
            "border": c.get("inset_border", True),
            "border_color": c.get("inset_border_color", "#ffffff"),
            "border_width": c.get("inset_border_width", 5),
            "radius": c.get("inset_radius", 4),
            "shadow": c.get("inset_shadow", True),
        },
        "aspects": render.ASPECTS,
    }


@app.post("/api/clips/{cid}/headline")
def suggest_headline(cid: str):
    """Generate a short on-screen headline from the clip's own words."""
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    text = c.get("text") or ""
    if not text.strip():
        raise HTTPException(400, "This clip has no transcript to work from.")
    from .titles import headline_variants
    return {"options": headline_variants(text, c.get("titles") or [], c.get("hook") or ""),
            "current": c.get("headline") or ""}


@app.get("/api/clips/{cid}/focus-suggestions")
def focus_suggestions(cid: str):
    """Face-derived focus points, so the editor can offer 'snap to subject'."""
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    project = db["projects"].get(c["project_id"]) or {}
    path = Path(project.get("file_path", ""))
    if not path.exists():
        raise HTTPException(400, "Source video is unavailable.")
    from .media import cached_frames
    meta = project.get("meta") or {}
    frames = cached_frames(path, meta.get("duration", c["end"]), sample_every=0.5,
                           media_hash=project.get("media_hash")).get("frames") or []
    # Frame editing happens on the trimmed clip, exactly as the renderer sees it.
    c_start = float(c["start"]) + max(float(c.get("trim_start") or 0), 0)
    c_end = float(c["end"]) - max(float(c.get("trim_end") or 0), 0)
    if c_end - c_start < 0.5:
        c_start, c_end = float(c["start"]), float(c["end"])
    ax, ay, faces = render._auto_focus(frames, c_start, c_end)
    (lx, ly), (rx, ry) = render._dual_focus(frames, c_start, c_end)
    # The camera path the renderer will follow, so the editor can animate the
    # frame exactly as the export will look.
    aspect = c.get("aspect") or "9:16"
    ow, oh = render.ASPECTS.get(aspect, render.ASPECTS["9:16"])
    zoom = max(float(c.get("crop_zoom") or 1.0), 1.0)
    t_path, xs, ys = render._track_path(meta, frames, c_start, c_end, ow / oh, zoom)
    # Path times are clip-relative, like the editor playhead.
    trim_offset = max(float(c.get("trim_start") or 0), 0)
    return {
        "single": {"x": round(ax, 3), "y": round(ay, 3), "faces": faces},
        "dual": {"top": {"x": round(lx, 3), "y": round(ly, 3)},
                 "bottom": {"x": round(rx, 3), "y": round(ry, 3)}},
        "path": {
            "times": [round(t + trim_offset, 2) for t in t_path],
            "x": [round(float(v), 4) for v in xs],
            "y": [round(float(v), 4) for v in ys],
        },
    }


RENDER_LOCK = threading.Lock()


class RenderRequest(BaseModel):
    options: dict | None = None
    preview: bool = False


@app.post("/api/clips/{cid}/render")
def render_clip_endpoint(cid: str, req: RenderRequest):
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    project = db["projects"].get(c["project_id"])
    if not project or not Path(project.get("file_path", "")).exists():
        raise HTTPException(400, "Source video is unavailable for this clip.")
    options = {**{k: c.get(k) for k in EDITABLE if k in (
        "aspect", "crop_mode", "caption_style", "caption_position", "caption_size", "trim_start",
        "trim_end", "volume", "denoise", "smart_cuts", "zoom", "music", "music_volume", "watermark", "watermark_size", "captions_enabled",
        "overlays", "crop_x", "crop_y", "crop_zoom", "dual_top_x", "dual_top_y", "dual_top_zoom",
        "dual_bottom_x", "dual_bottom_y", "dual_bottom_zoom", "dual_auto", "track_motion",
        "inset_x", "inset_y", "inset_zoom", "inset_size", "inset_shape", "inset_pos_x",
        "inset_pos_y", "inset_bg_fit", "inset_bg_x", "inset_bg_y", "inset_bg_zoom", "inset_border",
        "inset_border_color", "inset_border_width", "inset_radius", "inset_shadow",
        "headline", "headline_enabled", "headline_seconds", "progress_bar", "accent_color",
        "remove_fillers", "caption_font", "emoji_enabled", "keywords_enabled",
        "caption_words")}, **(req.options or {})}
    try:
        result = render.render_clip(project, c, options)
    except media.MediaError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Render failed: {exc}")

    def mutate(d):
        clip = d["clips"][cid]
        clip["export_path"] = result["path"]
        clip["export"] = result
        clip["exported_at"] = time.time()
        clip["status"] = "exported"
        clip.setdefault("exports", []).append({
            "path": result["path"], "url": result["url"], "at": time.time(),
            "size": result["size"], "duration": result["duration"],
            "aspect": options.get("aspect"), "caption_style": options.get("caption_style"),
        })
        clip["exports"] = clip["exports"][-8:]
    update(mutate)
    return result


@app.get("/api/clips/{cid}/download")
def download_clip(cid: str):
    db = load_db()
    c = db["clips"].get(cid)
    if not c:
        raise HTTPException(404, "Clip not found")
    path = c.get("export_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "This clip has not been exported yet. Render it first.")
    title = re.sub(r"[^A-Za-z0-9 _-]", "", (c.get("selected_title") or c["id"]))[:60].strip() or c["id"]
    return FileResponse(path, media_type="video/mp4", filename=f"{title}.mp4")


class BatchExportRequest(BaseModel):
    clip_ids: list[str]
    options: dict | None = None


@app.post("/api/clips/batch-export")
def batch_export(req: BatchExportRequest):
    db = load_db()
    errors: list[str] = []
    results = []
    for cid in req.clip_ids[:20]:
        c = db["clips"].get(cid)
        if not c:
            errors.append(f"{cid}: not found")
            continue
        project = db["projects"].get(c["project_id"])
        if not project or not Path(project.get("file_path", "")).exists():
            errors.append(f"{c.get('selected_title') or cid}: source missing")
            continue
        options = {**{k: c.get(k) for k in (
            "aspect", "crop_mode", "caption_style", "caption_position", "caption_size", "trim_start",
            "trim_end", "volume", "denoise", "smart_cuts", "zoom", "music", "music_volume", "watermark", "watermark_size", "captions_enabled",
            "overlays", "crop_x", "crop_y", "crop_zoom", "dual_top_x", "dual_top_y", "dual_top_zoom",
            "dual_bottom_x", "dual_bottom_y", "dual_bottom_zoom", "dual_auto", "track_motion",
            "inset_x", "inset_y", "inset_zoom", "inset_size", "inset_shape", "inset_pos_x",
            "inset_pos_y", "inset_bg_fit", "inset_bg_x", "inset_bg_y", "inset_bg_zoom", "inset_border",
        "inset_border_color", "inset_border_width", "inset_radius", "inset_shadow",
            "keyframes",
            "headline", "headline_enabled", "headline_seconds", "progress_bar", "accent_color",
            "remove_fillers", "caption_font", "emoji_enabled", "keywords_enabled",
            "caption_words")}, **(req.options or {})}
        try:
            result = render.render_clip(project, c, options)
            results.append(result)

            def mutate(d, cid=cid, result=result, options=options):
                clip = d["clips"][cid]
                clip["export_path"] = result["path"]
                clip["export"] = result
                clip["status"] = "exported"
                clip["exported_at"] = time.time()
                clip.setdefault("exports", []).append({
                    "path": result["path"], "url": result["url"], "at": time.time(),
                    "size": result["size"], "duration": result["duration"],
                    "aspect": options.get("aspect"), "caption_style": options.get("caption_style"),
                })
                clip["exports"] = clip["exports"][-8:]
            update(mutate)
        except Exception as exc:
            errors.append(f"{c.get('selected_title') or cid}: {exc}")
    return {"rendered": results, "errors": errors}


# ---------------------------------------------------------------- settings
class SettingsPatch(BaseModel):
    whisper_model: str | None = None
    llm_enabled: bool | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    max_clips: int | None = None
    default_aspect: str | None = None
    default_aspects: list[str] | None = None
    emoji_enabled: bool | None = None
    keywords_enabled: bool | None = None
    brand_kit: dict | None = None


@app.get("/api/settings")
def read_settings():
    s = get_settings()
    import os

    s["llm_api_key_set"] = bool(os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    return s


@app.put("/api/settings")
def write_settings(patch: SettingsPatch):
    data = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
    return save_settings(data)


BRAND_KEYS = [
    "caption_style", "caption_position", "caption_size", "caption_font",
    "accent_color", "watermark", "watermark_size", "music", "music_volume",
    "progress_bar", "emoji_enabled", "keywords_enabled",
    "inset_border_color", "inset_border_width", "inset_radius",
]


class BrandApply(BaseModel):
    # Empty list = every clip in the project, or the whole library.
    clip_ids: list[str] | None = None
    project_id: str | None = None


@app.post("/api/brand/apply")
def brand_apply(req: BrandApply):
    """Stamp the saved brand kit onto clips.

    The brand kit is the "channel look": caption style, colours, watermark and
    the on-screen extras, saved once and applied to any clip. Only keys the kit
    actually defines are touched, so a clip keeps its own crop and framing.
    """
    kit = get_settings().get("brand_kit") or {}
    patch = {k: kit[k] for k in BRAND_KEYS if k in kit and kit[k] is not None}
    if not patch:
        raise HTTPException(400, "No brand kit has been saved yet.")

    db = load_db()
    if req.clip_ids:
        targets = [cid for cid in req.clip_ids if cid in db["clips"]]
    elif req.project_id:
        targets = [cid for cid, c in db["clips"].items()
                   if c.get("project_id") == req.project_id]
    else:
        targets = list(db["clips"].keys())
    if not targets:
        raise HTTPException(404, "No clips to apply the brand kit to.")

    def mutate(d):
        for cid in targets:
            d["clips"][cid].update(patch)

    update(mutate)
    return {"applied": len(targets), "clip_ids": targets, "patch": patch}


@app.get("/api/brand")
def brand_read():
    return {"brand_kit": get_settings().get("brand_kit") or {}, "keys": BRAND_KEYS}


@app.get("/api/options")
def options():
    return {
        "platforms": PLATFORM_PRESETS,
        "aspects": render.ASPECTS,
        "caption_styles": render.CAPTION_STYLES,
        "music": render.MUSIC_MOODS,
        "categories": CATEGORIES,
        "presets": {
            "short": {"label": "15–30s", "min": 15, "max": 30},
            "medium": {"label": "30–45s", "min": 30, "max": 45},
            "long": {"label": "45–60s", "min": 45, "max": 60},
            "extended": {"label": "60–90s", "min": 60, "max": 90},
            "any": {"label": "Auto mix", "min": 15, "max": 90},
        },
        "whisper_models": ["tiny.en", "base.en", "small.en", "medium.en"],
    }
