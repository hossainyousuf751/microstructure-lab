"""Study 4: the Avellaneda-Stoikov market maker inside the zero-intelligence order book."""

import pandas as pd
from _study import DOCS

from lobkit import ASParams, simulate_lob
from lobkit.market_making import fill_intensity, optimal_spread, simulate_as_lob
from lobkit.plotting import plot_as_lob

# Calibrate the paper's inputs on the book itself: sigma from 1-second mid changes,
# A and k from fill rates of a quoter resting a fixed distance from the mid.
q = simulate_lob(400_000, seed=1).quotes
mid = pd.Series(0.5 * (q["bid_px"] + q["ask_px"]).to_numpy(), index=pd.to_datetime(q["ts"], unit="s"))
sigma = float(mid.resample("1s").last().ffill().diff().std())
table, A, k = fill_intensity()
print(table.round(4).to_string(index=False))
print(f"\nCalibrated: sigma = {sigma:.3f} ticks per sqrt(s), A = {A:.3f} fills/s, k = {k:.3f} per tick\n")

rows = []
for gamma in (0.001, 0.005, 0.02):
    p = ASParams(T=300.0, sigma=sigma, gamma=gamma, k=k, A=A)
    for strategy in ("inventory", "symmetric"):
        d = simulate_as_lob(p, strategy, n_episodes=200)
        rows.append({"gamma": gamma, "strategy": strategy, "spread_t0": optimal_spread(0, p),
                     "mean_pnl": d["pnl"].mean(), "std_pnl": d["pnl"].std(), "std_final_q": d["final_q"].std(),
                     "fills": d["n_fills"].mean(), "spread_capture": d["spread_capture"].mean(),
                     "adverse_1s": d["adverse_1s"].mean(), "adverse_10s": d["adverse_10s"].mean()})
res = pd.DataFrame(rows)
res["kept_pct"] = 100 * (1 + res["adverse_10s"] / res["spread_capture"])
print(res.round(3).to_string(index=False))
plot_as_lob(res, DOCS / "as_in_lob.png", "Avellaneda-Stoikov inside the order book: adverse selection eats the spread")
