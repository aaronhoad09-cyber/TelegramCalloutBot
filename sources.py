"""Network data sources: PumpPortal (migrations), DexScreener (market), RugCheck (safety)."""
import asyncio
import json
import logging
import time

import aiohttp

log = logging.getLogger("sources")

DEX = "https://api.dexscreener.com"
RUG = "https://api.rugcheck.xyz/v1"
PUMPPORTAL_WS = "wss://pumpportal.fun/api/data"
UA = {"User-Agent": "memecoin-callout-bot/1.0"}


async def get_json(session, url, timeout=20):
    try:
        async with session.get(url, headers=UA, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status == 429:
                log.warning("rate limited by %s", url.split("/")[2])
                await asyncio.sleep(5)
                return None
            if r.status != 200:
                return None
            return await r.json(content_type=None)
    except Exception as e:
        log.debug("GET %s failed: %s", url, e)
        return None


# ---------------------------------------------------------------- DexScreener

async def dex_pairs_for(session, mints):
    """Return {mint: [pairs]}.

    Batches of 10: each coin usually has 2 pairs (bonding curve + PumpSwap) and
    DexScreener caps how many pairs one response returns, so big batches drop coins.
    """
    out = {}
    for i in range(0, len(mints), 10):
        chunk = mints[i:i + 10]
        data = await get_json(session, f"{DEX}/tokens/v1/solana/{','.join(chunk)}")
        for p in data or []:
            m = (p.get("baseToken") or {}).get("address")
            if m in chunk:
                out.setdefault(m, []).append(p)
        await asyncio.sleep(0.3)
    return out


async def trending_metas(session):
    return await get_json(session, f"{DEX}/metas/trending/v1") or []


async def latest_profiles(session):
    """Backup discovery feed: newest Solana token profiles on DexScreener."""
    data = await get_json(session, f"{DEX}/token-profiles/latest/v1") or []
    return [d.get("tokenAddress") for d in data
            if d.get("chainId") == "solana" and d.get("tokenAddress")]


# ---------------------------------------------------------------- GeckoTerminal

GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"


def _iso_to_ts(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_gecko_pools(data, dex="pumpswap"):
    """[(mint, pool_created_ts)] for pools on `dex` in a GeckoTerminal pools response."""
    out = []
    for pool in (data or {}).get("data") or []:
        rel = pool.get("relationships") or {}
        if ((rel.get("dex") or {}).get("data") or {}).get("id") != dex:
            continue
        base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
        mint = base.split("_", 1)[1] if base.startswith("solana_") else ""
        if mint == "So11111111111111111111111111111111111111112":   # SOL as base: take the other side
            q = ((rel.get("quote_token") or {}).get("data") or {}).get("id") or ""
            mint = q.split("_", 1)[1] if q.startswith("solana_") else ""
        if 32 <= len(mint) <= 44:
            out.append((mint, _iso_to_ts((pool.get("attributes") or {}).get("pool_created_at"))))
    return out


async def gecko_pumpswap_coins(session, pages_new=5, pages_top=3):
    """Backup + backfill discovery: newest PumpSwap pools and the busiest PumpSwap pools."""
    found = []
    for page in range(1, pages_new + 1):
        found += parse_gecko_pools(await get_json(session, f"{GECKO}/new_pools?page={page}"))
        await asyncio.sleep(2.5)                         # public API: ~30 requests/minute
    for page in range(1, pages_top + 1):
        found += parse_gecko_pools(await get_json(
            session, f"{GECKO}/dexes/pumpswap/pools?page={page}&sort=h24_volume_usd_desc"))
        await asyncio.sleep(2.5)
    return found


# ---------------------------------------------------------------- RugCheck

async def rug_report(session, mint):
    return await get_json(session, f"{RUG}/tokens/{mint}/report", timeout=30)


async def token_description(session, report):
    """Pump.fun coins store their description in the metadata JSON."""
    fm = (report or {}).get("fileMeta") or {}
    if fm.get("description"):
        return fm["description"]
    uri = ((report or {}).get("tokenMeta") or {}).get("uri")
    if uri and uri.startswith("http"):
        meta = await get_json(session, uri, timeout=10)
        if isinstance(meta, dict):
            return meta.get("description") or ""
    return ""


# ---------------------------------------------------------------- PumpPortal

def parse_migration(raw):
    """Pull the mint out of a PumpPortal migration message. Returns None for non-events."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    mint = msg.get("mint") or msg.get("token") or msg.get("tokenAddress")
    if isinstance(mint, str) and 32 <= len(mint) <= 44:
        return mint
    return None


async def migration_stream(session, on_mint, status):
    """Listen to pump.fun -> PumpSwap migrations forever, reconnecting on failure."""
    backoff = 5
    while True:
        try:
            async with session.ws_connect(PUMPPORTAL_WS, heartbeat=30) as ws:
                await ws.send_str(json.dumps({"method": "subscribeMigration"}))
                status["stream"] = "connected"
                log.info("PumpPortal migration stream connected")
                backoff = 5
                logged = 0
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                        continue
                    if logged < 3:                     # show the format in the logs once per connect
                        log.info("PumpPortal message: %s", msg.data[:300])
                        logged += 1
                    mint = parse_migration(msg.data)
                    if mint:
                        status["last_migration"] = time.time()
                        status["migrations_seen"] = status.get("migrations_seen", 0) + 1
                        await on_mint(mint, "migration")
                    else:
                        log.debug("stream msg: %s", msg.data[:200])
        except Exception as e:
            log.warning("migration stream error: %s", e)
        status["stream"] = "reconnecting"
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 300)   # PumpPortal bans clients that reconnect too aggressively
