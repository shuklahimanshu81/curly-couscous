#!/usr/bin/env bash
# One-shot setup: create the repo, push, set secrets, create the approval gate.
#
#   ./setup.sh
#
# Needs the GitHub CLI, logged in:  https://cli.github.com  then  gh auth login
# Secrets are typed into hidden prompts on your machine and sent straight to
# GitHub, encrypted. Nothing is written to disk or echoed.

set -euo pipefail

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
note()  { printf '  %s\n' "$*"; }

command -v gh  >/dev/null || { echo "Install the GitHub CLI first: https://cli.github.com"; exit 1; }
command -v git >/dev/null || { echo "git is required"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first"; exit 1; }

cd "$(dirname "$0")"

# --- 1. repo ----------------------------------------------------------------
bold "1/5  Repository"
read -rp "  Repo name [reels-bot]: " NAME
NAME=${NAME:-reels-bot}
OWNER=$(gh api user --jq .login)
REPO="$OWNER/$NAME"

if [ ! -d .git ]; then
  git init -q -b main
fi
git add -A
git -c user.name="$OWNER" -c user.email="$OWNER@users.noreply.github.com" \
    commit -qm "Initial commit: sports reels bot" 2>/dev/null || true

if gh repo view "$REPO" >/dev/null 2>&1; then
  note "$REPO already exists, pushing to it"
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
  git push -u origin main
else
  # Public: approval gates are free only on public repos, and public release
  # assets are how Instagram fetches the video. No secrets live in the repo.
  gh repo create "$REPO" --public --source=. --push --description "Automated sports Reels"
fi
note "https://github.com/$REPO"

# --- 2. approval gate -------------------------------------------------------
bold "2/5  Approval gate"
UID_NUM=$(gh api user --jq .id)
gh api -X PUT "repos/$REPO/environments/publish-approval" \
  --input - >/dev/null <<JSON
{"reviewers":[{"type":"User","id":$UID_NUM}],"prevent_self_review":false}
JSON
note "Environment 'publish-approval' now requires your approval"

# --- 3. secrets -------------------------------------------------------------
bold "3/5  Secrets (hidden input; press Enter to skip any you don't have yet)"
set_secret() {
  local name=$1 hint=$2 val
  read -rsp "  $name  ($hint): " val; echo
  if [ -n "$val" ]; then
    printf '%s' "$val" | gh secret set "$name" --repo "$REPO" >/dev/null
    note "set"
  else
    note "skipped -- set later with: gh secret set $name --repo $REPO"
  fi
}
set_secret ANTHROPIC_API_KEY "console.anthropic.com"
set_secret HEYGEN_API_KEY    "HeyGen settings > API"
set_secret HEYGEN_AVATAR_ID  "see README"
set_secret HEYGEN_VOICE_ID   "see README"
set_secret IG_USER_ID        "see README, Instagram step 6"
set_secret IG_ACCESS_TOKEN   "60-day token"

read -rp "  Set up YouTube now? Needs scripts/get_youtube_token.py output [y/N]: " YT
if [[ "$YT" =~ ^[Yy]$ ]]; then
  set_secret YT_CLIENT_ID      "OAuth desktop client"
  set_secret YT_CLIENT_SECRET  "OAuth desktop client"
  set_secret YT_REFRESH_TOKEN  "from get_youtube_token.py"
  YT_ON=true
else
  YT_ON=false
fi

# --- 4. variables -----------------------------------------------------------
bold "4/5  Settings"
gh variable set TRENDS_GEO        --repo "$REPO" --body "IN"      >/dev/null
gh variable set MIN_SPORTS_SCORE  --repo "$REPO" --body "3"       >/dev/null
gh variable set TARGET_SECONDS    --repo "$REPO" --body "40"      >/dev/null
gh variable set ENABLE_INSTAGRAM  --repo "$REPO" --body "true"    >/dev/null
gh variable set ENABLE_YOUTUBE    --repo "$REPO" --body "$YT_ON"  >/dev/null
gh variable set YT_PRIVACY_STATUS --repo "$REPO" --body "private" >/dev/null
note "Geo IN, 40s scripts, YouTube $( [ "$YT_ON" = true ] && echo on || echo off )"

# --- 5. smoke test ----------------------------------------------------------
bold "5/5  Smoke test"
read -rp "  Trigger a dry run now (script only, no render, no spend)? [Y/n]: " RUN
if [[ ! "$RUN" =~ ^[Nn]$ ]]; then
  sleep 3  # give GitHub a moment to register the workflow file
  gh workflow run reels.yml --repo "$REPO" -f dry_run=true
  note "Started. Watch it: https://github.com/$REPO/actions"
fi

echo
bold "Done."
note "Manual run:  Actions tab > Sports Reel > Run workflow"
note "Schedule:    07:30 and 18:30 IST, automatic"
note "Reminder:    the Instagram token expires in 60 days"
