import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from apps.insiders.bot import answer, cluster_alerts
from apps.insiders.edgar import Edgar, parse_index
from apps.insiders.form4 import parse_form4
from apps.insiders.screen import clusters, early_signals, report

END = date(2026, 9, 30)


def form4(owner, cik, title, code="P", shares=1000, price=10.0, trade=date(2026, 9, 10), filed=date(2026, 9, 12),
          ticker="ACME", plan=0, after=None, director=0, acc=None, ad="A"):
    after = after if after is not None else shares * 3
    acc = acc or f"0000000000-26-{abs(hash((owner, trade, code, shares))) % 999999:06d}"
    return f"""<SEC-DOCUMENT>
ACCESSION NUMBER:\t{acc}
FILED AS OF DATE:\t{filed:%Y%m%d}
<XML>
<ownershipDocument>
 <documentType>4</documentType>
 <aff10b5One>{plan}</aff10b5One>
 <issuer><issuerCik>0000123456</issuerCik><issuerName>Acme Corp</issuerName><issuerTradingSymbol>{ticker}</issuerTradingSymbol></issuer>
 <reportingOwner>
  <reportingOwnerId><rptOwnerCik>{cik}</rptOwnerCik><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isDirector>{director}</isDirector><isOfficer>1</isOfficer><officerTitle>{title}</officerTitle></reportingOwnerRelationship>
 </reportingOwner>
 <nonDerivativeTable><nonDerivativeTransaction>
  <securityTitle><value>Common Stock</value></securityTitle>
  <transactionDate><value>{trade:%Y-%m-%d}</value></transactionDate>
  <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
  <transactionAmounts><transactionShares><value>{shares}</value></transactionShares>
   <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
   <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode></transactionAmounts>
  <postTransactionAmounts><sharesOwnedFollowingTransaction><value>{after}</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
 </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>
</XML>
</SEC-DOCUMENT>"""


def txns(*docs):
    return [t for d in docs for t in parse_form4(d)]


def test_parse_form4_fields():
    t = parse_form4(form4("DOE JANE", "111", "Chief Executive Officer", shares=2000, price=12.5))[0]
    assert (t.ticker, t.code, t.acq_disp, t.shares, t.value) == ("ACME", "P", "A", 2000, 25000)
    assert t.filed == date(2026, 9, 12) and t.trade_date == date(2026, 9, 10)
    assert t.url.startswith("https://www.sec.gov/Archives/edgar/data/123456/")


def test_only_open_market_purchases_count():
    rows = txns(form4("A", "1", "CEO"), form4("B", "2", "CFO", code="M"), form4("C", "3", "Director", code="S", ad="D"),
                form4("D", "4", "VP Sales", code="A"), form4("E", "5", "CTO", code="F", ad="D"))
    assert clusters(rows, END) == []                        # only 1 real buyer


def test_cluster_ranked_by_buyers_then_dollars():
    big = txns(*[form4(f"X{i}", f"9{i}", "Director", ticker="BIG", shares=10_000) for i in range(3)])
    many = txns(*[form4(f"Y{i}", f"8{i}", "CEO" if i == 0 else "Director", ticker="MANY", shares=100) for i in range(4)])
    cl = clusters(big + many, END)
    assert [c.ticker for c in cl] == ["MANY", "BIG"]
    assert len(cl[0].buyers) == 4


def test_same_insider_twice_is_one_buyer():
    rows = txns(form4("A", "1", "CEO"), form4("A", "1", "CEO", trade=date(2026, 9, 15), shares=500), form4("B", "2", "CFO"))
    assert clusters(rows, END) == []


def test_batch_is_flagged_and_outlier_surfaced():
    vps = [form4(f"VP{i}", f"7{i}", "Vice President, Operations", shares=1000, filed=date(2026, 9, 12)) for i in range(4)]
    ceo = form4("BOSS", "999", "Chief Executive Officer", shares=20_000, filed=date(2026, 9, 12), after=30_000)
    cl = clusters(txns(*vps, ceo), END)[0]
    assert any("same day" in r for r in cl.batch_reasons) and any("VP-level" in r for r in cl.batch_reasons)
    assert any("BOSS" in o and "3×" in o for o in cl.outliers)
    assert any("BOSS" in o and "VPs" in o for o in cl.outliers)


def test_plan_trades_count_as_batch_sign():
    rows = txns(*[form4(f"P{i}", f"6{i}", "Director", plan=1, shares=1000 + 700 * i, filed=date(2026, 9, 10 + i))
                  for i in range(3)])
    assert any("10b5-1" in r for r in clusters(rows, END)[0].batch_reasons)


def test_early_signals_rising_vs_crowded():
    recent = [form4(f"R{i}", f"5{i}", "Director", ticker="NEW", trade=END - timedelta(days=5)) for i in range(2)]
    old = [form4("O1", "59", "Director", ticker="NEW", trade=END - timedelta(days=60))]
    crowd = [form4(f"C{i}", f"4{i}", "Director", ticker="HOT", trade=END - timedelta(days=10 * i)) for i in range(6)]
    tr = {t.ticker: t for t in early_signals(txns(*recent, *old, *crowd), END)}
    assert tr["NEW"].state == "rising" and (tr["NEW"].recent, tr["NEW"].prior) == (2, 1)
    assert tr["HOT"].state == "crowded"


def test_report_cites_filings_and_both_dates():
    rows = txns(*[form4(f"Z{i}", f"3{i}", "Director", ticker="CITE") for i in range(3)])
    md = report(clusters(rows, END), early_signals(rows, END), END, 60)
    assert "sec.gov/Archives" in md and "| 2026-09-10 | 2026-09-12 | 2d |" in md and "WHAT I'D DOUBLE-CHECK" in md


def test_alerts_once_then_again_when_cluster_grows():
    rows = txns(*[form4(f"Q{i}", f"2{i}", "Director", ticker="ALRT", trade=END - timedelta(days=3)) for i in range(3)])
    sent = {}
    assert len(cluster_alerts(rows, END, sent)) == 1
    assert cluster_alerts(rows, END, sent) == []
    rows += txns(form4("Q9", "29", "CEO", ticker="ALRT", trade=END - timedelta(days=1)))
    assert "4 insideri" in cluster_alerts(rows, END, sent)[0]


def test_telegram_commands_are_parsed_as_data():
    rows = txns(*[form4(f"T{i}", f"1{i}", "Director", ticker="TEL") for i in range(3)])
    assert "TEL" in answer("/clusters 60", rows, END)
    assert "TEL: 3" in answer("/ticker tel; rm -rf /", rows, END) or "TEL" in answer("/ticker TEL", rows, END)
    assert answer("/ticker $(whoami)", rows, END).startswith("WHOAMI: 0")      # sanitized to a plain ticker
    assert "Comenzi" in answer("/unknown", rows, END)


def test_index_parsing_dedupes():
    idx = """Form Type   Company Name          CIK         Date Filed  File Name
---------------------------------------------------------------------------
4           ACME CORP             123456      20260912    edgar/data/123456/0000000000-26-000001.txt
4           DOE JANE              111         20260912    edgar/data/123456/0000000000-26-000001.txt
4/A         ACME CORP             123456      20260912    edgar/data/123456/0000000000-26-000002.txt
10-K        OTHER                 999         20260912    edgar/data/999/0000000000-26-000003.txt
"""
    assert parse_index(idx) == ["edgar/data/123456/0000000000-26-000001.txt", "edgar/data/123456/0000000000-26-000002.txt"]


def test_edgar_requires_declared_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SystemExit):
        Edgar()


def test_no_trading_code_in_insiders_package():
    src = "".join(p.read_text() for p in Path("apps/insiders").glob("*.py"))
    assert not re.search(r"create_order|place_order|ccxt", src)


@pytest.mark.parametrize("title,top,vp", [("Vice President, Operations", False, True), ("EVP & Chief Financial Officer", True, False),
                                          ("President and CEO", True, False), ("SVP Sales", False, True), ("Director", False, False),
                                          ("Chairman", True, False)])
def test_title_classes(title, top, vp):
    from apps.insiders.screen import is_top, is_vp_level
    assert (is_top(title), is_vp_level(title)) == (top, vp)


def test_quiver_rendering_and_locked_datasets():
    import pandas as pd
    from apps.insiders import quiver

    class Fake:
        def congress_trading(self, t):
            return pd.DataFrame({"Representative": ["A | B"], "TransactionDate": ["2026-08-01"], "ReportDate": ["2026-09-10"]})

        def lobbying(self, t):
            raise PermissionError("403")

        def __getattr__(self, name):
            return lambda t: pd.DataFrame()

    data = quiver.fetch(Fake(), "ACME")
    assert data["Lobbying"].startswith("LOCKED")
    md = "\n".join(quiver.markdown("ACME", data))
    assert "A / B" in md and "2026-09-10" in md and "LOCKED" in md


def test_batch_clusters_rank_below_real_ones():
    batch = [form4(f"V{i}", f"8{i}", "VP Finance", shares=1000, ticker="BAT", filed=date(2026, 9, 12)) for i in range(5)]
    real = [form4(f"D{i}", f"9{i}", "Director", shares=500 * (i + 1) ** 2, ticker="REAL", filed=date(2026, 9, 5 + i))
            for i in range(3)]
    assert [c.ticker for c in clusters(txns(*batch, *real), END)] == ["REAL", "BAT"]
