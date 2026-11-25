"""All settings come from environment variables (set them in Railway's Variables tab)."""
import os


def _f(name, default):
    v = os.getenv(name)
    return float(v) if v not in (None, "") else float(default)


def _i(name, default):
    return int(_f(name, default))


def _list(name, default=""):
    v = os.getenv(name, default)
    return [x.strip().lower() for x in v.split(",") if x.strip()]


class Config:
    # --- required ---
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- optional: better narrative write-ups ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

    # --- callout filters ---
    MIN_MCAP = _f("MIN_MCAP", 75_000)                 # USD market cap floor
    MIN_LIQUIDITY = _f("MIN_LIQUIDITY", 15_000)       # USD liquidity floor
    WATCH_HOURS = _f("WATCH_HOURS", 24)               # keep watching a migrated coin this long

    # --- rug-check standard ---
    RUG_MAX_SCORE = _f("RUG_MAX_SCORE", 50)           # RugCheck normalised score (0-100, lower = safer)
    MAX_TOP10_PCT = _f("MAX_TOP10_PCT", 30)           # top 10 wallets (excl. LP pools) combined
    MAX_SINGLE_HOLDER_PCT = _f("MAX_SINGLE_HOLDER_PCT", 10)
    MAX_INSIDER_PCT = _f("MAX_INSIDER_PCT", 10)       # holders RugCheck flags as insiders
    MAX_CREATOR_PCT = _f("MAX_CREATOR_PCT", 5)
    MIN_HOLDERS = _i("MIN_HOLDERS", 150)
    # RugCheck "danger" risks to ignore (comma-separated, case-insensitive), e.g. "low liquidity"
    IGNORE_RISKS = _list("IGNORE_RISKS")

    # --- timing ---
    SCAN_INTERVAL_SEC = _i("SCAN_INTERVAL_SEC", 60)
    RUG_RECHECK_MIN = _f("RUG_RECHECK_MIN", 10)       # re-run rug check on a failing coin after N minutes
    DIGEST_HOURS = _f("DIGEST_HOURS", 6)              # market-trend digest; 0 = off

    STATE_FILE = os.getenv("STATE_FILE", "state.json")

    @classmethod
    def validate(cls):
        missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not getattr(cls, k)]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
