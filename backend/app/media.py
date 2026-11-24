from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

from .config import CACHE, THUMBS, UPLOADS


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError((proc.stderr or proc.stdout or "command failed")[-1200:])
    return proc


def probe(path: Path) -> dict:
    proc = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=120)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise MediaError("This file has no video track.")
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise MediaError("Could not read the video duration.")
    fps_raw = video.get("avg_frame_rate") or "30/1"
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den or 1)
    except Exception:
        fps = 30.0
    return {
        "duration": round(duration, 3),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(fps or 30.0, 3),
        "codec": video.get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
        "has_audio": audio is not None,
        "bitrate": int(float(fmt.get("bit_rate") or 0)),
        "size": int(fmt.get("size") or path.stat().st_size),
        "format": (fmt.get("format_name") or "").split(",")[0],
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_audio(path: Path, out: Path, sample_rate: int = 16000) -> Path:
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(out),
    ])
    return out


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return data, sr


def make_thumb(path: Path, out: Path, at: float, width: int = 640) -> bool:
    try:
        run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{max(at, 0):.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out),
        ], timeout=120)
        return out.exists() and out.stat().st_size > 0
    except Exception:
        return False


_FACE_MODEL: Path = Path(__file__).resolve().parent / "assets" / "face_detection_yunet_2023mar.onnx"


def _face_detector(width: int, height: int, score: float = 0.5):
    """YuNet face detector (MIT licensed, bundled) with a Haar fallback."""
    if _FACE_MODEL.exists():
        try:
            det = cv2.FaceDetectorYN.create(str(_FACE_MODEL), "", (width, height), score, 0.3, 5000)
            det.setInputSize((width, height))
            return det
        except Exception:
            pass
    return None


def _rows_to_faces(found, w: int, h: int) -> list[dict]:
    faces: list[dict] = []
    if found is None:
        return faces
    for row in found:
        fx, fy, fw, fh = (float(v) for v in row[:4])
        if fw <= 2 or fh <= 2:
            continue
        faces.append({
            "x": round(float(fx + fw / 2) / w, 4),
            "y": round(float(fy + fh / 2) / h, 4),
            "w": round(float(fw) / w, 4),
            "h": round(float(fh) / h, 4),
            "area": round(float(fw * fh) / (w * h), 5),
        })
    faces.sort(key=lambda f: -f["area"])
    return faces


def _detect_faces(det, gray: "np.ndarray", cascade) -> list[dict]:
    """Return face boxes as normalised centres with area, largest first.

    YuNet works on colour images and finds faces Haar misses, especially at low
    resolution or in soft light, which is what made auto-follow look frozen.
    """
    h, w = gray.shape[:2]
    faces: list[dict] = []
    if det is not None:
        try:
            bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            _n, found = det.detect(bgr)
            faces = _rows_to_faces(found, w, h)
        except Exception:
            faces = []
    if not faces and cascade is not None:
        try:
            for (fx, fy, fw, fh) in cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24)):
                faces.append({
                    "x": round(float(fx + fw / 2) / w, 4),
                    "y": round(float(fy + fh / 2) / h, 4),
                    "w": round(float(fw) / w, 4),
                    "h": round(float(fh) / h, 4),
                    "area": round(float(fw * fh) / (w * h), 5),
                })
        except Exception:
            pass
    faces.sort(key=lambda f: -f["area"])
    return faces[:4]


def _detect_region(frame: "np.ndarray", box: tuple[float, float, float, float],
                   score: float = 0.35) -> list[dict]:
    """Detect faces inside a sub-region, for confirming a tracked subject.

    Small or motion-blurred faces often survive detection at full resolution
    inside a crop even when the whole downscaled frame finds nothing.
    """
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    px0, py0 = int(max(x0, 0) * w), int(max(y0, 0) * h)
    px1, py1 = int(min(x1, 1) * w), int(min(y1, 1) * h)
    crop = frame[py0:py1, px0:px1]
    if crop.size == 0 or crop.shape[0] < 48 or crop.shape[1] < 48:
        return []
    det = _face_detector(crop.shape[1], crop.shape[0], score)
    if det is None:
        return []
    try:
        _n, found = det.detect(crop)
    except Exception:
        return []
    out = _rows_to_faces(found, crop.shape[1], crop.shape[0])
    cw, ch = (px1 - px0) / w, (py1 - py0) / h
    for f in out:
        f["x"] = round(px0 / w + f["x"] * cw, 4)
        f["y"] = round(py0 / h + f["y"] * ch, 4)
        f["w"] = round(f["w"] * cw, 4)
        f["h"] = round(f["h"] * ch, 4)
        f["area"] = round(f["w"] * f["h"], 5)
    out.sort(key=lambda f: -f["area"])
    return out[:4]


def analyze_frames(path: Path, duration: float, sample_every: float = 0.5, max_frames: int = 6000,
                   face_hint: tuple[float, float] | None = None) -> dict:
    """Sample frames once, tracking scene cuts, brightness, motion and faces.

    Faces are found at 640px wide with a relaxed confidence threshold, then any
    frame that found nothing is retried inside a box around the subject's last
    known position. That second pass is what keeps the camera on the subject
    through motion blur, profile shots and brief occlusion, instead of snapping
    to the centre.

    Frames in between samples are only demuxed, never decoded, so a long video
    costs about one decode per sample rather than one per frame.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"fps": 30.0, "frames": [], "scenes": [0.0], "duration": duration}
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        total = int(duration * fps)
    step = max(int(round(fps * sample_every)), 1)
    if duration > max_frames * sample_every:
        step = max(int(fps * duration / max_frames), 1)
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    try:
        cascade = cv2.CascadeClassifier(str(cascade_path))
    except Exception:
        cascade = None
    detector = None
    det_size: tuple[int, int] = (0, 0)
    frames: list[dict] = []
    scenes = [0.0]
    prev_small = None
    tracked: tuple[float, float] | None = face_hint
    idx = 0
    while True:
        if not cap.grab():
            break
        if idx % step != 0:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        if not ok or frame is None:
            break
        h, w = frame.shape[:2]
        tw = 640
        th = max(int(tw * h / max(w, 1)), 2)
        small = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if detector is None or det_size != (gray.shape[1], gray.shape[0]):
            detector = _face_detector(gray.shape[1], gray.shape[0], 0.45)
            det_size = (gray.shape[1], gray.shape[0])
        t = idx / fps
        motion = 0.0
        if prev_small is not None and prev_small.shape == gray.shape:
            motion = float(np.mean(cv2.absdiff(gray, prev_small)) / 255.0)
        if prev_small is not None and motion > 0.16 and t - scenes[-1] > 1.5:
            scenes.append(round(t, 2))

        faces = _detect_faces(detector, gray, cascade)
        if not faces and tracked:
            # Retry around the last known face, at full resolution, so a turning
            # or blurred subject is not lost for a whole sample.
            box = (tracked[0] - 0.22, tracked[1] - 0.32,
                   tracked[0] + 0.22, tracked[1] + 0.32)
            faces = _detect_region(frame, box)
        if faces:
            # Keep following the same person: prefer the box nearest the last
            # position over the largest face, which would hop between speakers.
            if tracked:
                def near_score(f: dict) -> float:
                    d = ((f["x"] - tracked[0]) * (w / max(h, 1))) ** 2 + (f["y"] - tracked[1]) ** 2
                    return d - float(f.get("area", 0)) * 6

                best = min(faces, key=near_score)
                near = ((best["x"] - tracked[0]) * (w / max(h, 1))) ** 2 + (best["y"] - tracked[1]) ** 2
                tracked = (float(best["x"]), float(best["y"])) if near < 0.25 ** 2 \
                    else (float(faces[0]["x"]), float(faces[0]["y"]))
            else:
                tracked = (float(faces[0]["x"]), float(faces[0]["y"]))
        result = faces[:4]
        if tracked and not result:
            # Report the held position so downstream code never loses the subject.
            result = [{"x": round(tracked[0], 4), "y": round(tracked[1], 4),
                       "w": 0.0, "h": 0.0, "area": 0.0, "held": True}]
        frames.append({
            "t": round(t, 2),
            "brightness": round(float(np.mean(gray) / 255.0), 3),
            "motion": round(motion, 3),
            "faces": result,
        })
        prev_small = gray
        idx += 1
    cap.release()
    return {
        "fps": round(float(fps), 2),
        "frames": frames,
        "scenes": scenes,
        "duration": duration,
        "sample_every": round(step / float(fps), 2) if fps else 1.0,
    }


FRAME_ANALYSIS_VERSION = 3


def cached_frames(path: Path, duration: float, sample_every: float = 0.5,
                  media_hash: str | None = None) -> dict:
    """Frame/face analysis, cached on disk.

    Face detection is the slow part of a render and the editor asks for it on
    every clip open, so the result is stored per source file and sample rate.
    """
    key_src = media_hash or hashlib.sha256(f"{path}-{path.stat().st_mtime_ns}".encode()).hexdigest()
    tag = f"{key_src[:32]}-frames-v{FRAME_ANALYSIS_VERSION}-{sample_every:g}"
    cache_file = CACHE / f"{tag}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            if data.get("frames"):
                return data
        except Exception:
            pass
    data = analyze_frames(path, duration, sample_every=sample_every)
    try:
        cache_file.write_text(json.dumps(data))
    except Exception:
        pass
    return data


def download_remote(url: str, dest_dir: Path, video_id: str, progress=None,
                    cookies_file: str | None = None) -> tuple[Path, dict]:
    """Download a permitted remote video with yt-dlp. Respects source terms of service."""
    if shutil.which("yt-dlp") is None:
        import sys

        ytdlp = [sys.executable, "-m", "yt_dlp"]
    else:
        ytdlp = ["yt-dlp"]
    out_tpl = str(dest_dir / f"{video_id}.%(ext)s")
    cmd = ytdlp + [
        "--no-playlist", "--newline", "--no-warnings",
        "--socket-timeout", "30", "--retries", "3",
        "--format", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b",
        "--merge-output-format", "mp4",
        "--print-json", "--no-simulate",
        "-o", out_tpl,
    ]
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    cmd.append(url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines: list[str] = []
    meta: dict = {}
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        lines.append(line)
        if line.startswith("{"):
            try:
                meta = json.loads(line)
            except Exception:
                pass
        elif progress and "[download]" in line and "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                progress(min(0.35, 0.05 + pct / 100 * 0.3))
            except Exception:
                pass
    code = proc.wait()
    if code != 0:
        tail = "\n".join(lines[-8:])
        if "Sign in to confirm" in tail or "bot" in tail.lower():
            raise MediaError(
                "This site is blocking automated downloads from this server (bot check). "
                "Options: upload the video file directly, or add a cookies file for yt-dlp "
                "at backend/data/cookies.txt and retry."
            )
        if "Private video" in tail or "unavailable" in tail.lower():
            raise MediaError("This video is private or unavailable. Try another link or upload the file.")
        raise MediaError(
            "Could not download this link. The site may block downloads or the URL may be invalid. "
            f"Details: {tail[-300:]}"
        )
    candidates = sorted(dest_dir.glob(f"{video_id}.*"), key=lambda p: p.stat().st_size, reverse=True)
    candidates = [p for p in candidates if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4a"}]
    if not candidates:
        raise MediaError("Download finished but no video file was produced.")
    path = candidates[0]
    if meta.get("duration"):
        meta["duration"] = float(meta["duration"])
    return path, meta


def ffmpeg_progress_reader(proc: subprocess.Popen, duration: float, start_frac: float, end_frac: float, cb):
    """Parse -progress pipe:1 output from FFmpeg and report a bounded fraction."""
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if line.startswith("out_time_ms=") and duration > 0:
            try:
                ms = int(line.split("=")[1])
                frac = min(max(ms / 1_000_000 / duration, 0), 1)
                cb(start_frac + frac * (end_frac - start_frac))
            except Exception:
                pass
