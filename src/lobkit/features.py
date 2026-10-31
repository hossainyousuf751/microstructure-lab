"""Top-of-book features and order-flow imbalance (Cont, Kukanov & Stoikov 2014).

Input quotes: columns ts (seconds), bid_px, bid_sz, ask_px, ask_sz, one row
per book update; deeper levels, if any, as bid_px_2, bid_sz_2, ask_px_2, ...
Trades: ts, price, qty, side (+1 buyer-initiated).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def order_flow_imbalance(quotes: pd.DataFrame) -> np.ndarray:
    """Per-update OFI contribution e_n.

    e_n =  1{Pb_n >= Pb_n-1} qb_n - 1{Pb_n <= Pb_n-1} qb_n-1
         - 1{Pa_n <= Pa_n-1} qa_n + 1{Pa_n >= Pa_n-1} qa_n-1

    Positive values mean net buying pressure: bids added or asks removed.
    """
    pb, qb = quotes["bid_px"].to_numpy(), quotes["bid_sz"].to_numpy()
    pa, qa = quotes["ask_px"].to_numpy(), quotes["ask_sz"].to_numpy()
    e = np.zeros(len(quotes))
    e[1:] = ((pb[1:] >= pb[:-1]) * qb[1:] - (pb[1:] <= pb[:-1]) * qb[:-1]
             - (pa[1:] <= pa[:-1]) * qa[1:] + (pa[1:] >= pa[:-1]) * qa[:-1])
    return e


def multi_level_ofi(quotes: pd.DataFrame) -> pd.DataFrame:
    """OFI at each recorded level, columns ofi_1..ofi_M (Xu, Gould & Howison 2019, Section 2).

    Level m is the m-th best non-empty price level, and its OFI applies the
    Cont et al. formula to that level's prices and sizes.
    """
    n_levels = 1 + sum(c.startswith("bid_px_") for c in quotes.columns)
    out = {}
    for m in range(1, n_levels + 1):
        sfx = "" if m == 1 else f"_{m}"
        cols = {f"{k}{sfx}": k for k in ("bid_px", "bid_sz", "ask_px", "ask_sz")}
        out[f"ofi_{m}"] = order_flow_imbalance(quotes[list(cols)].rename(columns=cols))
    return pd.DataFrame(out, index=quotes.index)


def l1_features(quotes: pd.DataFrame) -> pd.DataFrame:
    q = quotes.reset_index(drop=True).copy()
    depth = q["bid_sz"] + q["ask_sz"]
    q["mid"] = 0.5 * (q["bid_px"] + q["ask_px"])
    q["spread"] = q["ask_px"] - q["bid_px"]
    q["imbalance"] = q["bid_sz"] / depth                      # 1 = all depth on the bid
    q["microprice"] = (q["bid_px"] * q["ask_sz"] + q["ask_px"] * q["bid_sz"]) / depth
    q["ofi"] = order_flow_imbalance(q)
    return q


def bucket_features(features: pd.DataFrame, trades: pd.DataFrame | None = None,
                    freq: str = "10s") -> pd.DataFrame:
    """Aggregate per-update features into fixed time buckets.

    d_mid is the change in mid from the end of the previous bucket to the end
    of this one, so it lines up with the OFI accumulated inside the bucket.
    A bucket with no updates is kept, with zero flow and the book state carried
    forward, so rows form a regular time grid: the next row is the next interval.
    """
    f = features.set_index(pd.to_datetime(features["ts"], unit="s"))
    g = f.resample(freq)
    out = pd.DataFrame({
        "ofi": g["ofi"].sum(),
        "mid": g["mid"].last(),
        "depth": (0.5 * (f["bid_sz"] + f["ask_sz"])).resample(freq).mean(),
        "spread": g["spread"].mean(),
        "imbalance": g["imbalance"].last(),
        "micro_gap": (f["microprice"] - f["mid"]).resample(freq).last(),
        "n_updates": g.size(),
    })
    for c in f.columns:
        if c.startswith("ofi_"):                              # multi-level OFI, if computed
            out[c] = g[c].sum()
    state = ["mid", "depth", "spread", "imbalance", "micro_gap"]
    out[state] = out[state].ffill()                           # empty bucket: the book did not change
    out["d_mid"] = out["mid"].diff()
    if trades is not None and len(trades):
        t = trades.set_index(pd.to_datetime(trades["ts"], unit="s"))
        out["trade_imbalance"] = (t["side"] * t["qty"]).resample(freq).sum().reindex(out.index).fillna(0.0)
    return out.dropna()
