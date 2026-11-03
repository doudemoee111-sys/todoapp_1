"""Regime-weighted empirical range model for XAU/USD daily bars.

Scale-free targets, measured from the prior NY close:
    up_t = (High_t - Close_{t-1}) / sigma_t
    dn_t = (Close_{t-1} - Low_t)  / sigma_t
with sigma_t an EWMA of true range known at t-1 (the regime estimate).

The forecast box is built from *exponentially weighted empirical quantiles*
of up/dn -- no normality assumption, so the fat right tail survives.
    High_hat(q) = C_{t-1} + Q_up(q) * sigma_t
    Low_hat(q)  = C_{t-1} - Q_dn(q) * sigma_t

Everything is evaluated walk-forward: day t only ever sees data before t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VOL_HALFLIFE = 20     # days -- regime estimate for sigma
HIST_HALFLIFE = 500   # days -- weighting of the empirical ratio distribution
MIN_HIST = 400        # days of history before the model will quote
TAIL_Q = 0.90         # per-side quantile -> ~80% two-sided containment


# ----------------------------------------------------------------- helpers
def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - pc).abs(),
                      (df["low"] - pc).abs()], axis=1).max(axis=1)


def wilder_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def wq(values: np.ndarray, weights: np.ndarray, qs) -> np.ndarray:
    """Weighted empirical quantile (interpolated on the weighted CDF)."""
    o = np.argsort(values)
    v, w = values[o], weights[o]
    cw = np.cumsum(w)
    cdf = (cw - 0.5 * w) / cw[-1]
    return np.interp(np.atleast_1d(qs), cdf, v)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    d = df.sort_values("date").reset_index(drop=True).copy()
    d["tr"] = true_range(d)
    d["atr14"] = wilder_atr(d, 14)
    # sigma must be knowable at t-1 -> shift the EWMA forward one day
    d["sigma"] = (d["tr"].ewm(halflife=VOL_HALFLIFE, adjust=False).mean()
                        .shift(1))
    d["prev_close"] = d["close"].shift(1)
    d["up"] = (d["high"] - d["prev_close"]) / d["sigma"]
    d["dn"] = (d["prev_close"] - d["low"]) / d["sigma"]
    d["rng"] = d["high"] - d["low"]
    d["rng_pct"] = d["rng"] / d["prev_close"] * 100
    d["dow"] = d["date"].dt.dayofweek
    return d.dropna(subset=["sigma", "up", "dn"]).reset_index(drop=True)


# ------------------------------------------------------------------ model
def quote(hist: pd.DataFrame, prev_close: float, sigma: float,
          qs=(0.50, 0.80, TAIL_Q, 0.95)) -> dict:
    """Build the forecast box from history strictly older than the target day."""
    age = np.arange(len(hist))[::-1]
    w = 0.5 ** (age / HIST_HALFLIFE)
    qu = wq(hist["up"].to_numpy(), w, qs)
    qd = wq(hist["dn"].to_numpy(), w, qs)
    return {
        "sigma": sigma,
        "q": list(qs),
        "high": [prev_close + r * sigma for r in qu],
        "low": [prev_close - r * sigma for r in qd],
        "up_ratio": list(qu),
        "dn_ratio": list(qd),
    }


def backtest(d: pd.DataFrame, tail_q: float = TAIL_Q) -> pd.DataFrame:
    """Walk-forward containment test of the tail_q box."""
    rows = []
    up, dn = d["up"].to_numpy(), d["dn"].to_numpy()
    for i in range(MIN_HIST, len(d)):
        age = np.arange(i)[::-1]
        w = 0.5 ** (age / HIST_HALFLIFE)
        ru = wq(up[:i], w, tail_q)[0]
        rd = wq(dn[:i], w, tail_q)[0]
        s, pc = d.at[i, "sigma"], d.at[i, "prev_close"]
        hh, ll = pc + ru * s, pc - rd * s
        rows.append({
            "date": d.at[i, "date"],
            "pred_high": hh, "pred_low": ll,
            "act_high": d.at[i, "high"], "act_low": d.at[i, "low"],
            "width": hh - ll,
            "width_pct": (hh - ll) / pc * 100,
            "hi_ok": d.at[i, "high"] <= hh,
            "lo_ok": d.at[i, "low"] >= ll,
            "both_ok": (d.at[i, "high"] <= hh) and (d.at[i, "low"] >= ll),
            # how much of the box the day actually used
            "fill": (d.at[i, "high"] - d.at[i, "low"]) / (hh - ll),
        })
    return pd.DataFrame(rows)


def report_backtest(bt: pd.DataFrame) -> str:
    g = bt.assign(year=bt["date"].dt.year).groupby("year")
    tbl = g.agg(n=("both_ok", "size"),
                contained=("both_ok", "mean"),
                high_ok=("hi_ok", "mean"),
                low_ok=("lo_ok", "mean"),
                width=("width", "mean"),
                width_pct=("width_pct", "mean"),
                fill=("fill", "mean")).round(3)
    last = bt.tail(250)
    tail = (f"\nlast 250 sessions: contained={last.both_ok.mean():.1%} "
            f"width=${last.width.mean():.0f} ({last.width_pct.mean():.2f}%) "
            f"fill={last.fill.mean():.2f}")
    return tbl.to_string() + tail


def dow_profile(d: pd.DataFrame, lookback: int = 500) -> pd.DataFrame:
    r = d.tail(lookback)
    return (r.groupby("dow")
             .agg(n=("rng", "size"), rng=("rng", "mean"),
                  rng_pct=("rng_pct", "mean"),
                  rng_over_sigma=("rng", "mean"))
             .round(2))
