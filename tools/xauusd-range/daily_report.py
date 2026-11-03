#!/usr/bin/env python3
"""XAU/USD daily high/low range report (NY-close sessions, JST presentation).

    python3 daily_report.py              # refresh data, write today's report
    python3 daily_report.py --no-update  # reuse data on disk

Writes reports/XAUUSD_<session>.md and prints it.
"""
from __future__ import annotations
import argparse, datetime as dt, sys
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import range_model as rm
import forecast as fc
import intraday_stats as ist
import calendar_jp as cal
from duka import session_label, JST, NY, UTC, OUT
from build_daily import build

REPORTS = Path(__file__).parent / "reports"; REPORTS.mkdir(exist_ok=True)
LEVELS = (0.50, 0.70, 0.80, 0.90)


def session_now(now=None) -> dt.date:
    now = now or dt.datetime.now(UTC)
    return (now.astimezone(NY) + dt.timedelta(hours=7)).date()


def session_bounds(sess: dt.date):
    a = dt.datetime.combine(sess - dt.timedelta(days=1), dt.time(17), tzinfo=NY)
    return a.astimezone(JST), (a + dt.timedelta(days=1)).astimezone(JST)


def conditional(d_hist, hourly, full_days, elapsed_hours, ph, pl, sigma):
    """Distribution of the final extremes given the session so far."""
    hh = hourly[hourly["day"].isin(full_days)]
    part = (hh[hh.jst.isin(elapsed_hours)].groupby("day")
              .agg(ph=("high", "max"), pl=("low", "min"), n=("high", "size")))
    part = part[part.n >= len(elapsed_hours) - 1]
    comp = d_hist.copy(); comp["dk"] = comp["date"].dt.date
    j = part.join(comp.set_index("dk")[["high", "low"]], how="inner")
    dd = rm.prepare(d_hist); dd["dk"] = dd["date"].dt.date
    j = j.join(dd.set_index("dk")[["sigma"]], how="inner").dropna()
    if len(j) < 200:
        return None
    j["eu"] = (j.high - j.ph) / j.sigma
    j["ed"] = (j.pl - j.low) / j.sigma
    w = 0.5 ** (np.arange(len(j))[::-1] / rm.HIST_HALFLIFE)
    eu, ed = j.eu.to_numpy(), j.ed.to_numpy()
    out = {"n": len(j),
           "p_high_set": float(w[eu <= 1e-9].sum() / w.sum()),
           "p_low_set": float(w[ed <= 1e-9].sum() / w.sum()), "boxes": []}
    for t in LEVELS:
        lo_q, hi_q = 0.5, 0.9995
        for _ in range(60):
            q = (lo_q + hi_q) / 2
            ru, rd = rm.wq(eu, w, q)[0], rm.wq(ed, w, q)[0]
            covq = w[(eu <= ru) & (ed <= rd)].sum() / w.sum()
            if covq < t: lo_q = q
            else: hi_q = q
        q = (lo_q + hi_q) / 2
        ru, rd = rm.wq(eu, w, q)[0], rm.wq(ed, w, q)[0]
        out["boxes"].append({"target": t, "high": ph + ru * sigma, "low": pl - rd * sigma,
                             "fit": float(w[(eu <= ru) & (ed <= rd)].sum() / w.sum())})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-update", action="store_true")
    a = ap.parse_args()

    if not a.no_update:
        from update import update_history, update_recent
        update_history(); update_recent()

    d_all, hourly = build()
    hourly = hourly.copy()
    hourly["jst"] = hourly["ts"].dt.tz_convert(JST).dt.hour
    sess = session_now()
    comp = d_all[(d_all["bars"] >= 20) & (d_all["date"].dt.date < sess)].reset_index(drop=True)
    prev = comp.iloc[-1]
    f = fc.build(prev["date"])

    cur = d_all[d_all["date"].dt.date == sess]
    s_start, s_end = session_bounds(sess)
    now_jst = dt.datetime.now(JST)
    # elapsed must follow the DATA, not the wall clock: the feed lags by an hour
    # or more, and the conditional model conditions on the hours actually covered.
    cur_h = hourly[hourly["day"] == sess]
    if len(cur_h):
        data_end = cur_h["ts"].max().tz_convert(JST) + dt.timedelta(hours=1)
        elapsed = max(0, int((min(data_end, s_end) - s_start).total_seconds() // 3600))
    else:
        elapsed = 0
        data_end = s_start

    # economic calendar
    try:
        evs = cal.session_events(cal.fetch(), sess)
    except Exception as e:
        evs = []; print(f"[warn] calendar unavailable: {e}", file=sys.stderr)

    st = ist.stats(250)
    L = []
    P = L.append
    P(f"# XAU/USD デイリーレンジ予測\n")
    P(f"## {sess.strftime('%Y年%-m月%-d日')}（{'月火水木金土日'[sess.weekday()]}）セッション\n")
    P(f"- **セッション**: {s_start:%m/%d %H:%M} JST 〜 {s_end:%m/%d %H:%M} JST（NY 17:00クローズ基準）")
    P(f"- **作成時刻**: {now_jst:%Y-%m-%d %H:%M} JST ／ データ終端 {data_end:%H:%M} JST（経過 {elapsed}時間）")
    P(f"- **データ**: Dukascopy XAU/USD bid 1時間足 / 実セッション {len(comp):,}本 "
      f"（{comp.date.min():%Y-%m-%d}〜{comp.date.max():%Y-%m-%d}）\n")

    P(f"## 1. 前セッション（{prev['date']:%m/%d}）\n")
    P("| 始値 | 高値 | 安値 | 終値 | 値幅 |")
    P("|---|---|---|---|---|")
    P(f"| {prev.open:.2f} | {prev.high:.2f} | {prev.low:.2f} | **{prev.close:.2f}** | ${prev.high-prev.low:.2f} |\n")
    P(f"σ(EWMA 半減期20日) **${f['sigma']:.2f}** / ATR14(Wilder) **${f['atr14']:.2f}**\n")

    P("## 2. 想定値幅（高値−安値）\n")
    P("| 25% | 中位 | 75% | 90% |")
    P("|---|---|---|---|")
    P("| " + " | ".join(f"${v:.2f}" for v in f["range_q"]) + " |\n")

    P(f"## 3. 高値・安値レンジ（基準：前日終値 {prev.close:.2f}）\n")
    P("| 被覆率 | 高値 上限 | 安値 下限 | 箱幅 |")
    P("|---|---|---|---|")
    for b in f["boxes"]:
        bold = "**" if b["target"] == 0.80 else ""
        P(f"| {bold}{b['target']*100:.0f}%{bold} | {bold}{b['high']:.2f}{bold} | "
          f"{bold}{b['low']:.2f}{bold} | ${b['high']-b['low']:.2f} |")
    P("")

    if len(cur) and elapsed >= 2:
        c = cur.iloc[0]
        P(f"## 4. 実測（{s_start:%H:%M} 〜 {data_end:%H:%M} JST、{elapsed}時間経過）\n")
        P("| 高値 | 安値 | 現在値 | 値幅 |")
        P("|---|---|---|---|")
        P(f"| **{c.high:.2f}** | **{c.low:.2f}** | {c.close:.2f} | ${c.high-c.low:.2f} |\n")
        inside = [b['target'] for b in f["boxes"] if c.high <= b["high"] and c.low >= b["low"]]
        P(f"判定：{'最小' + f'{min(inside)*100:.0f}' + '%箱の内側' if inside else '90%箱を逸脱'}\n")
        full_days = set(comp["date"].dt.date)
        hrs = sorted({(s_start + dt.timedelta(hours=i)).hour for i in range(elapsed)})
        cd = conditional(comp, hourly, full_days, hrs, c.high, c.low, f["sigma"])
        if cd:
            P(f"### 残りセッションの条件付き予測\n")
            P(f"- 高値がすでに確定している確率 **{cd['p_high_set']*100:.1f}%**")
            P(f"- 安値がすでに確定している確率 **{cd['p_low_set']*100:.1f}%**\n")
            P("| 被覆率 | 最終高値 上限 | 最終安値 下限 |")
            P("|---|---|---|")
            for b in cd["boxes"]:
                P(f"| {b['target']*100:.0f}% | {b['high']:.2f} | {b['low']:.2f} |")
            P("")

    P("## 5. 主要節目\n")
    piv = f["piv"]
    rows = [("前セッション高値", prev.high), ("前セッション安値", prev.low)]
    rows += [(k, v) for k, v in piv.items()]
    w20 = comp.tail(20)
    rows += [("直近20日高値", w20.high.max()), ("直近20日安値", w20.low.min())]
    P("| 区分 | 水準 |"); P("|---|---|")
    for k, v in sorted(rows, key=lambda x: -x[1]):
        P(f"| {k} | {v:.2f} |")
    P("")

    P(f"## 6. 高値・安値の形成時刻（直近{st['n_recent']}セッション）\n")
    P("| セッション | JST | 高値形成 | 安値形成 |"); P("|---|---|---|---|")
    for name, a_, b_ in ist.BLOCKS:
        P(f"| {name} | {a_:02d}–{b_:02d} | {st['block_high_recent'].get(name,0)*100:.1f}% "
          f"| {st['block_low_recent'].get(name,0)*100:.1f}% |")
    P("")
    P(f"- アジア時間の値幅＝日中値幅の **{st['asia_share']*100:.1f}%**（中位 {st['asia_share_med']*100:.1f}%）")
    P(f"- アジア高値が日中高値として残る **{st['asia_hi_held']*100:.1f}%** / "
      f"安値が残る **{st['asia_lo_held']*100:.1f}%** / 両端を破る **{st['asia_both_broken']*100:.1f}%**\n")

    P("## 7. イベント注記（本セッション内）\n")
    if evs:
        P("| 時刻 JST | 重要度 | 国 | 指標 | 予想 | 結果 |"); P("|---|---|---|---|---|---|")
        for e in evs:
            P(f"| {e['when']:%m/%d %H:%M} | {'★'*e['importance']} | {e['country']} | "
              f"{e['name']} | {e['forecast'] or '-'} | {e['actual'] or '-'} |")
    else:
        P("本セッション内に金相場に影響する主要指標はありません。")
    P("")

    P("## 8. 制約事項\n")
    P(f"1. 80%箱の幅は ${f['boxes'][2]['high']-f['boxes'][2]['low']:.0f} で、平均的な1日はその4割強しか使いません。"
      "エントリー根拠ではなく「この外側で逆張りしない」線として使ってください。")
    P("2. Dukascopyのbidレート。業者間でヒゲが数ドル〜十数ドル違うため、許容を持たせてください。")
    P("3. 22:00 UTC はロールオーバー休止でフィードが歯抜けになります。")
    P("4. 本レポートは定量分析であり、投資助言ではありません。")

    txt = "\n".join(L)
    out = REPORTS / f"XAUUSD_{sess:%Y%m%d}.md"
    out.write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n[saved] {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
