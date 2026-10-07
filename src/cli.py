"""Entrypoint for both workflow jobs.

    python cli.py draft    [--topic "..."] [--dry-run]
    python cli.py publish

`draft` picks a topic, writes the script, renders the avatar video, hosts it, and
writes draft.json plus a readable job summary. It publishes nothing.

`publish` reads draft.json and posts to Instagram and YouTube. The workflow only
reaches it after you approve the deployment in the Actions UI.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import config
import hosting
import script_gen
import state
import trends
from trends import Trend

DRAFT_FILE = Path(config.REPO_ROOT) / "draft.json"


def log(msg: str) -> None:
    print(msg, flush=True)


def summary(markdown: str) -> None:
    """Write to the Actions job summary -- this is what you read before approving."""
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    else:
        print(markdown)


def set_output(key: str, value: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


# --------------------------------------------------------------------------
# draft
# --------------------------------------------------------------------------

def pick_topic(forced: str | None) -> Trend | None:
    if forced:
        return Trend(title=forced, score=99)

    candidates = trends.fetch()
    if not candidates:
        log("No sports trends cleared the threshold this run.")
        return None

    for trend in candidates:
        if state.was_seen(trend.title):
            log(f"Skipping {trend.title!r} -- covered within the last "
                f"{config.DEDUPE_DAYS} days")
            continue
        log(f"Picked {trend.title!r} (score {trend.score})")
        return trend

    log("Every sports trend in this run has been covered already.")
    return None


def cmd_draft(args) -> int:
    trend = pick_topic(args.topic)
    if trend is None:
        summary("## Nothing to post\n\nNo fresh sports trend cleared the filter this run.")
        set_output("has_draft", "false")
        return 0

    log("Writing script...")
    draft = script_gen.generate(trend)
    log(f"Script ready: ~{draft['estimated_seconds']}s, "
        f"{len(draft['script'].split())} words")

    if args.dry_run:
        summary(
            f"## Dry run: {trend.title}\n\n"
            f"**Script** (~{draft['estimated_seconds']}s)\n\n"
            f"> {draft['script']}\n\n"
            f"**Caption**\n\n> {draft['caption']}\n"
        )
        set_output("has_draft", "false")
        return 0

    import avatar  # imported here so --dry-run never needs HeyGen creds

    log("Rendering avatar video. This usually takes a few minutes...")
    heygen_url = avatar.render(draft["script"])

    filename = f"reel-{time.strftime('%Y%m%d-%H%M')}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        video_url = hosting.host(heygen_url, filename, Path(tmp))
    hosting.prune_old_assets()
    log(f"Hosted at {video_url}")

    payload = {
        "topic": trend.title,
        "script": draft["script"],
        "caption": draft["caption"],
        "headline": draft["headline"],
        "seconds": draft["estimated_seconds"],
        "video_url": video_url,
        "filename": filename,
    }
    DRAFT_FILE.write_text(json.dumps(payload, indent=2) + "\n")

    state.mark_seen(trend.title)

    targets = []
    if config.ENABLE_INSTAGRAM:
        targets.append("Instagram Reel")
    if config.ENABLE_YOUTUBE:
        targets.append(f"YouTube Short ({config.YT_PRIVACY_STATUS})")

    summary(
        f"## Ready for review: {trend.title}\n\n"
        f"**[Watch the render]({video_url})** · ~{draft['estimated_seconds']}s · "
        f"going to {', '.join(targets) or 'nowhere, both targets are disabled'}\n\n"
        f"### Script\n\n> {draft['script']}\n\n"
        f"### Caption\n\n```\n{draft['caption']}\n```\n\n"
        f"---\n\nApprove the **publish** job below to send it, or reject to bin it. "
        f"Check the script against the real story before approving.\n"
    )
    set_output("has_draft", "true")
    set_output("topic", trend.title)
    return 0


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------

def cmd_publish(args) -> int:
    if not DRAFT_FILE.exists():
        log("No draft.json found -- nothing to publish.")
        return 1

    draft = json.loads(DRAFT_FILE.read_text())
    results, failures = [], []

    if config.ENABLE_INSTAGRAM:
        import publish_ig

        try:
            log("Publishing to Instagram...")
            media_id = publish_ig.publish_reel(draft["video_url"], draft["caption"])
            results.append(f"- Instagram Reel published, media id `{media_id}`")
            log(f"Instagram media id {media_id}")
        except Exception as exc:
            failures.append(f"- Instagram failed: `{exc}`")
            log(f"Instagram failed: {exc}")

    if config.ENABLE_YOUTUBE:
        import publish_yt

        try:
            log("Uploading to YouTube...")
            with tempfile.TemporaryDirectory() as tmp:
                local = hosting.download(
                    draft["video_url"], Path(tmp) / draft["filename"]
                )
                video_id = publish_yt.upload(local, draft["topic"], draft["caption"])
            note = (
                " (locked private until your API project passes the compliance audit; "
                "publish it from Studio)"
                if config.YT_PRIVACY_STATUS == "private"
                else ""
            )
            results.append(
                f"- YouTube upload complete: https://youtu.be/{video_id}{note}"
            )
            log(f"YouTube video id {video_id}")
        except Exception as exc:
            failures.append(f"- YouTube failed: `{exc}`")
            log(f"YouTube failed: {exc}")

    summary(
        f"## Published: {draft['topic']}\n\n"
        + "\n".join(results + failures)
        + "\n"
    )

    # A partial failure should turn the run red so the notification reaches you,
    # but only if nothing at all got through do we treat it as a total loss.
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft")
    draft.add_argument("--topic", default=None)
    draft.add_argument("--dry-run", action="store_true")
    draft.set_defaults(func=cmd_draft)

    publish = sub.add_parser("publish")
    publish.set_defaults(func=cmd_publish)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
