"""Upload the same video to YouTube as a Short.

Important limitation: for any Google Cloud project created after 28 July 2020,
videos uploaded through videos.insert are locked to private until the project
passes the YouTube API compliance audit. The privacyStatus you send is ignored
until then, and you cannot flip the video public from Studio either. So the
realistic flow before the audit is: this uploads a private draft, you publish it
yourself in Studio. The upload step is still worth automating.

Quota: an upload costs 1600 units against a 10,000/day default, so roughly six
uploads a day. Two is comfortable.
"""

from pathlib import Path

import requests

import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_CHUNK = 1 << 22  # 4 MiB, a multiple of 256 KiB as the resumable protocol requires


def _access_token() -> str:
    """Exchange the long-lived refresh token for a short-lived access token."""
    missing = [
        name
        for name, val in (
            ("YT_CLIENT_ID", config.YT_CLIENT_ID),
            ("YT_CLIENT_SECRET", config.YT_CLIENT_SECRET),
            ("YT_REFRESH_TOKEN", config.YT_REFRESH_TOKEN),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(f"YouTube creds missing: {', '.join(missing)}")

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": config.YT_CLIENT_ID,
            "client_secret": config.YT_CLIENT_SECRET,
            "refresh_token": config.YT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"YouTube token refresh failed: {resp.text}")
    return resp.json()["access_token"]


def _title_from(topic: str, caption: str) -> str:
    """YouTube caps titles at 100 characters."""
    title = topic.strip() or caption.split("\n")[0]
    if len(title) > 90:
        title = title[:87].rsplit(" ", 1)[0] + "..."
    return f"{title} #shorts"


def upload(video_path: Path, topic: str, caption: str) -> str:
    token = _access_token()

    metadata = {
        "snippet": {
            "title": _title_from(topic, caption),
            # #Shorts in the description is what gets it classified as a Short,
            # along with the vertical aspect ratio and sub-60s runtime.
            "description": f"{caption}\n\n#Shorts",
            "categoryId": config.YT_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": config.YT_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    size = video_path.stat().st_size

    # Phase 1: open a resumable session.
    init = requests.post(
        UPLOAD_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        params={"part": "snippet,status", "uploadType": "resumable"},
        json=metadata,
        timeout=60,
    )
    if init.status_code >= 400:
        raise RuntimeError(f"YouTube upload init failed: {init.status_code} {init.text}")

    session_url = init.headers.get("Location")
    if not session_url:
        raise RuntimeError("YouTube did not return a resumable session URL")

    # Phase 2: send the bytes.
    with open(video_path, "rb") as fh:
        resp = requests.put(
            session_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
            data=fh,
            timeout=900,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"YouTube upload failed: {resp.status_code} {resp.text}")

    video_id = resp.json().get("id")
    if not video_id:
        raise RuntimeError(f"No video id in YouTube response: {resp.text}")
    return video_id
