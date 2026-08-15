#!/usr/bin/env python3
"""公開artifact（元SVGデザイン）の本体を、git のデータで組み立てる。

  python3 fx/artifact/build_artifacts.py [out_dir=/tmp]

fx/artifact/candlestick.html, dashboard.html のテンプレート（データ部分が
プレースホルダ /*__FXDATA__*/）に、基準CSV+日次差分をマージした現在のデータを
元artifactと同じ形式 {"ドル円":{"unit":"JPY","rows":[[d,o,h,l,c],...]},...} で注入し、
公開用HTML（本体のみ）を出力する。出力を Artifact ツールで各URLへ publish する。
"""
import sys, json, csv, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "fx" / "data"
DAILY = DATA / "daily"
TPL = ROOT / "fx" / "artifact"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp")

# 元artifactのキー順・単位
SPEC = [("ドル円", "USDJPY", "JPY"), ("ユーロ円", "EURJPY", "JPY"), ("ポンド円", "GBPJPY", "JPY"),
        ("ユーロドル", "EURUSD", "USD"), ("ポンドドル", "GBPUSD", "USD"), ("ゴールド", "GOLD", "USD")]


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


data = {}
last_date = ""
for jp, gk, unit in SPEC:
    rows = load(gk)
    arr = [[d, *[round(v, 5) for v in rows[d]]] for d in sorted(rows)]
    data[jp] = {"unit": unit, "rows": arr}
    if arr:
        last_date = max(last_date, arr[-1][0])
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

OUT.mkdir(parents=True, exist_ok=True)
built = []
for name in ("candlestick", "dashboard"):
    tpl = (TPL / f"{name}.html").read_text(encoding="utf-8")
    if "/*__FXDATA__*/" not in tpl:
        sys.exit(f"placeholder missing in {name}.html")
    out = tpl.replace("/*__FXDATA__*/", payload)
    dst = OUT / f"artifact_{name}.html"
    dst.write_text(out, encoding="utf-8")
    built.append(str(dst))
    print(f"{name}: {len(out)/1024:.0f}KB -> {dst}")
print(f"data through {last_date} ({sum(len(v['rows']) for v in data.values())} rows total)")
