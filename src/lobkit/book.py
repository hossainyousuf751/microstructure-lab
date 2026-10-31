"""Level-2 order book and Binance depth-stream synchronisation.

Binance publishes a REST snapshot plus a stream of diffs carrying absolute
quantities per price level. A correct local book needs the sequence rules
(from the Binance spot API docs):

1. Buffer stream events, then fetch a snapshot with `lastUpdateId`.
2. Drop events with u <= lastUpdateId.
3. The first applied event must satisfy U <= lastUpdateId + 1 <= u.
4. Every later event must have U == previous u + 1, otherwise resync.
5. A quantity of 0 removes the level.
"""

from __future__ import annotations


class SequenceGap(Exception):
    """An update was missed; the local book is no longer trustworthy."""


class OrderBook:
    def __init__(self) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

    def apply(self, side: str, price: float, qty: float) -> None:
        book = self.bids if side == "bid" else self.asks
        if qty == 0:
            book.pop(price, None)    # removing an unknown level is normal on Binance
        else:
            book[price] = qty

    def load_snapshot(self, bids, asks) -> None:
        self.bids.clear()
        self.asks.clear()
        for p, q in bids:
            self.apply("bid", float(p), float(q))
        for p, q in asks:
            self.apply("ask", float(p), float(q))

    def best_bid(self) -> tuple[float, float] | None:
        if not self.bids:
            return None
        p = max(self.bids)
        return p, self.bids[p]

    def best_ask(self) -> tuple[float, float] | None:
        if not self.asks:
            return None
        p = min(self.asks)
        return p, self.asks[p]

    def levels(self, side: str, n: int = 10) -> list[tuple[float, float]]:
        book = self.bids if side == "bid" else self.asks
        prices = sorted(book, reverse=(side == "bid"))[:n]
        return [(p, book[p]) for p in prices]

    @property
    def mid(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        return None if bb is None or ba is None else 0.5 * (bb[0] + ba[0])

    @property
    def is_crossed(self) -> bool:
        bb, ba = self.best_bid(), self.best_ask()
        return bb is not None and ba is not None and bb[0] >= ba[0]


class BinanceDepthSync:
    """Maintains an OrderBook from a Binance diff-depth stream plus REST snapshot."""

    def __init__(self) -> None:
        self.book = OrderBook()
        self.last_update_id: int | None = None
        self.prev_u: int | None = None
        self.buffer: list[dict] = []

    @property
    def synced(self) -> bool:
        return self.last_update_id is not None

    def on_event(self, event: dict) -> bool:
        """Feed one diff event (keys U, u, b, a). Returns True if it changed the book."""
        if not self.synced:
            self.buffer.append(event)
            return False
        return self._apply(event)

    def on_snapshot(self, snapshot: dict) -> bool:
        """Install a REST snapshot. Returns False if it is too old and must be refetched."""
        if self.buffer and snapshot["lastUpdateId"] < self.buffer[0]["U"]:
            return False
        self.book.load_snapshot(snapshot["bids"], snapshot["asks"])
        self.last_update_id, self.prev_u = snapshot["lastUpdateId"], None
        pending, self.buffer = self.buffer, []
        for ev in pending:
            self._apply(ev)
        return True

    def _apply(self, ev: dict) -> bool:
        if ev["u"] <= self.last_update_id:
            return False                                   # already in the snapshot
        if self.prev_u is None:
            if not ev["U"] <= self.last_update_id + 1 <= ev["u"]:
                raise SequenceGap(f"first event U={ev['U']} u={ev['u']} vs snapshot {self.last_update_id}")
        elif ev["U"] != self.prev_u + 1:
            raise SequenceGap(f"expected U={self.prev_u + 1}, got U={ev['U']}")
        for p, q in ev["b"]:
            self.book.apply("bid", float(p), float(q))
        for p, q in ev["a"]:
            self.book.apply("ask", float(p), float(q))
        self.prev_u = self.last_update_id = ev["u"]
        return True
