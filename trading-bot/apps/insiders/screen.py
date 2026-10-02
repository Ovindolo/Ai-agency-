"""Insider screens on parsed Form 4 rows. Research only: nothing here places a trade.

cluster   3+ DISTINCT insiders with open-market purchases (code P, acquired) in the window;
          option exercises (M), grants (A), tax withholding (F), gifts (G) and sales (S) excluded.
batch     looks like a comp plan rather than conviction: same filing date, similar dollar sizes,
          mostly VP-level titles, or Rule 10b5-1 pre-scheduled trades. 2 of these 4 -> flagged.
outlier   inside a cluster: a buy >= 3x the median of the others, a buy that at least doubles the
          insider's holding, or a CEO/CFO/chair/director buying among VPs.
rising    early signal: < 5 distinct buyers in 90 days AND more distinct buyers in the last 30 days
          than in the 60 before. 'crowded' = 5+ distinct buyers already.

Evidence research: cluster buys earn more than solitary ones (Alldredge & Blank 2019, J. Financial
Research); routine insiders carry no information, opportunistic ones do (Cohen, Malloy & Pomorski 2012,
J. Finance). Neither is a guarantee, and both are decades of US small/mid caps, not a promise for one name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median, pstdev

import numpy as np

from apps.insiders.form4 import Txn

TOP = re.compile(r"\b(ceo|cfo|coo|chief|chair(man|woman|person)?|founder)\b|(?<!vice )\bpresident\b", re.I)
VP = re.compile(r"\b(vp|vice president|svp|evp)\b", re.I)


def is_top(title: str) -> bool:
    """CEO/CFO/Chief.../Chair/President (not Vice President)."""
    return bool(TOP.search(title))


def is_vp_level(title: str) -> bool:
    return bool(VP.search(title)) and not is_top(title)


def buys(txns: list[Txn], end: date, days: int) -> list[Txn]:
    start = end - timedelta(days=days)
    return [t for t in txns if t.code == "P" and t.acq_disp == "A" and start <= t.trade_date <= end and t.ticker]


@dataclass
class Buyer:
    owner: str
    title: str
    value: float
    shares: float
    first_trade: date
    filed: date
    accession: str
    url: str
    pct_increase: float | None
    plan: bool
    is_director: bool

    @property
    def lag_days(self) -> int:
        return (self.filed - self.first_trade).days


@dataclass
class Cluster:
    ticker: str
    issuer: str
    buyers: list[Buyer]
    batch_reasons: list[str] = field(default_factory=list)
    outliers: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(b.value for b in self.buyers)

    @property
    def batch(self) -> bool:
        return len(self.batch_reasons) >= 2


def _buyers(rows: list[Txn]) -> list[Buyer]:
    by: dict[str, list[Txn]] = {}
    for t in rows:
        by.setdefault(t.owner_cik or t.owner, []).append(t)
    out = []
    for ts in by.values():
        ts.sort(key=lambda t: t.trade_date)
        shares = sum(t.shares for t in ts)
        after = ts[-1].owned_after
        before = (after - shares) if after is not None else None
        out.append(Buyer(ts[0].owner, ts[0].title, sum(t.value for t in ts), shares, ts[0].trade_date,
                         max(t.filed for t in ts), ts[-1].accession, ts[-1].url,
                         (shares / before) if before and before > 0 else None,
                         all(t.plan_10b5_1 for t in ts), any(t.is_director for t in ts)))
    return sorted(out, key=lambda b: -b.value)


def batch_reasons(buyers: list[Buyer]) -> list[str]:
    r = []
    filed = [b.filed for b in buyers]
    top_day = max(set(filed), key=filed.count)
    if filed.count(top_day) / len(buyers) >= 2 / 3:
        r.append(f"{filed.count(top_day)}/{len(buyers)} filed the same day ({top_day})")
    vals = [b.value for b in buyers]
    if len(vals) >= 3 and np.mean(vals) > 0 and pstdev(vals) / np.mean(vals) < 0.25:
        r.append(f"similar sizes (spread {pstdev(vals) / np.mean(vals):.0%} of the mean)")
    vps = sum(1 for b in buyers if is_vp_level(b.title))
    if vps / len(buyers) >= 0.6:
        r.append(f"{vps}/{len(buyers)} VP-level")
    if all(b.plan for b in buyers):
        r.append("all under Rule 10b5-1 plans (pre-scheduled)")
    return r


def outliers(buyers: list[Buyer]) -> list[str]:
    out = []
    vp_heavy = sum(1 for b in buyers if is_vp_level(b.title)) / len(buyers) >= 0.5
    for b in buyers:
        others = [x.value for x in buyers if x is not b]
        if others and b.value >= 3 * median(others):
            out.append(f"{b.owner} ({b.title}) bought {b.value:,.0f}$, ≥3× the others' median")
        if b.pct_increase is not None and b.pct_increase >= 1.0:
            out.append(f"{b.owner} raised the holding by {b.pct_increase:.0%}")
        if vp_heavy and not is_vp_level(b.title) and (is_top(b.title) or b.is_director):
            out.append(f"{b.owner} ({b.title}) buys alongside VPs: senior money in a junior-looking cluster")
    return out


def clusters(txns: list[Txn], end: date, days: int = 60, min_buyers: int = 3) -> list[Cluster]:
    by_ticker: dict[str, list[Txn]] = {}
    for t in buys(txns, end, days):
        by_ticker.setdefault(t.ticker, []).append(t)
    out = []
    for tk, rows in by_ticker.items():
        b = _buyers(rows)
        if len(b) >= min_buyers:
            out.append(Cluster(tk, rows[0].issuer, b, batch_reasons(b), outliers(b)))
    # batch-looking clusters (comp plans) sink below real ones; within each group: distinct buyers, then $
    return sorted(out, key=lambda c: (not c.batch, len(c.buyers), c.total), reverse=True)


@dataclass
class Trend:
    ticker: str
    recent: int        # distinct buyers, last 30 days
    prior: int         # distinct buyers, days 31-90
    total: int         # distinct buyers, 90 days
    state: str         # rising | crowded | flat


def early_signals(txns: list[Txn], end: date) -> list[Trend]:
    rows = buys(txns, end, 90)
    cut = end - timedelta(days=30)
    names: dict[str, tuple[set, set]] = {}
    for t in rows:
        rec, pri = names.setdefault(t.ticker, (set(), set()))
        (rec if t.trade_date > cut else pri).add(t.owner_cik or t.owner)
    out = []
    for tk, (rec, pri) in names.items():
        tot = len(rec | pri)
        state = "crowded" if tot >= 5 else "rising" if len(rec) > len(pri) else "flat"
        out.append(Trend(tk, len(rec), len(pri), tot, state))
    order = {"rising": 0, "crowded": 1, "flat": 2}
    return sorted(out, key=lambda x: (order[x.state], -x.recent, -x.total))


def report(cl: list[Cluster], trends: list[Trend], end: date, days: int, congress: dict | None = None) -> str:
    L = [f"# Insider screen · {end} · last {days} days", "",
         "Source: SEC EDGAR Form 4 (code P = open-market purchase). Every line cites the filing. "
         "Insiders must file within 2 business days, so this is near-live.", "",
         "## Ranked shortlist", "",
         "Order: clusters that do not look like a batch first, then by distinct buyers, then total $. "
         "Batch-looking clusters stay listed, marked.", ""]
    if not cl:
        L.append("No company with 3+ distinct insider buyers in the window.")
    for i, c in enumerate(cl, 1):
        tag = " · ⚠️ looks like a BATCH (comp plan?)" if c.batch else ""
        L += [f"### {i}. {c.ticker} · {c.issuer} · {len(c.buyers)} buyers · {c.total:,.0f}${tag}", "",
              "| Insider | Title | $ | Trade date | Filed | Lag | +holding | 10b5-1 | Filing |", "|---|---|---|---|---|---|---|---|---|"]
        for b in c.buyers:
            L.append(f"| {b.owner} | {b.title} | {b.value:,.0f} | {b.first_trade} | {b.filed} | {b.lag_days}d | "
                     f"{f'{b.pct_increase:.0%}' if b.pct_increase is not None else '—'} | {'yes' if b.plan else 'no'} | "
                     f"[{b.accession}]({b.url}) |")
        L.append("")
        if c.batch_reasons:
            L.append(f"Batch signs: {'; '.join(c.batch_reasons)}.")
        if c.outliers:
            L.append("Outliers: " + "; ".join(c.outliers) + ".")
        L += ["", "What could explain it: conviction after a selloff; a compensation-linked purchase program; "
              "buying ahead of good news (which Form 4 timing makes public in 2 days).",
              "What would make it wrong: purchases required by an ownership guideline; a coming equity raise "
              "insiders support for optics; small $ relative to their pay.", ""]
    L += ["## Early signals (90 days)", "",
          "Rule: *rising* = fewer than 5 distinct buyers in 90 days AND more distinct buyers in the last 30 days "
          "than in days 31-90; *crowded* = 5+ distinct buyers. Counts are distinct insiders with code P only.", "",
          "| Ticker | Last 30d | Days 31-90 | 90d total | State |", "|---|---|---|---|---|"]
    L += [f"| {t.ticker} | {t.recent} | {t.prior} | {t.total} | {t.state} |" for t in trends if t.state != "flat"][:40]
    if congress is not None:
        L += ["", "## Congress (research context only)", "",
              "STOCK Act reports can arrive up to 45 days after the trade: not a trade signal. Both dates shown.", ""]
        L += congress.get("lines", ["Not available."])
    L += ["", "## WHAT I'D DOUBLE-CHECK", "",
          "- Open each filing: footnotes often say 'purchased in the company's offering' or 'through an ESPP' (not open market).",
          "- Whether the buyers are executives or directors: the research finds mixed groups carry more information.",
          "- Each insider's own history: someone who buys every March is routine (Cohen et al.); a first purchase in years is not.",
          "- Market cap and liquidity: clusters in microcaps are common and fragile.",
          "- Upcoming events (earnings, offerings, lock-up expiries) around the trade dates."]
    return "\n".join(L) + "\n"
