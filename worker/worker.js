/**
 * Cloudflare Worker — Stocks proxy
 *
 * Proxies Yahoo Finance v8 chart endpoint and adds CORS headers so your
 * GitHub Pages site can fetch stock quotes from the browser.
 *
 * Endpoints:
 *   GET /quote?symbols=AAPL,NVDA,^GSPC
 *     → { "AAPL": { name, symbol, price, prev, change, change_pct },
 *         "NVDA": {...}, "^GSPC": {...} }
 *
 *   GET /health
 *     → "ok"
 *
 * Security:
 *   ALLOWED_ORIGINS limits which sites can call this Worker. Add your
 *   GitHub Pages URL. Wildcard "*" allowed but not recommended.
 *
 * Caching:
 *   Each symbol's response is cached at Cloudflare's edge for 60 seconds,
 *   so even with many viewers you barely hit Yahoo.
 */

const ALLOWED_ORIGINS = [
  "https://bossgamer-09.github.io",
  "http://localhost:8000",  // local dev
];

// Hard cap to prevent abuse if your Worker URL leaks
const MAX_SYMBOLS_PER_REQUEST = 20;

// How long to cache each symbol at Cloudflare's edge (seconds)
const EDGE_CACHE_SECONDS = 60;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";

    // Build CORS headers based on origin allowlist
    const corsHeaders = {
      "Access-Control-Allow-Origin": ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    };

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    // Health check
    if (url.pathname === "/health") {
      return new Response("ok", {
        headers: { ...corsHeaders, "Content-Type": "text/plain" },
      });
    }

    // Quote endpoint
    if (url.pathname === "/quote") {
      const symbolsParam = url.searchParams.get("symbols") || "";
      const symbols = symbolsParam
        .split(",")
        .map(s => s.trim())
        .filter(Boolean)
        .slice(0, MAX_SYMBOLS_PER_REQUEST);

      if (symbols.length === 0) {
        return jsonResponse({ error: "Pass ?symbols=AAPL,NVDA" }, 400, corsHeaders);
      }

      // Fetch all symbols in parallel
      const results = await Promise.all(symbols.map(sym => fetchQuote(sym, ctx)));

      const out = {};
      for (const r of results) {
        if (r) out[r.symbol] = r;
      }

      return jsonResponse(out, 200, {
        ...corsHeaders,
        "Cache-Control": `public, max-age=${EDGE_CACHE_SECONDS}`,
      });
    }

    return new Response("Not found. Try /quote?symbols=AAPL or /health", {
      status: 404,
      headers: corsHeaders,
    });
  },
};

async function fetchQuote(symbol, ctx) {
  const yahooUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
    symbol
  )}?interval=1d&range=5d`;

  // Use the Cloudflare cache so a popular symbol only hits Yahoo once per minute globally.
  const cacheKey = new Request(`https://cache.local/quote/${symbol}`, { method: "GET" });
  const cache = caches.default;
  let cached = await cache.match(cacheKey);
  if (cached) {
    return await cached.json();
  }

  try {
    const r = await fetch(yahooUrl, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept: "application/json",
      },
      cf: { cacheTtl: EDGE_CACHE_SECONDS, cacheEverything: true },
    });
    if (!r.ok) {
      console.log(`Yahoo ${symbol} returned ${r.status}`);
      return null;
    }
    const data = await r.json();
    const result = data?.chart?.result?.[0];
    if (!result) return null;

    const meta = result.meta || {};
    const price = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose ?? meta.previousClose;
    if (price == null || prev == null) return null;

    const change = price - prev;
    const change_pct = prev !== 0 ? (change / prev) * 100 : null;

    const quote = {
      symbol,
      name: meta.longName || meta.shortName || symbol,
      price,
      prev,
      change,
      change_pct,
      currency: meta.currency || "USD",
      market_state: meta.marketState || null,
      ts: Date.now(),
    };

    // Cache it at Cloudflare's edge
    const cachedResp = new Response(JSON.stringify(quote), {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": `public, max-age=${EDGE_CACHE_SECONDS}`,
      },
    });
    ctx.waitUntil(cache.put(cacheKey, cachedResp));

    return quote;
  } catch (e) {
    console.log(`Yahoo ${symbol} error: ${e.message}`);
    return null;
  }
}

function jsonResponse(body, status, extraHeaders) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...extraHeaders,
    },
  });
}
