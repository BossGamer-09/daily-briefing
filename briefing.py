#!/usr/bin/env python3
"""
Daily Briefing v2 — static HTML generator for GitHub Pages.

Sources (no API keys required):
  - News RSS (politically diverse mix)
  - GDELT 2.0 (global conflict events)
  - ReliefWeb (UN humanitarian reports)
  - Hacker News top stories (tech)
  - Reddit r/worldnews top
  - Yahoo Finance v8 (stocks + indexes)
  - CoinGecko (crypto prices)
  - NOAA Space Weather (Kp + alerts)
  - Open-Meteo (weather + air quality)
  - Sunrise-Sunset.org
  - NOAA Tides & Currents (Edmonds/Seattle, station 9447130)

Writes: index.html
"""

from __future__ import annotations

import html
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import feedparser
import requests

# --- CONFIG ---------------------------------------------------------------

LOCATION_NAME = "Lynnwood, WA"
LAT, LON = 47.8279, -122.3054
TZ = ZoneInfo("America/Los_Angeles")

# Politically diverse mix: center-left, center, center-right, business
LOCAL_FEEDS = [
    ("KING 5 Seattle", "https://www.king5.com/feeds/syndication/rss/news/local"),
    ("Seattle Times", "https://www.seattletimes.com/seattle-news/feed/"),
    ("MyNorthwest", "https://mynorthwest.com/feed/"),
]

GLOBAL_FEEDS = [
    # Center-left of mainstream
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ("Guardian World", "https://www.theguardian.com/world/rss"),
    # Center / wire
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
    ("AP Top News", "https://feeds.apnews.com/apf-topnews"),  # alt AP feed
    # Business / center-right of mainstream
    ("WSJ World", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
    ("Washington Examiner", "https://www.washingtonexaminer.com/section/news/feed"),
]

MAX_PER_FEED = 4
USER_AGENT = "DailyBriefing/2.0 (github-actions; personal-use)"
SENTINEL_URL = "https://sentinel.axonia.us/"

# Stocks — Yahoo Finance symbols. Indexes use ^ prefix.
STOCK_INDEXES = [
    ("S&P 500", "^GSPC"),
    ("NASDAQ", "^IXIC"),
    ("Dow Jones", "^DJI"),
]
STOCK_TICKERS = [
    ("Apple", "AAPL"),
    ("Microsoft", "MSFT"),
    ("Alphabet", "GOOGL"),
    ("Tesla", "TSLA"),
    ("Nvidia", "NVDA"),
    ("Amazon", "AMZN"),
    ("Meta", "META"),
]

# Crypto — CoinGecko coin ids
CRYPTO_COINS = [
    ("Bitcoin",   "bitcoin",      "BTC"),
    ("Ethereum",  "ethereum",     "ETH"),
    ("Solana",    "solana",       "SOL"),
    ("XRP",       "ripple",       "XRP"),
    ("Cardano",   "cardano",      "ADA"),
    ("Dogecoin",  "dogecoin",     "DOGE"),
]

# NOAA tide station — 9447130 = Seattle (closest to Edmonds/Lynnwood)
TIDE_STATION = "9447130"
TIDE_STATION_NAME = "Seattle"

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


@dataclass
class Quote:
    name: str
    symbol: str
    price: float | None
    change: float | None       # absolute change
    change_pct: float | None   # percent change


@dataclass
class TideEvent:
    time: str   # local time string like "3:42 AM"
    height: float
    kind: str   # "H" or "L"


# --- HTTP helper ----------------------------------------------------------

def _get_json(url: str, timeout: int = 20, headers: dict | None = None) -> Any:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = requests.get(url, timeout=timeout, headers=h)
    r.raise_for_status()
    return r.json()


# --- NEWS / RSS -----------------------------------------------------------

def fetch_rss(name: str, url: str) -> list[Article]:
    try:
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
    params = {
        "query": "(theme:ARMEDCONFLICT OR theme:TERROR)",
        "mode": "ArtList",
        "maxrecords": "10",
        "timespan": "24H",
        "format": "json",
        "sort": "hybridrel",
    }
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params)}"
    try:
        data = _get_json(url, timeout=45)
        return [
            Article(
                source=a.get("domain", "GDELT"),
                title=a.get("title", "").strip(),
                url=a.get("url", "#"),
            )
            for a in data.get("articles", [])[:10]
            if a.get("title")
        ]
    except Exception as e:
        log.warning("GDELT failed: %s", e)
        return []


def fetch_reliefweb() -> list[Article]:
    params = {
        "appname": "github-pages-daily-briefing-r1200",
        "profile": "list",
        "preset": "latest",
        "limit": "8",
    }
    url = f"https://api.reliefweb.int/v2/reports?{urlencode(params)}"
    try:
        data = _get_json(url, timeout=20)
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


def fetch_hackernews() -> list[Article]:
    """HN top stories — pulls top 10 IDs then their items."""
    try:
        ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=15)
        out: list[Article] = []
        for sid in ids[:10]:
            try:
                item = _get_json(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=10
                )
                title = (item.get("title") or "").strip()
                url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
                if title:
                    out.append(Article(source="HN", title=title, url=url))
            except Exception:
                continue
        return out
    except Exception as e:
        log.warning("HN failed: %s", e)
        return []


def fetch_reddit_worldnews() -> list[Article]:
    """r/worldnews top from past 24h.
    Reddit requires a specific UA format: 'platform:appname:version (by /u/user)'.
    Generic UAs get 403'd.
    """
    url = "https://www.reddit.com/r/worldnews/top.json?t=day&limit=10"
    reddit_ua = "web:daily-briefing:v2.0 (github actions, personal use)"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": reddit_ua})
        r.raise_for_status()
        data = r.json()
        out: list[Article] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = (d.get("title") or "").strip()
            permalink = d.get("permalink") or ""
            if title and permalink:
                out.append(
                    Article(
                        source=f"r/worldnews ({d.get('score', 0)}↑)",
                        title=title,
                        url=f"https://reddit.com{permalink}",
                    )
                )
        return out
    except Exception as e:
        log.warning("Reddit failed: %s", e)
        return []


# --- MARKETS --------------------------------------------------------------

def fetch_yahoo_quotes(symbols: list[str]) -> dict[str, Quote]:
    """Yahoo Finance v8 chart API — works from cloud IPs (unlike v7 quote).
    One request per symbol, but they're parallel-friendly and return fast.
    """
    out: dict[str, Quote] = {}
    if not symbols:
        return out

    # Use a browser-style UA — Yahoo treats library-default UAs more strictly.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    for sym in symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
            r = requests.get(url, timeout=15, headers=headers)
            r.raise_for_status()
            data = r.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue
            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price is None or prev is None:
                continue
            change = price - prev
            pct = (change / prev * 100) if prev else None
            name = meta.get("longName") or meta.get("shortName") or sym
            out[sym] = Quote(
                name=name, symbol=sym,
                price=price, change=change, change_pct=pct,
            )
        except Exception as e:
            log.warning("Yahoo failed for %s: %s", sym, e)
            continue

    return out


def fetch_stocks() -> tuple[list[Quote], list[Quote]]:
    """Returns (indexes, tickers)."""
    all_pairs = STOCK_INDEXES + STOCK_TICKERS
    sym_to_name = {s: n for n, s in all_pairs}
    quotes = fetch_yahoo_quotes([s for _, s in all_pairs])
    # Re-map to original display names
    for sym, q in quotes.items():
        if sym in sym_to_name:
            q.name = sym_to_name[sym]
    indexes = [quotes[s] for _, s in STOCK_INDEXES if s in quotes]
    tickers = [quotes[s] for _, s in STOCK_TICKERS if s in quotes]
    return indexes, tickers


def fetch_crypto() -> list[Quote]:
    """CoinGecko simple price — free, no key."""
    ids = ",".join(c[1] for c in CRYPTO_COINS)
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        data = _get_json(url, timeout=20)
        out: list[Quote] = []
        for name, coin_id, sym in CRYPTO_COINS:
            d = data.get(coin_id)
            if not d:
                continue
            price = d.get("usd")
            pct = d.get("usd_24h_change")
            out.append(
                Quote(
                    name=name,
                    symbol=sym,
                    price=price,
                    change=None,
                    change_pct=pct,
                )
            )
        return out
    except Exception as e:
        log.warning("CoinGecko failed: %s", e)
        return []


# --- ENVIRONMENT ----------------------------------------------------------

def fetch_space_weather() -> str:
    """NOAA Kp index. As of late 2025 the format is a JSON array of dicts:
       [{"time_tag": "...", "Kp": 3.33, "a_running": 18, "station_count": 8}, ...]
    """
    try:
        kp = _get_json(
            "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
            timeout=15,
        )
        if not kp or not isinstance(kp, list):
            return "Unavailable"
        latest = kp[-1]
        # Handle both legacy (array of arrays) and current (array of dicts) formats
        if isinstance(latest, dict):
            kp_val = float(latest.get("Kp", 0))
            kp_time = latest.get("time_tag", "")
        else:
            # Legacy fallback
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
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "forecast_days": 2,
    }
    url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
    try:
        w = _get_json(url, timeout=15)
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


def fetch_air_quality() -> str:
    """Open-Meteo air quality — US AQI, PM2.5, PM10."""
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "us_aqi,pm2_5,pm10",
        "timezone": "auto",
    }
    url = f"https://air-quality-api.open-meteo.com/v1/air-quality?{urlencode(params)}"
    try:
        d = _get_json(url, timeout=15)
        c = d.get("current", {})
        aqi = c.get("us_aqi")
        pm25 = c.get("pm2_5")
        pm10 = c.get("pm10")
        if aqi is None:
            return "Air quality unavailable."
        if aqi <= 50:
            label = "Good"
        elif aqi <= 100:
            label = "Moderate"
        elif aqi <= 150:
            label = "Unhealthy for sensitive groups"
        elif aqi <= 200:
            label = "Unhealthy"
        elif aqi <= 300:
            label = "Very Unhealthy"
        else:
            label = "Hazardous"
        return f"AQI {aqi} ({label}) · PM2.5 {pm25} µg/m³ · PM10 {pm10} µg/m³"
    except Exception as e:
        log.warning("AQI failed: %s", e)
        return "Air quality unavailable."


def fetch_sun() -> str:
    """Sunrise/sunset for today, local time."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    url = (
        f"https://api.sunrise-sunset.org/json"
        f"?lat={LAT}&lng={LON}&date={today}&formatted=0"
    )
    try:
        d = _get_json(url, timeout=15)
        if d.get("status") != "OK":
            return "Sun times unavailable."
        results = d["results"]
        sunrise_utc = datetime.fromisoformat(results["sunrise"])
        sunset_utc = datetime.fromisoformat(results["sunset"])
        sr = sunrise_utc.astimezone(TZ).strftime("%-I:%M %p")
        ss = sunset_utc.astimezone(TZ).strftime("%-I:%M %p")
        # Day length in HH:MM
        secs = int(results["day_length"])
        h, m = secs // 3600, (secs % 3600) // 60
        return f"Sunrise {sr} · Sunset {ss} · Day length {h}h {m}m"
    except Exception as e:
        log.warning("Sun failed: %s", e)
        return "Sun times unavailable."


def fetch_tides() -> list[TideEvent]:
    """NOAA tide predictions for today, hi/low only."""
    url = (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        "?date=today&product=predictions&datum=mllw&interval=hilo"
        f"&format=json&units=english&time_zone=lst_ldt&station={TIDE_STATION}"
        "&application=daily-briefing-r1200"
    )
    try:
        d = _get_json(url, timeout=15)
        out: list[TideEvent] = []
        for p in d.get("predictions", []):
            t_str = p.get("t", "")  # "2026-04-26 03:42"
            # Convert to "3:42 AM"
            try:
                dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M")
                pretty = dt.strftime("%-I:%M %p")
            except ValueError:
                pretty = t_str
            out.append(
                TideEvent(
                    time=pretty,
                    height=float(p.get("v", 0)),
                    kind=p.get("type", ""),
                )
            )
        return out
    except Exception as e:
        log.warning("Tides failed: %s", e)
        return []


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


def render_quotes(quotes: list[Quote], price_fmt: str = "${:,.2f}") -> str:
    if not quotes:
        return '<p class="empty">No data.</p>'
    rows = []
    for q in quotes:
        if q.price is None:
            continue
        cls = "up" if (q.change_pct or 0) >= 0 else "down"
        arrow = "▲" if (q.change_pct or 0) >= 0 else "▼"
        pct = f"{q.change_pct:+.2f}%" if q.change_pct is not None else "—"
        price = price_fmt.format(q.price)
        rows.append(
            f'<tr>'
            f'<td class="qname"><strong>{html.escape(q.name)}</strong> '
            f'<span class="qsym">{html.escape(q.symbol)}</span></td>'
            f'<td class="qprice">{price}</td>'
            f'<td class="qchg {cls}">{arrow} {pct}</td>'
            f'</tr>'
        )
    if not rows:
        return '<p class="empty">No data.</p>'
    return f'<table class="quotes">{"".join(rows)}</table>'


def render_tides(tides: list[TideEvent]) -> str:
    if not tides:
        return '<p class="empty">No tide data.</p>'
    items = []
    for t in tides:
        kind = "High" if t.kind == "H" else "Low" if t.kind == "L" else t.kind
        items.append(
            f'<li><strong>{kind}</strong> · {html.escape(t.time)} · {t.height:.1f} ft</li>'
        )
    return f"<ul>{''.join(items)}</ul>"


def build_html(*, weather, air, sun, tides, space_wx,
               indexes, tickers, crypto,
               local, global_, gdelt, relief, hn, reddit) -> str:
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
  --up: #3fb950; --down: #f85149;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--text);
  margin: 0; padding: 16px; line-height: 1.55;
}}
.wrap {{ max-width: 1100px; margin: 0 auto; }}
header {{
  border-bottom: 1px solid var(--border);
  padding-bottom: 12px; margin-bottom: 20px;
}}
h1 {{ margin: 0 0 4px 0; font-size: 26px; }}
h1 .accent {{ color: var(--accent); }}
.muted {{ color: var(--muted); font-size: 13px; }}
.row {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
@media (min-width: 860px) {{ .row.two {{ grid-template-columns: 1fr 1fr; }} }}
.card {{
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 18px 22px; margin-bottom: 16px;
}}
.card h2 {{
  margin: 22px 0 10px 0; font-size: 16px; color: var(--accent2);
  border-bottom: 1px solid var(--border); padding-bottom: 8px;
  letter-spacing: 0.3px; text-transform: uppercase;
}}
.card h2:first-child {{ margin-top: 0; }}
.card ul {{ padding-left: 20px; margin: 0; }}
.card li {{ margin-bottom: 6px; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.empty {{ color: var(--muted); font-style: italic; margin: 6px 0; }}
.kv {{ font-size: 14px; margin: 6px 0; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
       font-size: 11px; margin-right: 6px; }}
.tag-gdelt   {{ background: #1f3a5f; color: #79c0ff; }}
.tag-relief  {{ background: #2d4f2d; color: #7ee787; }}
.tag-space   {{ background: #4a2d5f; color: #d2a8ff; }}
.tag-wx      {{ background: #5a3a1a; color: #ffd28a; }}
.tag-aqi     {{ background: #2d4f4f; color: #7eccd8; }}
.tag-sun     {{ background: #5a4a1a; color: #ffe28a; }}
.tag-tide    {{ background: #1a3a5a; color: #8ac4ff; }}
.tag-mkt     {{ background: #3a5a1a; color: #b4ff8a; }}
.tag-crypto  {{ background: #5a1a3a; color: #ff8ac4; }}
.tag-hn      {{ background: #5a3a1a; color: #ff9e3a; }}
.tag-reddit  {{ background: #5a1a1a; color: #ff8a8a; }}
.quotes {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.quotes td {{ padding: 6px 8px; border-bottom: 1px solid var(--border); }}
.quotes tr:last-child td {{ border-bottom: 0; }}
.qname {{ width: 50%; }}
.qsym {{ color: var(--muted); font-size: 12px; margin-left: 4px; }}
.qprice {{ font-variant-numeric: tabular-nums; text-align: right; }}
.qchg {{ font-variant-numeric: tabular-nums; text-align: right; width: 100px; }}
.qchg.up {{ color: var(--up); }}
.qchg.down {{ color: var(--down); }}
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

<!-- Top row: at-a-glance environment -->
<div class="card">
  <h2><span class="tag tag-wx">WEATHER</span> {LOCATION_NAME}</h2>
  <p class="kv">{html.escape(weather)}</p>

  <h2><span class="tag tag-aqi">AIR QUALITY</span></h2>
  <p class="kv">{html.escape(air)}</p>

  <h2><span class="tag tag-sun">SUN</span></h2>
  <p class="kv">{html.escape(sun)}</p>

  <h2><span class="tag tag-tide">TIDES</span> {TIDE_STATION_NAME}</h2>
  {render_tides(tides)}

  <h2><span class="tag tag-space">SPACE WX</span></h2>
  <p class="kv">{html.escape(space_wx)}</p>
</div>

<!-- Markets -->
<div class="row two">
  <div class="card">
    <h2><span class="tag tag-mkt">STOCKS</span> Indexes</h2>
    {render_quotes(indexes, "{:,.2f}")}
    <h2><span class="tag tag-mkt">STOCKS</span> Watchlist</h2>
    {render_quotes(tickers, "${:,.2f}")}
  </div>

  <div class="card">
    <h2><span class="tag tag-crypto">CRYPTO</span> Top coins</h2>
    {render_quotes(crypto, "${:,.2f}")}
  </div>
</div>

<!-- Geopolitics -->
<div class="card">
  <h2>🌍 Sentinel — Live Geopolitical Globe</h2>
  <p class="kv">For the live map of conflicts, military flights, and SIGINT:</p>
  <a class="sentinel-link" href="{SENTINEL_URL}" target="_blank" rel="noopener">
    Open Sentinel →
  </a>

  <h2><span class="tag tag-gdelt">GDELT</span> Global Events — past 24h</h2>
  {render_articles(gdelt)}

  <h2><span class="tag tag-relief">ReliefWeb</span> Humanitarian Reports</h2>
  {render_articles(relief)}
</div>

<!-- Tech / community -->
<div class="row two">
  <div class="card">
    <h2><span class="tag tag-hn">HN</span> Hacker News — Top</h2>
    {render_articles(hn)}
  </div>
  <div class="card">
    <h2><span class="tag tag-reddit">Reddit</span> r/worldnews — Top 24h</h2>
    {render_articles(reddit)}
  </div>
</div>

<!-- News -->
<div class="card">
  <h2>Local — Seattle / Lynnwood</h2>
  {render_articles(local)}

  <h2>Global — Politically diverse mix</h2>
  {render_articles(global_)}
</div>

<div class="footer">
  Generated {iso_built} UTC by GitHub Actions ·
  Sources: RSS, GDELT 2.0, ReliefWeb, HN, Reddit, Yahoo Finance, CoinGecko,
  NOAA SWPC, NOAA Tides, Open-Meteo, Sunrise-Sunset.org ·
  Auto-refreshes hourly
</div>

</div>
</body>
</html>
"""


# --- MAIN -----------------------------------------------------------------

def main() -> int:
    log.info("=== Starting briefing v2 ===")

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

    time.sleep(1)
    log.info("ReliefWeb...")
    relief = fetch_reliefweb()

    log.info("Hacker News...")
    hn = fetch_hackernews()

    log.info("Reddit r/worldnews...")
    reddit_news = fetch_reddit_worldnews()

    log.info("Stocks...")
    indexes, tickers = fetch_stocks()

    log.info("Crypto...")
    crypto = fetch_crypto()

    log.info("Space weather...")
    space_wx = fetch_space_weather()

    log.info("Weather...")
    weather = fetch_weather()

    log.info("Air quality...")
    air = fetch_air_quality()

    log.info("Sun times...")
    sun = fetch_sun()

    log.info("Tides...")
    tides = fetch_tides()

    log.info(
        "Counts — local:%d global:%d gdelt:%d relief:%d hn:%d reddit:%d "
        "indexes:%d tickers:%d crypto:%d tides:%d",
        len(local), len(global_), len(gdelt), len(relief), len(hn), len(reddit_news),
        len(indexes), len(tickers), len(crypto), len(tides),
    )

    html_doc = build_html(
        weather=weather, air=air, sun=sun, tides=tides, space_wx=space_wx,
        indexes=indexes, tickers=tickers, crypto=crypto,
        local=local, global_=global_, gdelt=gdelt, relief=relief,
        hn=hn, reddit=reddit_news,
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)
    log.info("Wrote index.html (%d bytes)", len(html_doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())