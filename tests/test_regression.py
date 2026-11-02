"""Pin README headline numbers to the examples that produce them (same seeds and settings)."""

from pathlib import Path

import pytest

from lobkit import ASParams, bucket_features, impact_by_depth, l1_features, ofi_price_impact, simulate_as, simulate_lob
from lobkit.recorder import load_recording

DATA = Path(__file__).resolve().parent.parent / "data"


def approx(x):
    return pytest.approx(x, rel=1e-10)


def test_study1_simulated_lob_impact():
    """examples/01_simulated_lob.py: simulate_lob(400_000, seed=1, n_levels=5), 10 s buckets."""
    sim = simulate_lob(n_events=400_000, seed=1, n_levels=5)
    assert sim.quotes["ts"].iloc[-1] / 3600 == approx(4.566941528222619)
    assert len(sim.trades) == 30972
    b = bucket_features(l1_features(sim.quotes), sim.trades, "10s")
    fit = ofi_price_impact(b)
    assert (fit.beta, fit.r2, fit.t_stat, fit.n) == approx((0.2846573905428561, 0.6598922992098832,
                                                            56.44362187813568, 1644))
    assert impact_by_depth(b)[1].r2 == approx(0.9290680093563712)


def test_study2_avellaneda_stoikov_table():
    """examples/02_avellaneda_stoikov.py: 4,000 paths, seed 0."""
    want = {(0.01, "inventory"): (66.80377699942281, 8.845334511701571),
            (0.01, "symmetric"): (67.08280332700323, 13.830883199905708),
            (0.1, "inventory"): (63.41819431324369, 6.4041682055384355),
            (0.1, "symmetric"): (66.76599381994905, 13.137002068967709),
            (0.5, "inventory"): (47.318371257131744, 5.773341711119144),
            (0.5, "symmetric"): (57.65382245272602, 11.629483587924508)}
    for (gamma, strategy), (mean, std) in want.items():
        s = simulate_as(ASParams(gamma=gamma), strategy, n_paths=4000, seed=0).summary()
        assert (s["mean_pnl"], s["std_pnl"]) == approx((mean, std))


@pytest.mark.parametrize("symbol, want", [
    ("btcusdt", (0.20327565282844887, 0.59284735319142, 187746, 18463)),
    ("ethusdt", (0.0008053427159352298, 0.6986908642013208, 127805, 14136)),
])
def test_study3_binance_recordings(symbol, want):
    """examples/04_analyze_recording.py on the local 2-hour recordings (git-ignored, so skipped on CI)."""
    path = DATA / f"{symbol}_20261101_042905"
    if not path.exists():
        pytest.skip(f"recording {path.name} not present")
    quotes, trades = load_recording(path)
    f = l1_features(quotes)
    fit = ofi_price_impact(bucket_features(f, trades, "1s"))
    assert (fit.beta, fit.r2, len(f), len(trades)) == approx(want)
