# Cloudflare Worker Setup — Stocks Live Updates

The Worker proxies Yahoo Finance with proper CORS headers so your GitHub Pages briefing can fetch live stock prices directly from the browser. **Free forever** at your usage level (~500 requests/day vs. the 100,000/day free quota).

---

## One-time setup (~5 minutes)

### 1. Create a Cloudflare account

1. Go to https://dash.cloudflare.com/sign-up
2. Sign up with email — **no credit card required**
3. Verify email
4. You can skip the "add a domain" prompt — Workers don't need one

### 2. Create the Worker

1. In the Cloudflare dashboard left sidebar: **Workers & Pages**
2. Click **Create application** → **Create Worker**
3. Name it `daily-briefing-stocks` (or anything; remember the name)
4. Click **Deploy** (deploys the default "hello world" — we'll replace it)

### 3. Paste the real code

1. After deploying, click **Edit code** (top right of the Worker's page)
2. The browser opens an editor with the hello-world code on the left
3. **Select all** in the editor and **delete it**
4. Open `worker/worker.js` from this repo and copy everything
5. Paste into the Cloudflare editor

### 4. Update the allowed origin

Near the top of the file you'll see:

```javascript
const ALLOWED_ORIGINS = [
  "https://bossgamer-09.github.io",
  "http://localhost:8000",
];
```

Change `bossgamer-09` to your actual GitHub username if different. Save the file (Ctrl+S in the editor).

### 5. Deploy

Click the blue **Deploy** button in the top right. Should say "Deployment successful" within ~10 seconds.

### 6. Get your Worker URL

At the top of the Worker's page you'll see something like:

```
daily-briefing-stocks.YOURUSER.workers.dev
```

That's your endpoint. Test it in your browser:

```
https://daily-briefing-stocks.YOURUSER.workers.dev/health
```

Should return: `ok`

Then test a quote:

```
https://daily-briefing-stocks.YOURUSER.workers.dev/quote?symbols=AAPL
```

Should return JSON like `{"AAPL":{"symbol":"AAPL","name":"Apple Inc.","price":271.06,...}}`.

### 7. Wire it into briefing.py

Open `briefing.py` and find this line near the top (~line 50):

```python
STOCK_WORKER_URL = "https://daily-briefing-stocks.bossgamer-09.workers.dev"
```

Change `bossgamer-09` to whatever your actual Worker subdomain is (Cloudflare assigns it based on your account name, which may differ from your GitHub username).

Commit and push. The next workflow run (or click "Run workflow" in the Actions tab to trigger immediately) will rebuild your page with the new Worker URL embedded.

### 8. Verify it works

Open your live briefing page. You should see:

- **🟢 live · last update Xs ago** indicator next to the timestamp at the top
- Stock prices that flash blue briefly when they change
- Crypto prices updating every 2 minutes
- ISS location updating every 30 seconds
- Weather updating every 10 minutes

Open your browser's DevTools → Console to see logs like:

```
[live] updater started {stockWorkerUrl: "...", ...}
[stocks] updated 10 symbols
[crypto] updated 6 coins
```

---

## Maintenance

**You don't have to do anything.** The Worker runs forever, no maintenance needed.

If Yahoo ever blocks Cloudflare's IPs (rare), you'll see `[stocks] failed: HTTP 401` in the console. The fix would be to switch the Worker to a different finance API. We'll cross that bridge if/when.

---

## Costs

- **Worker requests:** 500/day estimated (50/visit × 10 visits). Free tier: **100,000/day**. You're at 0.5%.
- **Worker compute time:** each request ~30ms. Free tier: 10ms/request average × 100K requests/day. We're slightly over the per-request average, but well under daily compute budget. Cloudflare lets you use bursts as long as the daily total fits.
- **Bandwidth:** ~10 MB/day estimated. Free tier: unlimited.

**Total cost: $0 forever** at this usage level.

---

## Troubleshooting

**"🔴 connection issues" in the indicator**
→ Open DevTools console. The error message will tell you which source is failing (stocks, crypto, weather, or ISS). Paste the error and we'll debug.

**Stock prices don't update but crypto does**
→ Worker URL is wrong, or Worker isn't deployed. Visit `https://YOUR-WORKER.workers.dev/health` directly — should return "ok". If it 404s, redeploy.

**CORS error in console**
→ Your GitHub Pages URL isn't in `ALLOWED_ORIGINS` in the Worker code. Update it and redeploy the Worker.

**Worker returns 200 but no data**
→ Yahoo blocked the Worker's specific IP. Cloudflare rotates these, so it usually self-heals within an hour. If persistent, the Worker needs a User-Agent rotation tweak.

**"⚪ paused (tab inactive)"**
→ Working as designed. Switch back to the tab to resume.

**Want to disable live updates entirely?**
→ Set `STOCK_WORKER_URL = ""` in `briefing.py`. The script stays in-place and updates only on the workflow's twice-daily schedule.
