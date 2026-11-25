"""Builds the Telegram messages (HTML parse mode)."""
from html import escape


def money(x):
    x = float(x or 0)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.2f}{unit}"
    return f"${x:,.0f}"


def pct(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    return f"{'🟢' if v >= 0 else '🔴'} {v:+.1f}%"


def socials_of(pair):
    info = (pair or {}).get("info") or {}
    out = []
    for s in info.get("socials") or []:
        t = (s.get("type") or "").lower()
        out.append({"twitter": "X", "telegram": "Telegram", "discord": "Discord"}.get(t, t.title()))
    if info.get("websites"):
        out.append("Website")
    return out


def social_links(pair):
    info = (pair or {}).get("info") or {}
    links = []
    for s in info.get("socials") or []:
        t = (s.get("type") or "link").lower()
        label = {"twitter": "X", "telegram": "TG"}.get(t, t.title())
        if s.get("url"):
            links.append(f'<a href="{escape(s["url"], quote=True)}">{escape(label)}</a>')
    for w in (info.get("websites") or [])[:1]:
        if w.get("url"):
            links.append(f'<a href="{escape(w["url"], quote=True)}">Web</a>')
    return links


def age_str(ms_created, now_ms):
    if not ms_created:
        return "n/a"
    mins = max(0, (now_ms - ms_created) / 60000)
    if mins < 60:
        return f"{mins:.0f}m"
    if mins < 48 * 60:
        return f"{mins / 60:.1f}h"
    return f"{mins / 1440:.0f}d"


def callout(mint, pair, rug, narrative_lines, ai_text, now_ms):
    base = pair.get("baseToken") or {}
    name, sym = escape(base.get("name") or "?"), escape(base.get("symbol") or "?")
    liq = (pair.get("liquidity") or {}).get("usd")
    vol = pair.get("volume") or {}
    ch = pair.get("priceChange") or {}
    tx = (pair.get("txns") or {}).get("h1") or {}
    dex = escape((pair.get("dexId") or "").title())

    lines = [
        f"🚨 <b>{name}</b> (${sym}) — post-migration callout",
        f"<code>{escape(mint)}</code>",
        "",
        f"💰 MC <b>{money(pair.get('marketCap') or pair.get('fdv'))}</b> · Liq {money(liq)} · {dex}",
        f"📈 5m {pct(ch.get('m5'))} · 1h {pct(ch.get('h1'))} · 24h {pct(ch.get('h24'))}",
        f"🔁 Vol 1h {money(vol.get('h1'))} · 24h {money(vol.get('h24'))} · 1h buys/sells {tx.get('buys', '?')}/{tx.get('sells', '?')}",
        f"⏱ Pair age {age_str(pair.get('pairCreatedAt'), now_ms)}",
        "",
        "🛡 <b>Rug checks: PASSED</b>",
        "✅ " + " · ".join(escape(n) for n in rug.notes),
        "",
        "🧠 <b>Narrative</b>",
    ]
    if ai_text:
        # AI summary replaces the raw description quote; keep the theme + socials lines
        lines.append(escape(ai_text))
        lines += [escape(l) for l in narrative_lines[-2:]]
    else:
        lines += [escape(l) for l in narrative_lines]
    links = [
        f'<a href="https://dexscreener.com/solana/{escape(pair.get("pairAddress") or mint)}">DexScreener</a>',
        f'<a href="https://rugcheck.xyz/tokens/{escape(mint)}">RugCheck</a>',
        f'<a href="https://pump.fun/coin/{escape(mint)}">Pump</a>',
        f'<a href="https://solscan.io/token/{escape(mint)}">Solscan</a>',
    ] + social_links(pair)
    lines += ["", " | ".join(links), "<i>Not financial advice — scanner output, DYOR.</i>"]
    return "\n".join(lines)


def check_report(mint, pair, market, rug):
    base = (pair or {}).get("baseToken") or {}
    head = f"🔎 <b>{escape(base.get('name') or mint[:6])}</b> (${escape(base.get('symbol') or '?')})"
    lines = [head, f"<code>{escape(mint)}</code>"]
    if pair:
        lines.append(f"MC {money(pair.get('marketCap') or pair.get('fdv'))} · Liq {money((pair.get('liquidity') or {}).get('usd'))}")
    lines.append("")
    lines.append("Market: " + ("✅ pass" if market.passed else "❌ " + "; ".join(market.reasons)))
    if rug is not None:
        lines.append("Rug checks: " + ("✅ pass" if rug.passed else "❌ " + "; ".join(escape(r) for r in rug.reasons)))
        if rug.notes:
            lines.append("Notes: " + " · ".join(escape(n) for n in rug.notes))
    return "\n".join(lines)


def digest(metas, movers):
    lines = ["📊 <b>Market trend digest</b>", "", "<b>Hot metas (24h mcap change)</b>"]
    ranked = sorted(metas or [], key=lambda m: ((m.get("marketCapChange") or {}).get("h24") or 0), reverse=True)
    for m in ranked[:6]:
        icon = (m.get("icon") or {}).get("value", "")
        lines.append(f"{icon} {escape(m.get('name', ''))}: {pct((m.get('marketCapChange') or {}).get('h24'))} · vol {money(m.get('volume'))}")
    if movers:
        lines += ["", "<b>Top watched post-migration coins (1h)</b>"]
        for p in movers[:5]:
            b = p.get("baseToken") or {}
            lines.append(f"${escape(b.get('symbol') or '?')}: MC {money(p.get('marketCap'))} · 1h {pct((p.get('priceChange') or {}).get('h1'))}")
    return "\n".join(lines)


# ---------------------------------------------------------------- watchlist & alerts

def parse_money(s):
    """'500k' -> 500000, '1.2m' -> 1200000, '$2B' -> 2e9, '750,000' -> 750000."""
    s = (s or "").strip().lower().replace("$", "").replace(",", "")
    mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(s[-1:], 1)
    if mult != 1:
        s = s[:-1]
    try:
        v = float(s) * mult
    except ValueError:
        return None
    return v if v > 0 else None


def _ago(ts, now):
    h = (now - ts) / 3600
    return f"{h * 60:.0f}m" if h < 1 else f"{h:.1f}h"


def watchlist(watch, last_pairs, now, limit=15):
    if not watch:
        return "👀 Watchlist is empty. Add a coin with /watch &lt;CA&gt;."
    manual = [(m, w) for m, w in watch.items() if w.get("source") == "manual"]
    auto = [(m, w) for m, w in watch.items() if w.get("source") != "manual"]

    def row(m, w):
        p = last_pairs.get(m) or {}
        sym = escape((p.get("baseToken") or {}).get("symbol") or m[:6] + "…")
        mc = money(p.get("marketCap") or p.get("fdv")) if p else "not migrated / no data"
        line = f"• <b>${sym}</b> · MC {mc} · added {_ago(w['added'], now)} ago\n  <code>{escape(m)}</code>"
        if w.get("rug_fail"):
            line += "\n  ❌ " + escape("; ".join(w["rug_fail"][:2]))
        return line

    lines = [f"👀 <b>Watchlist</b> — {len(watch)} coins"]
    if manual:
        lines += ["", f"<b>Added by you ({len(manual)})</b>"] + [row(m, w) for m, w in manual]
    if auto:
        auto.sort(key=lambda mw: float((last_pairs.get(mw[0]) or {}).get("marketCap") or 0), reverse=True)
        lines += ["", f"<b>Auto from migrations ({len(auto)}) — top {min(limit, len(auto))} by MC</b>"]
        lines += [row(m, w) for m, w in auto[:limit]]
    return "\n".join(lines)


def alert_list(alerts):
    if not alerts:
        return "⏰ No price alerts. Set one with /alert &lt;CA&gt; 500k"
    lines = ["⏰ <b>Price alerts</b>"]
    for m, targets in alerts.items():
        for a in targets:
            arrow = "↑ above" if a["dir"] == "above" else "↓ below"
            lines.append(f"• ${escape(a.get('symbol') or m[:6])} {arrow} {money(a['target'])}\n  <code>{escape(m)}</code>")
    lines.append("\nRemove with /alert &lt;CA&gt; off")
    return "\n".join(lines)


def alert_hit(mint, pair, a):
    base = (pair or {}).get("baseToken") or {}
    sym = escape(base.get("symbol") or a.get("symbol") or "?")
    verb = "is above" if a["dir"] == "above" else "dropped below"
    ch = (pair.get("priceChange") or {})
    return (f"⏰ <b>${sym} {verb} {money(a['target'])}</b>\n"
            f"MC now <b>{money(pair.get('marketCap') or pair.get('fdv'))}</b> · "
            f"Liq {money((pair.get('liquidity') or {}).get('usd'))} · 1h {pct(ch.get('h1'))}\n"
            f"<code>{escape(mint)}</code>\n"
            f'<a href="https://dexscreener.com/solana/{escape(pair.get("pairAddress") or mint)}">DexScreener</a>')
