# Sports Reels Bot

Twice a day, GitHub Actions pulls trending sports searches, writes a script with
Claude, renders it as a vertical avatar video, and parks it for your approval.
You press **Approve** in the Actions tab and it goes to Instagram and YouTube.

No server, no cron on a VM, no bot process to keep alive. The only infrastructure
is this repo.

```
  schedule (or Run workflow button)
             │
             ▼
   ┌──────────────────┐
   │  draft job       │  trends → script → HeyGen render → release asset
   └────────┬─────────┘  writes the script + video link into the job summary
            │
            ▼
   ╔══════════════════╗
   ║  WAITING FOR YOU ║  ← Review deployments: Approve / Reject
   ╚════════┬═════════╝     (email + mobile push from GitHub)
            │
            ▼
   ┌──────────────────┐
   │  publish job     │  Instagram Reel + YouTube Short
   └──────────────────┘
```

---

## Where your credentials go

Not to anyone. They go into **Settings → Secrets and variables → Actions** as
encrypted repository secrets. Only the workflow runner can decrypt them, they
never appear in logs, and GitHub masks them if a script accidentally prints one.

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `HEYGEN_API_KEY` | HeyGen → Settings → API |
| `HEYGEN_AVATAR_ID` | see "Finding your HeyGen ids" below |
| `HEYGEN_VOICE_ID` | same |
| `IG_USER_ID` | see Instagram setup |
| `IG_ACCESS_TOKEN` | see Instagram setup |
| `YT_CLIENT_ID` | `scripts/get_youtube_token.py` prints it back |
| `YT_CLIENT_SECRET` | same |
| `YT_REFRESH_TOKEN` | same |

`GITHUB_TOKEN` is provided automatically — don't create it.

Non-secret settings go under the **Variables** tab instead, so you can change them
without touching code: `TRENDS_GEO`, `MIN_SPORTS_SCORE`, `TARGET_SECONDS`,
`ENABLE_INSTAGRAM`, `ENABLE_YOUTUBE`, `YT_PRIVACY_STATUS`.

---

## Setup

### 1. The repo

Make it **public**. Two reasons: required-reviewer approval gates are free on
public repos but need a paid plan on private ones, and Release assets on a public
repo are served without authentication, which is how Instagram fetches the video.
Nothing sensitive lives in the repo — secrets are stored outside it.

If you need it private, you'll need GitHub Pro or Team for the approval gate, and
you'll need to swap `src/hosting.py` for an R2 or S3 uploader. It only has to
expose `host(source_url, filename, workdir) -> public_url`.

### 2. The approval gate — do not skip this

**Settings → Environments → New environment → `publish-approval`**

Tick **Required reviewers** and add yourself. Save.

Without this the environment exists but doesn't gate anything, and the workflow
will publish unattended. The job name in the Actions UI will still say it ran —
the only difference is whether it waited for you.

### 3. Instagram

A personal account cannot publish through the API. Meta grants no content
publishing access to personal accounts at all.

1. Instagram app → Settings → Account type → **Creator** or **Business**. Free.
2. Link it to a Facebook Page. Meta requires the Page to prove ownership; an empty
   Page is fine.
3. developers.facebook.com → create an app, type Business, add the Instagram
   product, connect your account.
4. Permissions: `instagram_business_basic`, `instagram_business_content_publish`,
   `pages_read_engagement`.

   These need App Review, which takes a few weeks — but you don't have to wait.
   While the app sits in **Development mode** it can publish to accounts holding a
   role on the app, and as the admin yours qualifies. Only file for review if you
   later add someone else's account.

5. Exchange your short-lived token (they die in an hour) for a 60-day one:

   ```
   GET https://graph.facebook.com/v26.0/oauth/access_token
       ?grant_type=fb_exchange_token
       &client_id=APP_ID&client_secret=APP_SECRET
       &fb_exchange_token=SHORT_LIVED_TOKEN
   ```

   **Put a reminder in your calendar for day 55.** An expired token is the single
   most likely way this quietly stops working.

6. Find your IG user id:
   `GET /v26.0/me/accounts` → take the Page id →
   `GET /v26.0/{page-id}?fields=instagram_business_account`

Limits: 50 API posts per rolling 24h (you use 2), and Reels are capped at **90
seconds** through the API even though the app allows longer.

### 4. YouTube — read this before you count on it

Google Cloud project → enable **YouTube Data API v3** → create an OAuth client of
type **Desktop app** → then:

```bash
python scripts/get_youtube_token.py
```

It opens your browser once and prints the three values to paste into secrets.

**The catch:** for any Cloud project created after 28 July 2020, every video
uploaded via `videos.insert` is locked to private until the project passes the
YouTube API compliance audit. The `privacyStatus` you send is ignored, and you
can't flip it public from Studio either. There's no development-mode workaround
like Instagram's.

So until you pass the audit, YouTube works as: this uploads a private draft, you
open Studio and hit publish. Still saves the upload. `YT_PRIVACY_STATUS` defaults
to `private` to reflect reality — change it to `public` only after the audit.

If that annoys you, set the variable `ENABLE_YOUTUBE=false` and run
Instagram-only until the audit clears.

Quota note: an upload costs 1600 of your 10,000 daily units, so about six a day.
Two is comfortable.

### 5. Finding your HeyGen ids

```bash
cd src && python -c "
import avatar
for a in avatar.list_avatars()[:20]: print(a['avatar_id'], a.get('avatar_name'))
for v in avatar.list_voices()[:20]: print(v['voice_id'], v.get('name'), v.get('language'))
"
```

Pick an Indian English voice so it matches the script register. HeyGen's free tier
watermarks output — budget for a paid tier before you post anything real. This is
your main recurring cost, well above the Claude calls.

---

## Using it

**Actions tab → Sports Reel → Run workflow.** That's your manual trigger, with
two optional inputs: force a topic, or tick dry run to see the script without
spending a render.

Start with a dry run. It costs one cheap Claude call and renders nothing, so it's
the right way to tune the script prompt and the trend filter.

When a real run finishes the draft job, open it. The **job summary** shows the
topic, the full script, the caption, and a link to watch the rendered video. Read
it, then scroll to the publish job and press **Review deployments → Approve**.
GitHub emails you and pushes to your phone when something is waiting, so you don't
have to go looking.

Reject instead and the run ends having posted nothing.

The schedule is 02:00 and 13:00 UTC, which is 07:30 and 18:30 IST. Edit the cron
lines in `.github/workflows/reels.yml` to move them. GitHub's scheduler can run a
few minutes late under load; it doesn't matter here.

---

## Things that will bite you

**The IG token expires in 60 days.** Most likely cause of silent failure. Calendar
reminder, day 55.

**Trends RSS is unofficial.** No SLA, format can change without notice. It's
isolated to `src/trends.py` so a break is contained. `trendspy` is the usual
fallback if the feed disappears.

**The sports filter is a heuristic.** It scores on sports news domains plus a term
lexicon. Run a few dry runs over a week and tune `SPORTS_TERMS` and
`MIN_SPORTS_SCORE` against what it actually catches — too low and finance stories
slip in, too high and quiet days produce nothing.

**Accuracy is the real risk, and the approval gate is what's handling it.** The
script is written from headlines nothing verified, and sports topics trend hardest
exactly when a story is disputed or still developing. The prompt constrains the
model to the supplied brief and forces hedging language, but that is not the same
as being right. Read the script before you approve, especially on injury,
transfer and death rumours, where being fast and wrong does damage that outlives
the post.

**Don't put match footage in these.** An avatar talking to camera is safe. Sports
leagues are the most aggressive rights-holders on short-form video, and borrowed
clips are the fastest route to strikes on a new account.

**Two a day from one voice gets stale.** Topics are deduped for 7 days, but watch
whether the evening slot is actually earning its place before you assume it is.
