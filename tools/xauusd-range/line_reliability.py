#!/usr/bin/env python3
"""Measure every line the EA draws, walk-forward, so they can be ranked.

Each line is scored on three things, all from data strictly older than the
session being measured:

  touch   P(the session traded through the level)
  hold    P(the extreme stopped there | it was touched), where "stopped"
          means it went no further than 0.10 x sigma beyond
  over    mean overshoot in dollars on the sessions that broke through

A boundary (the forecast boxes) wants a high hold. A level you trade off
(pivot, previous high) wants both: reached often enough to matter, and
respected when reached.

Measured result, 2,180 sessions: hold sits near 20% for every line, and every
classic level (previous high/low, pivot, R1/S1, 20-day high/low) holds LESS
often than a statistical level placed where it is reached equally often --
by 0.5 to 9.4 points, none above. The lines map how far price travels; they
do not mark where it turns.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import range_model as rm, forecast as fc
from duka import OUT, JST, session_label

CONV = "nyclose"
MIN_HIST = 400
TOL_SIGMA = 0.10          # how far past a level still counts as "stopped there"
COVS = [50, 70, 80, 90]


def hourly():
    h = pd.concat([pd.read_csv(OUT / "hourly.csv", parse_dates=["ts"]),
                   pd.read_csv(OUT / "hourly_recent.csv", parse_dates=["ts"])],
                  ignore_index=True).drop_duplicates("ts", keep="last").sort_values("ts")
    h = h[h["vol"] > 0].copy()
    h["day"] = session_label(h["ts"], CONV)
    h["jst"] = h["ts"].dt.tz_convert(JST).dt.hour
    return h


def main():
    d = pd.read_csv(OUT / f"daily_clean_{CONV}.csv", parse_dates=["date"])
    d = rm.prepare(d[d.bars >= 20].reset_index(drop=True))
    n = len(d)
    up, dn = d["up"].to_numpy(), d["dn"].to_numpy()
    hi, lo = d["high"].to_numpy(), d["low"].to_numpy()
    pc, sg = d["prev_close"].to_numpy(), d["sigma"].to_numpy()

    # per-side quantiles for each coverage, solved once on the whole sample.
    # They describe the distribution's shape, which is stable; re-solving each
    # session would cost an hour and move them in the third decimal.
    w_all = fc.weights(n)
    qs = {c: fc.solve_q(up, dn, w_all, c / 100) for c in COVS}

    # first two hours of each session, for the conditional lines the 09:08 run
    # publishes (two hours into the Axiory session)
    h = hourly()
    part = (h[h.jst.isin([7, 8])].groupby("day")
              .agg(ph=("high", "max"), pl=("low", "min"), k=("high", "size")))
    part = part[part.k >= 2]
    d["dk"] = d["date"].dt.date
    j = d.set_index("dk").join(part, how="left")
    ph, pl = j["ph"].to_numpy(), j["pl"].to_numpy()
    eu = np.where(np.isnan(ph), np.nan, (hi - ph) / sg)
    ed = np.where(np.isnan(pl), np.nan, (pl - lo) / sg)
    ok = ~np.isnan(eu) & ~np.isnan(ed)
    w_c = fc.weights(int(ok.sum()))
    qc = {c: fc.solve_q(eu[ok], ed[ok], w_c, c / 100) for c in (50, 80)}

    rows = {}

    def rec(name, i, level, side):
        """side 'U' -> resists above, 'L' -> supports below."""
        if level is None or not np.isfinite(level):
            return
        tol = TOL_SIGMA * sg[i]
        if side == "U":
            touched = hi[i] >= level
            held = touched and hi[i] <= level + tol
            over = max(0.0, hi[i] - level)
        else:
            touched = lo[i] <= level
            held = touched and lo[i] >= level - tol
            over = max(0.0, level - lo[i])
        r = rows.setdefault(name, {"side": side, "n": 0, "touch": 0,
                                   "held": 0, "over": []})
        r["n"] += 1
        if touched:
            r["touch"] += 1
            r["held"] += int(held)
            if not held:
                r["over"].append(over)

    for i in range(MIN_HIST, n):
        w = fc.weights(i)
        for c in COVS:
            ru = rm.wq(up[:i], w, qs[c])[0]
            rd = rm.wq(dn[:i], w, qs[c])[0]
            rec(f"{c}%H", i, pc[i] + ru * sg[i], "U")
            rec(f"{c}%L", i, pc[i] - rd * sg[i], "L")

        if ok[i]:
            m = ok[:i]
            if m.sum() > 200:
                wc = fc.weights(int(m.sum()))
                for c in (50, 80):
                    ru = rm.wq(eu[:i][m], wc, qc[c])[0]
                    rd = rm.wq(ed[:i][m], wc, qc[c])[0]
                    rec(f"C{c}H", i, ph[i] + ru * sg[i], "U")
                    rec(f"C{c}L", i, pl[i] - rd * sg[i], "L")

        H, L, C = hi[i - 1], lo[i - 1], d["close"].to_numpy()[i - 1]
        P = (H + L + C) / 3
        rec("PH", i, H, "U")
        rec("PL", i, L, "L")
        rec("R1", i, 2 * P - L, "U")
        rec("S1", i, 2 * P - H, "L")
        rec("R2", i, P + (H - L), "U")
        rec("S2", i, P - (H - L), "L")
        rec("R3", i, H + 2 * (P - L), "U")
        rec("S3", i, L - 2 * (H - P), "L")
        rec("PC", i, C, "U" if C >= pc[i] else "L")
        rec("P", i, P, "U" if P >= pc[i] else "L")
        if i >= 20:
            rec("20DH", i, hi[i - 20:i].max(), "U")
            rec("20DL", i, lo[i - 20:i].min(), "L")

    out = []
    for k, r in rows.items():
        t = r["touch"] / r["n"]
        hld = (r["held"] / r["touch"]) if r["touch"] else np.nan
        out.append({"line": k, "side": r["side"], "n": r["n"],
                    "touch_pct": round(t * 100, 1),
                    "hold_pct": round(hld * 100, 1) if r["touch"] else np.nan,
                    "contain_pct": round((1 - t + t * (hld if r["touch"] else 0)) * 100, 1),
                    "mean_over": round(float(np.mean(r["over"])), 1) if r["over"] else 0.0})
    df = pd.DataFrame(out)
    df["contain_pct"] = df["contain_pct"].round(1)
    df = df.sort_values("contain_pct", ascending=False)
    df.to_csv(Path(__file__).parent / "dashboard_data" / "line_reliability.csv", index=False)
    print(f"sessions measured: {n - MIN_HIST}   tolerance: {TOL_SIGMA:.2f} x sigma\n")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
