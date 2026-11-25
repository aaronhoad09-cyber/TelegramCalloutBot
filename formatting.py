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
