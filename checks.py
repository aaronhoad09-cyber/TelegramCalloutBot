"""Pure filter logic: post-migration, market cap, and the standard rug checks.

No network calls here, so it is easy to test.
"""
from dataclasses import dataclass, field

BONDING_CURVE_DEXES = {"pumpfun", "pump.fun", "moonshot", "launchlab", "bonk"}


@dataclass
class Result:
    passed: bool
    reasons: list = field(default_factory=list)   # why it failed
    notes: list = field(default_factory=list)     # green flags / context for the alert


# ---------------------------------------------------------------- market side

def best_pair(pairs):
    """Pick the post-migration AMM pair with the most liquidity (ignores the bonding curve)."""
    amm = [p for p in pairs or [] if (p.get("dexId") or "").lower() not in BONDING_CURVE_DEXES]
    if not amm:
        return None
    return max(amm, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))


def is_migrated(pairs):
    return best_pair(pairs) is not None


def mcap_of(pair):
    if not pair:
        return 0.0
    return float(pair.get("marketCap") or pair.get("fdv") or 0)


def market_check(pairs, cfg):
    pair = best_pair(pairs)
    if pair is None:
        return Result(False, ["not migrated yet (still on bonding curve)"])
    reasons = []
    mc = mcap_of(pair)
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    if mc < cfg.MIN_MCAP:
        reasons.append(f"mcap ${mc:,.0f} < ${cfg.MIN_MCAP:,.0f}")
    if liq < cfg.MIN_LIQUIDITY:
        reasons.append(f"liquidity ${liq:,.0f} < ${cfg.MIN_LIQUIDITY:,.0f}")
    return Result(not reasons, reasons)


# ---------------------------------------------------------------- rug side

def _pool_accounts(report):
    """Addresses/owners that belong to liquidity pools, so they don't count as whale wallets."""
    s = set()
    for m in report.get("markets") or []:
        for k in ("pubkey", "liquidityA", "liquidityB"):
            if m.get(k):
                s.add(m[k])
        for k in ("liquidityAAccount", "liquidityBAccount"):
            owner = (m.get(k) or {}).get("owner")
            if owner:
                s.add(owner)
    return s


def holder_stats(report):
    pools = _pool_accounts(report)
    holders = [
        h for h in (report.get("topHolders") or [])
        if h.get("address") not in pools and h.get("owner") not in pools
    ]
    pcts = sorted((float(h.get("pct") or 0) for h in holders), reverse=True)
    insider = sum(float(h.get("pct") or 0) for h in holders if h.get("insider"))
    return {
        "top10": sum(pcts[:10]),
        "max_single": pcts[0] if pcts else 0.0,
        "insider": insider,
    }


def creator_pct(report):
    bal = report.get("creatorBalance")
    supply = (report.get("token") or {}).get("supply")
    if bal is None or not supply:
        return None
    try:
        # creatorBalance is reported in raw units on RugCheck; normalise both the same way
        return 100.0 * float(bal) / float(supply)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def rug_check(report, cfg):
    if not report:
        return Result(False, ["RugCheck report unavailable"])
    reasons, notes = [], []

    if report.get("rugged"):
        reasons.append("flagged as RUGGED by RugCheck")

    mint_auth = report.get("mintAuthority", (report.get("token") or {}).get("mintAuthority"))
    freeze_auth = report.get("freezeAuthority", (report.get("token") or {}).get("freezeAuthority"))
    if mint_auth:
        reasons.append("mint authority NOT revoked")
    else:
        notes.append("mint revoked")
    if freeze_auth:
        reasons.append("freeze authority NOT revoked")
    else:
        notes.append("freeze revoked")

    score = report.get("score_normalised")
    if score is not None:
        if float(score) > cfg.RUG_MAX_SCORE:
            reasons.append(f"RugCheck score {score} > {cfg.RUG_MAX_SCORE:g}")
        else:
            notes.append(f"RugCheck score {score}")

    dangers = [
        r for r in (report.get("risks") or [])
        if (r.get("level") or "").lower() == "danger"
        and (r.get("name") or "").lower() not in cfg.IGNORE_RISKS
    ]
    for r in dangers:
        reasons.append(f"danger: {r.get('name')}")

    hs = holder_stats(report)
    if hs["top10"] > cfg.MAX_TOP10_PCT:
        reasons.append(f"top 10 hold {hs['top10']:.1f}% > {cfg.MAX_TOP10_PCT:g}%")
    else:
        notes.append(f"top10 {hs['top10']:.1f}%")
    if hs["max_single"] > cfg.MAX_SINGLE_HOLDER_PCT:
        reasons.append(f"one wallet holds {hs['max_single']:.1f}% > {cfg.MAX_SINGLE_HOLDER_PCT:g}%")
    if hs["insider"] > cfg.MAX_INSIDER_PCT:
        reasons.append(f"insiders hold {hs['insider']:.1f}% > {cfg.MAX_INSIDER_PCT:g}%")

    cp = creator_pct(report)
    if cp is not None and cp > cfg.MAX_CREATOR_PCT:
        reasons.append(f"dev holds {cp:.1f}% > {cfg.MAX_CREATOR_PCT:g}%")

    total = report.get("totalHolders")
    if total is not None:
        if int(total) < cfg.MIN_HOLDERS:
            reasons.append(f"only {total} holders < {cfg.MIN_HOLDERS}")
        else:
            notes.append(f"{int(total):,} holders")

    return Result(not reasons, reasons, notes)
