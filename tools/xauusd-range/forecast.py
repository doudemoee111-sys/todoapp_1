"""Daily XAU/USD range forecast, NY-close sessions, regime-weighted.

Boxes are calibrated JOINTLY: for a target containment we solve for the
per-side quantile q such that the weighted historical frequency of
(up <= Qup(q) AND dn <= Qdn(q)) equals the target. No independence
assumption, no normality.
"""
from __future__ import annotations
import sys; sys.path.insert(0, '.')
import numpy as np, pandas as pd
import range_model as rm
from duka import OUT

HL_HIST = rm.HIST_HALFLIFE


def weights(n: int, halflife: float = HL_HIST) -> np.ndarray:
    return 0.5 ** (np.arange(n)[::-1] / halflife)


def solve_q(up: np.ndarray, dn: np.ndarray, w: np.ndarray, target: float) -> float:
    """Per-side quantile whose joint box contains `target` of weighted history."""
    lo, hi = 0.50, 0.9995
    for _ in range(60):
        q = (lo + hi) / 2
        ru, rd = rm.wq(up, w, q)[0], rm.wq(dn, w, q)[0]
        cov = (w[(up <= ru) & (dn <= rd)].sum()) / w.sum()
        if cov < target: lo = q
        else: hi = q
    return (lo + hi) / 2


def box(up, dn, w, prev_close, sigma, target):
    q = solve_q(up, dn, w, target)
    ru, rd = rm.wq(up, w, q)[0], rm.wq(dn, w, q)[0]
    cov = (w[(up <= ru) & (dn <= rd)].sum()) / w.sum()
    return dict(target=target, q=q, high=prev_close + ru * sigma,
                low=prev_close - rd * sigma, up=ru * sigma, dn=rd * sigma,
                insample=cov)


def pivots(h, l, c):
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h,
            "R2": p + (h - l), "S2": p - (h - l),
            "R3": h + 2 * (p - l), "S3": l - 2 * (h - p)}


def build(asof_date=None, convention: str = "nyclose"):
    d_all = pd.read_csv(OUT / f"daily_clean_{convention}.csv", parse_dates=["date"])
    comp = d_all[d_all["bars"] >= 20].reset_index(drop=True)
    if asof_date is not None:
        comp = comp[comp["date"] <= pd.Timestamp(asof_date)].reset_index(drop=True)
    d = rm.prepare(comp)
    prev = comp.iloc[-1]

    tr = rm.true_range(comp)
    sigma = tr.ewm(halflife=rm.VOL_HALFLIFE, adjust=False).mean().iloc[-1]
    atr14 = rm.wilder_atr(comp, 14).iloc[-1]

    up, dn = d["up"].to_numpy(), d["dn"].to_numpy()
    w = weights(len(up))
    boxes = [box(up, dn, w, prev["close"], sigma, t) for t in (0.50, 0.70, 0.80, 0.90)]

    rr = (d["high"] - d["low"]) / d["sigma"]          # range in sigma units
    rq = rm.wq(rr.to_numpy(), w, [0.25, 0.50, 0.75, 0.90])

    return dict(prev=prev, d=d, comp=comp, sigma=sigma, atr14=atr14,
                boxes=boxes, range_q=rq * sigma,
                piv=pivots(prev["high"], prev["low"], prev["close"]))


if __name__ == "__main__":
    # forecast issued 07:30 JST 2026-11-03 -> uses data through the 2026-11-02 close only
    f = build("2026-11-02")
    p = f["prev"]
    print(f"prev session {p['date'].date()}  O {p.open:.2f} H {p.high:.2f} L {p.low:.2f} C {p.close:.2f}")
    print(f"sigma(EWMA hl20) ${f['sigma']:.2f}   ATR14 ${f['atr14']:.2f}   history n={len(f['d'])}")
    print("\n--- expected RANGE (high-low), regime-weighted ---")
    for lbl, v in zip(["p25", "median", "p75", "p90"], f["range_q"]):
        print(f"  {lbl:6}: ${v:7.2f}")
    print("\n--- forecast boxes (from prev close {:.2f}) ---".format(p.close))
    for b in f["boxes"]:
        print(f"  {b['target']*100:4.0f}%  high {b['high']:8.2f}  low {b['low']:8.2f} "
              f" width ${b['high']-b['low']:7.2f}  (+{b['up']:.0f}/-{b['dn']:.0f}, q={b['q']:.3f}, fit {b['insample']*100:.1f}%)")
    print("\n--- pivots from prev session ---")
    for k, v in f["piv"].items():
        print(f"  {k:3}: {v:8.2f}")
