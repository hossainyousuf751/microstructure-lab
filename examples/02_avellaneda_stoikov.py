"""Study 2: replicate Avellaneda & Stoikov (2008), Section 4, and sweep risk aversion."""

import pandas as pd
from _study import DOCS

from lobkit import ASParams, simulate_as
from lobkit.plotting import plot_as

rows, results = [], {}
for gamma in (0.01, 0.1, 0.5):
    p = ASParams(gamma=gamma)
    for strategy in ("inventory", "symmetric"):
        r = simulate_as(p, strategy, n_paths=4000, seed=0)
        rows.append({"gamma": gamma, "strategy": strategy, **r.summary()})
        if gamma == 0.1:
            results[strategy] = r

print(pd.DataFrame(rows).round(2).to_string(index=False))
print("\nPublished (gamma = 0.1): inventory ~62.9 (std ~5.9), symmetric ~67.2 (std ~13.4)")
plot_as(results, DOCS / "avellaneda_stoikov.png",
        "Avellaneda-Stoikov (γ = 0.1): inventory skew trades a little profit for much less risk")
