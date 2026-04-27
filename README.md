# Daily Briefing

A static morning briefing that regenerates twice a day on GitHub Actions and publishes to GitHub Pages. Aggregates local + global news (RSS), GDELT 2.0 conflict events, ReliefWeb humanitarian reports, NOAA space weather, and weather forecast. No API keys required. No server to run.

**Live page:** `https://YOURNAME.github.io/daily-briefing/` *(after setup below)*

---

## What's in here

| File | Purpose |
|---|---|
| `briefing.py` | Pulls all sources, writes `index.html` |
| `requirements.txt` | Python dependencies |
| `.github/workflows/daily-briefing.yml` | Runs the script twice daily, deploys to Pages |

---

## One-time setup

### 1. Create the repo

1. On GitHub, create a new **public** repo named `daily-briefing` (any name works; just use the same name in the URL).
2. Push these three files into it:

```bash
git init
git add briefing.py requirements.txt .github/
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOURNAME/daily-briefing.git
git push -u origin main
```

### 2. Enable GitHub Pages

1. In the repo: **Settings → Pages**
2. Under "Build and deployment", set **Source** to `GitHub Actions` (NOT "Deploy from a branch")
3. Save.

That's it — the workflow handles the rest.

### 3. Trigger the first run

Either push something to `main`, or:

1. Go to the **Actions** tab
2. Click "Daily Briefing" in the left sidebar
3. Click "Run workflow" → "Run workflow"

After ~30 seconds, your page is live at:
```
https://YOURNAME.github.io/daily-briefing/
```

(Replace `YOURNAME` with your GitHub username, and `daily-briefing` with whatever you named the repo.)

---

## Schedule

The workflow runs:

- **~7:00 AM Pacific** (14:00 UTC) — morning briefing
- **~7:00 PM Pacific** (02:00 UTC next day) — evening briefing
- **Whenever you push to `main`** — handy for testing changes
- **Manually** — Actions tab → Run workflow

> **Note:** GitHub's cron is best-effort and can be delayed up to ~15 minutes during peak hours. For a once-or-twice daily briefing this doesn't matter.

> **Note:** The cron times are tuned for PDT (Pacific Daylight Time, UTC-7). When the US switches to PST (UTC-8) in November, the runs shift by an hour. If you care, edit the cron lines in the workflow.

---

## Customizing

Open `briefing.py` and edit the **CONFIG** block at the top:

```python
LOCATION_NAME = "Lynnwood, WA"
LAT, LON = 47.8279, -122.3054
TZ = ZoneInfo("America/Los_Angeles")

LOCAL_FEEDS = [...]    # add/remove RSS feeds
GLOBAL_FEEDS = [...]
MAX_PER_FEED = 5       # headlines per source
```

Push the change, the workflow runs automatically, the live page updates. No restart, no redeploy steps.

---

## Adding your phone

On your phone:
1. Open the Pages URL in Safari/Chrome
2. Bookmark it / add to home screen
3. The page auto-refreshes every hour (`<meta refresh>`), so leaving the tab open gives you a live morning dashboard

---

## Costs

Zero. Public repos get unlimited Pages bandwidth and 2,000 free Actions minutes per month. Each run takes ~30-45 seconds, so even running every hour you'd use under 25% of the free quota.

---

## Troubleshooting

**Page shows 404 after first deploy**
→ GitHub Pages can take 2-3 minutes to propagate the very first time. Wait, then refresh.

**Some feeds show 'No items.'**
→ That source's RSS is temporarily down or rate-limited. The script gracefully skips broken feeds. If it happens for the same feed every run, the URL has changed — search "[publisher] rss feed" for the current URL and update `briefing.py`.

**Workflow fails with permission error**
→ In **Settings → Actions → General**, scroll to "Workflow permissions" and ensure "Read and write permissions" is selected (or that the workflow has the `permissions:` block — it does by default in the included workflow).

**No deploys happening on schedule**
→ GitHub disables scheduled workflows in repos with no recent activity (60+ days). Just push any commit (e.g. add a comment to `briefing.py`) to wake it back up.

**Want to see the logs?**
→ Actions tab → click the failed/successful run → click the "build-and-deploy" job → expand any step.

---

## Modifying the data sources

Want to add stocks, GitHub trending, your own RSS, etc? Just add a `fetch_xyz()` function in `briefing.py` following the same pattern as `fetch_weather()` or `fetch_gdelt()`, then add a card for it in `build_html()`. The whole thing is ~250 lines, no framework, easy to extend.
