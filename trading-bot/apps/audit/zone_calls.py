"""Audit "buy zone / targets" calls from a Telegram Desktop HTML export, losers included.

Recognizes the common spot-call format of Romanian/English crypto groups:

    #celrbtc                       or  CELR/BTC, #CELRUSDT, celr btc
    buy zone: 55-62 sats           or  entry / entry zone / entry price / intrare / buy area
    take profit: 68-72-80-90 sats  or  target(s) / tinta / tp / T1 ...
    stop loss: 48                  (optional; most calls have none)

A call is FILLED if price trades into the buy zone within `fill_days` of the post (fill at the zone top
or the open, whichever is lower). From the fill it records: which targets were reached and when, the
deepest drawdown before the first target, and the return after 7/30/90 days. Without a posted stop the
honest question is "how far against you did it go before paying", so drawdown is reported, not hidden.
BTC-quoted calls are measured in BTC (vs simply holding BTC); USDT calls in dollars.

The export holds other members' messages: it stays outside git, only aggregates are written.

  python -m apps.audit.zone_calls <export_dir> --author Dan
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
NUM = r"\d+(?:[.,]\d+)?"
PAIR = re.compile(r"#\s*([a-z0-9]{2,12}?)(btc|usdt|busd|eth)\b|\b([A-Za-z0-9]{2,12})\s*/\s*(BTC|USDT|BUSD|ETH)\b"
                  r"|\blong\s+([A-Za-z0-9]{2,10}?)(USDT|USD|BTC)\b", re.I)
ENTRY_WORDS = r"buy ?zone|buy area|entry(?: zone| price)?|entries|intrare|zona de (?:cumparare|intrare)|buy between|\bbuy\b"
ENTRY = re.compile(r"(?i)(?:" + ENTRY_WORDS + r")\s*[:\-]?\s*(.+)")
ENTRY_LINE = re.compile(r"(?im)^(.*\d.*)\s(?:" + ENTRY_WORDS + r")\s*$")       # "105 - 110 sats intrare"
TARGET = re.compile(r"(?i)(?:targets?|tinta|ținta|take ?profit|\btp\d?\b)\s*[:\-]?\s*(.+)")
STOP = re.compile(r"(?i)(?:stop ?loss|\bsl\b|stop)\s*[:\-]?\s*(" + NUM + ")")


@dataclass
class Call:
    t: pd.Timestamp
    msg_id: int
    base: str
    quote: str
    lo: float
    hi: float
    targets: list[float]
    stop: float | None
    text: str
    result: dict = field(default_factory=dict)


def _nums(s: str) -> list[float]:
    return [float(x.replace(",", ".")) for x in re.findall(NUM, s.split("http")[0])]


def _scale(values: list[float], text: str, quote: str) -> list[float]:
    """'sats' or bare integers on a BTC pair mean satoshis."""
    if quote == "BTC" and (re.search(r"(?i)sat", text) or all(v >= 1 for v in values)):
        return [v * 1e-8 for v in values]
    return values


def parse(text: str, t: pd.Timestamp, msg_id: int) -> Call | None:
    if re.search(r"(?i)\bshort\b", text.split("\n")[0]):
        return None                                        # spot audit: long calls only
    p = PAIR.search(text)
    g = TARGET.search(text)
    e = ENTRY.search(text)
    e_txt = e.group(1).split("\n")[0] if e and _nums(e.group(1).split("\n")[0]) else None
    if e_txt is None and (m := ENTRY_LINE.search(text)):
        e_txt = m.group(1)
    if not (p and e_txt and g):
        return None
    groups = [x for x in p.groups() if x]
    base, quote = groups[0].upper(), groups[1].upper().replace("BUSD", "USDT")
    quote = "USDT" if quote == "USD" else quote
    ent = _nums(e_txt)
    tg_line = g.group(1).split("\n")[0]
    tgs = _nums(tg_line)
    if not ent or not tgs or "%" in tg_line:             # percentage targets: a forwarded bot format
        return None
    ent, tgs = _scale(ent, e_txt, quote), _scale(tgs, tg_line, quote)
    lo, hi = min(ent[:2]), max(ent[:2])
    tgs = sorted(x for x in tgs if x > hi)
    if not tgs or lo <= 0 or hi / lo > 1.5:
        return None
    s = STOP.search(text)
    stop = _scale([float(s.group(1).replace(",", "."))], s.group(0), quote)[0] if s else None
    return Call(t, msg_id, base, quote, lo, hi, tgs, stop if stop and stop < lo else None, text)


def evaluate(call: Call, bars: pd.DataFrame, fill_days: int = 7) -> dict:
    """bars: 1h OHLC (open-time index, UTC) covering the post and the following 90+ days."""
    after = bars[bars.index >= call.t.ceil("h")]
    window = after[after.index < call.t + pd.Timedelta(days=fill_days)]
    touch = window[window["low"] <= call.hi]
    if touch.empty:
        return {"filled": False, "ran_away": bool((window["high"] >= call.targets[0]).any())}
    t0 = touch.index[0]
    entry = min(call.hi, touch["open"].iloc[0])
    path = after[after.index >= t0]
    res = {"filled": True, "entry": entry, "t_fill": t0}
    hits = []
    for x in call.targets:
        reached = path[path["high"] >= x]
        hits.append(reached.index[0] if not reached.empty else None)
    res["hits"] = sum(h is not None for h in hits)
    res["t1_days"] = (hits[0] - t0).total_seconds() / 86400 if hits[0] is not None else np.nan
    before_t1 = path if hits[0] is None else path[path.index <= hits[0]]
    res["dd_before_t1"] = float(before_t1["low"].min() / entry - 1)
    if call.stop is not None:
        stopped = path[path["low"] <= call.stop]
        res["stopped_first"] = bool(not stopped.empty and (hits[0] is None or stopped.index[0] < hits[0]))
    for d in (7, 30, 90):
        cut = path[path.index <= t0 + pd.Timedelta(days=d)]
        res[f"ret_{d}d"] = float(cut["close"].iloc[-1] / entry - 1) if len(cut) and path.index[-1] >= t0 + pd.Timedelta(days=d) else np.nan
    res["t1_gain"] = call.targets[0] / entry - 1
    return res


def read_export(folder: Path) -> pd.DataFrame:
    from bs4 import BeautifulSoup
    files = sorted(folder.glob("messages*.html"), key=lambda f: int(re.sub(r"\D", "", f.stem) or 0))
    rows, sender = [], None
    for f in files:
        soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
        for m in soup.select("div.message.default"):
            fn = m.select_one(".from_name")
            if fn:
                sender = " ".join(fn.get_text(" ", strip=True).split())
            d, txt = m.select_one(".date.details"), m.select_one(".text")
            rows.append({"id": int(re.sub(r"\D", "", m.get("id", "0")) or 0), "t": d["title"] if d else None,
                         "from": sender, "text": txt.get_text("\n", strip=True) if txt else ""})
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"].str.replace(r" UTC.*$", "", regex=True), format="%d %B %Y, %H:%M:%S", errors="coerce")
    return df


def bars_1h(base: str, quote: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    """Binance spot 1h klines from the public archive (delisted pairs included), cached per month."""
    from apps.model.data import ARCHIVE, OUT, _get, _to_utc, _zip_csv
    sym = f"{base}{quote}"
    folder = OUT / "spot_1h" / sym
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for m in pd.period_range(start.tz_localize(None), end.tz_localize(None), freq="M"):
        f = folder / f"{m}.csv"
        if f.exists():
            part = pd.read_csv(f, index_col=0)
            if part.empty:
                continue
            part.index = pd.DatetimeIndex(pd.to_datetime(part.index, utc=True, format="ISO8601"))
        else:
            blob = _get(f"{ARCHIVE}/spot/monthly/klines/{sym}/1h/{sym}-1h-{m}.zip")
            if blob is None:
                pd.DataFrame().to_csv(f)
                continue
            raw = _zip_csv(blob, header=None)
            if not str(raw.iat[0, 0]).isdigit():
                raw = raw.iloc[1:]
            part = pd.DataFrame({"open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4]}).astype(float)
            part.index = _to_utc(raw[0])
            part.to_csv(f)
        parts.append(part)
    return pd.concat(parts).sort_index() if parts else None


def summary(calls: list[Call]) -> pd.DataFrame:
    rows = [{"t": c.t, "pair": f"{c.base}/{c.quote}", "n_targets": len(c.targets), "has_stop": c.stop is not None,
             **c.result} for c in calls]
    return pd.DataFrame(rows)


def report(s: pd.DataFrame, author: str, n_msgs: int) -> str:
    f = s[s["filled"] == True]                                   # noqa: E712
    nodata = s["filled"].isna().sum()
    pct = lambda x: f"{x:.0%}" if pd.notna(x) else "—"
    def block(d: pd.DataFrame) -> str:
        if d.empty:
            return "| — | 0 | | | | | | |"
        return (f"| {len(d)} | {pct((d['hits'] >= 1).mean())} | {pct(d['t1_gain'].median())} | "
                f"{d['t1_days'].median():.1f} | {pct(d['dd_before_t1'].median())} | {pct((d['dd_before_t1'] <= -0.2).mean())} | "
                f"{pct(d['ret_30d'].median())} | {pct(d['ret_90d'].median())} |")
    yearly = "\n".join(f"| {y} {block(g)[1:]}" for y, g in f.groupby(f["t"].dt.year))
    by_quote = "\n".join(f"| {q} {block(g)[1:]}" for q, g in f.groupby(f["pair"].str.split("/").str[1]))
    return f"""# Audit of {author}'s buy-zone calls

{n_msgs} messages by {author} read; **{len(s)}** structured calls parsed (pair + buy zone + price targets).
{int(nodata)} had no Binance history (other exchange or delisted before archives); {int((s['filled'] == False).sum())}
never traded into the buy zone within 7 days ({int(s.get('ran_away', pd.Series(dtype=bool)).fillna(False).sum())} of
those ran to target 1 without you). **{len(f)} filled** and are measured below, losers included.

BTC pairs are measured in BTC (so "+0%" means "same as holding BTC"); USDT pairs in dollars.
No fees included (spot, ~0.1% per side, small next to these moves).

| Filled | Hit target 1 | Target 1 distance (median) | Days to T1 (median) | Worst drop before T1 (median) | Dropped ≥20% first | Return after 30d (median) | after 90d (median) |
|---|---|---|---|---|---|---|---|
{block(f)}

By year:

| Year | Filled | Hit T1 | T1 distance | Days to T1 | Drop before T1 | ≥20% drop first | 30d | 90d |
|---|---|---|---|---|---|---|---|---|
{yearly}

By quote currency:

| Quote | Filled | Hit T1 | T1 distance | Days to T1 | Drop before T1 | ≥20% drop first | 30d | 90d |
|---|---|---|---|---|---|---|---|---|
{by_quote}

How to read it: "Hit target 1" alone flatters every caller, because with no stop most coins touch a level
10% higher at some point. The columns that decide whether following the calls makes money are the drop
before target 1 (what you sit through, and what a stop would have cut) and the return after 30/90 days
(what holding the call actually paid).
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export", type=Path)
    ap.add_argument("--author", default="Dan")
    ap.add_argument("--fill-days", type=int, default=7)
    a = ap.parse_args()
    msgs = read_export(a.export)
    mine = msgs[(msgs["from"] == a.author) & ~msgs["text"].str.contains("(?i)liquidated")]
    calls = [c for _, r in mine.iterrows() if (c := parse(r["text"], r["t"].tz_localize("UTC"), r["id"]))]
    seen: dict[tuple, pd.Timestamp] = {}
    unique = []
    for c in sorted(calls, key=lambda c: c.t):                # the same call reposted within 3 days counts once
        key = (c.base, c.quote, round(c.lo, 12), round(c.hi, 12))
        if key in seen and c.t - seen[key] < pd.Timedelta(days=3):
            continue
        seen[key] = c.t
        unique.append(c)
    calls = unique
    for c in calls:
        bars = bars_1h(c.base, c.quote, c.t - pd.Timedelta(days=1), c.t + pd.Timedelta(days=100))
        c.result = evaluate(c, bars, a.fill_days) if bars is not None and len(bars) else {"filled": None}
    s = summary(calls)
    md = report(s, a.author, len(mine))
    out = ROOT / "reports" / f"AUDIT_{a.author.upper()}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(md)
    s.drop(columns=[c for c in s.columns if c.startswith("t_")], errors="ignore").to_csv(out.with_suffix(".csv"), index=False)
    print(md)


if __name__ == "__main__":
    main()
