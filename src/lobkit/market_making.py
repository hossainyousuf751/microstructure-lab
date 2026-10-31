"""Avellaneda & Stoikov (2008), "High-frequency trading in a limit order book".

A market maker with CARA utility (risk aversion gamma) quotes around a
reservation price that is skewed against inventory:
    r = s - q * gamma * sigma^2 * (T - t)
with total spread
    delta_a + delta_b = gamma * sigma^2 * (T - t) + (2 / gamma) * ln(1 + gamma / k).
Fills arrive with intensity A * exp(-k * delta), delta = distance from mid.

simulate_as replicates the paper, where that fill model holds by construction.
simulate_as_lob runs the same quotes inside the zero-intelligence order book,
where fills depend on queue position and arrive just before adverse moves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lobkit.simulator import Quoter, simulate_lob


@dataclass(frozen=True)
class ASParams:
    s0: float = 100.0
    T: float = 1.0
    sigma: float = 2.0
    dt: float = 0.005
    gamma: float = 0.1
    k: float = 1.5
    A: float = 140.0


def reservation_price(s, q, t, p: ASParams):
    return s - q * p.gamma * p.sigma**2 * (p.T - t)


def optimal_spread(t, p: ASParams):
    return p.gamma * p.sigma**2 * (p.T - t) + 2 / p.gamma * np.log(1 + p.gamma / p.k)


@dataclass
class ASResult:
    pnl: np.ndarray
    final_inventory: np.ndarray
    inventory_paths: np.ndarray    # (n_keep, n_steps + 1)
    mid_paths: np.ndarray
    mean_spread: float

    def summary(self) -> dict:
        return {"mean_pnl": float(self.pnl.mean()), "std_pnl": float(self.pnl.std(ddof=1)),
                "mean_final_q": float(self.final_inventory.mean()),
                "std_final_q": float(self.final_inventory.std(ddof=1)),
                "mean_spread": self.mean_spread}


def simulate_as(p: ASParams = ASParams(), strategy: str = "inventory", n_paths: int = 1000,
                seed: int | None = 0, keep_paths: int = 5) -> ASResult:
    """Monte Carlo of the paper's experiment.

    strategy="inventory": quotes centred on the reservation price.
    strategy="symmetric": same spread, centred on the mid (ignores inventory).
    """
    _check_strategy(strategy)
    rng = np.random.default_rng(seed)
    n_steps = round(p.T / p.dt)
    keep_paths = min(keep_paths, n_paths)
    s = np.full(n_paths, p.s0)
    q = np.zeros(n_paths)
    cash = np.zeros(n_paths)
    inv = np.zeros((keep_paths, n_steps + 1))
    mids = np.zeros((keep_paths, n_steps + 1))
    mids[:, 0] = p.s0
    spreads = []

    for i in range(n_steps):
        t = i * p.dt
        spread = optimal_spread(t, p)
        spreads.append(spread)
        centre = reservation_price(s, q, t, p) if strategy == "inventory" else s
        bid, ask = centre - spread / 2, centre + spread / 2
        # The mid moves while quotes rest, and fills are judged against the new mid.
        # This builds in adverse selection: quotes the price moved through fill more often.
        s = s + p.sigma * np.sqrt(p.dt) * np.where(rng.random(n_paths) < 0.5, 1.0, -1.0)
        p_ask = np.clip(p.A * np.exp(-p.k * (ask - s)) * p.dt, 0, 1)
        p_bid = np.clip(p.A * np.exp(-p.k * (s - bid)) * p.dt, 0, 1)
        sold = rng.random(n_paths) < p_ask
        bought = rng.random(n_paths) < p_bid
        q += bought.astype(float) - sold
        cash += sold * ask - bought * bid
        inv[:, i + 1], mids[:, i + 1] = q[:keep_paths], s[:keep_paths]

    return ASResult(cash + q * s, q, inv, mids, float(np.mean(spreads)))


def _check_strategy(strategy: str) -> None:
    if strategy not in ("inventory", "symmetric"):
        raise ValueError("strategy must be 'inventory' or 'symmetric'")


def as_quoter(p: ASParams, strategy: str = "inventory") -> Quoter:
    """Avellaneda-Stoikov quotes as a simulate_lob quoter; t and p.T in seconds, prices in ticks."""
    _check_strategy(strategy)

    def quote(t: float, mid: float, q: int) -> tuple[float, float]:
        t = min(t, p.T)
        centre = reservation_price(mid, q, t, p) if strategy == "inventory" else mid
        half = optimal_spread(t, p) / 2
        return centre - half, centre + half

    return quote


def simulate_as_lob(p: ASParams, strategy: str = "inventory", n_episodes: int = 100, requote_every: float = 1.0,
                    markouts=(1.0, 10.0), seed: int = 0, **lob_kwargs) -> pd.DataFrame:
    """The Avellaneda-Stoikov market maker inside simulate_lob, one row per episode of p.T seconds.

    p.sigma, p.k and p.T must be in the book's units (ticks, seconds); p.s0 is
    unused. Columns:
      pnl                cash + final inventory marked at the final mid
      final_q, n_fills
      spread_capture     mean over fills of side * (mid - fill price): what the quote earned on the spot
      adverse_<m>s       mean over fills of side * (mid m seconds later - mid at fill), for m in markouts;
                         fills less than m seconds before the episode ends are left out
    """
    quoter = as_quoter(p, strategy)
    rows = []
    for e in range(n_episodes):
        n_max = int(100 * p.T) + 1000                     # far above the ~25 events/s of the default book
        r = simulate_lob(n_max, seed=seed + e, quoter=quoter, requote_every=requote_every, t_end=p.T, **lob_kwargs)
        if len(r.quotes) == n_max:
            raise RuntimeError("episode ran out of events before p.T; the book is busier than expected")
        f, q = r.fills, r.quotes
        mid = 0.5 * (q["bid_px"] + q["ask_px"]).to_numpy()
        side = f["side"].to_numpy()
        row = {
            "pnl": float(-(side * f["price"]).sum() + side.sum() * mid[-1]),
            "final_q": int(side.sum()),
            "n_fills": len(f),
            "spread_capture": float(np.mean(side * (f["mid"] - f["price"]))) if len(f) else np.nan,
        }
        for m in markouts:
            full = (f["ts"] + m <= p.T).to_numpy()
            later = mid[np.searchsorted(q["ts"], f["ts"][full] + m) - 1]
            row[f"adverse_{m:g}s"] = float(np.mean(side[full] * (later - f["mid"][full]))) if full.any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def fill_intensity(deltas=(0.5, 1.0, 1.5, 2.0, 2.5, 3.0), t_end: float = 3000.0, seed: int = 7,
                   **lob_kwargs) -> tuple[pd.DataFrame, float, float]:
    """Calibrate the paper's fill model A * exp(-k * delta) on simulate_lob.

    A quoter rests one unit delta from the mid on each side, requoting every
    second; fills per second per side are regressed in logs on delta.
    Returns (table, A, k).
    """
    rows = []
    for d in deltas:
        r = simulate_lob(int(100 * t_end) + 1000, seed=seed, quoter=lambda t, m, q, d=d: (m - d, m + d),
                         t_end=t_end, **lob_kwargs)
        rows.append({"delta": d, "fills_per_s": len(r.fills) / 2 / t_end})
    table = pd.DataFrame(rows)
    ok = table["fills_per_s"] > 0
    slope, intercept = np.polyfit(table["delta"][ok], np.log(table["fills_per_s"][ok]), 1)
    return table, float(np.exp(intercept)), float(-slope)
