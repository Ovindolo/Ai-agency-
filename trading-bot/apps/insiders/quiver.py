"""Political exposure for one ticker through Quiver's official Python package (`pip install quiverquant`),
token in QUIVER_API_KEY. Column names are Quiver's; they are shown as delivered, never guessed.
A dataset the plan cannot reach is reported as locked, never worked around.
"""
from __future__ import annotations

import os

import pandas as pd

DATASETS = {  # label -> (method, takes ticker)
    "Congressional trades": ("congress_trading", True),
    "Federal contracts": ("gov_contracts", True),
    "Lobbying": ("lobbying", True),
    "Insider transactions (Quiver)": ("insiders", True),
    "Top shareholders": ("top_shareholders", True),
    "13F changes": ("sec13FChanges", True),
}


def client(token: str | None = None):
    import quiverquant
    token = token or os.getenv("QUIVER_API_KEY", "")
    if not token:
        raise SystemExit("QUIVER_API_KEY lipsește din .env.")
    return quiverquant.quiver(token)


def fetch(q, ticker: str) -> dict[str, pd.DataFrame | str]:
    out: dict[str, pd.DataFrame | str] = {}
    for label, (method, by_ticker) in DATASETS.items():
        try:
            df = getattr(q, method)(ticker) if by_ticker else getattr(q, method)()
            out[label] = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        except Exception as exc:  # noqa: BLE001 - plan limits surface as HTTP errors
            out[label] = f"LOCKED or unavailable on this plan ({type(exc).__name__})"
    return out


def date_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "date" in str(c).lower() or str(c).lower() in ("filed", "reported", "traded")]


def markdown(ticker: str, data: dict) -> list[str]:
    lines = [f"### {ticker}", ""]
    for label, df in data.items():
        lines.append(f"**{label}**")
        if isinstance(df, str):
            lines += [df, ""]
            continue
        if df.empty:
            lines += ["No rows.", ""]
            continue
        dc = date_columns(df)
        if label == "Congressional trades" and len(dc) < 2:
            lines.append("⚠️ Only one date column delivered: trade date and report date cannot both be shown.")
        lines += [_table(df.head(15)), ""]
    return lines


def _table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    cell = lambda v: str(v).replace("|", "/").replace("\n", " ")[:120]      # filing text stays inert data
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    rows += ["| " + " | ".join(cell(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)
