"""Record live spot market data from Binance and Bybit (requires `pip install -e '.[live]'`).

Binance, three streams on one websocket:
  <sym>@bookTicker      every best bid/ask change      -> l1.csv
  <sym>@aggTrade        trades with aggressor side     -> trades.csv
  <sym>@depth@100ms     L2 diffs, synchronised with a  -> depth.csv (top N levels, sampled;
                        REST snapshot via              load with load_depth)
                        BinanceDepthSync
Bybit (optional, same session and clock, for cross-venue studies):
  orderbook.1.<SYM>     best bid/ask                   -> bybit_l1.csv
  publicTrade.<SYM>     trades with aggressor side     -> bybit_trades.csv

Timestamps: `ts` is the local receive time for quotes on both venues, so the
two venues share one clock; trades carry the exchange time in `ts` and the
local time in `ts_local`. A dropped connection is reopened automatically (and
the Binance depth book resynchronised); the count is printed at the end.
Binance may be unavailable in some jurisdictions; adjust WS_BASE/REST_BASE
(e.g. to Binance.US endpoints) if needed.
"""

from __future__ import annotations

import asyncio
import csv
import json
import time
from pathlib import Path

import pandas as pd

from lobkit.book import BinanceDepthSync, SequenceGap

WS_BASE = "wss://stream.binance.com:9443"
REST_BASE = "https://api.binance.com"
BYBIT_WS = "wss://stream.bybit.com/v5/public/spot"

L1_HEADER = ["ts", "update_id", "bid_px", "bid_sz", "ask_px", "ask_sz"]
TRADES_HEADER = ["ts", "ts_local", "price", "qty", "side"]


def _fetch_snapshot(symbol: str, limit: int = 1000) -> dict:
    import requests

    r = requests.get(f"{REST_BASE}/api/v3/depth", params={"symbol": symbol.upper(), "limit": limit}, timeout=10)
    r.raise_for_status()
    return r.json()


def _writer(out: Path, name: str, header: list[str], files: list):
    f = open(out / f"{name}.csv", "w", newline="")    # closed by record_binance
    files.append(f)
    w = csv.writer(f)
    w.writerow(header)
    return w


async def record_binance(symbol: str = "btcusdt", seconds: int = 900, out_dir: str | Path = "data",
                         depth_levels: int = 10, depth_every: float = 1.0, bybit: bool = False) -> Path:
    """Record `seconds` of data into out_dir/<symbol>_<timestamp>/; bybit=True adds the Bybit streams."""
    sym = symbol.lower()
    out = Path(out_dir) / f"{sym}_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    t_end = time.time() + seconds
    files: list = []
    try:
        jobs = [_binance(sym, t_end, out, depth_levels, depth_every, files)]
        if bybit:
            jobs.append(_bybit(sym.upper(), t_end, out, files))
        for line in await asyncio.gather(*jobs):
            print(line)
    finally:
        for f in files:
            f.close()
    print(f"recorded to {out}")
    return out


async def _recv(ws) -> tuple[dict, float]:
    """Next message and its arrival time. The clock is read after recv() returns, never before:
    a time taken before waiting would stamp each message with the previous one's arrival."""
    raw = await asyncio.wait_for(ws.recv(), timeout=30)
    return json.loads(raw), time.time()


async def _reconnecting(name: str, url: str, t_end: float, session) -> int:
    """Run session(ws) until t_end, reopening the connection if it drops. Returns the reconnect count."""
    import websockets

    reconnects = -1
    while time.time() < t_end:
        reconnects += 1
        try:
            async with websockets.connect(url, max_size=None, ping_interval=20) as ws:
                await session(ws)
        except (websockets.ConnectionClosed, asyncio.TimeoutError, OSError) as e:
            print(f"{name}: connection lost ({e!r}); reconnecting")
            await asyncio.sleep(1)
    return max(reconnects, 0)


async def _binance(sym: str, t_end: float, out: Path, depth_levels: int, depth_every: float, files: list) -> str:
    l1 = _writer(out, "l1", L1_HEADER, files)
    trades = _writer(out, "trades", TRADES_HEADER, files)
    depth = _writer(out, "depth", ["ts", "side", "level", "price", "qty"], files)
    resyncs = 0

    async def session(ws):
        nonlocal resyncs
        sync, snapshot_task, last_depth, retry_at = BinanceDepthSync(), None, 0.0, 0.0   # fresh book per connection
        while time.time() < t_end:
            msg, now = await _recv(ws)
            stream, d = msg["stream"], msg["data"]
            if not stream.endswith("@depth@100ms"):
                name, row = _binance_row(stream, d, now)
                (l1 if name == "l1" else trades).writerow(row)
            else:
                try:
                    sync.on_event(d)
                    if snapshot_task is not None and snapshot_task.done():
                        task, snapshot_task = snapshot_task, None
                        if task.exception() is not None:
                            print(f"snapshot fetch failed: {task.exception()!r}; retrying in 5 s")
                            retry_at = now + 5    # don't hammer the REST API (rate limits, IP bans)
                        else:
                            sync.on_snapshot(task.result())    # False = too old; refetched below
                except SequenceGap:                # from the stream, or replaying the buffer
                    resyncs += 1
                    if snapshot_task is not None:
                        snapshot_task.cancel()     # its snapshot belongs to the abandoned book
                    sync, snapshot_task = BinanceDepthSync(), None
                    sync.on_event(d)
                if not sync.synced and snapshot_task is None and now >= retry_at:
                    snapshot_task = asyncio.create_task(asyncio.to_thread(_fetch_snapshot, sym))
                if sync.synced and now - last_depth >= depth_every:
                    last_depth = now
                    for side in ("bid", "ask"):
                        for lvl, (p, q) in enumerate(sync.book.levels(side, depth_levels)):
                            depth.writerow([now, side, lvl, p, q])

    url = f"{WS_BASE}/stream?streams={sym}@bookTicker/{sym}@aggTrade/{sym}@depth@100ms"
    reconnects = await _reconnecting("binance", url, t_end, session)
    return f"binance: {resyncs} depth resyncs, {reconnects} reconnects"


async def _bybit(sym: str, t_end: float, out: Path, files: list) -> str:
    l1 = _writer(out, "bybit_l1", L1_HEADER, files)
    trades = _writer(out, "bybit_trades", TRADES_HEADER, files)

    async def session(ws):
        await ws.send(json.dumps({"op": "subscribe", "args": [f"orderbook.1.{sym}", f"publicTrade.{sym}"]}))
        book = {"bid": None, "ask": None}                  # fresh best quotes per connection
        last_ping = time.time()
        while time.time() < t_end:
            if time.time() - last_ping > 20:               # Bybit drops connections without app-level pings
                await ws.send(json.dumps({"op": "ping"}))
                last_ping = time.time()
            msg, now = await _recv(ws)
            for name, row in _bybit_rows(msg, book, now):
                (l1 if name == "l1" else trades).writerow(row)

    reconnects = await _reconnecting("bybit", BYBIT_WS, t_end, session)
    return f"bybit: {reconnects} reconnects"


def _binance_row(stream: str, d: dict, now: float) -> tuple[str, list]:
    """("l1" | "trades", csv row) for a bookTicker or aggTrade message."""
    if stream.endswith("@bookTicker"):
        return "l1", [now, d["u"], d["b"], d["B"], d["a"], d["A"]]
    return "trades", [d["T"] / 1000, now, d["p"], d["q"], -1 if d["m"] else 1]    # m: buyer is maker


def _bybit_rows(msg: dict, book: dict, now: float) -> list[tuple[str, list]]:
    """CSV rows for one Bybit message; book holds the current best bid/ask and is updated.

    A snapshot replaces both sides (an empty side means no quote); a delta only
    replaces the sides it carries. No L1 row is written while a side is missing.
    """
    topic = msg.get("topic", "")
    if topic.startswith("orderbook"):
        d = msg["data"]
        for side, key in (("bid", "b"), ("ask", "a")):
            if d[key] or msg.get("type") == "snapshot":
                top = d[key][0] if d[key] else None
                book[side] = top if top and float(top[1]) > 0 else None     # size 0 = level deleted
        bid, ask = book["bid"], book["ask"]
        return [("l1", [now, d["u"], bid[0], bid[1], ask[0], ask[1]])] if bid and ask else []
    if topic.startswith("publicTrade"):
        return [("trades", [tr["T"] / 1000, now, tr["p"], tr["v"], 1 if tr["S"] == "Buy" else -1])
                for tr in msg["data"]]                                  # S: taker side
    if msg.get("success") is False:
        raise RuntimeError(f"bybit subscription failed: {msg}")
    return []                                                           # pong, subscription ack


def load_recording(path: str | Path, venue: str = "binance") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (quotes, trades) in lobkit's standard format for venue "binance" or "bybit".

    Trades are stamped with their local receive time, the clock the quotes use:
    the local clock can be off the exchange's by a second or more, which would
    misalign trade and quote buckets.
    """
    prefix = {"binance": "", "bybit": "bybit_"}[venue]
    path = Path(path)
    quotes = pd.read_csv(path / f"{prefix}l1.csv").drop(columns="update_id")
    trades = pd.read_csv(path / f"{prefix}trades.csv")
    trades = trades.assign(ts=trades["ts_local"]).drop(columns="ts_local")
    changed = quotes[["bid_px", "bid_sz", "ask_px", "ask_sz"]].diff().abs().sum(axis=1) > 0
    changed.iloc[0] = True
    return quotes[changed].reset_index(drop=True), trades


def load_depth(path: str | Path) -> pd.DataFrame:
    """Return the sampled L2 snapshots as a quotes frame with levels bid_px, ..., bid_px_2, ..."""
    d = pd.read_csv(Path(path) / "depth.csv")
    w = d.pivot(index="ts", columns=["side", "level"], values=["price", "qty"]).dropna()
    out = pd.DataFrame({"ts": w.index.to_numpy()})
    for lvl in sorted(d["level"].unique()):
        sfx = "" if lvl == 0 else f"_{lvl + 1}"
        for side in ("bid", "ask"):
            out[f"{side}_px{sfx}"] = w[("price", side, lvl)].to_numpy()
            out[f"{side}_sz{sfx}"] = w[("qty", side, lvl)].to_numpy()
    return out
