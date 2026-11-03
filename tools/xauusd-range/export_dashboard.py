#!/usr/bin/env python3
"""Emit the dashboard's datasets as CSV files under dashboard_data/."""
from __future__ import annotations
import datetime as dt, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import range_model as rm, forecast as fc, intraday_stats as ist, calendar_jp as cal
from duka import OUT, JST, NY, UTC, session_label
from build_daily import build
from daily_report import session_bounds, target_session, conditional, BROKERS

D = Path(__file__).parent / "dashboard_data"; D.mkdir(exist_ok=True)
CONVS = ["nyclose", "utc"]


def main():
    rows_fc, rows_cond, rows_sess, rows_lv, rows_rq = [], [], [], [], []
    for conv in CONVS:
        broker = BROKERS[conv][0].replace(" 方式", "")
        d_all, hourly = build(conv)
        hourly = hourly.copy(); hourly["jst"] = hourly["ts"].dt.tz_convert(JST).dt.hour
        sess, _ = target_session(conv)
        comp = d_all[(d_all.bars >= 20) & (d_all.date.dt.date < sess)].reset_index(drop=True)
        prev = comp.iloc[-1]
        f = fc.build(prev["date"], conv)
        s_start, s_end = session_bounds(sess, conv)

        for b in f["boxes"]:
            rows_fc.append({"broker": broker, "coverage": int(b["target"] * 100),
                            "high": round(b["high"], 2), "low": round(b["low"], 2),
                            "width": round(b["high"] - b["low"], 2)})
        for lbl, v in zip(["p25", "median", "p75", "p90"], f["range_q"]):
            rows_rq.append({"broker": broker, "quantile": lbl, "dollars": round(float(v), 2)})

        cur = d_all[d_all.date.dt.date == sess]
        cur_h = hourly[hourly["day"] == sess]
        if len(cur_h):
            data_end = cur_h["ts"].max().tz_convert(JST) + dt.timedelta(hours=1)
            elapsed = max(0, int((min(data_end, s_end) - s_start).total_seconds() // 3600))
        else:
            elapsed, data_end = 0, s_start
        rh = rl = rlast = np.nan
        if len(cur):
            c = cur.iloc[0]; rh, rl, rlast = c.high, c.low, c.close
        rows_sess.append({
            "broker": broker, "session": str(sess), "boundary": BROKERS[conv][2],
            "start_jst": s_start.strftime("%m/%d %H:%M"), "end_jst": s_end.strftime("%m/%d %H:%M"),
            "prev_open": round(prev.open, 2), "prev_high": round(prev.high, 2),
            "prev_low": round(prev.low, 2), "prev_close": round(prev.close, 2),
            "prev_range": round(prev.high - prev.low, 2),
            "sigma": round(f["sigma"], 2), "atr14": round(f["atr14"], 2),
            "sessions": len(comp), "elapsed_hours": elapsed,
            "data_end_jst": data_end.strftime("%m/%d %H:%M"),
            "realized_high": None if np.isnan(rh) else round(rh, 2),
            "realized_low": None if np.isnan(rl) else round(rl, 2),
            "last": None if np.isnan(rlast) else round(rlast, 2),
            "realized_range": None if np.isnan(rh) else round(rh - rl, 2)})

        for k, v in [("前セッション高値", prev.high), ("前セッション安値", prev.low)] + \
                    list(f["piv"].items()) + \
                    [("直近20日高値", comp.tail(20).high.max()),
                     ("直近20日安値", comp.tail(20).low.min())]:
            kind = ("ピボット" if k in ("P",) else
                    "レジスタンス" if k.startswith("R") else
                    "サポート" if k.startswith("S") else "節目")
            rows_lv.append({"broker": broker, "label": k, "price": round(float(v), 2), "kind": kind})

        if len(cur) and elapsed >= 2:
            cd = conditional(comp, hourly, set(comp.date.dt.date),
                             sorted({(s_start + dt.timedelta(hours=i)).hour for i in range(elapsed)}),
                             cur.iloc[0].high, cur.iloc[0].low, f["sigma"])
            if cd:
                for b in cd["boxes"]:
                    rows_cond.append({"broker": broker, "coverage": int(b["target"] * 100),
                                      "final_high": round(b["high"], 2), "final_low": round(b["low"], 2),
                                      "p_high_set": round(cd["p_high_set"] * 100, 1),
                                      "p_low_set": round(cd["p_low_set"] * 100, 1)})

    pd.DataFrame(rows_fc).to_csv(D / "forecast.csv", index=False)
    pd.DataFrame(rows_sess).to_csv(D / "session.csv", index=False)
    pd.DataFrame(rows_lv).to_csv(D / "levels.csv", index=False)
    pd.DataFrame(rows_rq).to_csv(D / "range_quantiles.csv", index=False)
    pd.DataFrame(rows_cond).to_csv(D / "conditional.csv", index=False)

    # hour-of-day profile (Axiory boundary)
    st = ist.stats(250, "nyclose")
    pd.DataFrame({"jst_hour": range(24),
                  "high_pct": (st["hour_high_recent"].reindex(range(24), fill_value=0) * 100).round(1).values,
                  "low_pct": (st["hour_low_recent"].reindex(range(24), fill_value=0) * 100).round(1).values,
                  }).to_csv(D / "hours.csv", index=False)

    # walk-forward containment, and the volatility regime, per year
    vr, cr = [], []
    for conv in CONVS:
        broker = BROKERS[conv][0].replace(" 方式", "")
        d = pd.read_csv(OUT / f"daily_clean_{conv}.csv", parse_dates=["date"])
        d = rm.prepare(d[d.bars >= 20].reset_index(drop=True))
        bt = rm.backtest(d)
        g = bt.assign(y=bt.date.dt.year).groupby("y")
        for y, k in g:
            cr.append({"broker": broker, "year": int(y), "n": len(k),
                       "containment": round(k.both_ok.mean() * 100, 1),
                       "width": round(k.width.mean(), 1), "fill": round(k.fill.mean(), 3)})
        if conv == "nyclose":
            dd = d.assign(y=d.date.dt.year, rng=d.high - d.low)
            for y, k in dd.groupby("y"):
                vr.append({"year": int(y), "n": len(k), "mean_range": round(k.rng.mean(), 2),
                           "median_range": round(k.rng.median(), 2),
                           "p90_range": round(k.rng.quantile(.9), 2),
                           "pct_of_price": round(k.rng_pct.mean(), 2)})
    pd.DataFrame(cr).to_csv(D / "validation.csv", index=False)
    pd.DataFrame(vr).to_csv(D / "regime.csv", index=False)

    # events inside the Axiory session window
    try:
        page = cal.fetch()
        s_start, s_end = session_bounds(target_session("nyclose")[0], "nyclose")
        ev = cal.session_events_window(page, s_start, s_end)
        pd.DataFrame([{"time_jst": e["when"].strftime("%m/%d %H:%M"),
                       "importance": e["importance"], "country": e["country"],
                       "name": e["name"], "forecast": e["forecast"] or "",
                       "actual": e["actual"] or ""} for ev_ in [ev] for e in ev_]
                     ).to_csv(D / "events.csv", index=False)
    except Exception as e:
        print(f"[warn] calendar: {e}", file=sys.stderr)
        pd.DataFrame(columns=["time_jst","importance","country","name","forecast","actual"]
                     ).to_csv(D / "events.csv", index=False)

    for p in sorted(D.glob("*.csv")):
        print(f"{p.name:22} {len(pd.read_csv(p)):4} rows")


if __name__ == "__main__":
    main()
