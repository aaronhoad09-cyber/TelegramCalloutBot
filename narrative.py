"""Narrative overview: what the coin is about and whether its theme is trending.

Always produces a rule-based overview. If ANTHROPIC_API_KEY is set, also asks Claude
for a short plain-English write-up (falls back silently if that call fails).
"""
import re

# extra keywords per DexScreener meta slug, on top of the meta's own name
META_HINTS = {
    "cat": ["cat", "kitty", "kitten", "meow", "pspsps", "neko"],
    "dog": ["dog", "doge", "shib", "inu", "puppy", "pup", "woof", "wif"],
    "ai": ["ai", "agent", "gpt", "llm", "neural", "bot", "agi"],
    "trump": ["trump", "maga", "donald"],
    "chinese": ["chinese", "china", "中"],
    "tiktok": ["tiktok"],
    "brainrot": ["brainrot", "skibidi", "rizz", "sigma", "gyatt"],
    "stonks": ["stonk", "stock", "wallstreet", "ticker"],
    "frog": ["frog", "pepe", "toad"],
}

WORD_RE = re.compile(r"[a-z0-9一-鿿]+")


def _words(*texts):
    out = set()
    for t in texts:
        out.update(WORD_RE.findall((t or "").lower()))
    return out


def match_metas(name, symbol, description, metas):
    """Return trending DexScreener metas whose theme matches this coin."""
    words = _words(name, symbol, description)
    blob = " ".join([(name or ""), (symbol or ""), (description or "")]).lower()
    hits = []
    for m in metas or []:
        slug = (m.get("slug") or "").lower()
        keys = set(_words(m.get("name"))) | set(META_HINTS.get(slug, []))
        keys = {k for k in keys if len(k) >= 2}
        if any((k in words) if k.isascii() else (k in blob) for k in keys):
            hits.append(m)
    return hits


def _pct(x):
    try:
        return f"{float(x):+.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def rule_based(token, metas_hit, socials):
    """Returns a list of lines: [description quote (optional), theme line, socials line]."""
    lines = []
    desc = (token.get("description") or "").strip().replace("\n", " ")
    if desc:
        lines.append(f"“{desc[:220]}{'…' if len(desc) > 220 else ''}”")
    if metas_hit:
        parts = []
        for m in metas_hit[:3]:
            icon = (m.get("icon") or {}).get("value", "")
            ch = (m.get("marketCapChange") or {}).get("h24")
            parts.append(f"{icon} {m.get('name')} ({_pct(ch)} 24h)".strip())
        lines.append("Trending theme: " + ", ".join(parts))
    else:
        lines.append("Theme: no match with today's trending metas")
    lines.append("Socials: " + (", ".join(socials) if socials else "none listed ⚠️"))
    return lines


PROMPT = """You write the "narrative overview" section of a Solana memecoin alert.
In 2-3 short sentences: what is this coin's meme/story, which current trend it rides (if any),
and anything notable about community signals. Plain text, no hype, no price predictions,
no buy/sell advice. If information is thin, say the narrative is unclear.

Name: {name} (${symbol})
Description: {description}
Socials: {socials}
Matching trending metas: {metas}
All trending metas right now: {all_metas}
Market: mcap ${mcap:,.0f}, 1h change {h1}, 24h volume ${vol:,.0f}, 1h buys/sells {buys}/{sells}
"""


async def ai_overview(session, cfg, token, metas_hit, all_metas, socials, pair):
    if not cfg.ANTHROPIC_API_KEY:
        return None
    txns = ((pair or {}).get("txns") or {}).get("h1") or {}
    prompt = PROMPT.format(
        name=token.get("name"), symbol=token.get("symbol"),
        description=(token.get("description") or "none")[:600],
        socials=", ".join(socials) or "none",
        metas=", ".join(m.get("name", "") for m in metas_hit) or "none",
        all_metas=", ".join(m.get("name", "") for m in (all_metas or [])[:15]),
        mcap=float((pair or {}).get("marketCap") or 0),
        h1=_pct(((pair or {}).get("priceChange") or {}).get("h1")),
        vol=float(((pair or {}).get("volume") or {}).get("h24") or 0),
        buys=txns.get("buys", "?"), sells=txns.get("sells", "?"),
    )
    try:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": cfg.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": cfg.ANTHROPIC_MODEL, "max_tokens": 220,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        ) as r:
            if r.status != 200:
                return None
            data = await r.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip() or None
    except Exception:
        return None
