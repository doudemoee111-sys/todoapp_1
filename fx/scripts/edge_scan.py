#!/usr/bin/env python3
"""蓄積データ（基準CSV+日次差分）から、経験的に勝率の高い日足ルールを走査する。

各ルールについて「シグナル発生時に翌営業日/当日が想定方向に動いた割合(勝率)」と
サンプル数、そして勝率が50%より有意に高い/低いかの95%信頼区間下限(Wilson)を出す。
土日は元々データに無い（営業日ベース）。
"""
import csv, json, math, statistics
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DAILY = DATA / "daily"
SYMS = [("USDJPY","ドル円"),("EURJPY","ユーロ円"),("GBPJPY","ポンド円"),
        ("EURUSD","ユーロドル"),("GBPUSD","ポンドドル"),("GOLD","ゴールド")]
WD = ["月","火","水","木","金","土","日"]


def load(key):
    rows = {}
    p = DATA / f"{key}.csv"
    if p.exists():
        r = csv.reader(open(p)); next(r, None)
        for x in r:
            if len(x) >= 5:
                try: rows[x[0]] = (float(x[1]),float(x[2]),float(x[3]),float(x[4]))
                except ValueError: pass
    if DAILY.exists():
        for fp in sorted(DAILY.glob("*.json")):
            try: o = json.loads(fp.read_text())
            except Exception: continue
            d = o.get("date") or fp.stem; b = o.get(key)
            if b:
                try: rows[d] = (float(b["open"]),float(b["high"]),float(b["low"]),float(b["close"]))
                except (KeyError,ValueError,TypeError): pass
    # 日付順の配列に
    out = []
    for d in sorted(rows):
        o,h,l,c = rows[d]
        out.append({"d":d,"o":o,"h":h,"l":l,"c":c})
    return out


def wilson_low(k, n, z=1.96):
    if n == 0: return 0.0
    p = k/n
    denom = 1+z*z/n
    centre = p + z*z/(2*n)
    margin = z*math.sqrt((p*(1-p)+z*z/(4*n))/n)
    return (centre - margin)/denom


def rpt(name, k, n):
    if n == 0:
        return f"  {name:34} n=0"
    wr = k/n*100
    lo = wilson_low(k,n)*100
    flag = "★" if lo >= 50 and n >= 60 else (" " if lo >= 50 else "")
    return f"  {name:34} 勝率{wr:5.1f}%  n={n:4d}  95%下限{lo:5.1f}% {flag}"


def analyze(key, label):
    rows = load(key)
    n = len(rows)
    print(f"\n===== {label} ({key})  {n}本  {rows[0]['d']}〜{rows[-1]['d']} =====")

    # 事前計算
    for i in range(n):
        r = rows[i]
        r["up"] = r["c"] > r["o"]          # 陽線(当日始値→終値)
        r["ret"] = r["c"] - r["o"]
        y,m,d = map(int, r["d"].split("-"))
        r["wd"] = None  # weekday from date
        import datetime
        r["wd"] = datetime.date(y,m,d).weekday()
        r["month"] = m

    # 1) 曜日別「当日陽線率」(その曜日に始値で買い→終値で決済)
    print(" [1] 曜日アノマリー: その曜日に寄付買い→引け決済で陽線になる率")
    byday = defaultdict(lambda:[0,0])
    for r in rows:
        byday[r["wd"]][0] += 1 if r["up"] else 0
        byday[r["wd"]][1] += 1
    for wd in range(5):
        k,tot = byday[wd]
        print(rpt(f"{WD[wd]}曜 買い(陽線)", k, tot))
        print(rpt(f"{WD[wd]}曜 売り(陰線)", tot-k, tot))

    # 2) 連続陰線→翌日反発(押し目買い) / 連続陽線→翌日反落
    print(" [2] 連続{n}陰線の翌日=陽線 / 連続{n}陽線の翌日=陰線 (逆張り)")
    for streak in (2,3,4):
        kb=nb=ks=ns=0
        for i in range(streak, n):
            prev = rows[i-streak:i]
            nxt = rows[i]
            if all(not p["up"] for p in prev):
                nb += 1; kb += 1 if nxt["up"] else 0
            if all(p["up"] for p in prev):
                ns += 1; ks += 1 if not nxt["up"] else 0
        print(rpt(f"{streak}連陰→翌日買い", kb, nb))
        print(rpt(f"{streak}連陽→翌日売り", ks, ns))

    # 3) モメンタム: 当日陽線→翌日も陽線 / 当日陰線→翌日も陰線
    print(" [3] 順張り: 当日と同じ方向が翌日も継続する率")
    kuu=nuu=kdd=ndd=0
    for i in range(1, n):
        if rows[i-1]["up"]:
            nuu+=1; kuu+= 1 if rows[i]["up"] else 0
        else:
            ndd+=1; kdd+= 1 if not rows[i]["up"] else 0
    print(rpt("陽線の翌日も陽線", kuu, nuu))
    print(rpt("陰線の翌日も陰線", kdd, ndd))

    # 4) ギャップ: 前日終値より上に寄れば当日陽線?（ギャップ順張り）
    print(" [4] ギャップ: 前日終値より高く寄った日→当日陽線 / 低く寄った日→当日陰線")
    kgu=ngu=kgd=ngd=0
    for i in range(1, n):
        gap = rows[i]["o"] - rows[i-1]["c"]
        if gap > 0:
            ngu+=1; kgu+= 1 if rows[i]["up"] else 0
        elif gap < 0:
            ngd+=1; kgd+= 1 if not rows[i]["up"] else 0
    print(rpt("上ギャップ→当日陽線", kgu, ngu))
    print(rpt("下ギャップ→当日陰線", kgd, ngd))

    # 5) 月末/月初アノマリー: 各月の最終営業日・第1営業日の翌日方向
    print(" [5] 月初(その月の最初の営業日)は陽線か")
    firsts = []
    seen = set()
    for r in rows:
        ym = r["d"][:7]
        if ym not in seen:
            seen.add(ym); firsts.append(r)
    kf = sum(1 for r in firsts if r["up"])
    print(rpt("月初 買い(陽線)", kf, len(firsts)))

    # 6) トレンドフィルタ: 200日移動平均より上で「陰線の翌日買い」(トレンド内押し目)
    print(" [6] 200日線より上で 2連陰線→翌日買い (順張り環境での押し目)")
    closes = [r["c"] for r in rows]
    kt=nt=0
    for i in range(200, n):
        ma = sum(closes[i-200:i])/200
        if rows[i-1]["c"] > ma and not rows[i-1]["up"] and not rows[i-2]["up"]:
            nt += 1; kt += 1 if rows[i]["up"] else 0
    print(rpt("上昇環境の2連陰→翌買い", kt, nt))


for key,label in SYMS:
    analyze(key, label)

print("\n★ = 95%信頼区間下限が50%超 かつ n>=60（統計的に勝率>50%と言える候補）")
