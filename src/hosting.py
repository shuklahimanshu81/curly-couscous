"""Host the rendered MP4 at a public URL that Instagram can fetch.

Instagram's Graph API does not accept raw bytes for Reels -- you hand it a URL and
it downloads the file itself. On a public repo, GitHub Release assets are served
without authentication, which means zero extra infrastructure: no bucket, no CDN,
no credentials beyond the workflow's own GITHUB_TOKEN.

If you need the repo private, swap this module for an R2 or S3 uploader. It only
has to expose `host(source_url, filename) -> public_url`.
"""

from pathlib import Path

import requests

import config

_CHUNK = 1 << 20


def _headers() -> dict:
    if not config.GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                if chunk:
                    fh.write(chunk)
    return dest


def _ensure_release() -> int:
    """Find or create the rolling release that holds draft videos."""
    repo = config.GITHUB_REPOSITORY
    url = f"{config.GITHUB_API}/repos/{repo}/releases/tags/{config.RELEASE_TAG}"

    resp = requests.get(url, headers=_headers(), timeout=30)
    if resp.status_code == 200:
        return resp.json()["id"]
    if resp.status_code != 404:
        resp.raise_for_status()

    created = requests.post(
        f"{config.GITHUB_API}/repos/{repo}/releases",
        headers=_headers(),
        json={
            "tag_name": config.RELEASE_TAG,
            "name": "Reel drafts",
            "body": "Rendered videos awaiting or past approval. Managed automatically.",
            "prerelease": True,
        },
        timeout=30,
    )
    created.raise_for_status()
    return created.json()["id"]


def _delete_existing_asset(release_id: int, filename: str) -> None:
    repo = config.GITHUB_REPOSITORY
    resp = requests.get(
        f"{config.GITHUB_API}/repos/{repo}/releases/{release_id}/assets",
        headers=_headers(),
        params={"per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    for asset in resp.json():
        if asset["name"] == filename:
            requests.delete(
                f"{config.GITHUB_API}/repos/{repo}/releases/assets/{asset['id']}",
                headers=_headers(),
                timeout=30,
            )


def upload(local_path: Path, filename: str) -> str:
    release_id = _ensure_release()
    _delete_existing_asset(release_id, filename)

    headers = _headers() | {"Content-Type": "video/mp4"}
    with open(local_path, "rb") as fh:
        resp = requests.post(
            f"{config.GITHUB_UPLOADS}/repos/{config.GITHUB_REPOSITORY}"
            f"/releases/{release_id}/assets",
            headers=headers,
            params={"name": filename},
            data=fh,
            timeout=600,
        )
    resp.raise_for_status()
    return resp.json()["browser_download_url"]


def prune_old_assets(keep: int = 20) -> None:
    """Release assets count toward repo storage; keep only the recent ones."""
    try:
        release_id = _ensure_release()
        resp = requests.get(
            f"{config.GITHUB_API}/repos/{config.GITHUB_REPOSITORY}"
            f"/releases/{release_id}/assets",
            headers=_headers(),
            params={"per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        assets = sorted(resp.json(), key=lambda a: a["created_at"], reverse=True)
        for asset in assets[keep:]:
            requests.delete(
                f"{config.GITHUB_API}/repos/{config.GITHUB_REPOSITORY}"
                f"/releases/assets/{asset['id']}",
                headers=_headers(),
                timeout=30,
            )
    except Exception:
        pass  # housekeeping should never fail a run


def host(source_url: str, filename: str, workdir: Path) -> str:
    local = download(source_url, workdir / filename)
    try:
        return upload(local, filename)
    finally:
        local.unlink(missing_ok=True)
