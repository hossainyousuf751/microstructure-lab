"""Study 5: which venue leads? Usage: python 06_cross_venue.py ../data/btcusdt_<stamp>

Needs a recording made with Bybit enabled (the default in 03_record_binance.py).
The estimators are first run on a simulated pair with a known 300 ms delay.
"""

import sys
from pathlib import Path

from _study import DOCS

from lobkit import bucket_features, cross_venue_impact, l1_features, lead_lag, simulate_lob
from lobkit.plotting import plot_lead_lag


def report(a, b, names, freq):
    t = lead_lag(a, b, "50ms", 40)
    peak = t.loc[t["corr"].idxmax()]
    print(f"Lead-lag {names[0]} -> {names[1]}: peak corr {peak['corr']:.3f} at {1000 * peak['lag_s']:+.0f} ms "
          f"(corr at 0 ms: {t.loc[t['lag_s'].abs() < 1e-9, 'corr'].iloc[0]:.3f})")
    c = cross_venue_impact(bucket_features(a, freq=freq), bucket_features(b, freq=freq), names)
    print(f"Order flow and prices, {freq} buckets (R² in-sample; next-bucket R² out of sample):")
    print(c.round(4).to_string(index=False), "\n")
    return t


sim = l1_features(simulate_lob(100_000, seed=11).quotes)
print("[Simulated] venue B is venue A delayed by 300 ms")
sim_table = report(sim, sim.assign(ts=sim["ts"] + 0.3), ("A", "B"), "1s")

if len(sys.argv) > 1:
    from lobkit.recorder import load_recording

    path = Path(sys.argv[1])
    binance = l1_features(load_recording(path, "binance")[0])
    bybit = l1_features(load_recording(path, "bybit")[0])
    span = min(binance["ts"].iloc[-1], bybit["ts"].iloc[-1]) - max(binance["ts"].iloc[0], bybit["ts"].iloc[0])
    print(f"[Live] {path.name}: {span / 60:.0f} minutes, "
          f"{len(binance):,} Binance and {len(bybit):,} Bybit quote updates")
    live_table = report(binance, bybit, ("binance", "bybit"), "1s")
    plot_lead_lag({"simulated, B = A delayed 300 ms": sim_table, "Binance (A) vs Bybit (B), BTCUSDT": live_table},
                  DOCS / "cross_venue_lead_lag.png", "Which venue moves first?")
