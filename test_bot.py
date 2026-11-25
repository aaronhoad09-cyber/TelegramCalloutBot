"""Offline tests: filters, narrative, formatting, and one full scan with fake APIs.

Run with:  python -m pytest -q
"""
import asyncio
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import aiohttp  # noqa: F401
except ImportError:  # lets tests run without network libs installed
    fake = types.ModuleType("aiohttp")
    fake.ClientTimeout = lambda **k: None
    fake.WSMsgType = types.SimpleNamespace(TEXT=1, CLOSED=2, ERROR=3)
    sys.modules["aiohttp"] = fake

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import checks  # noqa: E402
import formatting  # noqa: E402
import narrative  # noqa: E402
import sources  # noqa: E402
from config import Config as C  # noqa: E402

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHpump"  # 44 chars
POOL = "PoolPubkey1111111111111111111111111111111111"


def pair(dex="pumpswap", mc=120_000, liq=30_000):
    return {
        "dexId": dex, "pairAddress": "PairAddr", "marketCap": mc,
        "baseToken": {"address": MINT, "name": "Sleepy Cat", "symbol": "SLEEPY"},
        "liquidity": {"usd": liq}, "volume": {"h1": 50_000, "h24": 400_000},
        "priceChange": {"m5": 3.2, "h1": 25, "h24": 140}, "txns": {"h1": {"buys": 420, "sells": 210}},
        "pairCreatedAt": 1_700_000_000_000,
        "info": {"socials": [{"type": "twitter", "url": "https://x.com/sleepy"}],
                 "websites": [{"url": "https://sleepy.cat"}]},
    }


def report(**over):
    r = {
        "mintAuthority": None, "freezeAuthority": None, "rugged": False,
        "score_normalised": 12, "totalHolders": 900, "creatorBalance": 0,
        "token": {"supply": 1_000_000_000_000_000, "decimals": 6},
        "fileMeta": {"description": "the sleepiest cat on solana"},
        "risks": [{"name": "Low amount of LP Providers", "level": "warn"}],
        "markets": [{"pubkey": POOL, "liquidityAAccount": {"owner": POOL}}],
        "topHolders": [{"address": "LPvault", "owner": POOL, "pct": 18.0}]
        + [{"address": f"w{i}", "owner": f"o{i}", "pct": 2.0, "insider": False} for i in range(12)],
    }
    r.update(over)
    return r


# ---------------------------------------------------------------- filters

def test_bonding_curve_is_not_migrated():
    res = checks.market_check([pair(dex="pumpfun")], C)
    assert not res.passed and "not migrated" in res.reasons[0]


def test_mcap_threshold():
    assert checks.market_check([pair(mc=120_000)], C).passed
    assert not checks.market_check([pair(mc=60_000)], C).passed


def test_best_pair_skips_curve():
    p = checks.best_pair([pair(dex="pumpfun", liq=99_999), pair(dex="pumpswap", liq=20_000)])
    assert p["dexId"] == "pumpswap"


def test_clean_token_passes_and_pool_is_excluded():
    res = checks.rug_check(report(), C)
    assert res.passed, res.reasons
    assert any("top10 20.0%" in n for n in res.notes)   # 18% LP vault not counted


def test_each_rug_rule_fails():
    bad = [
        report(mintAuthority="Abc"),
        report(freezeAuthority="Abc"),
        report(rugged=True),
        report(score_normalised=80),
        report(risks=[{"name": "Single holder ownership", "level": "danger"}]),
        report(totalHolders=40),
        report(topHolders=[{"address": "whale", "owner": "w", "pct": 25.0}]),
        report(topHolders=[{"address": f"i{i}", "owner": "x", "pct": 4.0, "insider": True} for i in range(4)]),
        report(creatorBalance=80_000_000_000_000),
    ]
    for r in bad:
        assert not checks.rug_check(r, C).passed


def test_missing_report_fails():
    assert not checks.rug_check(None, C).passed


# ---------------------------------------------------------------- narrative / format

METAS = [{"name": "Cat", "slug": "cat", "icon": {"value": "🐈"}, "marketCapChange": {"h24": 12.0}, "volume": 1e7},
         {"name": "AI", "slug": "ai", "icon": {"value": "🤖"}, "marketCapChange": {"h24": -3.0}, "volume": 5e6}]


def test_meta_matching():
    hit = narrative.match_metas("Sleepy Cat", "SLEEPY", "zzz", METAS)
    assert [m["slug"] for m in hit] == ["cat"]
    assert narrative.match_metas("Bob", "BOB", "", METAS) == []
    # 'ai' must match as a word only, not inside 'rain'
    assert narrative.match_metas("Rain", "RAIN", "", METAS) == []


def test_callout_message():
    rug = checks.rug_check(report(), C)
    lines = narrative.rule_based({"description": "the sleepiest cat"}, METAS[:1], ["X", "Website"])
    msg = formatting.callout(MINT, pair(), rug, lines, None, 1_700_003_600_000)
    for s in ("Sleepy Cat", "$120.00K", "Rug checks: PASSED", "Trending theme", "🐈 Cat", "rugcheck.xyz", "1.0h"):
        assert s in msg, s
    ai_msg = formatting.callout(MINT, pair(), rug, lines, "A cat coin <riding> the cat meta.", 0)
    assert "&lt;riding&gt;" in ai_msg and "sleepiest" not in ai_msg


def test_parse_migration():
    assert sources.parse_migration('{"signature":"s","mint":"%s","txType":"migrate"}' % MINT) == MINT
    assert sources.parse_migration('{"message":"Successfully subscribed"}') is None
    assert sources.parse_migration("not json") is None


# ---------------------------------------------------------------- end-to-end scan

def test_full_scan(tmp_path, monkeypatch):
    import bot as botmod

    sent = []

    class FakeTG:
        async def send(self, text, chat_id=None):
            sent.append(text)
            return True

    async def fake_pairs(session, mints):
        return {MINT: [pair(dex="pumpfun"), pair()], "lowcap": [pair(mc=40_000)]}

    async def fake_report(session, mint):
        return report()

    async def fake_metas(session):
        return METAS

    async def fake_profiles(session):
        return []

    monkeypatch.setattr(sources, "dex_pairs_for", fake_pairs)
    monkeypatch.setattr(sources, "rug_report", fake_report)
    monkeypatch.setattr(sources, "trending_metas", fake_metas)
    monkeypatch.setattr(sources, "latest_profiles", fake_profiles)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(botmod.asyncio, "sleep", lambda *_: real_sleep(0))
    monkeypatch.setattr(C, "STATE_FILE", str(tmp_path / "state.json"))

    b = botmod.Bot(session=None)
    b.tg = FakeTG()

    async def go():
        await b.on_mint(MINT, "migration")
        await b.on_mint("lowcap", "migration")
        await b.scan_once()
        await b.scan_once()   # must not alert twice
        await b.send_digest()

    asyncio.run(go())
    callouts = [m for m in sent if "callout" in m]
    assert len(callouts) == 1 and "SLEEPY" in callouts[0]
    assert "lowcap" in b.state.watch and MINT not in b.state.watch
    assert "Market trend digest" in sent[-1]


# ---------------------------------------------------------------- new commands

def test_parse_money():
    assert formatting.parse_money("500k") == 500_000
    assert formatting.parse_money("$1.2M") == 1_200_000
    assert formatting.parse_money("750,000") == 750_000
    assert formatting.parse_money("2b") == 2e9
    assert formatting.parse_money("abc") is None and formatting.parse_money("0") is None


def test_commands_and_alerts(tmp_path, monkeypatch):
    import bot as botmod

    sent = []
    mc = {"v": 120_000}

    class FakeTG:
        async def send(self, text, chat_id=None):
            sent.append(text)
            return True

    async def fake_pairs(session, mints):
        return {m: [pair(mc=mc["v"])] for m in mints}

    async def none(*a, **k):
        return []

    monkeypatch.setattr(sources, "dex_pairs_for", fake_pairs)
    monkeypatch.setattr(sources, "latest_profiles", none)
    monkeypatch.setattr(sources, "rug_report", lambda *a: none())   # rug fails -> no callout
    monkeypatch.setattr(C, "STATE_FILE", str(tmp_path / "state.json"))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(botmod.asyncio, "sleep", lambda *_: real_sleep(0))

    b = botmod.Bot(session=None)
    b.tg = FakeTG()

    async def go():
        await b.handle(f"/watch {MINT}", "1")
        await b.scan_once()
        await b.on_mint("AutoMigratedCoin1111111111111111111111pump", "migration")
        await b.handle("/watchlist", "1")
        assert "Your watchlist</b> — 1 coin" in sent[-1] and "SLEEPY" in sent[-1]
        assert "RugCheck report unavailable" in sent[-1] and "AutoMigrated" not in sent[-1]
        await b.handle(f"/unwatch {MINT}", "1")
        assert MINT not in b.state.watch and "Removed" in sent[-1]

        await b.handle(f"/alert {MINT} 200k", "1")
        assert "rises above $200.00K" in sent[-1]
        await b.handle(f"/alert {MINT} 50k", "1")
        assert "falls below $50.00K" in sent[-1]
        await b.handle("/alert", "1")
        assert "↑ above" in sent[-1] and "↓ below" in sent[-1]
        await b.handle(f"/alert {MINT} lots", "1")
        assert "Couldn't read" in sent[-1]

        n = len(sent)
        await b.scan_once()                      # 120k: nothing fires
        assert len(sent) == n
        mc["v"] = 250_000
        await b.scan_once()                      # up alert fires once
        assert "is above $200.00K" in sent[-1] and len(b.state.alerts[MINT]) == 1
        await b.scan_once()
        mc["v"] = 40_000
        await b.scan_once()                      # down alert fires, nothing left
        assert "dropped below $50.00K" in sent[-1] and MINT not in b.state.alerts

        await b.handle(f"/alert {MINT} 1m", "1")
        await b.handle(f"/alert {MINT} off", "1")
        assert MINT not in b.state.alerts and "removed" in sent[-1]

    asyncio.run(go())
    # alerts survive a restart
    b.state.alerts = {MINT: [{"target": 1, "dir": "above", "symbol": "S"}]}
    b.state.save()
    from storage import State
    assert State(C.STATE_FILE).alerts[MINT][0]["target"] == 1


def test_digest_schedule_survives_restart(tmp_path, monkeypatch):
    import bot as botmod
    from storage import State
    monkeypatch.setattr(C, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(C, "DIGEST_HOURS", 6)
    t0 = 1_000_000.0

    b = botmod.Bot(session=None)
    assert not b.digest_due(t0)                 # fresh start: no digest, timer starts
    assert not b.digest_due(t0 + 3 * 3600)

    b2 = botmod.Bot(session=None)               # "redeploy" 3h in: still nothing
    assert State(C.STATE_FILE).last_digest == t0
    assert not b2.digest_due(t0 + 3 * 3600 + 120)
    assert b2.digest_due(t0 + 6 * 3600)         # fires on schedule

    monkeypatch.setattr(C, "DIGEST_HOURS", 0)
    assert not b2.digest_due(t0 + 99 * 3600)    # 0 = off


# ---------------------------------------------------------------- v1.4

GECKO_SAMPLE = {"data": [
    {"attributes": {"pool_created_at": "2026-11-25T06:00:00Z"},
     "relationships": {"dex": {"data": {"id": "pumpswap"}},
                       "base_token": {"data": {"id": f"solana_{MINT}"}},
                       "quote_token": {"data": {"id": "solana_So11111111111111111111111111111111111111112"}}}},
    {"attributes": {"pool_created_at": "2026-11-25T06:00:00Z"},
     "relationships": {"dex": {"data": {"id": "pump-fun"}},
                       "base_token": {"data": {"id": "solana_CurveCoin111111111111111111111111111pump"}}}},
    {"attributes": {"pool_created_at": None},
     "relationships": {"dex": {"data": {"id": "pumpswap"}},
                       "base_token": {"data": {"id": "solana_So11111111111111111111111111111111111111112"}},
                       "quote_token": {"data": {"id": "solana_FlippedCoin1111111111111111111111111pump"}}}},
]}


def test_parse_gecko_pools():
    got = sources.parse_gecko_pools(GECKO_SAMPLE)
    assert [m for m, _ in got] == [MINT, "FlippedCoin1111111111111111111111111pump"]
    assert got[0][1] == 1795586400.0 and got[1][1] is None


def test_dex_batches_of_10(monkeypatch):
    calls = []

    async def fake_get(session, url, timeout=20):
        calls.append(url)
        return []
    monkeypatch.setattr(sources, "get_json", fake_get)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(sources.asyncio, "sleep", lambda *_: real_sleep(0))
    asyncio.run(sources.dex_pairs_for(None, [f"m{i}" for i in range(25)]))
    assert len(calls) == 3


def test_funnel_and_stats(tmp_path, monkeypatch):
    import bot as botmod
    sent = []

    class FakeTG:
        async def send(self, text, chat_id=None):
            sent.append(text)
            return True

    async def fake_pairs(session, mints):
        return {"curve": [pair(dex="pumpfun")], "small": [pair(mc=30_000)],
                "thin": [pair(liq=2_000)], "whale": [pair()]}

    async def whale_report(session, mint):
        return report(topHolders=[{"address": "x", "owner": "y", "pct": 45.0}])

    async def none(*a, **k):
        return []

    monkeypatch.setattr(sources, "dex_pairs_for", fake_pairs)
    monkeypatch.setattr(sources, "rug_report", whale_report)
    monkeypatch.setattr(sources, "latest_profiles", none)
    monkeypatch.setattr(sources, "gecko_pumpswap_coins", none)
    monkeypatch.setattr(C, "STATE_FILE", str(tmp_path / "state.json"))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(botmod.asyncio, "sleep", lambda *_: real_sleep(0))

    b = botmod.Bot(session=None)
    b.tg = FakeTG()

    async def go():
        for m in ("curve", "small", "thin", "whale", "ghost"):
            await b.on_mint(m, "migration")
        await b.scan_once()
        await b.handle("/stats", "1")

    asyncio.run(go())
    f = b.funnel
    assert (f["watched"], f["no_dex_data"], f["on_bonding_curve"], f["below_mcap"],
            f["low_liquidity"], f["rug_failed"]) == (5, 1, 1, 1, 1, 1)
    assert "top 10 hold too much: 1" in sent[-1] and "single whale wallet: 1" in sent[-1]


def test_gecko_discovery_skips_old(tmp_path, monkeypatch):
    import bot as botmod
    import time as _t
    now = _t.time()

    async def fake_gecko(session):
        return [("fresh", now - 3600), ("old", now - 48 * 3600), ("unknown", None)]

    async def none(*a, **k):
        return []
    monkeypatch.setattr(sources, "gecko_pumpswap_coins", fake_gecko)
    monkeypatch.setattr(sources, "latest_profiles", none)
    monkeypatch.setattr(C, "STATE_FILE", str(tmp_path / "state.json"))
    b = botmod.Bot(session=None)
    asyncio.run(b.discover())
    assert set(b.state.watch) == {"fresh", "unknown"}
    assert abs(b.state.watch["fresh"]["added"] - (now - 3600)) < 1
