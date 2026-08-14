#!/usr/bin/env python3
"""指定日以降の「追加データ」だけを CSV でstdoutに出力する（Drive companion 用）。

  python3 fx/scripts/export_recent.py [cutoff=2026-08-13] [SYMBOL_KEY]

- SYMBOL_KEY 省略時: 全通貨を1枚に（銘柄列付き・long形式）
- SYMBOL_KEY 指定時 (USDJPY/EURJPY/GBPJPY/EURUSD/GBPUSD/GOLD): その通貨だけを
  元Excelと同じ14列（日付〜第N週、銘柄列なし）で出力 → 各シートへ直接貼付可能

過去10年分はユーザーの Excel マスターにあるので触らない。ここでは cutoff 以降の
新しい行（基準CSV + 日次差分をマージ）だけを軽量CSVで出す。
"""
import csv, json, datetime, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DAILY = DATA / "daily"
SYMS = [("USDJPY", "ドル円", 3), ("EURJPY", "ユーロ円", 3), ("GBPJPY", "ポンド円", 3),
        ("EURUSD", "ユーロドル", 5), ("GBPUSD", "ポンドドル", 5), ("GOLD", "ゴールド", 2)]
WD = ["月", "火", "水", "木", "金", "土", "日"]
CUT = sys.argv[1] if len(sys.argv) > 1 else "2026-08-13"
ONLY = sys.argv[2] if len(sys.argv) > 2 else None
# 元Excelと同じ列（通貨別モード用）
COLS = ["日付", "始値", "高値", "安値", "終値", "高値ー安値", "始値ー終値",
        "始値ー安値", "始値ー高値", "年", "月", "日", "曜日", "第N週"]


def load(key):
    rows = {}
    p = DATA / f"{key}.csv"
    if p.exists():
        r = csv.reader(open(p)); next(r, None)
        for x in r:
            if len(x) >= 5:
                try: rows[x[0]] = (float(x[1]), float(x[2]), float(x[3]), float(x[4]))
                except ValueError: pass
    if DAILY.exists():
        for fp in sorted(DAILY.glob("*.json")):
            try: o = json.loads(fp.read_text())
            except Exception: continue
            d = o.get("date") or fp.stem; b = o.get(key)
            if b:
                try: rows[d] = (float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]))
                except (KeyError, ValueError, TypeError): pass
    return rows


w = csv.writer(sys.stdout)
n = 0
if ONLY:
    dec = dict((k, d) for k, _, d in SYMS).get(ONLY, 3)
    w.writerow(COLS)
    rows = load(ONLY)
    for d in sorted(rows):
        if d < CUT:
            continue
        o, h, l, c = rows[d]; dt = datetime.date.fromisoformat(d); r = lambda v: round(v, dec)
        w.writerow([d, r(o), r(h), r(l), r(c), r(h - l), r(o - c), r(o - l), r(o - h),
                    dt.year, dt.month, dt.day, WD[dt.weekday()], (dt.day - 1) // 7 + 1])
        n += 1
else:
    w.writerow(["銘柄"] + COLS)
    for key, label, dec in SYMS:
        rows = load(key)
        for d in sorted(rows):
            if d < CUT:
                continue
            o, h, l, c = rows[d]; dt = datetime.date.fromisoformat(d); r = lambda v: round(v, dec)
            w.writerow([label, d, r(o), r(h), r(l), r(c), r(h - l), r(o - c), r(o - l), r(o - h),
                        dt.year, dt.month, dt.day, WD[dt.weekday()], (dt.day - 1) // 7 + 1])
            n += 1
sys.stderr.write(f"{n} rows since {CUT}{(' for ' + ONLY) if ONLY else ''}\n")
