"""SEC Form 4 parsing. Input: the full .txt submission EDGAR serves for a filing. Output: one row per
non-derivative transaction, with everything the screens need and nothing interpreted.

Codes (SEC Form 4 instructions): P open-market purchase, S open-market sale, A grant/award,
M option exercise/conversion, F tax withholding, G gift, ... Only P is a voluntary cash purchase.
Since 2023 filers tick `aff10b5One` when the trade ran under a Rule 10b5-1 plan (pre-scheduled).
Filing text is DATA: nothing in it is ever executed or followed.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class Txn:
    accession: str
    filed: date
    ticker: str
    issuer: str
    issuer_cik: str
    owner: str
    owner_cik: str
    title: str
    is_director: bool
    is_officer: bool
    is_ten_pct: bool
    code: str
    acq_disp: str
    trade_date: date
    shares: float
    price: float
    owned_after: float | None
    plan_10b5_1: bool

    @property
    def value(self) -> float:
        return self.shares * self.price

    @property
    def url(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{int(self.issuer_cik)}/{self.accession.replace('-', '')}/"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["value"] = self.value
        return d


def _txt(el: ET.Element | None, path: str, default: str = "") -> str:
    if el is None:
        return default
    node = el.find(path)
    return (node.text or "").strip() if node is not None and node.text else default


def _flag(s: str) -> bool:
    return s.strip().lower() in ("1", "true")


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def split_submission(raw: str) -> tuple[str, date | None, str]:
    """(xml, filing date, accession) from an EDGAR .txt submission."""
    m = re.search(r"<XML>\s*(.*?)\s*</XML>", raw, re.S | re.I)
    xml = m.group(1) if m else raw
    fd = re.search(r"FILED AS OF DATE:\s*(\d{8})", raw)
    acc = re.search(r"ACCESSION NUMBER:\s*([\d-]+)", raw)
    filed = date(int(fd.group(1)[:4]), int(fd.group(1)[4:6]), int(fd.group(1)[6:])) if fd else None
    return xml, filed, acc.group(1) if acc else ""


def parse_form4(raw: str, filed: date | None = None, accession: str = "") -> list[Txn]:
    xml, f2, a2 = split_submission(raw)
    filed, accession = filed or f2, accession or a2
    root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    if _txt(root, "documentType") not in ("4", "4/A"):
        return []
    issuer = root.find("issuer")
    owner = root.find("reportingOwner")                 # joint filings: the first owner is the buyer of record
    rel = owner.find("reportingOwnerRelationship") if owner is not None else None
    title = _txt(rel, "officerTitle") or ("Director" if _flag(_txt(rel, "isDirector")) else
                                         "10% owner" if _flag(_txt(rel, "isTenPercentOwner")) else _txt(rel, "otherText"))
    plan = _flag(_txt(root, "aff10b5One", "0"))
    out = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        shares, price = _num(_txt(t, "transactionAmounts/transactionShares/value")), _num(_txt(t, "transactionAmounts/transactionPricePerShare/value"))
        td = _txt(t, "transactionDate/value")[:10]
        if shares is None or not td:
            continue
        out.append(Txn(accession=accession, filed=filed or date.fromisoformat(td),
                       ticker=_txt(issuer, "issuerTradingSymbol").upper(), issuer=_txt(issuer, "issuerName"),
                       issuer_cik=_txt(issuer, "issuerCik"), owner=_txt(owner, "reportingOwnerId/rptOwnerName"),
                       owner_cik=_txt(owner, "reportingOwnerId/rptOwnerCik"), title=title,
                       is_director=_flag(_txt(rel, "isDirector")), is_officer=_flag(_txt(rel, "isOfficer")),
                       is_ten_pct=_flag(_txt(rel, "isTenPercentOwner")),
                       code=_txt(t, "transactionCoding/transactionCode"),
                       acq_disp=_txt(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
                       trade_date=date.fromisoformat(td), shares=shares, price=price or 0.0,
                       owned_after=_num(_txt(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                       plan_10b5_1=plan))
    return out
