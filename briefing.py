#!/usr/bin/env python3
"""
Daily Briefing v3 — static HTML generator for GitHub Pages.
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

# Feeds
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
STOCK_WORKER_URL = "https://daily-briefing-stocks.mwilmot.workers.dev"

STOCK_INDEXES = [("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("Dow Jones", "^DJI")]
STOCK_TICKERS = [
    ("Apple", "AAPL"), ("Microsoft", "MSFT"), ("Alphabet", "GOOGL"),
    ("Tesla", "TSLA"), ("Nvidia", "NVDA"), ("Amazon", "AMZN"), ("Meta", "META"),
]

CRYPTO_COINS = [
    ("Bitcoin", "bitcoin", "BTC"), ("Ethereum", "ethereum", "ETH"),
    ("Solana", "solana", "SOL"), ("XRP", "ripple", "XRP"),
    ("Cardano", "cardano", "ADA"), ("Dogecoin", "dogecoin", "DOGE"),
]

# --- LOGGING --------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("briefing")

# --- DATA TYPES -----------------------------------------------------------

@dataclass
class Article:
    source: str; title: str; url: str

@dataclass
class Quote:
    name: str; symbol: str; price: float | None; change: float | None; change_pct: float | None

# --- FETCHERS -------------------------------------------------------------

def _get_json(url: str, timeout: int = 20, headers: dict | None = None) -> Any:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers: h.update(headers)
    r = requests.get(url, timeout=timeout, headers=h)
    r.raise_for_status()
    return r.json()

def fetch_rss(name: str, url: str) -> list[Article]:
    try:
        parsed = feedparser.parse(url, agent=USER_AGENT)
        out = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or "#"
            if title: out.append(Article(source=name, title=title, url=link))
        return out
    except: return []

def fetch_stocks(symbols: list[tuple[str, str]]) -> tuple[list[Quote], list[Quote]]:
    """Fetch and split stocks into indexes and tickers."""
    if not STOCK_WORKER_URL or not symbols: return [], []
    symbol_list = ",".join([s[1] for s in symbols])
    url = f"{STOCK_WORKER_URL.rstrip('/')}/quote?symbols={symbol_list}"
    try:
        data = _get_json(url, timeout=20)
        results = []
        for name, symbol in symbols:
            q = data.get(symbol, {})
            if q:
                results.append(Quote(
                    name=name, symbol=symbol, 
                    price=q.get("price"), change=q.get("change"), 
                    change_pct=q.get("change_pct")
                ))
        idx_len = len(STOCK_INDEXES)
        return results[:idx_len], results[idx_len:]
    except Exception as e:
        log.warning(f"Stock fetch failed: {e}")
        return [], []

def fetch_crypto() -> list[Quote]:
    ids = ",".join(c[1] for c in CRYPTO_COINS)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    try:
        data = _get_json(url, timeout=20)
        return [Quote(name, sym, data[cid].get("usd"), None, data[cid].get("usd_24hr_change")) 
                for name, cid, sym in CRYPTO_COINS if cid in data]
    except: return []

def fetch_weather() -> str:
    params = {"latitude": LAT, "longitude": LON, "current": "temperature_2m", "daily": "temperature_2m_max,temperature_2m_min", "temperature_unit": "fahrenheit", "forecast_days": 1}
    try:
        w = _get_json(f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}", timeout=15)
        return f"Now: {w['current']['temperature_2m']}°F. Today: {w['daily']['temperature_2m_max'][0]}°F / {w['daily']['temperature_2m_min'][0]}°F."
    except: return "Weather unavailable."

def fetch_air_quality() -> str:
    return "Air quality data currently placeholder."

def fetch_sun() -> str:
    return "Sun times data currently placeholder."

def fetch_tides() -> list[Any]:
    return []

def fetch_apod() -> dict | None:
    return None

def fetch_spaceflight_news() -> list[Any]:
    return []

def fetch_iss() -> dict:
    return {"crew_count": 0}

def fetch_launches() -> list[Any]:
    return []

def fetch_asteroids() -> list[Any]:
    return []

def fetch_gdelt() -> list[Article]:
    return []

def fetch_hackernews() -> list[Article]:
    return []

# --- HTML BUILDER ---------------------------------------------------------

def build_html(weather, air, sun, tides, space_wx, indexes, tickers, crypto, local, global_, gdelt, hn) -> str:
    return f"""
    <html>
    <head><title>Daily Briefing</title></head>
    <body>
        <h1>Daily Briefing</h1>
        <section><h2>Weather</h2>{weather}</section>
        <section><h2>Stocks</h2>Fetched {len(indexes) + len(tickers)} symbols.</section>
        <section><h2>Local News</h2>{len(local)} articles.</section>
    </body>
    </html>
    """

# --- MAIN -----------------------------------------------------------------

def main():
    log.info("Starting update...")
    
    # 1. Fetching Stocks (Fixed argument passing)
    all_symbols = STOCK_INDEXES + STOCK_TICKERS
    indexes, tickers = fetch_stocks(all_symbols)
    
    # 2. Fetching other data
    crypto = fetch_crypto()
    local = fetch_rss("Local", LOCAL_FEEDS[0][1])
    global_ = fetch_rss("Global", GLOBAL_FEEDS[0][1])
    weather = fetch_weather()
    air = fetch_air_quality()
    sun = fetch_sun()
    tides = fetch_tides()
    space_wx = None 
    gdelt = fetch_gdelt()
    hn = fetch_hackernews()
    
    # 3. Generation
    html_doc = build_html(
        weather=weather, air=air, sun=sun, tides=tides, space_wx=space_wx,
        indexes=indexes, tickers=tickers, crypto=crypto,
        local=local, global_=global_, gdelt=gdelt, hn=hn
    )
    
    with open("index.html", "w") as f:
        f.write(html_doc)
    
    log.info("Update complete.")

if __name__ == "__main__":
    main()