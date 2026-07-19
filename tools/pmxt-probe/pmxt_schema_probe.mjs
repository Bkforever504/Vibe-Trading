#!/usr/bin/env node
import { Kalshi, Limitless, Polymarket } from "pmxtjs";

const VENUES = {
  polymarket: Polymarket,
  kalshi: Kalshi,
  limitless: Limitless,
};

function parseArgs(argv) {
  const args = {
    query: "Fed",
    venues: Object.keys(VENUES),
    timeoutMs: 12000,
    maxMarkets: 8,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key === "--query" && value) {
      args.query = value;
      i += 1;
    } else if (key === "--venues" && value) {
      args.venues = value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
      i += 1;
    } else if (key === "--timeout-ms" && value) {
      args.timeoutMs = Number(value);
      i += 1;
    } else if (key === "--max-markets" && value) {
      args.maxMarkets = Number(value);
      i += 1;
    }
  }
  return args;
}

function pick(obj, keys) {
  for (const key of keys) {
    if (obj && obj[key] !== undefined && obj[key] !== null && obj[key] !== "") {
      return obj[key];
    }
  }
  return null;
}

function normalizeMarket(market) {
  const raw = market || {};
  return {
    id: pick(raw, ["id", "marketId", "ticker", "conditionId", "slug"]),
    title: pick(raw, ["title", "question", "name", "eventTitle"]),
    ticker: pick(raw, ["ticker", "symbol"]),
    slug: pick(raw, ["slug"]),
    url: pick(raw, ["url", "marketUrl"]),
    volume: pick(raw, ["volume", "volume24hr", "volume24h", "totalVolume"]),
    liquidity: pick(raw, ["liquidity", "liquidityNum"]),
    best_bid: pick(raw, ["bestBid", "best_bid", "bid"]),
    best_ask: pick(raw, ["bestAsk", "best_ask", "ask"]),
    yes_price: pick(raw, ["yesPrice", "yes_price", "lastTradePrice", "price"]),
    end_date: pick(raw, ["endDate", "end_date", "closeTime", "expirationTime"]),
    raw_keys: Object.keys(raw).sort().slice(0, 80),
  };
}

async function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

async function fetchVenue(venue, args) {
  const Cls = VENUES[venue];
  if (!Cls) {
    return { venue, status: "error", error: `unsupported venue ${venue}`, markets: [] };
  }
  try {
    const exchange = new Cls();
    const fetched = await withTimeout(exchange.fetchMarkets({ query: args.query }), args.timeoutMs, venue);
    const markets = Array.isArray(fetched) ? fetched : Array.isArray(fetched?.markets) ? fetched.markets : [];
    return {
      venue,
      status: "ok",
      market_count: markets.length,
      markets: markets.slice(0, args.maxMarkets).map(normalizeMarket),
    };
  } catch (error) {
    return {
      venue,
      status: "error",
      error: error?.message || String(error),
      markets: [],
    };
  }
}

const args = parseArgs(process.argv);
const startedAt = new Date().toISOString();
const results = [];
for (const venue of args.venues) {
  results.push(await fetchVenue(venue, args));
}

console.log(JSON.stringify({
  provider: "pmxt_schema_probe_node",
  mode: "read_only",
  execution_enabled: false,
  started_at: startedAt,
  finished_at: new Date().toISOString(),
  query: args.query,
  venues: args.venues,
  results,
}, null, 2));
