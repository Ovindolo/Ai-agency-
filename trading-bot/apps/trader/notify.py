"""Telegram notifications (Romanian, user-facing). Falls back to stdout without a token. Never sends secrets."""
from __future__ import annotations

import json
import os
import urllib.request


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None, echo: bool = True):
        self.token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_ADMIN_ID", "")
        self.echo = echo
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        if self.echo:
            print(f"[telegram] {text}")
        if not (self.token and self.chat_id):
            return
        try:
            body = json.dumps({"chat_id": self.chat_id, "text": text}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendMessage", data=body,
                                         headers={"content-type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as exc:          # a failed alert must never stop trading logic
            print(f"[telegram] send failed: {type(exc).__name__}")
