"""Diagnostic plots (requires matplotlib)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lobkit.analysis import RegressionResult

C = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]


def _save(fig, ax, path, title):
    ax.set_title(title, fontweight="bold", loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")


def plot_ofi_impact(buckets: pd.DataFrame, fit: RegressionResult, path: str, title: str, unit: str = "ticks"):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(buckets["ofi"], buckets["d_mid"], s=8, alpha=0.35, color=C[0], edgecolor="none")
    x = np.linspace(buckets["ofi"].min(), buckets["ofi"].max(), 50)
    ax.plot(x, fit.alpha + fit.beta * x, color=C[3], lw=2,
            label=f"slope {fit.beta:.3f} {unit}/unit OFI,  R² = {fit.r2:.2f}")
    ax.axhline(0, color="grey", lw=0.6), ax.axvline(0, color="grey", lw=0.6)
    ax.set_xlabel("order-flow imbalance in bucket")
    ax.set_ylabel(f"mid-price change ({unit})")
    ax.legend(frameon=False)
    _save(fig, ax, path, title)
    plt.close(fig)


def plot_imbalance(table: pd.DataFrame, path: str, title: str, min_n: int = 200):
    import matplotlib.pyplot as plt

    t = table[table["n"] >= min_n]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(t["imbalance_mid"], t["p_up"], "o-", color=C[0], lw=2)
    ax.axhline(0.5, color="grey", ls="--", lw=1)
    ax.set_xlabel("queue imbalance  bid size / (bid size + ask size)")
    ax.set_ylabel("P(next mid move is up)")
    ax.set_ylim(0, 1)
    _save(fig, ax, path, title)
    plt.close(fig)


def plot_impact_vs_depth(table: pd.DataFrame, fit: RegressionResult, path: str, title: str):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    inv = 1 / table["mean_depth"]
    ax.plot(inv, table["beta"], "o", ms=8, color=C[0])
    x = np.linspace(0, inv.max() * 1.05, 20)
    ax.plot(x, fit.alpha + fit.beta * x, "--", color=C[3], label=f"linear fit, R² = {fit.r2:.2f}")
    ax.set_xlabel("1 / average depth at best quotes")
    ax.set_ylabel("price impact coefficient β")
    ax.legend(frameon=False)
    _save(fig, ax, path, title)
    plt.close(fig)


def plot_as(results: dict, path: str, title: str):
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
    bins = np.linspace(min(r.pnl.min() for r in results.values()), max(r.pnl.max() for r in results.values()), 50)
    for i, (name, r) in enumerate(results.items()):
        label = f"{name}: mean {r.pnl.mean():.1f}, std {r.pnl.std(ddof=1):.1f}"
        ax1.hist(r.pnl, bins=bins, alpha=0.6, color=C[i], label=label)
        t = np.linspace(0, 1, r.inventory_paths.shape[1])
        ax2.plot(t, r.inventory_paths[0], ["-", "--"][i], color=C[i], lw=1.4, label=name)
    ax1.set_xlabel("terminal P&L"), ax1.set_ylabel("simulations"), ax1.legend(frameon=False)
    ax2.set_xlabel("time / T"), ax2.set_ylabel("inventory (one sample path)"), ax2.legend(frameon=False)
    ax2.spines[["top", "right"]].set_visible(False)
    _save(fig, ax1, path, title)
    plt.close(fig)


def plot_multi_level(table: pd.DataFrame, path: str, title: str):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(table["levels"], table["oos_r2"], "o-", color=C[0], lw=2, label="out-of-sample")
    ax.plot(table["levels"], table["r2"], "s--", color=C[1], lw=1.2, label="in-sample")
    ax.set_xlabel("OFI from the best m price levels")
    ax.set_ylabel("R² of mid-price change")
    ax.set_xticks(table["levels"])
    ax.legend(frameon=False)
    _save(fig, ax, path, title)
    plt.close(fig)


def plot_microprice(adjustment: np.ndarray, path: str, title: str, unit: str = "ticks"):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    n_imb = adjustment.shape[1]
    x = (np.arange(n_imb) + 0.5) / n_imb
    for s, row in enumerate(adjustment):
        ax.plot(x, row, "o-", color=C[s % len(C)], lw=2, label=f"spread {s + 1} tick{'s' if s else ''}")
    ax.plot(x, (x - 0.5), ":", color="grey", label="naive microprice, spread 1 tick")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_xlabel("queue imbalance  bid size / (bid size + ask size)")
    ax.set_ylabel(f"micro-price minus mid ({unit})")
    ax.legend(frameon=False)
    _save(fig, ax, path, title)
    plt.close(fig)


def plot_as_lob(table: pd.DataFrame, path: str, title: str):
    """Per-fill edge by strategy and risk aversion: spread captured, lost to adverse selection, kept."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    labels = [f"γ={g}\n{s}" for g, s in zip(table["gamma"], table["strategy"], strict=True)]
    x = np.arange(len(table))
    ax.bar(x - 0.27, table["spread_capture"], 0.27, color=C[0], label="spread captured")
    ax.bar(x, table["adverse_1s"], 0.27, color=C[1], label="adverse selection after 1 s")
    ax.bar(x + 0.27, table["adverse_10s"], 0.27, color=C[3], label="adverse selection after 10 s")
    ax.plot(x, table["spread_capture"] + table["adverse_10s"], "D", color="black", label="kept after 10 s")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_xticks(x, labels)
    ax.set_ylabel("ticks per fill")
    ax.legend(frameon=False)
    _save(fig, ax, path, title)
    plt.close(fig)


def plot_lead_lag(tables: dict, path: str, title: str):
    """tables: label -> lead_lag() output. A peak right of zero means the first venue leads."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (name, t) in enumerate(tables.items()):
        ax.plot(t["lag_s"] * 1000, t["corr"], "-", color=C[i % len(C)], lw=2, label=name)
        peak = t.loc[t["corr"].idxmax()]
        ax.plot(peak["lag_s"] * 1000, peak["corr"], "o", color=C[i % len(C)])
    ax.axvline(0, color="grey", lw=0.6)
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_xlabel("lag (ms): correlation of venue A's return now with venue B's return this much later")
    ax.set_ylabel("correlation of mid returns")
    ax.legend(frameon=False)
    _save(fig, ax, path, title)
    plt.close(fig)
