"""Publish a Reel through the Instagram Graph API.

Two-step flow: create a media container pointing at a public video URL, poll until
Instagram has finished downloading and transcoding it, then publish the container.

Account requirements (these are Meta's, not negotiable):
  - Instagram Business or Creator account, connected to a Facebook Page
  - a Meta app with instagram_business_content_publish
  - Reels published this way are capped at 90 seconds
"""

import time

import requests

import config


def _check(resp: requests.Response) -> dict:
    body = resp.json()
    if "error" in body:
        err = body["error"]
        raise RuntimeError(
            f"Instagram API error {err.get('code')}: {err.get('message')} "
            f"({err.get('error_user_msg') or 'no user message'})"
        )
    resp.raise_for_status()
    return body


def create_container(video_url: str, caption: str, share_to_feed: bool = True) -> str:
    resp = requests.post(
        f"{config.IG_GRAPH}/{config.IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": config.IG_ACCESS_TOKEN,
        },
        timeout=60,
    )
    container_id = _check(resp).get("id")
    if not container_id:
        raise RuntimeError("Instagram returned no container id")
    return container_id


def wait_for_container(container_id: str) -> None:
    """Instagram downloads and transcodes asynchronously; publishing early fails."""
    deadline = time.time() + config.IG_TIMEOUT_MINUTES * 60

    while time.time() < deadline:
        resp = requests.get(
            f"{config.IG_GRAPH}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": config.IG_ACCESS_TOKEN,
            },
            timeout=30,
        )
        body = _check(resp)
        status = body.get("status_code")

        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(
                f"Container {container_id} ended as {status}: {body.get('status')}"
            )

        time.sleep(config.IG_POLL_SECONDS)

    raise TimeoutError(f"Container {container_id} was not ready in time")


def publish_container(container_id: str) -> str:
    resp = requests.post(
        f"{config.IG_GRAPH}/{config.IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": config.IG_ACCESS_TOKEN},
        timeout=60,
    )
    media_id = _check(resp).get("id")
    if not media_id:
        raise RuntimeError("Instagram returned no media id on publish")
    return media_id


def publishing_quota() -> dict:
    """Instagram allows 50 API posts per rolling 24h. Worth checking before a burst."""
    resp = requests.get(
        f"{config.IG_GRAPH}/{config.IG_USER_ID}/content_publishing_limit",
        params={"fields": "config,quota_usage", "access_token": config.IG_ACCESS_TOKEN},
        timeout=30,
    )
    return _check(resp)


def publish_reel(video_url: str, caption: str) -> str:
    if not (config.IG_USER_ID and config.IG_ACCESS_TOKEN):
        raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN are not set")
    container_id = create_container(video_url, caption)
    wait_for_container(container_id)
    return publish_container(container_id)
