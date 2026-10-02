"""Fetch Form 4 filings straight from SEC EDGAR (official, free, no key).

SEC fair-access rules: declare who you are in the User-Agent ("Name email") and stay under 10 requests
per second. SEC_USER_AGENT comes from .env; without it nothing is fetched (SEC blocks anonymous clients).

Daily index  https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/form.YYYYMMDD.idx  lists every
filing of the day; each Form 4's full submission (.txt) contains the XML and the filing date.
Parsed filings are cached in data/form4/, so a 60-day backfill is paid once (~1-2k filings per day),
and the alert loop afterwards only reads the newest days.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from apps.insiders.form4 import Txn, parse_form4

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "form4"
BASE = "https://www.sec.gov/Archives/"


class Edgar:
    def __init__(self, user_agent: str | None = None, rate: float = 8.0, opener=None):
        self.ua = user_agent or os.getenv("SEC_USER_AGENT", "")
        if not self.ua or "@" not in self.ua:
            raise SystemExit('Setează SEC_USER_AGENT="Numele Tău email@domeniu" în .env (cerință SEC).')
        self.gap, self._last = 1.0 / rate, 0.0
        self.opener = opener or urllib.request.urlopen

    def get(self, url: str) -> str:
        wait = self._last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
        with self.opener(req, timeout=30) as r:
            return r.read().decode("latin-1")

    def form4_paths(self, day: date) -> list[str]:
        q = (day.month - 1) // 3 + 1
        try:
            idx = self.get(f"{BASE}edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx")
        except Exception:  # noqa: BLE001 - weekends/holidays have no index
            return []
        return parse_index(idx)

    def filing(self, path: str) -> list[Txn]:
        key = CACHE / (path.rsplit("/", 1)[-1] + ".json")
        if key.exists():
            return [_from_json(d) for d in json.loads(key.read_text())]
        try:
            txns = parse_form4(self.get(BASE + path))
        except Exception:  # noqa: BLE001 - a malformed filing is skipped, not fatal
            txns = []
        CACHE.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps([t.as_dict() for t in txns], default=str))
        return txns

    def load(self, days: int, end: date | None = None, progress=print) -> list[Txn]:
        end = end or date.today()
        out: list[Txn] = []
        for k in range(days, -1, -1):
            d = end - timedelta(days=k)
            if d.weekday() >= 5:
                continue
            paths = self.form4_paths(d)
            for i, p in enumerate(paths):
                out += self.filing(p)
            progress(f"{d}: {len(paths)} Form 4")
        return out


def parse_index(idx: str) -> list[str]:
    """Rows of form.idx whose form type is 4 or 4/A -> unique 'edgar/data/...txt' paths."""
    seen, out = set(), []
    for line in idx.splitlines():
        if not (line.startswith("4 ") or line.startswith("4/A ")):
            continue
        path = line.split()[-1]
        if path.endswith(".txt") and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _from_json(d: dict) -> Txn:
    d = {k: v for k, v in d.items() if k != "value"}
    for k in ("filed", "trade_date"):
        d[k] = date.fromisoformat(d[k])
    return Txn(**d)
