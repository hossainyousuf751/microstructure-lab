"""Price impact and short-horizon predictability."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RegressionResult:
    alpha: float
    beta: float
    t_stat: float
    r2: float
    n: int


def _ols(x, y) -> RegressionResult:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    X = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n = len(y)
    s2 = resid @ resid / (n - 2)
    se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    r2 = 1 - resid @ resid / np.sum((y - y.mean()) ** 2)
    return RegressionResult(float(coef[0]), float(coef[1]), float(coef[1] / se), float(r2), n)


def ofi_price_impact(buckets: pd.DataFrame) -> RegressionResult:
    """Contemporaneous regression d_mid = alpha + beta * OFI (Cont et al. 2014, eq. 3)."""
    return _ols(buckets["ofi"], buckets["d_mid"])


def impact_by_depth(buckets: pd.DataFrame, n_groups: int = 5) -> tuple[pd.DataFrame, RegressionResult]:
    """Impact coefficient per depth quantile, and beta regressed on 1/depth.

    Cont et al. find beta is inversely proportional to market depth: the same
    order flow moves a thin book further.
    """
    b = buckets.assign(group=pd.qcut(buckets["depth"], n_groups, labels=False, duplicates="drop"))
    rows = []
    for g, s in b.groupby("group"):
        r = _ols(s["ofi"], s["d_mid"])
        rows.append({"group": g, "mean_depth": s["depth"].mean(), "beta": r.beta, "r2": r.r2, "n": r.n})
    table = pd.DataFrame(rows)
    return table, _ols(1 / table["mean_depth"], table["beta"])


def predictive_r2(buckets: pd.DataFrame, features: list[str], horizon: int = 1,
                  train_frac: float = 0.7) -> dict:
    """Predict the NEXT bucket's mid change from this bucket's features.

    Chronological split; out-of-sample R^2 is measured against the training
    mean, so a positive value means genuine predictive content.
    """
    df = buckets[features].assign(target=buckets["d_mid"].shift(-horizon)).dropna()
    split = int(len(df) * train_frac)
    train, test = df.iloc[:split], df.iloc[split:]
    X_tr = np.column_stack([np.ones(len(train)), train[features]])
    X_te = np.column_stack([np.ones(len(test)), test[features]])
    coef, *_ = np.linalg.lstsq(X_tr, train["target"], rcond=None)
    pred = X_te @ coef
    y = test["target"].to_numpy()
    sse, sst = np.sum((y - pred) ** 2), np.sum((y - train["target"].mean()) ** 2)
    moving = y != 0
    hit = np.mean(np.sign(pred[moving]) == np.sign(y[moving])) if moving.any() else np.nan
    return {"oos_r2": float(1 - sse / sst), "hit_rate": float(hit), "n_test": len(test),
            "coef": dict(zip(["const", *features], map(float, coef), strict=True))}


def imbalance_next_move(features: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    """P(next mid move is up | queue imbalance), as in Gould & Bonart (2016)."""
    sign = np.sign(features["mid"].diff())
    next_sign = sign.where(sign != 0).shift(-1).bfill()
    df = pd.DataFrame({"imbalance": features["imbalance"], "next_up": next_sign > 0,
                       "valid": next_sign.notna()})
    df = df[df["valid"]]
    df["bin"] = pd.cut(df["imbalance"], np.linspace(0, 1, n_bins + 1), include_lowest=True)
    out = df.groupby("bin", observed=True).agg(p_up=("next_up", "mean"), n=("next_up", "size"))
    out["imbalance_mid"] = [iv.mid for iv in out.index]
    return out.reset_index(drop=True)


def multi_level_impact(buckets: pd.DataFrame, train_frac: float = 0.7) -> pd.DataFrame:
    """Explain d_mid with the OFI of the best 1, 2, ..., M levels (Xu, Gould & Howison 2019).

    In-sample R^2 can only rise as levels are added, so the fair comparison is
    the out-of-sample R^2 on a chronological split.
    """
    cols = sorted((c for c in buckets.columns if c.startswith("ofi_")), key=lambda c: int(c[4:]))
    y = buckets["d_mid"].to_numpy(dtype=float)
    split = int(len(y) * train_frac)
    rows = []
    for m in range(1, len(cols) + 1):
        X = np.column_stack([np.ones(len(y)), buckets[cols[:m]]])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        r2 = 1 - np.sum((y - X @ coef) ** 2) / np.sum((y - y.mean()) ** 2)
        coef, *_ = np.linalg.lstsq(X[:split], y[:split], rcond=None)
        oos = 1 - np.sum((y[split:] - X[split:] @ coef) ** 2) / np.sum((y[split:] - y[:split].mean()) ** 2)
        rows.append({"levels": m, "r2": float(r2), "oos_r2": float(oos)})
    return pd.DataFrame(rows)


def microprice_forecast_error(features: pd.DataFrame, horizons=(1, 10, 100, 1000),
                              predictors=("microprice",), clock: str = "updates") -> pd.DataFrame:
    """Do the predictor columns forecast the future mid better than the mid itself?

    clock="updates": the mid h book updates ahead.
    clock="moves":   the mid just after the h-th future mid change, the horizon
                     Stoikov's (2018) micro-price is built for.
    improvement_<p>_pct > 0 means a lower mean squared error than the mid.
    """
    if clock not in ("updates", "moves"):
        raise ValueError("clock must be 'updates' or 'moves'")
    mid = features["mid"].to_numpy(dtype=float)
    rows_idx = np.arange(len(mid))
    changes = np.flatnonzero(np.diff(mid) != 0) + 1
    next_change = np.searchsorted(changes, rows_idx, side="right")
    rows = []
    for h in horizons:
        if clock == "updates":
            target = rows_idx + h
            ok = target < len(mid)
            future = mid[target[ok]]
        else:
            j = next_change + h - 1
            ok = j < len(changes)
            future = mid[changes[j[ok]]]
        mse_mid = np.mean((future - mid[ok]) ** 2)
        row = {f"horizon_{clock}": h, "mse_mid": mse_mid}
        for c in predictors:
            mse = np.mean((future - features[c].to_numpy(dtype=float)[ok]) ** 2)
            row[f"mse_{c}"], row[f"improvement_{c}_pct"] = mse, 100 * (1 - mse / mse_mid)
        rows.append(row)
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class MicroPrice:
    """Fitted Stoikov (2018) micro-price: mid + adjustment[spread - 1, imbalance bucket].

    States never seen in the fitting data (NaN) or with a spread outside
    1..n_spread ticks get no adjustment (the mid).
    """
    adjustment: np.ndarray    # (n_spread, n_imb), in price units
    tick: float

    def __call__(self, features: pd.DataFrame) -> pd.Series:
        n_spread, n_imb = self.adjustment.shape
        s = np.rint(features["spread"].to_numpy() / self.tick).astype(int)
        b = _imbalance_bucket(features["imbalance"].to_numpy(), n_imb)
        ok = (s >= 1) & (s <= n_spread) & np.isfinite(features["imbalance"].to_numpy())   # NaN: an empty book
        adj = np.where(ok, np.nan_to_num(self.adjustment)[np.clip(s, 1, n_spread) - 1, b], 0.0)
        return features["mid"] + adj


def _imbalance_bucket(imb: np.ndarray, n_imb: int) -> np.ndarray:
    """Equal-width buckets with bucket(1 - x) == n_imb - 1 - bucket(x), so symmetrisation is exact."""
    imb = np.nan_to_num(imb, nan=0.5)                 # callers mask NaN rows; this only keeps the index valid
    lo = np.minimum((imb * n_imb).astype(int), n_imb - 1)
    hi = n_imb - 1 - np.minimum(((1 - imb) * n_imb).astype(int), n_imb - 1)
    return np.where(imb < 0.5, lo, hi)


def estimate_microprice(features: pd.DataFrame, tick: float = 1.0, n_imb: int = 11, n_spread: int = 2,
                        n_iter: int = 6) -> MicroPrice:
    """Stoikov (2018), "The micro-price", Sections 3-4.

    The state is (spread in ticks, imbalance bucket). Consecutive updates give
    transitions that either leave the mid unchanged (Q) or move it by
    K = (-1, -1/2, 1/2, 1) ticks (R1, landing in a new state R2). Then
        g1 = (I - Q)^-1 R1 K       expected next mid move
        B  = (I - Q)^-1 R2         state just after that move
        g  = g1 + B g1 + ... + B^(n_iter-1) g1
    The data is symmetrised (imbalance -> 1 - imbalance, move -> -move), as in
    the paper, so the estimate has no drift. Larger moves and wider spreads are
    dropped. n_imb is odd so a balanced book (imbalance 0.5, common when queues
    are small integers) gets its own centre bucket.
    """
    s = np.rint(features["spread"].to_numpy() / tick).astype(int)
    imb = features["imbalance"].to_numpy()
    dm = np.rint(2 * np.diff(features["mid"].to_numpy()) / tick) / 2     # half-tick resolution
    keep = (s[:-1] >= 1) & (s[:-1] <= n_spread) & (s[1:] >= 1) & (s[1:] <= n_spread) & (np.abs(dm) <= 1)
    keep &= np.isfinite(imb[:-1]) & np.isfinite(imb[1:])
    s0, s1, i0, i1, dm = s[:-1][keep], s[1:][keep], imb[:-1][keep], imb[1:][keep], dm[keep]
    s0, s1 = np.r_[s0, s0], np.r_[s1, s1]
    i0, i1, dm = np.r_[i0, 1 - i0], np.r_[i1, 1 - i1], np.r_[dm, -dm]

    n = n_spread * n_imb
    x0 = (s0 - 1) * n_imb + _imbalance_bucket(i0, n_imb)
    x1 = (s1 - 1) * n_imb + _imbalance_bucket(i1, n_imb)
    K = np.array([-1.0, -0.5, 0.5, 1.0])
    move = dm != 0
    Q, R1, R2 = np.zeros((n, n)), np.zeros((n, 4)), np.zeros((n, n))
    np.add.at(Q, (x0[~move], x1[~move]), 1)
    np.add.at(R1, (x0[move], np.searchsorted(K, dm[move])), 1)
    np.add.at(R2, (x0[move], x1[move]), 1)
    total = Q.sum(axis=1) + R1.sum(axis=1)
    norm = np.where(total > 0, total, 1.0)[:, None]                     # unvisited states: no adjustment
    Q, R1, R2 = Q / norm, R1 / norm, R2 / norm

    inv = np.linalg.pinv(np.eye(n) - Q)     # = inv() unless a sparse state never leads to a move
    g1, B = inv @ R1 @ K, inv @ R2
    g, term = g1.copy(), g1
    for _ in range(n_iter - 1):
        term = B @ term
        g += term
    g[total == 0] = np.nan                                              # never observed
    return MicroPrice((g * tick).reshape(n_spread, n_imb), tick)


def lead_lag(a: pd.DataFrame, b: pd.DataFrame, step: str = "50ms", max_lag: int = 40) -> pd.DataFrame:
    """Cross-correlation of two venues' mid returns, corr(r_a(t), r_b(t + lag)).

    a and b need columns ts (seconds, one shared clock) and mid. Both are
    sampled on a common grid of `step`; a peak at a positive lag means venue a
    moves first and b follows lag seconds later (Hayashi & Yoshida 2005 avoid
    the grid; at these sampling rates a fine grid is a close approximation).
    """
    def sampled(f):
        s = pd.Series(np.log(f["mid"].to_numpy()), index=pd.to_datetime(f["ts"], unit="s"))
        return s[~s.index.duplicated(keep="last")]

    sa, sb = sampled(a), sampled(b)
    grid = pd.date_range(max(sa.index[0], sb.index[0]).ceil(step), min(sa.index[-1], sb.index[-1]), freq=step)
    ra = sa.reindex(sa.index.union(grid)).ffill().reindex(grid).diff().to_numpy()[1:]
    rb = sb.reindex(sb.index.union(grid)).ffill().reindex(grid).diff().to_numpy()[1:]
    dt = pd.Timedelta(step).total_seconds()
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        x, y = (ra[:len(ra) - lag], rb[lag:]) if lag >= 0 else (ra[-lag:], rb[:len(rb) + lag])
        rows.append({"lag_s": lag * dt, "corr": float(np.corrcoef(x, y)[0, 1])})
    return pd.DataFrame(rows)


def cross_venue_impact(buckets_a: pd.DataFrame, buckets_b: pd.DataFrame, names=("a", "b"),
                       train_frac: float = 0.7) -> pd.DataFrame:
    """Whose order flow moves whose price, now and one bucket ahead.

    For each venue as the target: in-sample R^2 of its d_mid on its own OFI, the
    other venue's OFI, and both (contemporaneous); and out-of-sample R^2 of its
    NEXT bucket's d_mid from the other venue's OFI and d_mid in this bucket. If
    one venue leads, its flow and returns predict the other's next move.
    """
    j = buckets_a[["ofi", "d_mid"]].add_suffix("_a").join(buckets_b[["ofi", "d_mid"]].add_suffix("_b"), how="inner")
    rows = []
    for tgt, oth, tname in (("a", "b", names[0]), ("b", "a", names[1])):
        y = j[f"d_mid_{tgt}"].to_numpy(dtype=float)
        row = {"target": tname}
        for label, cols in (("own_ofi", [f"ofi_{tgt}"]), ("other_ofi", [f"ofi_{oth}"]),
                            ("both_ofi", [f"ofi_{tgt}", f"ofi_{oth}"])):
            X = np.column_stack([np.ones(len(j)), j[cols]])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            row[f"r2_{label}"] = float(1 - np.sum((y - X @ coef) ** 2) / np.sum((y - y.mean()) ** 2))
        lead = j.rename(columns={f"d_mid_{tgt}": "d_mid", f"ofi_{oth}": "other_ofi", f"d_mid_{oth}": "other_d_mid"})
        for feats in (["other_ofi"], ["other_d_mid"]):
            row[f"next_oos_r2_{feats[0]}"] = predictive_r2(lead, feats, train_frac=train_frac)["oos_r2"]
        rows.append(row)
    return pd.DataFrame(rows)
