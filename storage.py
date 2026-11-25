"""Tiny JSON-file state: the watchlist and the coins already called out."""
import json
import os
import time


class State:
    def __init__(self, path):
        self.path = path
        self.watch = {}       # mint -> {"added": ts, "source": str, "rug_checked": ts, "rug_fail": [..]}
        self.alerted = {}     # mint -> ts
        self.paused = False
        self.last_digest = 0  # unix time of the last scheduled digest
        self.alerts = {}      # mint -> [{"target": usd, "dir": "above"|"below", "symbol": str}]
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    d = json.load(f)
                self.watch = d.get("watch", {})
                self.alerted = d.get("alerted", {})
                self.paused = d.get("paused", False)
                self.alerts = d.get("alerts", {})
                self.last_digest = d.get("last_digest", 0)
            except (OSError, ValueError):
                pass

    def save(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"watch": self.watch, "alerted": self.alerted, "paused": self.paused,
                       "alerts": self.alerts, "last_digest": self.last_digest}, f)
        os.replace(tmp, self.path)

    def add(self, mint, source):
        if mint in self.watch or mint in self.alerted:
            return False
        self.watch[mint] = {"added": time.time(), "source": source}
        return True

    def prune(self, watch_hours, max_size=1500):
        now = time.time()
        self.watch = {m: w for m, w in self.watch.items() if now - w["added"] < watch_hours * 3600}
        if len(self.watch) > max_size:   # keep the newest
            keep = sorted(self.watch.items(), key=lambda kv: kv[1]["added"], reverse=True)[:max_size]
            self.watch = dict(keep)
        # forget alerts older than 7 days
        self.alerted = {m: t for m, t in self.alerted.items() if now - t < 7 * 86400}
