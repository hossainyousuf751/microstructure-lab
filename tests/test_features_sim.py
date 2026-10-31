import numpy as np
import pandas as pd
import pytest

from lobkit import (
    bucket_features, cross_venue_impact, estimate_microprice, imbalance_next_move, impact_by_depth, l1_features,
    lead_lag, microprice_forecast_error, multi_level_impact, multi_level_ofi, ofi_price_impact, order_flow_imbalance,
    simulate_lob,
)


@pytest.fixture(scope="module")
def sim():
    return simulate_lob(150_000, seed=3)


@pytest.fixture(scope="module")
def sim5():
    return simulate_lob(150_000, seed=3, n_levels=5)


def test_ofi_hand_computed_cases():
    q = pd.DataFrame({
        "bid_px": [100, 100, 101, 101, 100],
        "bid_sz": [5, 7, 2, 2, 4],
        "ask_px": [102, 102, 102, 101.5, 101.5],
        "ask_sz": [3, 3, 1, 6, 6],
    })
    # 1: bid queue +2 -> +2 ; 2: bid improves (new queue 2), ask queue 3->1 -> 2 + 2 = 4
    # 3: ask improves to new level with 6 -> -6 ; 4: bid drops a level (old queue 2 gone) -> -2
    np.testing.assert_allclose(order_flow_imbalance(q), [0, 2, 4, -6, -2])


def test_microprice_and_imbalance():
    q = pd.DataFrame({"ts": [0.0], "bid_px": [100.0], "bid_sz": [3.0], "ask_px": [101.0], "ask_sz": [1.0]})
    f = l1_features(q)
    assert f["imbalance"].iloc[0] == pytest.approx(0.75)
    assert f["microprice"].iloc[0] == pytest.approx(100.75)    # leans toward the thin ask


def test_simulator_invariants(sim):
    q = sim.quotes
    assert (q["ask_px"] > q["bid_px"]).all()
    assert (q["bid_sz"] > 0).all() and (q["ask_sz"] > 0).all()
    assert q["ts"].is_monotonic_increasing
    assert set(sim.trades["side"]) == {-1, 1}


def test_simulator_is_reproducible():
    a, b = simulate_lob(2_000, seed=9), simulate_lob(2_000, seed=9)
    pd.testing.assert_frame_equal(a.quotes, b.quotes)


def test_ofi_explains_price_changes(sim):
    b = bucket_features(l1_features(sim.quotes), sim.trades, "10s")
    fit = ofi_price_impact(b)
    assert fit.beta > 0 and fit.r2 > 0.4


def test_impact_falls_with_depth(sim):
    b = bucket_features(l1_features(sim.quotes), freq="10s")
    _, fit = impact_by_depth(b)
    assert fit.beta > 0


def test_queue_imbalance_predicts_next_move(sim):
    t = imbalance_next_move(l1_features(sim.quotes))
    t = t[t["n"] >= 200]
    assert t["p_up"].is_monotonic_increasing
    assert t["p_up"].iloc[0] < 0.4 and t["p_up"].iloc[-1] > 0.6


def test_empty_bucket_does_not_drop_next_move():
    q = pd.DataFrame({"ts": [0.0, 1.0, 25.0], "bid_px": [100.0, 100, 101], "bid_sz": [1.0, 1, 1],
                      "ask_px": [102.0, 102, 103], "ask_sz": [1.0, 1, 1]})
    b = bucket_features(l1_features(q), freq="10s")               # bucket 10-20 s is empty
    assert b["d_mid"].tolist() == [0.0, 1.0]                        # kept, flat; the move is not lost
    assert b["ofi"].iloc[0] == 0 and b["n_updates"].iloc[0] == 0
    assert (b.index.to_series().diff().dropna() == pd.Timedelta("10s")).all()   # next row = next interval


def test_multi_level_simulation_and_ofi():
    one, five = simulate_lob(3_000, seed=4), simulate_lob(3_000, seed=4, n_levels=5)
    pd.testing.assert_frame_equal(one.quotes, five.quotes[one.quotes.columns])   # level 1 unchanged
    q = five.quotes
    for m, prev in zip(range(2, 6), ["", "_2", "_3", "_4"], strict=True):
        assert (q[f"bid_px_{m}"] < q[f"bid_px{prev}"]).all() and (q[f"ask_px_{m}"] > q[f"ask_px{prev}"]).all()
        assert (q[f"bid_sz_{m}"] > 0).all() and (q[f"ask_sz_{m}"] > 0).all()
    ofi = multi_level_ofi(q)
    assert list(ofi.columns) == [f"ofi_{m}" for m in range(1, 6)]
    np.testing.assert_allclose(ofi["ofi_1"], order_flow_imbalance(q))


def test_deeper_levels_explain_more_out_of_sample(sim5):
    f = l1_features(sim5.quotes).join(multi_level_ofi(sim5.quotes))
    t = multi_level_impact(bucket_features(f, freq="10s"))
    assert t["oos_r2"].iloc[-1] > t["oos_r2"].iloc[0] + 0.1


def test_forecast_error_moves_clock_hand_case():
    f = pd.DataFrame({"mid": [0.0, 0, 1, 1, 1, 3], "microprice": [1.0, 1, 3, 3, 3, 3]})
    t = microprice_forecast_error(f, horizons=(1,), clock="moves")
    assert t["mse_mid"].iloc[0] == pytest.approx((1 + 1 + 4 + 4 + 4) / 5)
    assert t["improvement_microprice_pct"].iloc[0] == pytest.approx(100)    # a perfect forecast


def test_stoikov_microprice_shape_and_skill(sim5):
    f = l1_features(sim5.quotes)
    split = int(len(f) * 0.7)
    mp = estimate_microprice(f.iloc[:split])
    adj = mp.adjustment[0, 1:-1]                                   # spread 1 tick, visited buckets
    assert np.isnan(mp.adjustment[0, [0, -1]]).all()               # extreme imbalance never seen at 1 tick
    assert np.all(np.diff(adj) > 0)                                 # more bid depth -> higher price
    assert np.all(np.abs(adj) < 0.5)                                # stays inside the spread
    np.testing.assert_allclose(adj, -adj[::-1], atol=1e-9)          # symmetric by construction
    test = f.iloc[split:].reset_index(drop=True).assign(stoikov=lambda d: mp(d))
    t = microprice_forecast_error(test, (1,), ("microprice", "stoikov"), clock="moves")
    assert t["improvement_stoikov_pct"].iloc[0] > max(2.0, t["improvement_microprice_pct"].iloc[0])


def test_cross_venue_estimators_recover_a_known_delay():
    a = l1_features(simulate_lob(30_000, seed=6).quotes)
    b = a.assign(ts=a["ts"] + 0.3)                                  # venue b copies venue a 300 ms late
    t = lead_lag(a, b, "50ms", 20)
    assert t.loc[t["corr"].idxmax(), "lag_s"] == pytest.approx(0.3)
    c = cross_venue_impact(bucket_features(a, freq="1s"), bucket_features(b, freq="1s"), ("a", "b"))
    c = c.set_index("target")
    assert c.loc["b", "next_oos_r2_other_d_mid"] > 0.1             # the leader's move predicts the follower's
    assert c.loc["a", "next_oos_r2_other_d_mid"] < 0.02            # but not the other way round
    assert c.loc["b", "r2_other_ofi"] < c.loc["b", "r2_own_ofi"]


def test_microprice_handles_an_empty_book(sim5):
    f = l1_features(sim5.quotes.iloc[:20_000])
    mp = estimate_microprice(f)
    g = f.iloc[:3].copy()
    g.loc[g.index[0], ["imbalance"]] = np.nan                       # both best sizes 0
    out = mp(g)
    assert out.iloc[0] == g["mid"].iloc[0] and np.isfinite(out).all()
