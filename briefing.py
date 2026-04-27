#!/usr/bin/env python3
"""
Daily Briefing — static HTML generator for GitHub Pages.

Pulls:
  - Local + global news RSS
  - GDELT 2.0 (global conflict events)
  - ReliefWeb (UN humanitarian reports)
  - NOAA Space Weather (Kp + alerts)
  - Open-Meteo (weather)

Writes: index.html (committed to gh-pages branch by the workflow)
"""

from __future__ import annotations

import html
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import feedparser
import requests

# --- CONFIG ---------------------------------------------------------------

LOCATION_NAME = "Lynnwood, WA"
LAT, LON = 47.8279, -122.3054
TZ = ZoneInfo("America/Los_Angeles")

LOCAL_FEEDS = [
    ("KING 5 Seattle", "https://www.king5.com/feeds/syndication/rss/news/local"),
    ("Seattle Times", "https://www.seattletimes.com/seattle-news/feed/"),
    ("MyNorthwest", "https://mynorthwest.com/feed/"),
]

GLOBAL_FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Guardian World", "https://www.theguardian.com/world/rss"),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
]

MAX_PER_FEED = 5
USER_AGENT = "DailyBriefing/1.0 (github-actions; personal-use)"
SENTINEL_URL = "https://sentinel.axonia.us/"

# --- LOGGING --------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("briefing")


# --- DATA TYPES -----------------------------------------------------------

@dataclass
class Article:
    source: str
    title: str
    url: str


# --- FETCHERS -------------------------------------------------------------

def fetch_rss(name: str, url: str) -> list[Article]:
    """Pull RSS, return up to MAX_PER_FEED articles. Resilient to feed errors."""
    try:
        # feedparser handles redirects, encodings, and weird feeds well.
        parsed = feedparser.parse(url, agent=USER_AGENT)
        if parsed.bozo and not parsed.entries:
            log.warning("Feed bad: %s — %s", name, parsed.bozo_exception)
            return []
        out: list[Article] = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or "#"
            if title:
                out.append(Article(source=name, title=title, url=link))
        return out
    except Exception as e:
        log.warning("Feed failed: %s — %s", name, e)
        return []


def fetch_gdelt() -> list[Article]:
    """Global conflict/terror events from past 24h, sorted by relevance."""
    query = "(theme:ARMEDCONFLICT OR theme:TERROR)"
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": "10",
        "timespan": "24H",
        "format": "json",
        "sort": "hybridrel",
    }
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params)}"
    try:
        r = requests.get(url, timeout=45, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
        articles = data.get("articles", [])
        return [
            Article(
                source=a.get("domain", "GDELT"),
                title=a.get("title", "").strip(),
                url=a.get("url", "#"),
            )
            for a in articles[:10]
            if a.get("title")
        ]
    except Exception as e:
        log.warning("GDELT failed: %s", e)
        return []


def fetch_reliefweb() -> list[Article]:
    """UN humanitarian reports — latest 8."""
    # ReliefWeb v2 requires a unique appname; using a personal identifier.
    params = {
        "appname": "github-pages-daily-briefing-r1200",
        "profile": "list",
        "preset": "latest",
        "limit": "8",
    }
    url = f"https://api.reliefweb.int/v2/reports?{urlencode(params)}"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
        out: list[Article] = []
        for item in data.get("data", []):
            f = item.get("fields", {})
            title = (f.get("title") or "").strip()
            link = f.get("url") or "#"
            if title:
                out.append(Article(source="ReliefWeb", title=title, url=link))
        return out
    except Exception as e:
        log.warning("ReliefWeb failed: %s", e)
        return []


def fetch_space_weather() -> str:
    """Kp index + recent alerts. Returns one-line summary."""
    try:
        kp = requests.get(
            "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
            timeout=15,
        ).json()
        # Skip header row, take last data row
        latest = kp[-1]
        kp_val = float(latest[1])
        kp_time = latest[0]
        if kp_val >= 7:
            status = "G3+ severe geomagnetic storm"
        elif kp_val >= 5:
            status = "G1-G2 minor/moderate storm"
        elif kp_val >= 4:
            status = "active — auroras possible at high latitudes"
        else:
            status = "quiet"
        return f"Kp {kp_val:.1f} ({status}) as of {kp_time} UTC"
    except Exception as e:
        log.warning("NOAA failed: %s", e)
        return "Unavailable"


def fetch_weather() -> str:
    """Open-Meteo — current conditions + today's forecast for LAT/LON."""
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "forecast_days": 2,
    }
    url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        w = r.json()
        c = w["current"]
        d = w["daily"]
        return (
            f"Now: {c['temperature_2m']}°F · humidity {c['relative_humidity_2m']}% · "
            f"wind {c['wind_speed_10m']} mph. "
            f"Today: high {d['temperature_2m_max'][0]}°F / low {d['temperature_2m_min'][0]}°F · "
            f"precip {d['precipitation_probability_max'][0]}%."
        )
    except Exception as e:
        log.warning("Weather failed: %s", e)
        return "Weather unavailable."


# --- HTML BUILDER ---------------------------------------------------------

def render_articles(arts: list[Article]) -> str:
    if not arts:
        return '<p class="empty">No items.</p>'
    lis = []
    for a in arts:
        lis.append(
            f'<li><a href="{html.escape(a.url)}" target="_blank" rel="noopener">'
            f'<strong>{html.escape(a.source)}</strong> — {html.escape(a.title)}'
            f"</a></li>"
        )
    return f"<ul>{''.join(lis)}</ul>"


def build_html(
    *,
    weather: str,
    space_wx: str,
    local: list[Article],
    global_: list[Article],
    gdelt: list[Article],
    relief: list[Article],
) -> str:
    now_local = datetime.now(TZ)
    now_utc = datetime.now(timezone.utc)
    timestamp = now_local.strftime("%A, %B %-d, %Y — %-I:%M %p %Z")
    iso_built = now_utc.isoformat(timespec="seconds")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="3600">
<title>Daily Briefing — {timestamp}</title>
<meta name="generated-at" content="{iso_built}">
<style>
:root {{
  --bg: #0e1116; --panel: #161b22; --border: #30363d;
  --text: #e6edf3; --muted: #8b949e;
  --accent: #58a6ff; --accent2: #f0883e;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--text);
  margin: 0; padding: 16px; line-height: 1.55;
}}
.wrap {{ max-width: 980px; margin: 0 auto; }}
header {{
  border-bottom: 1px solid var(--border);
  padding-bottom: 12px; margin-bottom: 20px;
}}
h1 {{ margin: 0 0 4px 0; font-size: 26px; }}
h1 .accent {{ color: var(--accent); }}
.muted {{ color: var(--muted); font-size: 13px; }}
.card {{
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 18px 22px; margin-bottom: 18px;
}}
.card h2 {{
  margin: 22px 0 10px 0; font-size: 17px; color: var(--accent2);
  border-bottom: 1px solid var(--border); padding-bottom: 8px;
}}
.card h2:first-child {{ margin-top: 0; }}
.card ul {{ padding-left: 20px; margin: 0; }}
.card li {{ margin-bottom: 6px; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.empty {{ color: var(--muted); font-style: italic; margin: 6px 0; }}
.kv {{ font-size: 14px; }}
.kv strong {{ color: var(--accent2); }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
       font-size: 11px; margin-right: 6px; }}
.tag-gdelt {{ background: #1f3a5f; color: #79c0ff; }}
.tag-relief {{ background: #2d4f2d; color: #7ee787; }}
.tag-space {{ background: #4a2d5f; color: #d2a8ff; }}
.tag-wx    {{ background: #5a3a1a; color: #ffd28a; }}
.footer {{
  text-align: center; color: var(--muted); font-size: 12px;
  margin-top: 24px; padding-top: 12px; border-top: 1px solid var(--border);
}}
.footer a {{ color: var(--muted); }}
.sentinel-link {{
  display: inline-block; margin-top: 6px; padding: 8px 14px;
  background: #1f3a5f; color: #79c0ff; border-radius: 6px;
  text-decoration: none; font-size: 14px;
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1><span class="accent">☕</span> Daily Briefing</h1>
  <div class="muted">{timestamp} · {LOCATION_NAME}</div>
</header>

<div class="card">
  <h2><span class="tag tag-wx">WEATHER</span> {LOCATION_NAME}</h2>
  <p class="kv">{html.escape(weather)}</p>

  <h2><span class="tag tag-space">NOAA</span> Space Weather</h2>
  <p class="kv">{html.escape(space_wx)}</p>

  <h2>🌍 Sentinel — Live Geopolitical Globe</h2>
  <p class="kv">For the live map of conflicts, military flights, and SIGINT:</p>
  <a class="sentinel-link" href="{SENTINEL_URL}" target="_blank" rel="noopener">
    Open Sentinel →
  </a>
</div>

<div class="card">
  <h2><span class="tag tag-gdelt">GDELT</span> Global Events — past 24h</h2>
  {render_articles(gdelt)}

  <h2><span class="tag tag-relief">ReliefWeb</span> Humanitarian Reports</h2>
  {render_articles(relief)}
</div>

<div class="card">
  <h2>Local — Seattle / Lynnwood</h2>
  {render_articles(local)}

  <h2>Global</h2>
  {render_articles(global_)}
</div>

<div class="footer">
  Generated {iso_built} UTC by
  <a href="https://github.com/" target="_blank">GitHub Actions</a> ·
  Sources: RSS, GDELT 2.0, ReliefWeb, NOAA SWPC, Open-Meteo ·
  Auto-refreshes hourly
</div>

</div>
</body>
</html>
"""


# --- MAIN -----------------------------------------------------------------

def main() -> int:
    log.info("Starting briefing generation...")

    log.info("Local news...")
    local: list[Article] = []
    for name, url in LOCAL_FEEDS:
        local.extend(fetch_rss(name, url))

    log.info("Global news...")
    global_: list[Article] = []
    for name, url in GLOBAL_FEEDS:
        global_.extend(fetch_rss(name, url))

    log.info("GDELT...")
    gdelt = fetch_gdelt()

    # Tiny pause to be polite to ReliefWeb
    time.sleep(1)
    log.info("ReliefWeb...")
    relief = fetch_reliefweb()

    log.info("Space weather...")
    space_wx = fetch_space_weather()

    log.info("Weather...")
    weather = fetch_weather()

    log.info(
        "Counts — local:%d global:%d gdelt:%d relief:%d",
        len(local), len(global_), len(gdelt), len(relief),
    )

    html_doc = build_html(
        weather=weather,
        space_wx=space_wx,
        local=local,
        global_=global_,
        gdelt=gdelt,
        relief=relief,
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)
    log.info("Wrote index.html (%d bytes)", len(html_doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
