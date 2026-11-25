"""Minimal Telegram Bot API client (sendMessage + long-polling for commands)."""
import asyncio
import logging

import aiohttp

log = logging.getLogger("telegram")


class Telegram:
    def __init__(self, session, token, chat_id):
        self.session = session
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.offset = 0

    async def send(self, text, chat_id=None):
        payload = {
            "chat_id": chat_id or self.chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for attempt in range(3):
            try:
                async with self.session.post(f"{self.base}/sendMessage", json=payload,
                                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                    data = await r.json(content_type=None)
                    if data.get("ok"):
                        return True
                    retry = (data.get("parameters") or {}).get("retry_after")
                    if retry:
                        await asyncio.sleep(retry)
                        continue
                    log.warning("sendMessage failed: %s", data.get("description"))
                    if "parse" in (data.get("description") or "").lower():
                        payload.pop("parse_mode", None)   # fall back to plain text
                        continue
                    return False
            except Exception as e:
                log.warning("sendMessage error: %s", e)
                await asyncio.sleep(2)
        return False

    async def updates(self):
        try:
            async with self.session.get(
                f"{self.base}/getUpdates",
                params={"timeout": 30, "offset": self.offset, "allowed_updates": '["message"]'},
                timeout=aiohttp.ClientTimeout(total=40),
            ) as r:
                data = await r.json(content_type=None)
        except Exception as e:
            log.debug("getUpdates error: %s", e)
            await asyncio.sleep(3)
            return []
        res = data.get("result") or []
        if res:
            self.offset = res[-1]["update_id"] + 1
        return res
