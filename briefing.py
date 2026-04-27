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
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ("Guardian World", "https://www.theguardian.com/world/rss"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
    ("WSJ World", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
    ("Washington Examiner", "https://www.washingtonexaminer.com/section/news/feed"),
]

MAX_PER_FEED = 4
USER_AGENT = "DailyBriefing/2.0 (github-actions; personal-use)"

# Stock Config
STOCK_WORKER_URL = "https://daily-briefing-stocks.mwilmot.workers.dev"
STOCK_INDEXES = [("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("Dow Jones", "^DJI")]
STOCK_TICKERS = [
    ("Apple", "AAPL"), ("Microsoft", "MSFT"), ("Alphabet", "GOOGL"),
    ("Tesla", "TSLA"), ("Nvidia", "NVDA"), ("Amazon", "AMZN"), ("Meta", "META"),
]

# Crypto Config
CRYPTO_COINS = [
    ("Bitcoin", "bitcoin", "BTC"),
    ("Ethereum", "ethereum", "ETH"),
    ("Solana", "solana", "SOL"),
    ("XRP", "ripple", "XRP"),
    ("Cardano", "cardano", "ADA"),
    ("Dogecoin", "dogecoin", "DOGE"),
]

# Tides Config
TIDE_STATION = "9447130" # Seattle
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
    change: float | None
    change_pct: float | None

@dataclass
class TideEvent:
    time: str
    height: float
    kind: str # "High" or "Low"

# --- HTTP HELPER ----------------------------------------------------------

def _get_json(url: str, timeout: int = 20, headers: dict | None = None) -> Any:
    """Helper to fetch JSON with a timeout and user agent."""
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = requests.get(url, timeout=timeout, headers=h)
    r.raise_for_status()
    return r.json()

# --- FETCHERS -------------------------------------------------------------

def fetch_rss(name: str, url: str) -> list[Article]:
    """Fetches and parses an RSS feed."""
    try:
        parsed = feedparser.parse(url, agent=USER_AGENT)
        out = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or "#"
            if title:
                out.append(Article(source=name, title=title, url=link))
        return out
    except Exception as e:
        log.warning(f"Failed to fetch {name}: {e}")
        return []

def fetch_gdelt() -> list[Article]:
    """Fetches recent world events from GDELT 2.0 API."""
    params = {
        "query": "(theme:ARMEDCONFLICT OR theme:TERROR OR theme:REBELLION)",
        "mode": "ArtList",
        "maxrecords": "10",
        "timespan": "24H",
        "format": "json",
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
        log.warning(f"GDELT fetch failed: {e}")
        return []

def fetch_hackernews() -> list[Article]:
    """Fetches top stories from Hacker News."""
    try:
        top_ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=15)
        out = []
        for sid in top_ids[:10]:
            item = _get_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=10)
            if item.get("title"):
                out.append(Article(
                    source="HN",
                    title=item["title"].strip(),
                    url=item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
                ))
        return out
    except Exception as e:
        log.warning(f"HN fetch failed: {e}")
        return []

def fetch_stocks(symbols: list[tuple[str, str]]) -> tuple[list[Quote], list[Quote]]:
    """Fetches stock data and splits into indexes/tickers."""
    if not symbols:
        return [], []
    
    # Extract only the symbol strings for the worker query
    symbol_str = ",".join([s[1] for s in symbols])
    url = f"{STOCK_WORKER_URL}/quote?symbols={symbol_str}"
    
    try:
        data = _get_json(url, timeout=20)
        results = []
        for name, symbol in symbols:
            q = data.get(symbol)
            if q:
                results.append(Quote(
                    name=name,
                    symbol=symbol,
                    price=q.get("price"),
                    change=q.get("change"),
                    change_pct=q.get("change_pct")
                ))
        
        # Split back based on initial lengths
        idx_len = len(STOCK_INDEXES)
        return results[:idx_len], results[idx_len:]
    except Exception as e:
        log.warning(f"Stock fetch failed: {e}")
        return [], []

def fetch_crypto() -> list[Quote]:
    """Fetches crypto prices from CoinGecko."""
    ids = ",".join(c[1] for c in CRYPTO_COINS)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    try:
        data = _get_json(url, timeout=20)
        out = []
        for name, cid, sym in CRYPTO_COINS:
            if cid in data:
                out.append(Quote(
                    name=name,
                    symbol=sym,
                    price=data[cid].get("usd"),
                    change=None,
                    change_pct=data[cid].get("usd_24hr_change"),
                ))
        return out
    except Exception as e:
        log.warning(f"Crypto fetch failed: {e}")
        return []

def fetch_space_weather() -> dict | None:
    """Fetches Kp-index and alerts from NOAA."""
    try:
        kp_data = _get_json("https://services.swpc.noaa.gov/products/noaa-estimated-planetary-k-index-1-minute.json", timeout=15)
        latest_kp = kp_data[-1][1] if kp_data else "N/A"
        return {"kp": latest_kp}
    except:
        return None

def fetch_weather() -> str:
    """Fetches current/daily weather from Open-Meteo."""
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,relative_humidity_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": 1,
    }
    url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
    try:
        w = _get_json(url, timeout=15)
        curr = w["current"]["temperature_2m"]
        hi = w["daily"]["temperature_2m_max"][0]
        lo = w["daily"]["temperature_2m_min"][0]
        return f"Currently {curr}°F. High: {hi}°F / Low: {lo}°F."
    except:
        return "Weather currently unavailable."

def fetch_air_quality() -> str:
    """Fetches US AQI from Open-Meteo."""
    params = {"latitude": LAT, "longitude": LON, "current": "us_aqi"}
    url = f"https://air-quality-api.open-meteo.com/v1/air-quality?{urlencode(params)}"
    try:
        aq = _get_json(url, timeout=15)
        val = aq["current"]["us_aqi"]
        label = "Good" if val <= 50 else "Moderate" if val <= 100 else "Unhealthy"
        return f"{val} ({label})"
    except:
        return "N/A"

def fetch_sun() -> str:
    """Fetches sunrise/sunset times."""
    url = f"https://api.sunrise-sunset.org/json?lat={LAT}&lng={LON}&formatted=0"
    try:
        data = _get_json(url, timeout=15)
        res = data["results"]
        # Convert UTC to local
        sr = datetime.fromisoformat(res["sunrise"]).astimezone(TZ).strftime("%-I:%M %p")
        ss = datetime.fromisoformat(res["sunset"]).astimezone(TZ).strftime("%-I:%M %p")
        return f"Sunrise: {sr} | Sunset: {ss}"
    except:
        return "N/A"

def fetch_tides() -> list[TideEvent]:
    """Fetches today's high/low tides from NOAA."""
    today = datetime.now(TZ).strftime("%Y%m%d")
    params = {
        "station": TIDE_STATION,
        "begin_date": today,
        "range": 24,
        "product": "predictions",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "interval": "hilo",
        "units": "english",
        "format": "json",
    }
    url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?{urlencode(params)}"
    try:
        data = _get_json(url, timeout=15)
        out = []
        for p in data.get("predictions", []):
            out.append(TideEvent(
                time=datetime.strptime(p["t"], "%Y-%m-%d %H:%M").strftime("%-I:%M %p"),
                height=float(p["v"]),
                kind="High" if p["type"] == "H" else "Low"
            ))
        return out
    except:
        return []

def fetch_apod() -> dict | None:
    """NASA Astronomy Picture of the Day (Scraped/API mix)."""
    try:
        data = _get_json("https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY", timeout=15)
        return {
            "url": data.get("url"),
            "title": data.get("title"),
            "explanation": data.get("explanation", "")[:200] + "..."
        }
    except:
        return None

def fetch_spaceflight_news() -> list[Article]:
    """Latest space-related news."""
    try:
        data = _get_json("https://api.spaceflightnewsapi.net/v4/articles/?limit=5", timeout=20)
        return [
            Article(a["news_site"], a["title"], a["url"])
            for a in data.get("results", [])
        ]
    except:
        return []

def fetch_iss() -> dict:
    """ISS Location and Crew."""
    try:
        pos = _get_json("http://api.open-notify.org/iss-now.json", timeout=10)
        crew = _get_json("http://api.open-notify.org/astros.json", timeout=10)
        return {
            "lat": pos["iss_position"]["latitude"],
            "lon": pos["iss_position"]["longitude"],
            "crew_count": crew["number"],
            "crew_names": [p["name"] for p in crew["people"]]
        }
    except:
        return {"crew_count": "Unknown"}

def fetch_launches() -> list[Any]:
    """Upcoming Rocket Launches."""
    try:
        data = _get_json("https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=3", timeout=20)
        return data.get("results", [])
    except:
        return []

def fetch_asteroids() -> list[Any]:
    """Near Earth Objects."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"https://api.nasa.gov/planetary/neo/rest/v1/feed?start_date={today}&end_date={today}&api_key=DEMO_KEY"
    try:
        data = _get_json(url, timeout=20)
        return data.get("near_earth_objects", {}).get(today, [])[:5]
    except:
        return []

# --- HTML BUILDER ---------------------------------------------------------

def build_html(
    weather: str, air: str, sun: str, tides: list[TideEvent], space_wx: dict | None,
    indexes: list[Quote], tickers: list[Quote], crypto: list[Quote],
    local: list[Article], global_: list[Article], gdelt: list[Article], hn: list[Article],
    apod: dict | None, space_news: list[Article], iss: dict, launches: list[Any], asteroids: list[Any]
) -> str:
    """Generates the single-file index.html."""
    
    timestamp = datetime.now(TZ).strftime("%A, %B %d, %Y | %-I:%M %p")
    
    def render_news_list(articles: list[Article]):
        if not articles: return "<li>No updates.</li>"
        return "\n".join([
            f'<li><span class="source">[{html.escape(a.source)}]</span> <a href="{a.url}" target="_blank">{html.escape(a.title)}</a></li>'
            for a in articles
        ])

    def render_quotes(quotes: list[Quote]):
        html_out = ""
        for q in quotes:
            color = "pos" if (q.change_pct or 0) >= 0 else "neg"
            sign = "+" if (q.change_pct or 0) >= 0 else ""
            price_fmt = f"{q.price:,.2f}" if q.price else "N/A"
            pct_fmt = f"{sign}{q.change_pct:.2f}%" if q.change_pct is not None else "N/A"
            html_out += f"""
            <div class="quote-card">
                <div class="quote-name">{html.escape(q.name)}</div>
                <div class="quote-price">{price_fmt}</div>
                <div class="quote-pct {color}">{pct_fmt}</div>
            </div>"""
        return html_out

    # Minimal logic for space sections
    launch_html = ""
    for l in launches:
        launch_html += f"<li><strong>{l.get('name')}</strong> - {l.get('window_start')}</li>"
    
    neo_html = ""
    for a in asteroids:
        dist = float(a['close_approach_data'][0]['miss_distance']['miles'])
        neo_html += f"<li>{a['name']} ({dist/1e6:.1f}M miles)</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Briefing</title>
    <style>
        :root {{
            --bg: #0f1115; --card: #1a1d23; --text: #e0e0e0; --dim: #a0a0a0;
            --accent: #4a9eff; --pos: #4cd964; --neg: #ff3b30;
        }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; line-height: 1.4; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{ border-bottom: 1px solid #333; padding-bottom: 10px; margin-bottom: 20px; }}
        h1 {{ margin: 0; font-size: 1.5rem; color: var(--accent); }}
        .timestamp {{ font-size: 0.8rem; color: var(--dim); }}
        
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; }}
        section {{ background: var(--card); padding: 15px; border-radius: 8px; }}
        h2 {{ margin-top: 0; font-size: 1rem; border-bottom: 1px solid #333; padding-bottom: 5px; color: var(--dim); }}
        
        .weather-grid {{ display: flex; justify-content: space-between; }}
        .quote-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 10px; }}
        .quote-card {{ background: #252a33; padding: 10px; border-radius: 4px; text-align: center; }}
        .quote-name {{ font-size: 0.7rem; color: var(--dim); overflow: hidden; white-space: nowrap; }}
        .quote-price {{ font-weight: bold; margin: 2px 0; }}
        .quote-pct {{ font-size: 0.8rem; }}
        .pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }}

        ul {{ list-style: none; padding: 0; margin: 0; }}
        li {{ margin-bottom: 8px; font-size: 0.9rem; border-bottom: 1px solid #222; padding-bottom: 4px; }}
        li:last-child {{ border: 0; }}
        .source {{ font-weight: bold; color: var(--accent); font-size: 0.75rem; margin-right: 5px; }}
        a {{ color: var(--text); text-decoration: none; }}
        a:hover {{ color: var(--accent); }}
        
        .apod {{ width: 100%; border-radius: 4px; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Daily Briefing</h1>
            <div class="timestamp">{timestamp}</div>
        </header>

        <div class="grid">
            <section>
                <h2>Environment & Conditions</h2>
                <div class="weather-grid">
                    <div><strong>Weather:</strong> {weather}</div>
                    <div><strong>AQI:</strong> {air}</div>
                </div>
                <p>{sun}</p>
                <strong>Tides ({TIDE_STATION_NAME}):</strong>
                <ul>{"".join([f"<li>{t.kind}: {t.time} ({t.height} ft)</li>" for t in tides])}</ul>
            </section>

            <section>
                <h2>Market Indexes</h2>
                <div class="quote-grid">{render_quotes(indexes)}</div>
                <h2 style="margin-top:15px">Equities</h2>
                <div class="quote-grid">{render_quotes(tickers)}</div>
                <h2 style="margin-top:15px">Digital Assets</h2>
                <div class="quote-grid">{render_quotes(crypto)}</div>
            </section>

            <section>
                <h2>World News (GDELT / Global)</h2>
                <ul>{render_news_list(gdelt + global_)}</ul>
            </section>

            <section>
                <h2>Regional & Tech News</h2>
                <ul>{render_news_list(local + hn)}</ul>
            </section>

            <section>
                <h2>Space & Science</h2>
                {f'<h3>{apod["title"]}</h3><img class="apod" src="{apod["url"]}">' if apod else ''}
                <ul>{render_news_list(space_news)}</ul>
                <p>🚀 <strong>Upcoming:</strong></p><ul>{launch_html}</ul>
                <p>☄️ <strong>NEO:</strong></p><ul>{neo_html}</ul>
                <p>🛰️ <strong>ISS:</strong> {iss["crew_count"]} souls aboard.</p>
            </section>
        </div>
    </div>
</body>
</html>
"""

# --- MAIN -----------------------------------------------------------------

def main():
    log.info("Starting Daily Briefing update...")

    # 1. Stocks & Indexes
    log.info("Fetching stocks...")
    all_symbols = STOCK_INDEXES + STOCK_TICKERS
    indexes, tickers = fetch_stocks(all_symbols)

    # 2. Crypto
    log.info("Fetching crypto...")
    crypto = fetch_crypto()

    # 3. News
    log.info("Fetching news feeds...")
    local = []
    for name, url in LOCAL_FEEDS:
        local.extend(fetch_rss(name, url))

    global_ = []
    for name, url in GLOBAL_FEEDS:
        global_.extend(fetch_rss(name, url))

    log.info("Fetching GDELT...")
    gdelt = fetch_gdelt()

    log.info("Fetching Hacker News...")
    hn = fetch_hackernews()

    # 4. Environment
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

    # 5. Space
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

    # Final summary log
    log.info(
        "Counts — local:%d global:%d gdelt:%d hn:%d "
        "indexes:%d tickers:%d crypto:%d tides:%d "
        "apod:%s spx_news:%d launches:%d asteroids:%d iss_crew:%s",
        len(local), len(global_), len(gdelt), len(hn),
        len(indexes), len(tickers), len(crypto), len(tides),
        "yes" if apod else "no", len(space_news), len(launches), len(asteroids),
        iss.get("crew_count"),
    )

    # 6. Build and Write
    html_doc = build_html(
        weather=weather, air=air, sun=sun, tides=tides, space_wx=space_wx,
        indexes=indexes, tickers=tickers, crypto=crypto,
        local=local, global_=global_, gdelt=gdelt, hn=hn,
        apod=apod, space_news=space_news, iss=iss, launches=launches, asteroids=asteroids
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

    log.info("Success: index.html generated.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Critical failure: {e}")
        sys.exit(1)