from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import DB_PATH, DEFAULT_SETTINGS, SETTINGS_PATH

_lock = threading.RLock()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _load(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text())
    except Exception:
        return fallback


def load_db() -> dict:
    with _lock:
        db = _load(DB_PATH, {"projects": {}, "clips": {}, "jobs": {}})
        db.setdefault("projects", {})
        db.setdefault("clips", {})
        db.setdefault("jobs", {})
        return db


def save_db(db: dict) -> None:
    with _lock:
        tmp = DB_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(db, indent=2))
        tmp.replace(DB_PATH)


def update(mutator) -> dict:
    with _lock:
        db = load_db()
        mutator(db)
        save_db(db)
        return db


def get_settings() -> dict:
    return {**DEFAULT_SETTINGS, **_load(SETTINGS_PATH, {})}


def save_settings(patch: dict[str, Any]) -> dict:
    with _lock:
        current = get_settings()
        allowed = {k: v for k, v in patch.items() if k in DEFAULT_SETTINGS and k != "llm_api_key_set"}
        # The brand kit is edited field by field in the UI, so merge it instead
        # of replacing it: sending `{caption_style: "neon"}` must not wipe the
        # watermark and music already saved.
        if isinstance(allowed.get("brand_kit"), dict):
            merged = {**(current.get("brand_kit") or {}), **allowed["brand_kit"]}
            allowed["brand_kit"] = merged
        current.update(allowed)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2))
        tmp.replace(SETTINGS_PATH)
        return current


def set_job(job_id: str, **fields) -> None:
    def mutate(db):
        job = db["jobs"].setdefault(job_id, {"id": job_id, "created_at": time.time()})
        job.update(fields)
        job["updated_at"] = time.time()
        # keep job table bounded
        if len(db["jobs"]) > 300:
            oldest = sorted(db["jobs"].values(), key=lambda j: j.get("updated_at", 0))[:100]
            for j in oldest:
                db["jobs"].pop(j["id"], None)
    update(mutate)


def get_job(job_id: str) -> dict | None:
    return load_db()["jobs"].get(job_id)
