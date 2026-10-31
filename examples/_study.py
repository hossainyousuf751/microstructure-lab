"""Shared analysis, run identically on simulated and live data."""

from pathlib import Path

from lobkit import (
    bucket_features, estimate_microprice, imbalance_next_move, impact_by_depth, l1_features,
    microprice_forecast_error, multi_level_impact, multi_level_ofi, ofi_price_impact, predictive_r2,
)
from lobkit.plotting import (
    plot_imbalance, plot_impact_vs_depth, plot_microprice, plot_multi_level, plot_ofi_impact,
)

DOCS = Path(__file__).resolve().parent.parent / "docs"
DOCS.mkdir(exist_ok=True)


def run_study(quotes, trades, label: str, freq: str = "10s", unit: str = "ticks", tick: float = 1.0):
    f = l1_features(quotes)
    b = bucket_features(f, trades, freq)
    slug = label.lower().replace(" ", "_")
    print(f"[{label}] {len(f):,} book updates, {len(trades):,} trades, {len(b):,} {freq} buckets")
    print(f"  mean spread {f['spread'].mean():.3f}, mean best-queue size {f[['bid_sz', 'ask_sz']].mean().mean():.2f}\n")
    if len(b) < 300:
        print(f"  WARNING: only {len(b)} buckets; results below are noise. Record at least 15 minutes.\n")

    fit = ofi_price_impact(b)
    print(f"Contemporaneous impact: d_mid = {fit.alpha:.4f} + {fit.beta:.4f} * OFI, "
          f"R² = {fit.r2:.3f}, t = {fit.t_stat:.1f}")
    depth_table, depth_fit = impact_by_depth(b)
    print(f"Impact vs depth: beta = {depth_fit.alpha:.3f} + {depth_fit.beta:.3f} / depth, R² = {depth_fit.r2:.2f}")
    print(depth_table.round(3).to_string(index=False), "\n")

    for feats in (["ofi"], ["imbalance"], ["micro_gap"], ["ofi", "imbalance", "trade_imbalance"]):
        if all(c in b for c in feats):
            r = predictive_r2(b, feats)
            print(f"Predict next {freq} mid change from {feats}: OOS R² = {r['oos_r2']:.4f}, "
                  f"hit rate = {r['hit_rate']:.3f} (n = {r['n_test']})")

    imb = imbalance_next_move(f)
    print("\nP(next mid move up | queue imbalance):")
    print(imb[imb["n"] >= 200].round(3).to_string(index=False))

    # Stoikov (2018) micro-price: fit on the first 70% of updates, evaluate on the rest
    split = int(len(f) * 0.7)
    mp = estimate_microprice(f.iloc[:split], tick=tick)
    test = f.iloc[split:].reset_index(drop=True).assign(stoikov=lambda d: mp(d))
    print("\nMicro-price adjustment (ticks), rows = spread 1, 2 ticks, columns = imbalance bucket:")
    print((mp.adjustment / tick).round(3))
    for clock, horizons in (("updates", (1, 10, 100, 1000)), ("moves", (1, 2, 5, 20))):
        print(f"\nForecast of the future mid, out of sample, horizon in {clock}:")
        print(microprice_forecast_error(test, horizons, ("microprice", "stoikov"), clock).round(4)
              .to_string(index=False))

    plot_ofi_impact(b, fit, DOCS / f"{slug}_ofi_impact.png",
                    f"{label}: order-flow imbalance explains price moves", unit)
    plot_imbalance(imb, DOCS / f"{slug}_queue_imbalance.png",
                   f"{label}: queue imbalance predicts the next move")
    plot_impact_vs_depth(depth_table, depth_fit, DOCS / f"{slug}_impact_depth.png",
                         f"{label}: thinner books move more per unit of flow")
    plot_microprice(mp.adjustment / tick, DOCS / f"{slug}_microprice.png",
                    f"{label}: Stoikov micro-price vs the naive weighted mid")
    if "bid_px_2" in quotes:
        run_multi_level(quotes, label, freq)


def run_multi_level(quotes, label: str, freq: str):
    """Multi-level OFI (Xu, Gould & Howison 2019); quotes must carry bid_px_2, ... columns."""
    f = l1_features(quotes).join(multi_level_ofi(quotes))
    t = multi_level_impact(bucket_features(f, freq=freq))
    print(f"\nMulti-level OFI, {freq} buckets: R² of d_mid on OFI from the best 1..{len(t)} levels")
    print(t.round(4).to_string(index=False))
    plot_multi_level(t, DOCS / f"{label.lower().replace(' ', '_')}_multi_level_ofi.png",
                     f"{label}: deeper order flow explains more of the price move")
