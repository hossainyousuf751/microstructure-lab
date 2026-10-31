import asyncio
import time

import pandas as pd
import pytest

from lobkit.recorder import _binance_row, _bybit_rows, _recv, load_depth, load_recording


def test_load_recording_drops_unchanged_quotes(tmp_path):
    (tmp_path / "l1.csv").write_text("ts,update_id,bid_px,bid_sz,ask_px,ask_sz\n"
                                     "1.0,1,100,2,101,3\n1.1,2,100,2,101,3\n1.2,3,100,1,101,3\n")
    (tmp_path / "trades.csv").write_text("ts,ts_local,price,qty,side\n1.05,1.06,101,0.5,1\n")
    quotes, trades = load_recording(tmp_path)
    assert quotes["ts"].tolist() == [1.0, 1.2]                       # the repeat at 1.1 is dropped
    assert list(trades.columns) == ["ts", "price", "qty", "side"]
    assert trades["ts"].tolist() == [1.06]                           # local clock, same as the quotes


def test_load_depth_pivots_levels(tmp_path):
    (tmp_path / "depth.csv").write_text(
        "ts,side,level,price,qty\n"
        "1.0,bid,0,100,2\n1.0,bid,1,99,4\n1.0,ask,0,101,3\n1.0,ask,1,102,5\n"
        "2.0,bid,0,100,1\n2.0,bid,1,99,4\n2.0,ask,0,101,3\n2.0,ask,1,103,6\n")
    d = load_depth(tmp_path)
    expected = pd.DataFrame({"ts": [1.0, 2.0], "bid_px": [100.0, 100], "bid_sz": [2.0, 1], "ask_px": [101.0, 101],
                             "ask_sz": [3.0, 3], "bid_px_2": [99.0, 99], "bid_sz_2": [4.0, 4],
                             "ask_px_2": [102.0, 103], "ask_sz_2": [5.0, 6]})
    pd.testing.assert_frame_equal(d, expected, check_dtype=False)


def test_binance_messages_to_rows():
    tick = {"u": 7, "b": "100.0", "B": "2", "a": "100.1", "A": "3"}
    assert _binance_row("btcusdt@bookTicker", tick, 5.0) == ("l1", [5.0, 7, "100.0", "2", "100.1", "3"])
    seller = {"T": 4500, "p": "100.0", "q": "0.5", "m": True}        # buyer was the maker: a sell
    assert _binance_row("btcusdt@aggTrade", seller, 5.0) == ("trades", [4.5, 5.0, "100.0", "0.5", -1])


def test_bybit_messages_to_rows():
    book = {"bid": None, "ask": None}
    snap = {"topic": "orderbook.1.BTCUSDT", "type": "snapshot",
            "data": {"u": 1, "b": [["100.0", "2"]], "a": [["100.1", "3"]]}}
    assert _bybit_rows(snap, book, 1.0) == [("l1", [1.0, 1, "100.0", "2", "100.1", "3"])]
    delta = {"topic": "orderbook.1.BTCUSDT", "type": "delta", "data": {"u": 2, "b": [], "a": [["100.2", "1"]]}}
    assert _bybit_rows(delta, book, 2.0) == [("l1", [2.0, 2, "100.0", "2", "100.2", "1"])]   # bid carried over
    empty_bid = {"topic": "orderbook.1.BTCUSDT", "type": "snapshot", "data": {"u": 3, "b": [], "a": [["100.2", "1"]]}}
    assert _bybit_rows(empty_bid, book, 3.0) == [] and book["bid"] is None    # no stale bid from before
    trade = {"topic": "publicTrade.BTCUSDT", "data": [{"T": 2500, "p": "100.1", "v": "0.1", "S": "Buy"}]}
    assert _bybit_rows(trade, book, 3.0) == [("trades", [2.5, 3.0, "100.1", "0.1", 1])]
    deleted = {"topic": "orderbook.1.BTCUSDT", "type": "delta", "data": {"u": 4, "b": [], "a": [["100.2", "0"]]}}
    assert _bybit_rows(deleted, book, 4.0) == [] and book["ask"] is None      # a size-0 level is not a quote
    assert _bybit_rows({"op": "pong", "success": True}, book, 3.0) == []
    with pytest.raises(RuntimeError):
        _bybit_rows({"op": "subscribe", "success": False, "ret_msg": "bad symbol"}, book, 3.0)


def test_messages_are_stamped_on_arrival():
    class SlowSocket:                                               # a message arrives 0.2 s after recv() is called
        async def recv(self):
            await asyncio.sleep(0.2)
            return '{"x": 1}'

    async def go():
        called = time.time()
        msg, ts = await _recv(SlowSocket())
        return msg, ts - called

    msg, delay = asyncio.run(go())
    assert msg == {"x": 1} and delay >= 0.19
