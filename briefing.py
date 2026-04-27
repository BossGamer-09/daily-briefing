#!/usr/bin/env python3
"""
Daily Briefing v3 — static HTML generator for GitHub Pages.

Sources (no API keys required):
  - News RSS (politically diverse mix)
  - GDELT 2.0 (global conflict events)
  - Hacker News top stories
  - Yahoo Finance v8 (stocks + indexes)
  - CoinGecko (crypto prices)
  - NOAA Space Weather (Kp + alerts)
  - Open-Meteo (weather + air quality)
  - Sunrise-Sunset.org
  - NOAA Tides & Currents
  - 🚀 Space:
      * NASA APOD (image of the day)
      * Spaceflight News API (latest articles)
      * Open Notify (ISS position + crew)
      * The Space Devs (upcoming launches)
      * NASA NeoWs (near-Earth asteroids)

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
    # Center / international
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
    # Business / center-right of mainstream
    ("WSJ World", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
    ("Washington Examiner", "https://www.washingtonexaminer.com/section/news/feed"),
]

MAX_PER_FEED = 4
USER_AGENT = "DailyBriefing/2.0 (github-actions; personal-use)"
SENTINEL_URL = "https://sentinel.axonia.us/"

# Stocks via Cloudflare Worker (proxies Yahoo Finance with CORS).
# Set this to your deployed Worker URL after one-time setup.
# Format: https://daily-briefing-stocks.YOURUSER.workers.dev
# Leave as-is to disable browser-side stock updates (server still works).
STOCK_WORKER_URL = "https://daily-briefing-stocks.mwilmot.workers.dev"

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


# --- SPACE ----------------------------------------------------------------
# All free, no key required (NASA's DEMO_KEY works at low traffic — twice/day is fine).
# Drop in a personal NASA key from https://api.nasa.gov/ if you want headroom.

NASA_KEY = "DEMO_KEY"  # 30 req/hr GLOBAL across all DEMO_KEY users; fine for our 2x/day


def fetch_apod() -> dict | None:
    """NASA Astronomy Picture of the Day. Returns dict or None."""
    try:
        url = f"https://api.nasa.gov/planetary/apod?api_key={NASA_KEY}"
        d = _get_json(url, timeout=15)
        return {
            "title": d.get("title", ""),
            "date": d.get("date", ""),
            "url": d.get("url", ""),
            "hdurl": d.get("hdurl", ""),
            "media_type": d.get("media_type", ""),  # "image" or "video"
            "explanation": d.get("explanation", ""),
            "copyright": d.get("copyright", ""),
        }
    except Exception as e:
        log.warning("APOD failed: %s", e)
        return None


def fetch_spaceflight_news() -> list[Article]:
    """Spaceflight News API — aggregates SpaceNews, NASASpaceflight, ESA, etc."""
    url = "https://api.spaceflightnewsapi.net/v4/articles/?limit=10&ordering=-published_at"
    try:
        d = _get_json(url, timeout=15)
        out: list[Article] = []
        for a in d.get("results", [])[:10]:
            title = (a.get("title") or "").strip()
            link = a.get("url") or "#"
            site = a.get("news_site") or "Space"
            if title:
                out.append(Article(source=site, title=title, url=link))
        return out
    except Exception as e:
        log.warning("Spaceflight News failed: %s", e)
        return []


def fetch_iss() -> dict:
    """ISS current location + crew. Returns dict with location, crew_count, crew names."""
    out = {"location": None, "crew_count": None, "crew_names": []}
    try:
        # Position
        pos = _get_json("http://api.open-notify.org/iss-now.json", timeout=10)
        if pos.get("message") == "success":
            lat = float(pos["iss_position"]["latitude"])
            lon = float(pos["iss_position"]["longitude"])
            # Reverse-geocode to a human-readable location
            try:
                geo = _get_json(
                    f"https://api.bigdatacloud.net/data/reverse-geocode-client"
                    f"?latitude={lat}&longitude={lon}&localityLanguage=en",
                    timeout=10,
                )
                country = geo.get("countryName")
                locality = geo.get("locality")
                # If over an ocean, locality has the ocean name; country empty
                if country:
                    place = f"{locality}, {country}" if locality else country
                else:
                    place = locality or "open ocean"
                out["location"] = f"{place} ({lat:.1f}°, {lon:.1f}°)"
            except Exception:
                out["location"] = f"{lat:.1f}°N, {lon:.1f}°E"
    except Exception as e:
        log.warning("ISS position failed: %s", e)

    try:
        # Crew (filters to ISS only since open-notify also lists Tiangong)
        crew = _get_json("http://api.open-notify.org/astros.json", timeout=10)
        iss_people = [p["name"] for p in crew.get("people", []) if p.get("craft") == "ISS"]
        out["crew_count"] = len(iss_people)
        out["crew_names"] = iss_people
    except Exception as e:
        log.warning("ISS crew failed: %s", e)

    return out


def fetch_launches() -> list[dict]:
    """Upcoming rocket launches via The Space Devs Launch Library 2."""
    url = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/?limit=5&mode=list"
    try:
        d = _get_json(url, timeout=20)
        out: list[dict] = []
        for l in d.get("results", [])[:5]:
            net_iso = l.get("net", "")  # "2026-04-28T00:52:00Z"
            try:
                net_dt = datetime.fromisoformat(net_iso.replace("Z", "+00:00"))
                net_local = net_dt.astimezone(TZ).strftime("%a %b %-d, %-I:%M %p %Z")
            except Exception:
                net_local = net_iso[:16]
            out.append({
                "name": l.get("name", "?"),
                "when": net_local,
                "status": (l.get("status") or {}).get("name", ""),
            })
        return out
    except Exception as e:
        log.warning("Launches failed: %s", e)
        return []


def fetch_asteroids() -> list[dict]:
    """Today's near-Earth asteroid close passes from NASA NeoWs."""
    today = datetime.now(TZ).date().isoformat()
    url = (
        f"https://api.nasa.gov/neo/rest/v1/feed?start_date={today}&end_date={today}"
        f"&api_key={NASA_KEY}"
    )
    try:
        d = _get_json(url, timeout=20)
        neos = d.get("near_earth_objects", {}).get(today, [])
        out: list[dict] = []
        for n in neos:
            ca = (n.get("close_approach_data") or [{}])[0]
            miss_lunar = ca.get("miss_distance", {}).get("lunar")
            try:
                miss_lunar_f = float(miss_lunar) if miss_lunar is not None else None
            except (TypeError, ValueError):
                miss_lunar_f = None
            diam = n.get("estimated_diameter", {}).get("meters", {})
            d_min = diam.get("estimated_diameter_min")
            d_max = diam.get("estimated_diameter_max")
            try:
                d_avg = (float(d_min) + float(d_max)) / 2 if d_min and d_max else None
            except (TypeError, ValueError):
                d_avg = None
            time_utc = ca.get("close_approach_date_full", "")[-5:]  # "HH:MM"
            out.append({
                "name": n.get("name", "?"),
                "diameter_m": d_avg,
                "miss_lunar": miss_lunar_f,
                "time_utc": time_utc,
                "hazardous": n.get("is_potentially_hazardous_asteroid", False),
                "url": n.get("nasa_jpl_url", "#"),
            })
        # Sort by closest miss distance
        out.sort(key=lambda x: x["miss_lunar"] if x["miss_lunar"] is not None else 9999)
        return out[:5]
    except Exception as e:
        log.warning("Asteroids failed: %s", e)
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


def render_quotes(quotes: list[Quote], price_fmt: str = "${:,.2f}",
                  kind: str = "stock") -> str:
    """kind: 'stock' or 'crypto' — controls which data-attr we emit so JS can
    target the right rows."""
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
        # data-* attributes let the live-updater find this row and refresh it
        if kind == "crypto":
            data_attr = f'data-coin-id="{html.escape(q.symbol.lower())}"'
            # Crypto symbols are uppercased coin tickers; we'll match by symbol below
            # Actually: for crypto we want the coingecko id, which is in the original config.
            # The symbol shown is e.g. "BTC", but coingecko id is "bitcoin".
            # Simpler: emit data-symbol and look it up client-side via a map we inject.
            data_attr = f'data-crypto-sym="{html.escape(q.symbol)}"'
        else:
            data_attr = f'data-stock-sym="{html.escape(q.symbol)}"'
        rows.append(
            f'<tr {data_attr}>'
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


def render_apod(apod: dict | None) -> str:
    if not apod:
        return '<p class="empty">APOD unavailable.</p>'
    title = html.escape(apod.get("title", ""))
    date = html.escape(apod.get("date", ""))
    url = html.escape(apod.get("url", ""))
    hdurl = html.escape(apod.get("hdurl") or apod.get("url", ""))
    media = apod.get("media_type", "")
    explain = html.escape((apod.get("explanation", "") or "")[:400])
    if explain and len(apod.get("explanation", "")) > 400:
        explain += "…"
    copyright_ = apod.get("copyright")
    credit = f' · © {html.escape(copyright_.strip())}' if copyright_ else ""

    if media == "image":
        return f"""
<a href="{hdurl}" target="_blank" rel="noopener">
  <img class="apod-img" src="{url}" alt="{title}" loading="lazy">
</a>
<p class="apod-cap"><strong>{title}</strong>
  <span class="muted">· {date}{credit}</span>
</p>
<p class="apod-text">{explain}</p>
"""
    elif media == "video":
        return f"""
<p class="apod-cap"><strong>{title}</strong>
  <span class="muted">· {date} · video</span>
</p>
<p class="apod-text">{explain}</p>
<p><a href="{url}" target="_blank" rel="noopener">▶ Watch on NASA →</a></p>
"""
    else:
        return f'<p class="empty">APOD format not supported.</p>'


def render_iss(iss: dict) -> str:
    loc = iss.get("location") or "Position unavailable"
    crew_count = iss.get("crew_count")
    crew_names = iss.get("crew_names") or []
    crew_str = (
        f"<strong>{crew_count} crew aboard</strong>: " + ", ".join(html.escape(n) for n in crew_names)
        if crew_count else "<em>Crew info unavailable</em>"
    )
    return f"""
<p class="kv" data-iss-location><strong>Currently over:</strong> <span data-iss-place>{html.escape(loc)}</span></p>
<p class="kv">{crew_str}</p>
"""


def render_launches(launches: list[dict]) -> str:
    if not launches:
        return '<p class="empty">No upcoming launches.</p>'
    items = []
    for l in launches:
        name = html.escape(l.get("name", ""))
        when = html.escape(l.get("when", ""))
        status = l.get("status", "")
        status_html = f' <span class="muted">({html.escape(status)})</span>' if status and status != "Go for Launch" else ""
        items.append(f'<li><strong>{when}</strong> — {name}{status_html}</li>')
    return f"<ul>{''.join(items)}</ul>"


def render_asteroids(asteroids: list[dict]) -> str:
    if not asteroids:
        return '<p class="empty">No close passes today.</p>'
    items = []
    for a in asteroids:
        name = html.escape(a.get("name", "?"))
        miss = a.get("miss_lunar")
        diam = a.get("diameter_m")
        url = html.escape(a.get("url", "#"))
        miss_str = f"{miss:.2f} LD" if miss is not None else "?"
        diam_str = f"~{diam:.0f}m" if diam else "size unknown"
        haz = ' <span class="haz">⚠ PHA</span>' if a.get("hazardous") else ""
        items.append(
            f'<li><a href="{url}" target="_blank" rel="noopener">'
            f'<strong>{name}</strong></a> · {diam_str} · {miss_str}{haz}</li>'
        )
    return f'<ul>{"".join(items)}</ul><p class="muted" style="font-size:11px;margin-top:6px">LD = lunar distance (~384,400 km). Earth&rsquo;s atmosphere ends at ~0.0003 LD.</p>'


def build_html(*, weather, air, sun, tides, space_wx,
               indexes, tickers, crypto,
               local, global_, gdelt, hn,
               apod, space_news, iss, launches, asteroids) -> str:
    import json as _json
    now_local = datetime.now(TZ)
    now_utc = datetime.now(timezone.utc)
    timestamp = now_local.strftime("%A, %B %-d, %Y — %-I:%M %p %Z")
    iso_built = now_utc.isoformat(timespec="seconds")

    # Config that gets inlined into the live-update <script> block.
    # All values are JSON-encoded so we can embed them directly into JS.
    stock_worker_json = _json.dumps(STOCK_WORKER_URL)
    all_stock_syms = [s for _, s in STOCK_INDEXES] + [s for _, s in STOCK_TICKERS]
    stock_symbols_json = _json.dumps(all_stock_syms)
    # Map of display symbol → coingecko id (e.g. "BTC" → "bitcoin")
    crypto_map_json = _json.dumps({sym: coin_id for _, coin_id, sym in CRYPTO_COINS})
    location_name_json = _json.dumps(LOCATION_NAME)

    # Build optional sub-blocks first (cleaner than inlining in the f-string)
    apod_block = render_apod(apod)
    iss_block = render_iss(iss)
    launches_block = render_launches(launches)
    asteroids_block = render_asteroids(asteroids)

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
.tag-space   {{ background: #4a2d5f; color: #d2a8ff; }}
.tag-spx     {{ background: #2d1f5f; color: #b8a8ff; }}
.tag-wx      {{ background: #5a3a1a; color: #ffd28a; }}
.tag-aqi     {{ background: #2d4f4f; color: #7eccd8; }}
.tag-sun     {{ background: #5a4a1a; color: #ffe28a; }}
.tag-tide    {{ background: #1a3a5a; color: #8ac4ff; }}
.tag-mkt     {{ background: #3a5a1a; color: #b4ff8a; }}
.tag-crypto  {{ background: #5a1a3a; color: #ff8ac4; }}
.tag-hn      {{ background: #5a3a1a; color: #ff9e3a; }}
.tag-iss     {{ background: #1a4a4a; color: #8ae8e8; }}
.tag-launch  {{ background: #4a1a1a; color: #ff9e9e; }}
.tag-rock    {{ background: #3a3a1a; color: #d8d88a; }}
.apod-img {{ width: 100%; max-height: 480px; object-fit: cover;
            border-radius: 8px; display: block; }}
.apod-cap {{ font-size: 14px; margin: 8px 0 4px 0; }}
.apod-text {{ font-size: 13px; color: var(--text); margin: 4px 0;
              line-height: 1.5; }}
.haz {{ background: #5a1a1a; color: #ff9e9e; padding: 1px 5px;
        border-radius: 3px; font-size: 11px; }}
.live-indicator {{
  display: inline-block; margin-left: 8px; padding: 1px 8px;
  border-radius: 10px; font-size: 11px; font-weight: 500;
  background: #1a1a1a; color: var(--muted);
  transition: all 0.3s;
}}
.live-indicator.on    {{ background: #0d2818; color: #3fb950; }}
.live-indicator.off   {{ background: #281818; color: #f85149; }}
.live-indicator.idle  {{ background: #1a1a1a; color: #8b949e; }}
.qprice, .qchg {{ transition: background 0.6s ease-out; }}
.qprice.flash, .qchg.flash {{ background: rgba(88, 166, 255, 0.25); }}
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
  <div class="muted">{timestamp} · {LOCATION_NAME} <span id="live-indicator" class="live-indicator off">⚪ initializing</span></div>
</header>

<!-- Top row: at-a-glance environment -->
<div class="card">
  <h2><span class="tag tag-wx">WEATHER</span> {LOCATION_NAME}</h2>
  <p class="kv" data-weather>{html.escape(weather)}</p>

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
    {render_quotes(indexes, "{:,.2f}", kind="stock")}
    <h2><span class="tag tag-mkt">STOCKS</span> Watchlist</h2>
    {render_quotes(tickers, "${:,.2f}", kind="stock")}
  </div>

  <div class="card">
    <h2><span class="tag tag-crypto">CRYPTO</span> Top coins</h2>
    {render_quotes(crypto, "${:,.2f}", kind="crypto")}
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
</div>

<!-- 🚀 SPACE CARD -->
<div class="card">
  <h2><span class="tag tag-space">APOD</span> NASA Picture of the Day</h2>
  {apod_block}

  <h2><span class="tag tag-spx">NEWS</span> Spaceflight Headlines</h2>
  {render_articles(space_news)}

  <h2><span class="tag tag-iss">ISS</span> International Space Station</h2>
  {iss_block}

  <h2><span class="tag tag-launch">LAUNCH</span> Upcoming Launches</h2>
  {launches_block}

  <h2><span class="tag tag-rock">NEO</span> Today&rsquo;s Asteroid Close Passes</h2>
  {asteroids_block}
</div>

<!-- Tech -->
<div class="card">
  <h2><span class="tag tag-hn">HN</span> Hacker News — Top</h2>
  {render_articles(hn)}
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
  Sources: RSS · GDELT 2.0 · HN · Yahoo Finance · CoinGecko ·
  NOAA SWPC · NOAA Tides · Open-Meteo · Sunrise-Sunset · NASA APOD/NeoWs ·
  Spaceflight News · The Space Devs · Open Notify ·
  Live updates via Cloudflare Worker
</div>

</div>

<script>
// === LIVE UPDATER ===========================================================
// Refreshes stocks/crypto/weather/ISS in-place without a page reload.
// Pauses when tab is hidden. Backs off on errors.
// All config below is inlined from briefing.py at build time.

const CONFIG = {{
  stockWorkerUrl: {stock_worker_json},
  stockSymbols: {stock_symbols_json},
  cryptoMap: {crypto_map_json},
  weather: {{
    lat: {LAT},
    lon: {LON},
    locationName: {location_name_json}
  }},
  intervals: {{
    stock: 2 * 60 * 1000,
    crypto: 2 * 60 * 1000,
    weather: 10 * 60 * 1000,
    iss: 30 * 1000
  }}
}};

const STATE = {{
  errorCounts: {{ stock: 0, crypto: 0, weather: 0, iss: 0 }},
  lastSuccess: {{ stock: 0, crypto: 0, weather: 0, iss: 0 }},
  visible: !document.hidden
}};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function setIndicator(state, msg) {{
  const el = $('#live-indicator');
  if (!el) return;
  el.className = 'live-indicator ' + state;
  const dot = state === 'on' ? '🟢' : state === 'off' ? '🔴' : '⚪';
  el.textContent = dot + ' ' + msg;
}}

function flash(el) {{
  if (!el) return;
  el.classList.remove('flash');
  void el.offsetWidth; // restart animation
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 600);
}}

function fmtPrice(n, withDollar = true) {{
  if (n == null) return '—';
  const opts = {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }};
  if (n >= 1000) opts.maximumFractionDigits = 0;
  return (withDollar ? '$' : '') + n.toLocaleString('en-US', opts);
}}

function fmtPct(p) {{
  if (p == null || isNaN(p)) return '—';
  return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
}}

function updateRow(row, price, changePct, withDollar = true) {{
  if (!row || price == null) return;
  const priceEl = row.querySelector('.qprice');
  const chgEl = row.querySelector('.qchg');
  if (!priceEl || !chgEl) return;

  const oldPrice = priceEl.textContent.replace(/[^0-9.\\-]/g, '');
  const newPriceText = fmtPrice(price, withDollar);
  if (oldPrice !== '' && parseFloat(oldPrice).toFixed(2) !== price.toFixed(2)) {{
    flash(priceEl);
  }}
  priceEl.textContent = newPriceText;

  const arrow = (changePct ?? 0) >= 0 ? '▲' : '▼';
  chgEl.className = 'qchg ' + ((changePct ?? 0) >= 0 ? 'up' : 'down');
  chgEl.textContent = arrow + ' ' + fmtPct(changePct);
}}

// --- Stocks (via Cloudflare Worker) -----------------------------------------
async function refreshStocks() {{
  if (!CONFIG.stockWorkerUrl || !CONFIG.stockSymbols.length) return;
  if (!isMarketOpenOrRecent() && Date.now() - STATE.lastSuccess.stock < 30 * 60 * 1000) {{
    return; // markets closed, last update <30 min ago — skip
  }}
  try {{
    const url = CONFIG.stockWorkerUrl + '/quote?symbols=' +
      encodeURIComponent(CONFIG.stockSymbols.join(','));
    const r = await fetch(url, {{ cache: 'no-store' }});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    let updated = 0;
    for (const [sym, q] of Object.entries(data)) {{
      const row = document.querySelector(`[data-stock-sym="${{sym}}"]`);
      if (row && q.price != null) {{
        updateRow(row, q.price, q.change_pct, sym.startsWith('^') ? false : true);
        updated++;
      }}
    }}
    STATE.errorCounts.stock = 0;
    STATE.lastSuccess.stock = Date.now();
    console.log(`[stocks] updated ${{updated}} symbols`);
  }} catch (e) {{
    STATE.errorCounts.stock++;
    console.warn('[stocks] failed:', e.message);
  }}
}}

// --- Crypto (CoinGecko, CORS-friendly) --------------------------------------
async function refreshCrypto() {{
  const ids = Object.values(CONFIG.cryptoMap).join(',');
  if (!ids) return;
  try {{
    const url = `https://api.coingecko.com/api/v3/simple/price?ids=${{ids}}&vs_currencies=usd&include_24hr_change=true`;
    const r = await fetch(url, {{ cache: 'no-store' }});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    let updated = 0;
    for (const [sym, coinId] of Object.entries(CONFIG.cryptoMap)) {{
      const d = data[coinId];
      if (!d) continue;
      const row = document.querySelector(`[data-crypto-sym="${{sym}}"]`);
      if (row) {{
        updateRow(row, d.usd, d.usd_24h_change, true);
        updated++;
      }}
    }}
    STATE.errorCounts.crypto = 0;
    STATE.lastSuccess.crypto = Date.now();
    console.log(`[crypto] updated ${{updated}} coins`);
  }} catch (e) {{
    STATE.errorCounts.crypto++;
    console.warn('[crypto] failed:', e.message);
  }}
}}

// --- Weather (Open-Meteo, CORS-friendly) ------------------------------------
async function refreshWeather() {{
  try {{
    const u = `https://api.open-meteo.com/v1/forecast?latitude=${{CONFIG.weather.lat}}&longitude=${{CONFIG.weather.lon}}&current=temperature_2m,relative_humidity_2m,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto&forecast_days=2`;
    const r = await fetch(u, {{ cache: 'no-store' }});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const w = await r.json();
    const c = w.current, d = w.daily;
    const txt = `Now: ${{c.temperature_2m}}°F · humidity ${{c.relative_humidity_2m}}% · wind ${{c.wind_speed_10m}} mph. Today: high ${{d.temperature_2m_max[0]}}°F / low ${{d.temperature_2m_min[0]}}°F · precip ${{d.precipitation_probability_max[0]}}%.`;
    const el = $('[data-weather]');
    if (el && el.textContent !== txt) {{
      el.textContent = txt;
      flash(el);
    }}
    STATE.errorCounts.weather = 0;
    STATE.lastSuccess.weather = Date.now();
  }} catch (e) {{
    STATE.errorCounts.weather++;
    console.warn('[weather] failed:', e.message);
  }}
}}

// --- ISS (CORS proxy + reverse geocoding) -----------------------------------
// open-notify is HTTP-only, so we use wheretheiss.at which is HTTPS + CORS.
async function refreshIss() {{
  try {{
    const r = await fetch('https://api.wheretheiss.at/v1/satellites/25544', {{ cache: 'no-store' }});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const lat = d.latitude;
    const lon = d.longitude;
    // Reverse geocode (CORS-friendly)
    let place = `${{lat.toFixed(1)}}°, ${{lon.toFixed(1)}}°`;
    try {{
      const g = await fetch(
        `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${{lat}}&longitude=${{lon}}&localityLanguage=en`,
        {{ cache: 'no-store' }}
      );
      if (g.ok) {{
        const geo = await g.json();
        const country = geo.countryName;
        const locality = geo.locality;
        const where = country
          ? (locality ? `${{locality}}, ${{country}}` : country)
          : (locality || 'open ocean');
        place = `${{where}} (${{lat.toFixed(1)}}°, ${{lon.toFixed(1)}}°)`;
      }}
    }} catch (e) {{ /* fall through to bare coords */ }}

    const el = $('[data-iss-place]');
    if (el && el.textContent !== place) {{
      el.textContent = place;
      flash(el.parentElement);
    }}
    STATE.errorCounts.iss = 0;
    STATE.lastSuccess.iss = Date.now();
  }} catch (e) {{
    STATE.errorCounts.iss++;
    console.warn('[iss] failed:', e.message);
  }}
}}

// --- Helpers ---------------------------------------------------------------

function isMarketOpenOrRecent() {{
  // US equity hours: M-F 9:30am-4pm ET. Approximate without DST headaches:
  // ET is UTC-5 (EST) or UTC-4 (EDT). We accept a generous 14:00-21:00 UTC window
  // M-F. Outside that, "stale-ok" mode kicks in.
  const now = new Date();
  const day = now.getUTCDay();      // 0=Sun, 6=Sat
  const hour = now.getUTCHours();
  if (day === 0 || day === 6) return false;
  return hour >= 13 && hour < 22;
}}

function backoffMs(base, errors) {{
  // Double interval per consecutive failure, capped at 1 hour
  return Math.min(base * Math.pow(2, errors), 60 * 60 * 1000);
}}

function scheduleAll() {{
  // Initial fetch right away
  refreshStocks();
  refreshCrypto();
  refreshWeather();
  refreshIss();

  // Recurring polls — recompute interval each tick to honor backoff
  function loop(name, fn) {{
    const tick = async () => {{
      if (STATE.visible) {{
        await fn();
        updateIndicator();
      }}
      const interval = backoffMs(CONFIG.intervals[name], STATE.errorCounts[name]);
      setTimeout(tick, interval);
    }};
    setTimeout(tick, CONFIG.intervals[name]);
  }}

  loop('stock', refreshStocks);
  loop('crypto', refreshCrypto);
  loop('weather', refreshWeather);
  loop('iss', refreshIss);
}}

function updateIndicator() {{
  const totalErrors = Object.values(STATE.errorCounts).reduce((a, b) => a + b, 0);
  const lastUpdate = Math.max(...Object.values(STATE.lastSuccess));
  if (lastUpdate === 0) {{
    setIndicator('off', 'no data yet');
  }} else if (totalErrors >= 3) {{
    setIndicator('off', 'connection issues');
  }} else if (!STATE.visible) {{
    setIndicator('idle', 'paused (tab inactive)');
  }} else {{
    const ageSec = Math.floor((Date.now() - lastUpdate) / 1000);
    const ageStr = ageSec < 60 ? `${{ageSec}}s ago`
                  : ageSec < 3600 ? `${{Math.floor(ageSec/60)}}m ago`
                  : `${{Math.floor(ageSec/3600)}}h ago`;
    setIndicator('on', `live · last update ${{ageStr}}`);
  }}
}}

// Pause polling when tab hidden, resume on return
document.addEventListener('visibilitychange', () => {{
  STATE.visible = !document.hidden;
  updateIndicator();
  if (STATE.visible) {{
    // Refresh everything immediately on return
    refreshStocks();
    refreshCrypto();
    refreshWeather();
    refreshIss();
  }}
}});

// Update the "last X seconds ago" indicator every second
setInterval(updateIndicator, 1000);

// Boot
scheduleAll();
console.log('[live] updater started', CONFIG);

</script>

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

    log.info("Hacker News...")
    hn = fetch_hackernews()

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

    log.info("APOD...")
    apod = fetch_apod()

    log.info("Spaceflight News...")
    space_news = fetch_spaceflight_news()

    log.info("ISS...")
    iss = fetch_iss()

    log.info("Upcoming launches...")
    launches = fetch_launches()

    log.info("Near-Earth asteroids...")
    asteroids = fetch_asteroids()

    log.info(
        "Counts — local:%d global:%d gdelt:%d hn:%d "
        "indexes:%d tickers:%d crypto:%d tides:%d "
        "apod:%s spx_news:%d launches:%d asteroids:%d iss_crew:%s",
        len(local), len(global_), len(gdelt), len(hn),
        len(indexes), len(tickers), len(crypto), len(tides),
        "yes" if apod else "no", len(space_news), len(launches), len(asteroids),
        iss.get("crew_count"),
    )

    html_doc = build_html(
        weather=weather, air=air, sun=sun, tides=tides, space_wx=space_wx,
        indexes=indexes, tickers=tickers, crypto=crypto,
        local=local, global_=global_, gdelt=gdelt, hn=hn,
        apod=apod, space_news=space_news, iss=iss,
        launches=launches, asteroids=asteroids,
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)
    log.info("Wrote index.html (%d bytes)", len(html_doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
