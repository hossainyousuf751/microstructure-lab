"""Cost calibration and bars, the inputs quant-stack hands to a backtester."""

import numpy as np
import pandas as pd
import pytest

from lobkit import bucket_features, calibrate_costs, l1_features, ofi_price_impact, simulate_lob, to_bars


def test_to_bars_by_hand():
    quotes = pd.DataFrame({"ts": [0.2, 0.7, 2.5], "bid_px": [99.0, 100.0, 98.0], "bid_sz": [1.0, 2.0, 1.0],
                           "ask_px": [101.0, 102.0, 100.0], "ask_sz": [1.0, 1.0, 3.0]})
    trades = pd.DataFrame({"ts": [0.5, 2.6, 2.9], "price": [101.0, 98.0, 98.0], "qty": [2.0, 1.0, 0.5],
                           "side": [1, -1, -1]})
    bars = to_bars(l1_features(quotes), "1s", trades)
    assert list(bars.index) == list(pd.to_datetime([1, 2, 3], unit="s"))  # labelled by the bar's end
    np.testing.assert_allclose(bars[["open", "high", "low", "close"]].to_numpy(),
                               [[100, 101, 100, 101], [101, 101, 101, 101], [99, 99, 99, 99]])
    assert list(bars["n_updates"]) == [2, 0, 1]
    np.testing.assert_allclose(bars["spread"], [2.0, 2.0, 2.0])
    np.testing.assert_allclose(bars["volume"], [2.0, 0.0, 1.5])
    np.testing.assert_allclose(bars["signed_volume"], [2.0, 0.0, -1.5])


def test_calibrate_costs_by_hand_and_against_the_impact_regression():
    rng = np.random.default_rng(0)
    n = 2000
    mid = 100 + np.cumsum(rng.choice([-1.0, 0.0, 1.0], n))
    quotes = pd.DataFrame({"ts": np.arange(n) * 0.5, "bid_px": mid - 1, "ask_px": mid + 1,
                           "bid_sz": rng.integers(1, 5, n).astype(float),
                           "ask_sz": rng.integers(1, 5, n).astype(float)})
    trades = pd.DataFrame({"ts": np.arange(0, n * 0.5, 2.0), "price": 100.0, "qty": 3.0, "side": 1})
    c = calibrate_costs(quotes, trades, freq="10s")
    assert c["half_spread_bps"] == pytest.approx(np.median(1 / mid) * 1e4, rel=1e-12)
    assert c["mean_depth"] == pytest.approx(0.5 * (quotes["bid_sz"] + quotes["ask_sz"]).mean(), rel=1e-12)
    assert (c["trade_size_mean"], c["trade_size_median"], c["trade_size_p95"]) == (3.0, 3.0, 3.0)
    seconds = quotes["ts"].iloc[-1] - quotes["ts"].iloc[0]
    assert c["volume_per_sec"] == pytest.approx(3.0 * len(trades) / seconds)
    assert c["trades_per_sec"] == pytest.approx(len(trades) / seconds)
    fit = ofi_price_impact(bucket_features(l1_features(quotes), trades, "10s"))
    assert (c["ofi_impact_beta"], c["ofi_impact_r2"]) == (fit.beta, fit.r2)


def test_calibrate_costs_on_the_simulator_is_plain_floats():
    sim = simulate_lob(n_events=50_000, seed=3)
    c = calibrate_costs(sim.quotes, sim.trades)
    assert all(type(v) is float and np.isfinite(v) for v in c.values())
    assert c["ofi_impact_beta"] > 0 and c["half_spread_bps"] > 0 and c["mid_vol_per_sqrt_sec"] > 0
