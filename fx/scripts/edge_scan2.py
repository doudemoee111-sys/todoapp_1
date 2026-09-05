#!/usr/bin/env python3
"""終値ベース（前日終値→当日終値）でエッジを走査する。
始値/高値/安値は基準データに合成臭（O=H=L=C多数）があるため使わない。
close-to-close の騰落だけを使うので、データの日中クセに影響されない。
"""
import csv, json, math, datetime
from pathlib import Path
from collections import defaultdict

DATA = Path(__file__).resolve().parents[1] / "data"
DAILY = DATA / "daily"
SYMS = [("USDJPY","ドル円"),("EURJPY","ユーロ円"),("GBPJPY","ポンド円"),
        ("EURUSD","ユーロドル"),("GBPUSD","ポンドドル"),("GOLD","ゴールド")]
WD = ["月","火","水","木","金"]


def load(key):
    rows={}
    r=csv.reader(open(DATA/f"{key}.csv")); next(r)
    for x in r:
        if len(x)>=5:
            try: rows[x[0]]=float(x[4])
            except: pass
    for fp in sorted(DAILY.glob("*.json")):
        o=json.loads(fp.read_text()); d=o.get("date") or fp.stem; b=o.get(key)
        if b:
            try: rows[d]=float(b["close"])
            except: pass
    return [(d,rows[d]) for d in sorted(rows)]


def wl(k,n,z=1.96):
    if n==0: return 0.0
    p=k/n; return (p+z*z/(2*n)-z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/(1+z*z/n)

def rpt(name,k,n):
    if n==0: return f"  {name:30} n=0"
    wr=k/n*100; lo=wl(k,n)*100
    flag="★" if lo>=50 and n>=60 else ("◎" if lo>=55 else "")
    return f"  {name:30} 勝率{wr:5.1f}%  n={n:4d}  下限{lo:5.1f}% {flag}"


def analyze(key,label):
    s=load(key); n=len(s)
    c=[v for _,v in s]; dts=[d for d,_ in s]
    up=[None]+[c[i]>c[i-1] for i in range(1,n)]  # up[i]: close up vs prev
    print(f"\n===== {label}  {n}本  {dts[0]}〜{dts[-1]} =====")
    base_up=sum(1 for x in up[1:] if x)
    print(f"  参考: 全体の上昇日率 {base_up/(n-1)*100:.1f}%")

    # A) 曜日別 前日終値→当日終値 上昇率
    print(" [A] 曜日別: 前日終値比で当日終値が上/下")
    bd=defaultdict(lambda:[0,0])
    for i in range(1,n):
        y,m,d=map(int,dts[i].split("-")); wd=datetime.date(y,m,d).weekday()
        if wd<5:
            bd[wd][0]+= 1 if up[i] else 0; bd[wd][1]+=1
    for wd in range(5):
        k,t=bd[wd]
        better = k if k>=t-k else t-k
        side = "上昇" if k>=t-k else "下落"
        print(rpt(f"{WD[wd]}曜 {side}方向", better, t))

    # B) 連続{k}下落→翌日上昇 / 連続{k}上昇→翌日下落 (終値ベース逆張り)
    print(" [B] 終値ベース逆張り: N連続下落の翌日=上昇 / N連続上昇の翌日=下落")
    for k in (2,3,4,5):
        kb=nb=ks=ns=0
        for i in range(k+1,n):
            seg=up[i-k:i]
            if all(x is False for x in seg):
                nb+=1; kb+= 1 if up[i] else 0
            if all(x is True for x in seg):
                ns+=1; ks+= 1 if up[i] is False else 0
        print(rpt(f"{k}連下落→翌日買い",kb,nb))
        print(rpt(f"{k}連上昇→翌日売り",ks,ns))

    # C) モメンタム: 当日上昇→翌日も上昇
    kuu=nuu=kdd=ndd=0
    for i in range(2,n):
        if up[i-1]: nuu+=1; kuu+= 1 if up[i] else 0
        else: ndd+=1; kdd+= 1 if up[i] is False else 0
    print(" [C] 順張り(終値): 前日と同方向が継続")
    print(rpt("上昇の翌日も上昇",kuu,nuu))
    print(rpt("下落の翌日も下落",kdd,ndd))

    # D) トレンドフォロー: 終値 > Nsma のとき翌日上昇率 / 終値<Nsma で翌日下落率
    print(" [D] トレンドフィルタ: 終値が移動平均の上=翌日上昇 / 下=翌日下落")
    for w in (50,100,200):
        ka=na=kb2=nb2=0
        for i in range(w,n-1):
            ma=sum(c[i-w:i])/w
            if c[i]>ma:
                na+=1; ka+= 1 if up[i+1] else 0
            elif c[i]<ma:
                nb2+=1; kb2+= 1 if up[i+1] is False else 0
        print(rpt(f"{w}日線 上→翌日上昇",ka,na))
        print(rpt(f"{w}日線 下→翌日下落",kb2,nb2))

    # E) トレンド内押し目: 200日線の上で 2連続下落→翌日上昇
    print(" [E] 上昇トレンド(>200日線)内の 2連続下落→翌日上昇")
    for w in (100,200):
        k2=n2=0
        for i in range(w+2,n):
            ma=sum(c[i-w:i])/w
            if c[i-1]>ma and up[i-1] is False and up[i-2] is False:
                n2+=1; k2+= 1 if up[i] else 0
        print(rpt(f">{w}日線 2連下落→翌買い",k2,n2))

    # F) 週次: 月曜安→金曜高? (週の傾向) — 各週で最初と最後の終値比較
    print(" [F] 週間: 週の最初の終値<週の最後の終値 (週足陽線率)")
    weeks=defaultdict(list)
    for i in range(n):
        y,m,d=map(int,dts[i].split("-")); iso=datetime.date(y,m,d).isocalendar()
        weeks[(iso[0],iso[1])].append(c[i])
    wk=[v for _,v in sorted(weeks.items()) if len(v)>=2]
    kw=sum(1 for v in wk if v[-1]>v[0])
    print(rpt("週足 上昇",kw,len(wk)))


for k,l in SYMS:
    analyze(k,l)
print("\n★=95%下限が50%超(n>=60)  ◎=95%下限が55%超（特に堅い）")
