"""Study 1: microstructure analytics on a zero-intelligence order book."""

from _study import run_study

from lobkit import simulate_lob

sim = simulate_lob(n_events=400_000, seed=1, n_levels=5)
print(f"Simulated {sim.quotes['ts'].iloc[-1] / 3600:.1f} hours of trading\n")
run_study(sim.quotes, sim.trades, "Simulated LOB")
