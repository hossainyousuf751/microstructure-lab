"""Zero-intelligence limit order book (Cont, Stoikov & Talreja 2010).

Unit-size orders on a tick grid:
  * limit buy (sell) orders arrive i ticks below the best ask (above the best
    bid) at rate lambda(i), i = 1..K;
  * market buy and sell orders arrive at rate mu each;
  * each order resting i ticks from the opposite best is cancelled at rate
    theta(i), so a queue of size Q is cancelled at rate theta(i) * Q.

No agent has information, yet the model reproduces key empirical facts:
order-flow imbalance moves prices linearly, and queue imbalance predicts the
next mid-price move. That makes it a ground truth for testing analytics code.

An optional quoter (e.g. a market maker) can rest one unit on each side. Its
orders join the back of the queue, move up as orders ahead of them trade or
cancel, and fill only when a market order reaches them.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

CST_LAMBDA = (1.85, 1.51, 1.09, 0.88, 0.77)   # orders/second at distance 1..5 ticks
CST_THETA = (0.71, 0.81, 0.68, 0.56, 0.47)    # cancellation rate per resting order
CST_MU = 0.94                                  # market orders/second per side


@dataclass
class SimulationResult:
    quotes: pd.DataFrame   # ts, bid_px, bid_sz, ask_px, ask_sz (+ bid_px_2, ... if n_levels > 1) after every event
    trades: pd.DataFrame   # ts, price, qty, side (+1 buyer-initiated)
    fills: pd.DataFrame | None = None   # quoter's fills: ts, side (+1 quoter bought), price, mid before the fill


# quoter(t, mid, inventory) -> (bid, ask) in price units, or None to stay out of the book
Quoter = Callable[[float, float, int], "tuple[float, float] | None"]


def simulate_lob(n_events: int = 300_000, lam=CST_LAMBDA, theta=CST_THETA, mu: float = CST_MU,
                 initial_depth: int = 3, n_ticks: int = 20_000, tick: float = 1.0,
                 seed: int | None = 0, n_levels: int = 1, quoter: Quoter | None = None,
                 requote_every: float = 1.0, t_end: float | None = None) -> SimulationResult:
    """Simulate up to n_events book events, stopping early at time t_end if given.

    n_levels > 1 also records the 2nd..n-th best non-empty levels. A quoter is
    asked for new quotes every requote_every seconds; its old orders are
    cancelled first, and a quote that would cross the book is placed one tick
    inside it instead (post-only). Without a quoter the random stream, and so
    every result, is the same as before quoters existed.
    """
    rng = random.Random(seed)
    K = len(lam)
    bid = [0] * n_ticks
    ask = [0] * n_ticks
    centre = n_ticks // 2
    for p in range(centre):
        bid[p] = initial_depth
    for p in range(centre + 1, n_ticks):
        ask[p] = initial_depth
    bb, ba = centre - 1, centre + 1
    lam_total = sum(lam)

    ts = np.empty(n_events)
    rec = np.empty((n_events, 4 * n_levels), dtype=np.int64)
    trades, fills = [], []
    t = 0.0
    my_b = my_a = -1                  # quoter's bid / ask level, -1 = none
    ahead_b = ahead_a = inv = 0       # orders queued ahead of it, its inventory
    next_quote = 0.0

    for n in range(n_events):
        if bb < K + 1 or ba > n_ticks - K - 2:
            raise RuntimeError("price walked off the grid; increase n_ticks")
        c_bid = [theta[i] * bid[ba - 1 - i] for i in range(K)]
        c_ask = [theta[i] * ask[bb + 1 + i] for i in range(K)]
        if 0 <= ba - 1 - my_b < K:                          # the quoter's own orders don't cancel randomly
            c_bid[ba - 1 - my_b] -= theta[ba - 1 - my_b]
        if 0 <= my_a - bb - 1 < K:
            c_ask[my_a - bb - 1] -= theta[my_a - bb - 1]
        sc_bid, sc_ask = sum(c_bid), sum(c_ask)
        total = 2 * lam_total + 2 * mu + sc_bid + sc_ask
        t += rng.expovariate(total)
        if t_end is not None and t >= t_end:
            break
        u = rng.random() * total

        if u < lam_total:                                   # limit buy
            for i in range(K):
                u -= lam[i]
                if u < 0:
                    p = ba - 1 - i
                    bid[p] += 1
                    bb = max(bb, p)
                    break
            else:
                bid[ba - K] += 1
        elif (u := u - lam_total) < lam_total:              # limit sell
            for i in range(K):
                u -= lam[i]
                if u < 0:
                    p = bb + 1 + i
                    ask[p] += 1
                    ba = min(ba, p)
                    break
            else:
                ask[bb + K] += 1
        elif (u := u - lam_total) < mu:                     # market buy
            trades.append((t, ba * tick, 1.0, 1))
            if ba == my_a:
                if ahead_a == 0:
                    fills.append((t, -1, ba * tick, (bb + ba) * tick / 2))
                    inv, my_a = inv - 1, -1
                else:
                    ahead_a -= 1
            ask[ba] -= 1
            while ask[ba] == 0:
                ba += 1
        elif (u := u - mu) < mu:                            # market sell
            trades.append((t, bb * tick, 1.0, -1))
            if bb == my_b:
                if ahead_b == 0:
                    fills.append((t, 1, bb * tick, (bb + ba) * tick / 2))
                    inv, my_b = inv + 1, -1
                else:
                    ahead_b -= 1
            bid[bb] -= 1
            while bid[bb] == 0:
                bb -= 1
        elif (u := u - mu) < sc_bid:                        # cancel a bid
            for i in range(K):
                u -= c_bid[i]
                if u < 0:
                    break
            else:                                           # float rounding: never cancel an empty queue
                i = max(j for j in range(K) if c_bid[j] > 0)
            p = ba - 1 - i
            if p == my_b and rng.random() * (bid[p] - 1) < ahead_b:   # the cancelled order was ahead of ours
                ahead_b -= 1
            bid[p] -= 1
            while bid[bb] == 0:
                bb -= 1
        else:                                               # cancel an ask
            u -= sc_bid
            for i in range(K):
                u -= c_ask[i]
                if u < 0:
                    break
            else:
                i = max(j for j in range(K) if c_ask[j] > 0)
            p = bb + 1 + i
            if p == my_a and rng.random() * (ask[p] - 1) < ahead_a:
                ahead_a -= 1
            ask[p] -= 1
            while ask[ba] == 0:
                ba += 1

        if quoter is not None and t >= next_quote:
            next_quote = t + requote_every
            xb, xa = bb, ba                                 # best quotes of everyone else
            if xb == my_b and bid[xb] == 1:
                xb -= 1
                while bid[xb] == 0:
                    xb -= 1
            if xa == my_a and ask[xa] == 1:
                xa += 1
                while ask[xa] == 0:
                    xa += 1
            q = quoter(t, (xb + xa) * tick / 2, inv)
            b = a = -1
            if q is not None:
                b = min(math.floor(q[0] / tick + 1e-9), xa - 1)
                a = max(math.ceil(q[1] / tick - 1e-9), xb + 1)
                if b >= a:
                    b = a = -1
            if b != my_b:                                   # an unchanged level keeps its queue priority
                if my_b >= 0:
                    bid[my_b] -= 1
                    while bid[bb] == 0:
                        bb -= 1
                if b >= 0:
                    ahead_b = bid[b]
                    bid[b] += 1
                    bb = max(bb, b)
                my_b = b
            if a != my_a:
                if my_a >= 0:
                    ask[my_a] -= 1
                    while ask[ba] == 0:
                        ba += 1
                if a >= 0:
                    ahead_a = ask[a]
                    ask[a] += 1
                    ba = min(ba, a)
                my_a = a

        ts[n] = t
        if n_levels == 1:
            rec[n] = (bb, bid[bb], ba, ask[ba])
        else:
            rec[n] = _top_levels(bid, ask, bb, ba, n_levels)

    else:
        n = n_events                                        # no early stop at t_end
    ts, rec = ts[:n], rec[:n]
    quotes = pd.DataFrame({"ts": ts})
    for m in range(n_levels):
        sfx = "" if m == 0 else f"_{m + 1}"
        quotes[f"bid_px{sfx}"] = rec[:, 4 * m] * tick
        quotes[f"bid_sz{sfx}"] = rec[:, 4 * m + 1].astype(float)
        quotes[f"ask_px{sfx}"] = rec[:, 4 * m + 2] * tick
        quotes[f"ask_sz{sfx}"] = rec[:, 4 * m + 3].astype(float)
    trade_df = pd.DataFrame(trades, columns=["ts", "price", "qty", "side"])
    fill_df = pd.DataFrame(fills, columns=["ts", "side", "price", "mid"]) if quoter is not None else None
    return SimulationResult(quotes, trade_df, fill_df)


def _top_levels(bid: list[int], ask: list[int], bb: int, ba: int, n: int) -> list[int]:
    """(bid_px, bid_sz, ask_px, ask_sz) for the n best non-empty levels, flattened."""
    out = []
    for _ in range(n):
        out += [bb, bid[bb], ba, ask[ba]]
        bb -= 1
        while bid[bb] == 0:
            bb -= 1
        ba += 1
        while ask[ba] == 0:
            ba += 1
    return out
