"""Render the script as a vertical avatar video via the HeyGen API."""

import time

import requests

import config


def _headers() -> dict:
    if not config.HEYGEN_API_KEY:
        raise RuntimeError("HEYGEN_API_KEY is not set")
    return {"X-Api-Key": config.HEYGEN_API_KEY, "Content-Type": "application/json"}


def list_avatars() -> list[dict]:
    """Helper for first-time setup: find the avatar_id and voice_id to put in .env."""
    resp = requests.get(f"{config.HEYGEN_BASE}/v2/avatars", headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("avatars", [])


def list_voices() -> list[dict]:
    resp = requests.get(f"{config.HEYGEN_BASE}/v2/voices", headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("voices", [])


def submit(script: str) -> str:
    """Kick off a render and return the HeyGen video_id."""
    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": config.HEYGEN_AVATAR_ID,
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "text",
                    "input_text": script,
                    "voice_id": config.HEYGEN_VOICE_ID,
                    "speed": 1.0,
                },
            }
        ],
        # 1080x1920 is the Reels aspect ratio; anything else gets letterboxed.
        "dimension": {"width": 1080, "height": 1920},
    }

    resp = requests.post(
        f"{config.HEYGEN_BASE}/v2/video/generate",
        headers=_headers(),
        json=payload,
        timeout=60,
    )
    body = resp.json()
    if resp.status_code >= 400 or body.get("error"):
        raise RuntimeError(f"HeyGen rejected the render: {body}")

    video_id = body.get("data", {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"No video_id in HeyGen response: {body}")
    return video_id


def wait_for(video_id: str) -> str:
    """Block until the render finishes; return the downloadable video URL."""
    deadline = time.time() + config.HEYGEN_TIMEOUT_MINUTES * 60

    while time.time() < deadline:
        resp = requests.get(
            f"{config.HEYGEN_BASE}/v1/video_status.get",
            headers=_headers(),
            params={"video_id": video_id},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status")

        if status == "completed":
            url = data.get("video_url")
            if not url:
                raise RuntimeError(f"HeyGen reported completed with no URL: {data}")
            return url
        if status == "failed":
            raise RuntimeError(f"HeyGen render failed: {data.get('error') or data}")

        time.sleep(config.HEYGEN_POLL_SECONDS)

    raise TimeoutError(
        f"HeyGen render {video_id} did not finish within "
        f"{config.HEYGEN_TIMEOUT_MINUTES} minutes"
    )


def render(script: str) -> str:
    return wait_for(submit(script))
