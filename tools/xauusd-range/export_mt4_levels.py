#!/usr/bin/env python3
"""Emit mt4/latest.txt -- the level feed the MT4 Expert Advisor fetches.

Pipe-delimited with a fixed field count per record type. MQL4 has no JSON
parser, and a hand-rolled one is the usual source of breakage, so the feed is
shaped for StringSplit instead.

    V2
    META|generated_at|<UTC ISO>
    META|symbol|XAUUSD
    INFO|<conv>|<key>|<value>
    LEVEL|<conv>|<kind>|<coverage>|<ASCII label>|<price>

conv is "nyclose" (server GMT+2/+3, e.g. Axiory) or "utc" (server GMT+0,
e.g. Exness). Labels are ASCII so no codepage can mangle an object's text.
"""
from __future__ import annotations
import datetime as dt, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import forecast as fc, range_model as rm
from duka import JST
from build_daily import build
from daily_report import session_bounds, target_session, conditional, BROKERS

OUT = Path(__file__).parent / "mt4" / "latest.txt"
CONVS = ["nyclose", "utc"]
PIVOT_ASCII = {"P": "PIVOT", "R1": "R1", "R2": "R2", "R3": "R3",
               "S1": "S1", "S2": "S2", "S3": "S3"}


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    lines = ["V2", f"META|generated_at|{now:%Y-%m-%dT%H:%M:%SZ}", "META|symbol|XAUUSD"]
    wrote = 0

    for conv in CONVS:
        broker = BROKERS[conv][0].replace(" 方式", "")
        d_all, hourly = build(conv)
        hourly = hourly.copy(); hourly["jst"] = hourly["ts"].dt.tz_convert(JST).dt.hour
        sess, _ = target_session(conv)
        s_start, s_end = session_bounds(sess, conv)
        if s_start > dt.datetime.now(JST):
            print(f"[skip] {conv}: session starts {s_start:%m/%d %H:%M} JST, "
                  "previous close not printed yet", file=sys.stderr)
            continue
        comp = d_all[(d_all.bars >= 20) & (d_all.date.dt.date < sess)].reset_index(drop=True)
        if comp.empty:
            print(f"[skip] {conv}: no closed session", file=sys.stderr); continue
        prev = comp.iloc[-1]
        f = fc.build(prev["date"], conv)

        cur = d_all[d_all.date.dt.date == sess]
        cur_h = hourly[hourly["day"] == sess]
        if len(cur_h):
            data_end = cur_h["ts"].max().tz_convert(JST) + dt.timedelta(hours=1)
            elapsed = max(0, int((min(data_end, s_end) - s_start).total_seconds() // 3600))
        else:
            elapsed, data_end = 0, s_start

        I = lambda k, v: lines.append(f"INFO|{conv}|{k}|{v}")
        I("broker", broker)
        I("session", sess)
        I("session_jst", f"{s_start:%m/%d %H:%M} - {s_end:%m/%d %H:%M} JST")
        I("prev_close", f"{prev.close:.2f}")
        I("sigma", f"{f['sigma']:.2f}")
        I("atr14", f"{f['atr14']:.2f}")
        I("elapsed_hours", elapsed)
        I("data_end_jst", f"{data_end:%m/%d %H:%M}")
        I("range_median", f"{float(f['range_q'][1]):.2f}")

        L = lambda kind, cov, label, price: lines.append(
            f"LEVEL|{conv}|{kind}|{cov}|{label}|{price:.2f}")
        for b in f["boxes"]:
            c = int(b["target"] * 100)
            L("box_high", c, f"{c}% HIGH", b["high"])
            L("box_low", c, f"{c}% LOW", b["low"])
        L("prev_high", 0, "PREV HIGH", prev.high)
        L("prev_low", 0, "PREV LOW", prev.low)
        L("prev_close", 0, "PREV CLOSE", prev.close)
        for k, v in f["piv"].items():
            L("pivot", 0, PIVOT_ASCII.get(k, k), float(v))
        w20 = comp.tail(20)
        L("swing_high", 0, "20D HIGH", float(w20.high.max()))
        L("swing_low", 0, "20D LOW", float(w20.low.min()))

        if len(cur) and elapsed >= 2:
            c0 = cur.iloc[0]
            I("realized_high", f"{c0.high:.2f}")
            I("realized_low", f"{c0.low:.2f}")
            I("realized_range", f"{c0.high - c0.low:.2f}")
            cd = conditional(comp, hourly, set(comp.date.dt.date),
                             sorted({(s_start + dt.timedelta(hours=i)).hour
                                     for i in range(elapsed)}),
                             c0.high, c0.low, f["sigma"])
            if cd:
                I("p_high_set", f"{cd['p_high_set'] * 100:.1f}")
                I("p_low_set", f"{cd['p_low_set'] * 100:.1f}")
                for b in cd["boxes"]:
                    c = int(b["target"] * 100)
                    L("cond_high", c, f"COND {c}% HIGH", b["high"])
                    L("cond_low", c, f"COND {c}% LOW", b["low"])
        wrote += 1

    if not wrote:
        print("[error] no convention could be written", file=sys.stderr)
        return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"{OUT} : {len(lines)} records, {wrote} convention(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
