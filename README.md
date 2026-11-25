# Solana Memecoin Callout Bot

A private Telegram bot that calls out pump.fun coins **after they migrate**, once they reach a
**market cap of $75K or more** and **pass a standard set of rug checks**. Each callout includes a **narrative overview**.
Every 6 hours it also sends a short market-trend digest.

## What a callout means

| Filter | How it's checked |
|---|---|
| Post-migration | The coin is caught on the PumpPortal migration feed (pump.fun → PumpSwap) and must have a live AMM pair on DexScreener. A coin still on the bonding curve never passes. |
| MC ≥ $75K | DexScreener market cap. Each migrated coin is watched for 24h, so it gets called out if it crosses $75K later. |
| Liquidity ≥ $15K | DexScreener pool liquidity. |
| Rug checks | Mint authority and freeze authority are revoked. RugCheck has not flagged the coin as rugged and reports no "danger" risks. RugCheck score is 50 or below. The top 10 wallets hold 30% or less, with no single wallet above 10% (liquidity pools aren't counted). Insiders hold 10% or less and the dev holds 5% or less. There are at least 150 holders. |
| Narrative | The coin's own description, any match with DexScreener's trending "metas" (Cat, AI, Trump, …) and its socials. If you add an Anthropic API key, the bot also writes a 2–3 sentence summary. |

A coin that fails the rug checks is checked again every 10 minutes while it's being watched. Holder concentration often improves after migration, so a later check can pass. Each coin is called out at most once.

## Setup (about 15 minutes)

### 1. Create the Telegram bot
1. In Telegram, message **@BotFather**, send `/newbot` and follow the prompts.
2. Copy the **token** it gives you. Keep it secret.
3. Open your new bot and press **Start**. A bot can't message you until you've done this.
4. Message **@userinfobot** to get your numeric **chat ID**.

### 2. Put the code on GitHub
1. Create a free account at github.com and click **New repository**. Make it **Private** and name it something like `memecoin-bot`.
2. Click **uploading an existing file** and drag in everything from this folder, including `railway.json`, `requirements.txt` and `.python-version`.
3. Click **Commit changes**.

### 3. Deploy on Railway
1. Sign up at railway.com with your GitHub account. The Hobby plan is $5/month, and this bot fits within the usage that's included.
2. Click **New Project → Deploy from GitHub repo** and pick your repo.
3. Open the service, go to **Variables** and add:
   - `TELEGRAM_BOT_TOKEN`: your token
   - `TELEGRAM_CHAT_ID`: your chat ID
   - Optional: `ANTHROPIC_API_KEY` for AI narrative summaries, which cost a fraction of a cent each
4. Recommended: right-click the service and choose **Attach volume** with mount path `/data`, then add the variable `STATE_FILE=/data/state.json`. The bot will then remember its watchlist and past callouts when you redeploy.
5. Railway deploys automatically. Within about a minute you should get "✅ Callout bot online" in Telegram.

If nothing arrives, open the service's **Deployments → View logs**. The usual cause is a wrong token or chat ID, or not having pressed Start on the bot.

## Commands
- `/status`: migration stream status, how many coins are being watched, and the number of callouts
- `/check <mint>`: run every filter on any coin and see which checks it passes or fails
- `/watch <mint>`: add a coin to the watchlist yourself
- `/digest`: send the trend digest now
- `/settings`: show the current filters
- `/pause`, `/resume`

## Tuning
Every threshold is an environment variable. `.env.example` lists them all with their defaults. Change one in Railway → Variables and the service restarts with the new value. Examples:
- Fewer, safer calls: `MIN_MCAP=150000`, `MAX_TOP10_PCT=25`, `MIN_HOLDERS=300`
- More calls: `RUG_MAX_SCORE=60`, `MIN_HOLDERS=100`
- No digest: `DIGEST_HOURS=0`

## Data sources (all free, no keys)
- **PumpPortal** websocket (`subscribeMigration`): the main feed of new migrations
- **DexScreener** API: price, market cap, liquidity, volume, socials and trending metas. Its latest token profiles are a backup discovery feed.
- **RugCheck** API: authorities, risks, holders and score

## Running locally (optional)
```
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
python bot.py
```
Tests: `pip install pytest && python -m pytest -q`

---
*This is a scanner, not advice. Even coins that pass every check can still rug or go to zero. Do your own research.*
