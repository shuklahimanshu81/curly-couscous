"""Config. Everything comes from the environment, which on CI means repo secrets.

Nothing here reads a credentials file, so there is no secret anywhere in the repo
and nothing to leak if the repo is public.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Loading a .env is only for running locally; on Actions the env is already set.
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# --- Trends ---------------------------------------------------------------
TRENDS_GEO = _opt("TRENDS_GEO", "IN")
TRENDS_RSS = f"https://trends.google.com/trending/rss?geo={TRENDS_GEO}"
MIN_SPORTS_SCORE = int(_opt("MIN_SPORTS_SCORE", "3"))

# --- Script ---------------------------------------------------------------
ANTHROPIC_API_KEY = _opt("ANTHROPIC_API_KEY")
SCRIPT_MODEL = _opt("SCRIPT_MODEL", "claude-sonnet-5-5")
TARGET_SECONDS = int(_opt("TARGET_SECONDS", "40"))

# --- HeyGen ---------------------------------------------------------------
HEYGEN_API_KEY = _opt("HEYGEN_API_KEY")
HEYGEN_AVATAR_ID = _opt("HEYGEN_AVATAR_ID")
HEYGEN_VOICE_ID = _opt("HEYGEN_VOICE_ID")
HEYGEN_BASE = "https://api.heygen.com"
HEYGEN_POLL_SECONDS = int(_opt("HEYGEN_POLL_SECONDS", "15"))
HEYGEN_TIMEOUT_MINUTES = int(_opt("HEYGEN_TIMEOUT_MINUTES", "20"))

# --- Hosting (GitHub Release assets on a public repo) --------------------
GITHUB_REPOSITORY = _opt("GITHUB_REPOSITORY")          # "owner/repo", set by Actions
GITHUB_TOKEN = _opt("GITHUB_TOKEN")                    # the workflow's own token
RELEASE_TAG = _opt("RELEASE_TAG", "drafts")
GITHUB_API = "https://api.github.com"
GITHUB_UPLOADS = "https://uploads.github.com"

# --- Instagram ------------------------------------------------------------
IG_USER_ID = _opt("IG_USER_ID")
IG_ACCESS_TOKEN = _opt("IG_ACCESS_TOKEN")
IG_API_VERSION = _opt("IG_API_VERSION", "v26.0")
IG_GRAPH = f"https://graph.facebook.com/{IG_API_VERSION}"
IG_POLL_SECONDS = int(_opt("IG_POLL_SECONDS", "10"))
IG_TIMEOUT_MINUTES = int(_opt("IG_TIMEOUT_MINUTES", "10"))

# --- YouTube --------------------------------------------------------------
YT_CLIENT_ID = _opt("YT_CLIENT_ID")
YT_CLIENT_SECRET = _opt("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = _opt("YT_REFRESH_TOKEN")
# Unaudited API projects have every upload locked to private regardless of what
# you send here, so "private" is the honest default. Change it only once your
# project has passed the YouTube API compliance audit.
YT_PRIVACY_STATUS = _opt("YT_PRIVACY_STATUS", "private")
YT_CATEGORY_ID = _opt("YT_CATEGORY_ID", "17")  # 17 = Sports

# --- Toggles --------------------------------------------------------------
ENABLE_INSTAGRAM = _opt("ENABLE_INSTAGRAM", "true").lower() == "true"
ENABLE_YOUTUBE = _opt("ENABLE_YOUTUBE", "true").lower() == "true"

# --- State ----------------------------------------------------------------
STATE_FILE = REPO_ROOT / "state" / "seen_topics.json"
DEDUPE_DAYS = int(_opt("DEDUPE_DAYS", "7"))
