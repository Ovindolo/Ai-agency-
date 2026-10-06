import json

import pytest

from apps.audit.freqtrade_tg import parse, split_messages, stats

SAMPLE = """Cryptopedia Trading Bot, [Sep 22, 2026 at 07:00]
🔴 #COTI/USDT SHORT
ENTRY: 0.016672
SL: 0.016965
TP1: 0.016523
TP2: 0.016407
Stake COIN: 438459.7
Stake USDT: 7310
 Cryptopedia Trading Bot, [Sep 22, 2026 at 07:00]
🟢 #QTUM/USDT LONG
ENTRY: 0.9798
SL: 0.9626
TP1: 0.9885
TP2: 0.9954
Stake COIN: 7460.7
Stake USDT: 7310
 Cryptopedia Trading Bot, [Sep 22, 2026 at 08:00]
✓ Bybit (dry): New Trade filled (#1475)
Pair: QTUM/USDT:USDT
Enter Tag: Msg: 
Amount: 7460.7
Direction: Long (10x)
Open Rate: 0.9798 USDT
Total: 730.999 USDT / 730.812 USD
 Cryptopedia Trading Bot, [Sep 22, 2026 at 11:00]
CANCELING TRADE: 1474
🔴 #COTI/USDT SHORT
Cancel REASON: ENTRY not hit in 4h
 Cryptopedia Trading Bot, [Sep 23, 2026 at 00:03]
🚀 Bybit (dry): Partially exited QTUM/USDT:USDT (#1475)
Sub Profit: 13.08% (profit: 47.797 USDT / 47.795 USD)
Cumulative Profit: 49.557 USDT / 49.554 USD
Exit Reason: TP2
Direction: Long (10x)
 Cryptopedia Trading Bot, [Sep 23, 2026 at 19:01]
❌ Bybit (dry): Exited QTUM/USDT:USDT (#1475)
Sub Profit: -16.03% (loss: -11.132 USDT / -11.129 USD)
Final Profit: 18.12% (132.48625361 USDT / 132.447 USD)
Exit Reason: trailing_stop_loss
Direction: Long (10x)
Exit Rate: 0.9673 USDT
 Cryptopedia Trading Bot, [Sep 27, 2026 at 08:37]
✓ Bybit (dry): New Trade filled (#1478)
Pair: STRK/USDT:USDT
Direction: Short (10x)
Open Rate: 0.04048 USDT
Total: 731 USDT / 730.845 USD
 Cryptopedia Trading Bot, [Sep 27, 2026 at 09:18]
❌ Bybit (dry): Exited STRK/USDT:USDT (#1478)
Profit: -18.75% (loss: -137.022 USDT / -136.993 USD)
Exit Reason: trailing_stop_loss
Direction: Short (10x)
"""


def test_parse_channel_record():
    ch = parse(SAMPLE)
    assert len(ch.signals) == 2 and len(ch.cancels) == 1 and len(ch.trades) == 2
    q = ch.trades[0]
    assert (q.pair, q.side, q.leverage, q.margin) == ("QTUM/USDT", "long", 10.0, 730.999)
    assert q.pnl == pytest.approx(132.48625361) and q.partials[0][1] == "TP2"
    s = ch.trades[1]
    assert s.side == "short" and s.pnl == pytest.approx(-137.022) and not s.partials
    st = stats(ch)
    assert st["wins"] == 1 and st["losses"] == 1 and st["full_losses"] == 1
    assert st["net"] == pytest.approx(132.48625361 - 137.022)
    assert st["risk_per_signal"] == pytest.approx((7310 * 0.000293 / 0.016672 + 7310 * 0.0172 / 0.9798) / 2, rel=1e-3)


def test_telegram_json_export_is_read():
    export = {"messages": [{"date": "2026-09-27T09:18:00", "text": [
        "❌ Bybit (dry): Exited STRK/USDT:USDT (#1478)\nProfit: -18.75% (loss: -137.022 USDT / -136.993 USD)"]}]}
    msgs = split_messages(json.dumps(export))
    assert len(msgs) == 1 and "Exited" in msgs[0][1]
