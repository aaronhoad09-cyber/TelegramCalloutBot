"""Solana memecoin callout bot.

Flow: PumpPortal migration stream -> watchlist -> every minute DexScreener market check
(post-migration + mcap + liquidity) -> RugCheck standard -> narrative -> Telegram callout.
"""
import asyncio
import logging
import time

import aiohttp

import checks
import formatting
import narrative
import sources
from config import Config as C
from storage import State
from telegram import Telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


class Bot:
    def __init__(self, session):
        self.s = session
        self.tg = Telegram(session, C.TELEGRAM_BOT_TOKEN, C.TELEGRAM_CHAT_ID)
        self.state = State(C.STATE_FILE)
        self.status = {"stream": "starting", "migrations_seen": 0, "started": time.time(),
                       "callouts": 0, "last_scan": None}
        self.metas = []
        self.metas_at = 0
        self.last_pairs = {}

    # ------------------------------------------------------------ helpers
    async def get_metas(self):
        if time.time() - self.metas_at > 600:
            m = await sources.trending_metas(self.s)
            if m:
                self.metas, self.metas_at = m, time.time()
        return self.metas

    async def on_mint(self, mint, source):
        if self.state.add(mint, source):
            log.info("watching %s (%s)", mint, source)

    async def build_callout(self, mint, pair, report, rug):
        base = pair.get("baseToken") or {}
        desc = await sources.token_description(self.s, report)
        token = {"name": base.get("name"), "symbol": base.get("symbol"), "description": desc}
        metas = await self.get_metas()
        hit = narrative.match_metas(token["name"], token["symbol"], desc, metas)
        socials = formatting.socials_of(pair)
        lines = narrative.rule_based(token, hit, socials)
        ai = await narrative.ai_overview(self.s, C, token, hit, metas, socials, pair)
        return formatting.callout(mint, pair, rug, lines, ai, int(time.time() * 1000))

    # ------------------------------------------------------------ main scan
    async def scan_once(self):
        self.state.prune(C.WATCH_HOURS)
        for mint in await sources.latest_profiles(self.s):   # backup discovery feed
            if mint.endswith("pump"):
                await self.on_mint(mint, "dexscreener-profile")

        mints = list(self.state.watch)
        if not mints:
            return
        pairs_map = await sources.dex_pairs_for(self.s, mints)
        now = time.time()
        for mint in mints:
            pairs = pairs_map.get(mint)
            best = checks.best_pair(pairs)
            if best:
                self.last_pairs[mint] = best
            if self.state.paused or not checks.market_check(pairs, C).passed:
                continue

            w = self.state.watch[mint]
            if w.get("rug_checked") and now - w["rug_checked"] < C.RUG_RECHECK_MIN * 60:
                continue
            report = await sources.rug_report(self.s, mint)
            w["rug_checked"] = now
            rug = checks.rug_check(report, C)
            await asyncio.sleep(1.5)                          # be polite to RugCheck
            if not rug.passed:
                w["rug_fail"] = rug.reasons[:4]
                log.info("rug fail %s: %s", mint, "; ".join(rug.reasons))
                continue

            msg = await self.build_callout(mint, best, report, rug)
            if await self.tg.send(msg):
                self.state.alerted[mint] = now
                self.state.watch.pop(mint, None)
                self.status["callouts"] += 1
                log.info("CALLOUT %s", mint)
        self.last_pairs = {m: p for m, p in self.last_pairs.items() if m in self.state.watch}
        self.status["last_scan"] = now
        self.state.save()

    async def scan_loop(self):
        while True:
            try:
                await self.scan_once()
            except Exception:
                log.exception("scan failed")
            await asyncio.sleep(C.SCAN_INTERVAL_SEC)

    # ------------------------------------------------------------ digest
    async def send_digest(self, chat_id=None):
        metas = await self.get_metas()
        movers = sorted(self.last_pairs.values(),
                        key=lambda p: float((p.get("priceChange") or {}).get("h1") or 0), reverse=True)
        movers = [p for p in movers if checks.mcap_of(p) >= C.MIN_MCAP * 0.5]
        await self.tg.send(formatting.digest(metas, movers), chat_id)

    async def digest_loop(self):
        if C.DIGEST_HOURS <= 0:
            return
        await asyncio.sleep(120)
        while True:
            if not self.state.paused:
                try:
                    await self.send_digest()
                except Exception:
                    log.exception("digest failed")
            await asyncio.sleep(C.DIGEST_HOURS * 3600)

    # ------------------------------------------------------------ commands
    async def cmd_check(self, mint, chat):
        pairs = (await sources.dex_pairs_for(self.s, [mint])).get(mint)
        pair = checks.best_pair(pairs) or (pairs[0] if pairs else None)
        market = checks.market_check(pairs, C)
        report = await sources.rug_report(self.s, mint)
        rug = checks.rug_check(report, C)
        await self.tg.send(formatting.check_report(mint, pair, market, rug), chat)

    async def handle(self, text, chat):
        parts = text.strip().split()
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/help"):
            await self.tg.send(
                "👋 <b>Memecoin callout bot</b>\n"
                f"Calls out pump.fun coins after migration with MC ≥ {formatting.money(C.MIN_MCAP)} "
                "that pass the rug-check standard, with a narrative overview.\n\n"
                "/status — what the bot is doing\n/check &lt;mint&gt; — run the checks on any coin\n"
                "/watch &lt;mint&gt; — add a coin to the watchlist\n/digest — market trend digest now\n"
                "/settings — current filters\n/pause · /resume — stop/start callouts", chat)
        elif cmd == "/status":
            st = self.status
            last = f"{time.time() - st['last_scan']:.0f}s ago" if st["last_scan"] else "not yet"
            await self.tg.send(
                f"📡 Stream: {st['stream']}\n👀 Watching: {len(self.state.watch)} coins\n"
                f"🔄 Migrations seen: {st['migrations_seen']}\n🚨 Callouts this run: {st['callouts']}\n"
                f"⏱ Last scan: {last}\n⏸ Paused: {self.state.paused}\n"
                f"🧠 AI narrative: {'on' if C.ANTHROPIC_API_KEY else 'off'}", chat)
        elif cmd == "/check" and len(parts) > 1:
            await self.tg.send("Checking…", chat)
            await self.cmd_check(parts[1], chat)
        elif cmd == "/watch" and len(parts) > 1:
            self.state.alerted.pop(parts[1], None)
            await self.on_mint(parts[1], "manual")
            self.state.save()
            await self.tg.send("👀 Added to watchlist.", chat)
        elif cmd == "/digest":
            await self.send_digest(chat)
        elif cmd == "/settings":
            await self.tg.send(
                "<b>Filters</b>\n"
                f"Post-migration only · MC ≥ {formatting.money(C.MIN_MCAP)} · Liq ≥ {formatting.money(C.MIN_LIQUIDITY)}\n"
                f"Watch window: {C.WATCH_HOURS:g}h after migration\n\n<b>Rug standard</b>\n"
                "Mint + freeze authority revoked · not flagged rugged · no RugCheck 'danger' risks\n"
                f"RugCheck score ≤ {C.RUG_MAX_SCORE:g} · top10 ≤ {C.MAX_TOP10_PCT:g}% · "
                f"single wallet ≤ {C.MAX_SINGLE_HOLDER_PCT:g}% · insiders ≤ {C.MAX_INSIDER_PCT:g}% · "
                f"dev ≤ {C.MAX_CREATOR_PCT:g}% · holders ≥ {C.MIN_HOLDERS}\n\n"
                "Change these in Railway → Variables.", chat)
        elif cmd in ("/pause", "/resume"):
            self.state.paused = cmd == "/pause"
            self.state.save()
            await self.tg.send("⏸ Callouts paused." if self.state.paused else "▶️ Callouts resumed.", chat)

    async def command_loop(self):
        while True:
            for u in await self.tg.updates():
                msg = u.get("message") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                text = msg.get("text") or ""
                if chat != str(C.TELEGRAM_CHAT_ID):
                    continue   # private bot: ignore everyone else
                if text.startswith("/"):
                    try:
                        await self.handle(text, chat)
                    except Exception:
                        log.exception("command failed")

    async def run(self):
        await self.tg.send("✅ Callout bot online. Send /help for commands.")
        await asyncio.gather(
            sources.migration_stream(self.s, self.on_mint, self.status),
            self.scan_loop(),
            self.digest_loop(),
            self.command_loop(),
        )


async def main():
    C.validate()
    async with aiohttp.ClientSession() as session:
        await Bot(session).run()


if __name__ == "__main__":
    asyncio.run(main())
