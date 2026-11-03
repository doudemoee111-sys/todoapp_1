#!/usr/bin/env python3
"""Determine a broker's daily-bar boundary and feed offset from an MT4 export.

Server-time claims found on the web are unreliable and change. This settles it
from the broker's own bars: build reference daily bars from Dukascopy hourly
data under each candidate boundary, then see which one reproduces the broker's
D1 highs and lows.

    python3 calibrate_broker.py axiory_xauusd_d1.csv --name Axiory

Export from MT4: F2 (History Center) -> Metals -> XAUUSD -> Daily (1440)
-> Export, or open a D1 chart, press Home to load history, File -> Save As.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from duka import session_label, CONVENTIONS, OUT

# candidate boundaries, including the DST variants a broker might run
CANDIDATES = {
    "nyclose": "サーバー GMT+2/+3・米DST追随（Axiory型）／NY 17:00区切り",
    "utc":     "サーバー GMT+0 固定・DSTなし（Exness型）／00:00 UTC = 09:00 JST 区切り",
}


def read_mt4(path: str) -> pd.DataFrame:
    """MT4 CSV: Date,Time,Open,High,Low,Close,Volume -- header optional."""
    raw = pd.read_csv(path, header=None, dtype=str,
                      engine="python", skip_blank_lines=True)
    first = str(raw.iloc[0, 0]).lower()
    if any(k in first for k in ("date", "time", "<")):
        raw = raw.iloc[1:]
    cols = ["date", "time", "open", "high", "low", "close"]
    raw = raw.iloc[:, :max(6, min(7, raw.shape[1]))]
    raw.columns = (cols + ["vol"])[:raw.shape[1]]
    d = pd.DataFrame({
        "date": pd.to_datetime(raw["date"].str.strip().str.replace(".", "-", regex=False)
                               .str.replace("/", "-", regex=False), errors="coerce"),
    })
    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(raw[c].str.strip(), errors="coerce")
    return d.dropna().sort_values("date").reset_index(drop=True)


def reference(convention: str) -> pd.DataFrame:
    frames = [pd.read_csv(OUT / "hourly.csv", parse_dates=["ts"])]
    try:
        frames.append(pd.read_csv(OUT / "hourly_recent.csv", parse_dates=["ts"]))
    except FileNotFoundError:
        pass
    h = (pd.concat(frames, ignore_index=True)
           .drop_duplicates("ts", keep="last").sort_values("ts"))
    h = h[h["vol"] > 0]
    h["day"] = session_label(h["ts"], convention)
    g = h.groupby("day")
    r = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(),
                      "bars": g["high"].size()}).reset_index()
    r = r[r.bars >= 12].rename(columns={"day": "date"})
    r["date"] = pd.to_datetime(r["date"])
    return r[["date", "high", "low"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="MT4 D1 export for XAUUSD")
    ap.add_argument("--name", default="broker")
    a = ap.parse_args()

    b = read_mt4(a.csv)
    print(f"=== {a.name} ===")
    print(f"broker bars: {len(b)}  {b.date.min().date()} -> {b.date.max().date()}\n")

    results = []
    for conv, desc in CANDIDATES.items():
        r = reference(conv)
        j = b.merge(r, on="date", suffixes=("_b", "_r")).dropna()
        if len(j) < 20:
            print(f"{conv:8}: 重なる日数が不足（{len(j)}日）"); continue
        dh, dl = j.high_b - j.high_r, j.low_b - j.low_r
        # a constant feed offset shifts high and low together; remove it before
        # judging the boundary, so offset and boundary are not confounded
        off = float(np.median(np.concatenate([dh, dl])))
        rh, rl = dh - off, dl - off
        err = float(np.median(np.abs(np.concatenate([rh, rl]))))
        match = float(((rh.abs() < 0.30) & (rl.abs() < 0.30)).mean())
        results.append((conv, desc, len(j), off, err, match))
        print(f"{conv:8}: n={len(j):4}  推定オフセット {off:+.3f}  "
              f"残差中位 ${err:.3f}  高安とも一致 {match*100:5.1f}%")

    if not results:
        sys.exit("判定できません。期間が重なるデータを増やしてください。")
    best = max(results, key=lambda x: (x[5], -x[4]))
    print(f"\n--> 判定: {best[0]}")
    print(f"    {CANDIDATES[best[0]]}")
    print(f"    フィードのオフセット {best[3]:+.3f} ドル（Dukascopy bid 基準）")
    print(f"    一致率 {best[5]*100:.1f}% / 残差中位 ${best[4]:.3f}")
    if len(results) > 1:
        other = [r for r in results if r[0] != best[0]][0]
        if best[5] - other[5] < 0.15:
            print(f"\n    注意: {other[0]} との差が小さい（{other[5]*100:.1f}%）。"
                  "期間を長めに（90日以上）エクスポートし直すと確度が上がります。")
    print(f"\n    -> daily_report.py --convention {best[0]}")


if __name__ == "__main__":
    main()
