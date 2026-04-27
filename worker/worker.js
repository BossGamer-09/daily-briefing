/**
 * Cloudflare Worker — Stocks Proxy
 */

const ALLOWED_ORIGINS = [
  "https://bossgamer-09.github.io",
  "http://localhost:8000"
];

const EDGE_CACHE_SECONDS = 60;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    
    // Determine CORS policy
    const isAllowed = ALLOWED_ORIGINS.includes(origin);
    const corsHeaders = {
      "Access-Control-Allow-Origin": isAllowed ? origin : "null",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    // 1. Handle CORS Preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // 2. Health Check (Test this first to verify deployment)
    if (url.pathname === "/health") {
      return new Response("ok", { 
        headers: { ...corsHeaders, "Content-Type": "text/plain" } 
      });
    }

    // 3. Stock Quote Endpoint
    if (url.pathname === "/quote") {
      const symbols = url.searchParams.get("symbols");
      if (!symbols) {
        return new Response("Missing symbols", { status: 400, headers: corsHeaders });
      }

      try {
        const yahooUrl = `https://query2.finance.yahoo.com/v7/finance/quote?symbols=${symbols}`;
        const response = await fetch(yahooUrl, {
          headers: { "User-Agent": "Mozilla/5.0" }
        });
        const data = await response.json();
        
        return new Response(JSON.stringify(data), {
          headers: { 
            ...corsHeaders, 
            "Content-Type": "application/json",
            "Cache-Control": `public, max-age=${EDGE_CACHE_SECONDS}`
          }
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { 
          status: 500, 
          headers: corsHeaders 
        });
      }
    }

    return new Response("Not Found", { status: 404, headers: corsHeaders });
  }
};