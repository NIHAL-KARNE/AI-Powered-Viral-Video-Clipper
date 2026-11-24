from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CLIPPER_DATA", ROOT / "data"))
UPLOADS = DATA / "uploads"
THUMBS = DATA / "thumbs"
CLIPS = DATA / "clips"
CACHE = DATA / "cache"
EXPORTS = DATA / "exports"
DB_PATH = DATA / "db.json"
SETTINGS_PATH = DATA / "settings.json"

for folder in (DATA, UPLOADS, THUMBS, CLIPS, CACHE, EXPORTS):
    folder.mkdir(parents=True, exist_ok=True)

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
WHISPER_DIR = os.environ.get("WHISPER_CACHE", str(Path.home() / ".cache" / "whisper"))

DEFAULT_SETTINGS = {
    "whisper_model": WHISPER_MODEL,
    "llm_enabled": False,
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "llm_api_key_set": False,
    "max_clips": 10,
    "default_aspect": "9:16",
    # Ratios the analyzer produces clips for by default (multi-select).
    "default_aspects": ["9:16"],
    # Auto emoji + keyword highlighting are on by default for new renders.
    "emoji_enabled": True,
    "keywords_enabled": True,
    # A saved "channel look" applied to any clip in one click: caption style and
    # colour, font, watermark, music and the on-screen extras. Stored once so a
    # creator does not re-set the same seven controls on every clip.
    "brand_kit": {
        "name": "My channel",
        "caption_style": "bold-pop",
        "caption_position": "bottom",
        "caption_size": 100,
        "caption_font": "",
        "accent_color": "#8b5cf6",
        "watermark": "",
        "watermark_size": 100,
        "music": "none",
        "music_volume": 0.12,
        "progress_bar": True,
        "emoji_enabled": True,
        "keywords_enabled": True,
        "inset_border_color": "#ffffff",
        "inset_border_width": 4,
        "inset_radius": 26,
    },
}

PLATFORM_PRESETS = {
    "tiktok": {"label": "TikTok", "aspect": "9:16", "width": 1080, "height": 1920},
    "reels": {"label": "Instagram Reels", "aspect": "9:16", "width": 1080, "height": 1920},
    "shorts": {"label": "YouTube Shorts", "aspect": "9:16", "width": 1080, "height": 1920},
    "square": {"label": "Square", "aspect": "1:1", "width": 1080, "height": 1080},
    "landscape": {"label": "Landscape", "aspect": "16:9", "width": 1920, "height": 1080},
}

ALLOWED_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"}
