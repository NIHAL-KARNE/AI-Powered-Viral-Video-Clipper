from __future__ import annotations

import json
import os

import httpx

from .db import get_settings

SYSTEM = """You are a short-form video editor. You receive candidate clips from a long video with transcript.
For each clip return improved metadata that is faithful to the transcript and never misleading.
Reply with strict JSON: {"clips":[{"id":str,"score":number 0-100,"titles":[5 strings],"hook":str,
"description":str <=200 chars,"hashtags":[3-6 strings],"keywords":[5-8 strings],"category":str}]}
Score reflects likely short-form performance given hook, emotion, novelty, context. Do not invent facts."""


def refine_clips(clips: list[dict], segments: list[dict]) -> list[dict]:
    settings = get_settings()
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("LLM is enabled but no API key is configured (set LLM_API_KEY in the backend environment).")
    base = settings.get("llm_base_url", "https://api.openai.com/v1").rstrip("/")
    payload_clips = [{
        "id": c["id"], "start": c["start"], "end": c["end"], "duration": c["duration"],
        "local_score": c["score"], "category": c["category"], "transcript": c["text"][:4000],
    } for c in clips]
    body = {
        "model": settings.get("llm_model", "gpt-4o-mini"),
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({"clips": payload_clips})},
        ],
    }
    with httpx.Client(timeout=90) as client:
        resp = client.post(f"{base}/chat/completions", json=body,
                           headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    by_id = {c["id"]: c for c in clips}
    for item in parsed.get("clips", []):
        clip = by_id.get(item.get("id"))
        if not clip:
            continue
        titles = [str(t).strip() for t in (item.get("titles") or []) if str(t).strip()]
        if titles:
            clip["titles"] = titles[:5]
            clip["selected_title"] = titles[0]
            clip["title_source"] = "llm"
        if item.get("hook"):
            clip["hook"] = str(item["hook"])[:200]
        if item.get("description"):
            clip["description"] = str(item["description"])[:240]
        tags = [str(t) for t in (item.get("hashtags") or [])]
        if tags:
            clip["hashtags"] = [t if t.startswith("#") else f"#{t}" for t in tags[:6]]
        if item.get("keywords"):
            clip["keywords"] = [str(k) for k in item["keywords"]][:8]
        if item.get("category"):
            clip["category_label"] = str(item["category"])[:60]
        try:
            s = float(item.get("score"))
            clip["score"] = round(max(0.0, min(99.0, s)), 1)
            clip["llm_boost"] = clip["score"]
        except (TypeError, ValueError):
            pass
    return clips
