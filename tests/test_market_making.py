import numpy as np
import pytest

from lobkit import ASParams, optimal_spread, reservation_price, simulate_as, simulate_lob
from lobkit.market_making import simulate_as_lob


def test_reservation_price_skews_against_inventory():
    p = ASParams()
    assert reservation_price(100, 0, 0.5, p) == 100
    assert reservation_price(100, 5, 0.5, p) < 100 < reservation_price(100, -5, 0.5, p)


def test_spread_formula_and_decay():
    p = ASParams()
    assert optimal_spread(1.0, p) == pytest.approx(2 / p.gamma * np.log(1 + p.gamma / p.k))
    assert optimal_spread(0.0, p) > optimal_spread(0.9, p)


def test_inventory_strategy_trades_profit_for_lower_risk():
    inv = simulate_as(strategy="inventory", n_paths=2000, seed=1).summary()
    sym = simulate_as(strategy="symmetric", n_paths=2000, seed=1).summary()
    assert inv["std_pnl"] < 0.6 * sym["std_pnl"]
    assert inv["std_final_q"] < 0.5 * sym["std_final_q"]
    assert inv["mean_pnl"] < sym["mean_pnl"]


def test_close_to_published_results():
    # Avellaneda & Stoikov (2008), gamma = 0.1: inventory ~62.9 (std ~5.9), symmetric ~67.2 (~13.4)
    inv = simulate_as(strategy="inventory", n_paths=4000, seed=2).summary()
    sym = simulate_as(strategy="symmetric", n_paths=4000, seed=2).summary()
    assert inv["mean_pnl"] == pytest.approx(62.9, abs=2.0)
    assert sym["mean_pnl"] == pytest.approx(67.2, abs=2.0)
    assert sym["std_pnl"] == pytest.approx(13.4, rel=0.15)


def test_fewer_paths_than_kept_paths():
    r = simulate_as(n_paths=2, keep_paths=5)
    assert r.inventory_paths.shape[0] == 2


def test_quoter_mechanics_in_lob():
    calls = []

    def quoter(t, mid, q):
        calls.append((t, q))
        return mid - 0.5, mid + 0.5                                 # join the best quotes

    r = simulate_lob(20_000, seed=5, quoter=quoter, t_end=500.0)
    assert r.quotes["ts"].iloc[-1] < 500.0
    assert (r.quotes["ask_px"] > r.quotes["bid_px"]).all()         # post-only quotes never cross
    f = r.fills
    assert len(f) > 20
    assert (f["side"] * (f["mid"] - f["price"]) > 0).all()          # bought below the mid, sold above
    for t, q in calls[::50]:                                        # inventory = net fills so far
        assert q == f.loc[f["ts"] <= t, "side"].sum()


def test_inventory_skew_reduces_risk_inside_the_book():
    p = ASParams(T=300.0, sigma=1.08, gamma=0.005, k=1.39, A=0.59)   # as calibrated in examples/05
    inv = simulate_as_lob(p, "inventory", n_episodes=60)
    sym = simulate_as_lob(p, "symmetric", n_episodes=60)
    assert inv["pnl"].std() < 0.5 * sym["pnl"].std()
    assert inv["final_q"].std() < 0.6 * sym["final_q"].std()
    for d in (inv, sym):                                            # fills earn the spread, then lose some of it
        assert d["spread_capture"].mean() > 0.5 and d["adverse_1s"].mean() < 0 and d["adverse_10s"].mean() < 0
