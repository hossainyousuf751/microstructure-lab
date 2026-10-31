import pytest

from lobkit import BinanceDepthSync, OrderBook, SequenceGap

SNAP = {"lastUpdateId": 100, "bids": [["99.0", "2"], ["98.0", "5"]], "asks": [["101.0", "3"], ["102.0", "1"]]}


def ev(U, u, b=(), a=()):
    return {"U": U, "u": u, "b": [list(x) for x in b], "a": [list(x) for x in a]}


def test_order_book_basics():
    ob = OrderBook()
    ob.load_snapshot(SNAP["bids"], SNAP["asks"])
    assert ob.best_bid() == (99.0, 2.0) and ob.best_ask() == (101.0, 3.0)
    assert ob.mid == 100.0 and not ob.is_crossed
    ob.apply("bid", 99.0, 0)
    assert ob.best_bid() == (98.0, 5.0)
    ob.apply("ask", 50.0, 0)                       # unknown level removal is harmless
    ob.apply("bid", 101.5, 1)
    assert ob.is_crossed


def test_sync_drops_stale_and_applies_bridging_event():
    s = BinanceDepthSync()
    s.on_event(ev(90, 95, b=[("97.0", "9")]))        # entirely before snapshot -> dropped
    s.on_event(ev(96, 103, b=[("99.0", "4")]))       # straddles lastUpdateId + 1 -> applied
    assert s.on_snapshot(SNAP)
    assert s.book.bids[99.0] == 4.0 and 97.0 not in s.book.bids
    assert s.on_event(ev(104, 110, a=[("101.0", "0")]))
    assert s.book.best_ask() == (102.0, 1.0)


def test_sync_rejects_snapshot_older_than_buffer():
    s = BinanceDepthSync()
    s.on_event(ev(150, 160))
    assert not s.on_snapshot(SNAP)                  # lastUpdateId 100 < first U 150


def test_sync_detects_gap():
    s = BinanceDepthSync()
    s.on_event(ev(96, 103))
    s.on_snapshot(SNAP)
    with pytest.raises(SequenceGap):
        s.on_event(ev(105, 110))                     # 104 missing


def test_first_event_must_bridge_snapshot():
    s = BinanceDepthSync()
    s.on_event(ev(96, 99))                           # stale, dropped
    s.on_event(ev(102, 110))                         # update 101 was missed
    with pytest.raises(SequenceGap):
        s.on_snapshot(SNAP)                          # needs U <= 101 <= u
