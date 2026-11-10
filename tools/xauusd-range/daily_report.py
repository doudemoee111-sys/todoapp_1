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

# Which broker clock each boundary corresponds to, and when its bar turns over.
BROKERS = {
    "nyclose": ("Axiory 方式", "NY 17:00クローズ（サーバー GMT+2/+3）",
                "冬 07:00 JST / 夏 06:00 JST"),
    "utc": ("Exness 方式", "00:00 UTC（サーバー GMT+0 固定・DSTなし）",
            "通年 09:00 JST"),
}


def session_bounds(sess: dt.date, convention: str):
    if convention == "utc":
        a = dt.datetime.combine(sess, dt.time(0), tzinfo=UTC)
    else:
        a = dt.datetime.combine(sess - dt.timedelta(days=1), dt.time(17), tzinfo=NY)
    return a.astimezone(JST), (a + dt.timedelta(days=1)).astimezone(JST)


def session_now(convention: str, now=None) -> dt.date:
    now = now or dt.datetime.now(UTC)
    if convention == "utc":
        return now.astimezone(UTC).date()
    return (now.astimezone(NY) + dt.timedelta(hours=7)).date()


def target_session(convention: str, now=None):
    """The session to forecast.

    A session with under 3 hours left is nearly over, so the next one is the
    useful target. Its previous close is only known once the boundary passes,
    so a report for the `utc` boundary cannot be produced before 09:00 JST --
    see HANDOFF in the README.
    """
    now = now or dt.datetime.now(UTC)
    sess = session_now(convention, now)
    _, end = session_bounds(sess, convention)
    if (end - now.astimezone(JST)).total_seconds() < 3 * 3600:
        return sess + dt.timedelta(days=1), True
    return sess, False


def conditional(d_hist, hourly, full_days, elapsed, ph, pl, sigma):
    """Distribution of the final extremes given the session so far.

    `elapsed` counts hours from the session's own start, not clock hours. The
    session starts at 07:00 JST in winter and 06:00 in summer, so matching on
    absolute JST hours pulls the wrong bars once DST moves: in summer a window
    of {06:00, 07:00} also selects, on every winter session, the hour that
    CLOSES it -- the partial high and low would then contain the end of the
    day they are meant to predict.
    """
    hh = hourly[hourly["day"].isin(full_days)].copy()
    hh = hh[hh["vol"] > 0].sort_values("ts")
    hh["pos"] = hh.groupby("day").cumcount()
    part = (hh[hh["pos"] < elapsed].groupby("day")
              .agg(ph=("high", "max"), pl=("low", "min"), n=("high", "size")))
    part = part[part.n >= elapsed - 1]
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


def render(convention: str, lines: list) -> dict | None:
    """Append one convention's full report block. Returns summary info."""
    P = lines.append
    label, boundary, turnover = BROKERS[convention]

    d_all, hourly = build(convention)
    hourly = hourly.copy()
    hourly["jst"] = hourly["ts"].dt.tz_convert(JST).dt.hour
    sess, rolled = target_session(convention)
    comp = d_all[(d_all["bars"] >= 20) & (d_all["date"].dt.date < sess)].reset_index(drop=True)
    if comp.empty:
        P(f"## {label}\n\n前セッションが未確定のためレポートを生成できません。\n")
        return None
    prev = comp.iloc[-1]
    s_start, s_end = session_bounds(sess, convention)
    now_jst = dt.datetime.now(JST)

    # the previous close must already have printed
    if prev["date"].date() != sess - dt.timedelta(days=1) and not rolled:
        pass
    if s_start > now_jst:
        P(f"## {label}（{boundary}）\n")
        P(f"対象セッションは {s_start:%m/%d %H:%M} JST 開始で、前セッションの終値が未確定です。")
        P(f"この方式のレポートは **{turnover} 以降**に生成してください。\n")
        return None

    f = fc.build(prev["date"], convention)
    cur = d_all[d_all["date"].dt.date == sess]
    cur_h = hourly[hourly["day"] == sess]
    if len(cur_h):
        data_end = cur_h["ts"].max().tz_convert(JST) + dt.timedelta(hours=1)
        elapsed = max(0, int((min(data_end, s_end) - s_start).total_seconds() // 3600))
    else:
        elapsed, data_end = 0, s_start

    P(f"## {label}\n")
    P(f"- **日足区切り**: {boundary} / バー切替 {turnover}")
    P(f"- **対象セッション**: {s_start:%m/%d %H:%M} JST 〜 {s_end:%m/%d %H:%M} JST")
    P(f"- **データ終端**: {data_end:%m/%d %H:%M} JST（経過 {elapsed}時間）")
    P(f"- **実セッション**: {len(comp):,}本（{comp.date.min():%Y-%m-%d}〜{comp.date.max():%Y-%m-%d}）\n")

    P(f"### 前セッション（{prev['date']:%m/%d}）\n")
    P("| 始値 | 高値 | 安値 | 終値 | 値幅 |")
    P("|---|---|---|---|---|")
    P(f"| {prev.open:.2f} | {prev.high:.2f} | {prev.low:.2f} | **{prev.close:.2f}** | ${prev.high-prev.low:.2f} |\n")
    P(f"σ(EWMA 半減期20日) **${f['sigma']:.2f}** / ATR14(Wilder) **${f['atr14']:.2f}**\n")

    P("### 想定値幅（高値−安値）\n")
    P("| 25% | 中位 | 75% | 90% |")
    P("|---|---|---|---|")
    P("| " + " | ".join(f"${v:.2f}" for v in f["range_q"]) + " |\n")

    P(f"### 高値・安値レンジ（基準：前日終値 {prev.close:.2f}）\n")
    P("| 被覆率 | 高値 上限 | 安値 下限 | 箱幅 |")
    P("|---|---|---|---|")
    for b in f["boxes"]:
        bd = "**" if b["target"] == 0.80 else ""
        P(f"| {bd}{b['target']*100:.0f}%{bd} | {bd}{b['high']:.2f}{bd} | {bd}{b['low']:.2f}{bd} | ${b['high']-b['low']:.2f} |")
    P("")

    if len(cur) and elapsed >= 2:
        c = cur.iloc[0]
        P(f"### 実測（{s_start:%H:%M} 〜 {data_end:%H:%M} JST、{elapsed}時間経過）\n")
        P("| 高値 | 安値 | 現在値 | 値幅 |")
        P("|---|---|---|---|")
        P(f"| **{c.high:.2f}** | **{c.low:.2f}** | {c.close:.2f} | ${c.high-c.low:.2f} |\n")
        inside = [b["target"] for b in f["boxes"] if c.high <= b["high"] and c.low >= b["low"]]
        P(f"判定：{f'最小 {min(inside)*100:.0f}%箱の内側' if inside else '90%箱を逸脱'}\n")
        full_days = set(comp["date"].dt.date)
        cd = conditional(comp, hourly, full_days, elapsed, c.high, c.low, f["sigma"])
        if cd:
            P("### 残りセッションの条件付き予測\n")
            P(f"- 高値がすでに確定している確率 **{cd['p_high_set']*100:.1f}%**")
            P(f"- 安値がすでに確定している確率 **{cd['p_low_set']*100:.1f}%**\n")
            P("| 被覆率 | 最終高値 上限 | 最終安値 下限 |")
            P("|---|---|---|")
            for b in cd["boxes"]:
                P(f"| {b['target']*100:.0f}% | {b['high']:.2f} | {b['low']:.2f} |")
            P("")

    P("### 主要節目\n")
    rows = [("前セッション高値", prev.high), ("前セッション安値", prev.low)]
    rows += list(f["piv"].items())
    w20 = comp.tail(20)
    rows += [("直近20日高値", w20.high.max()), ("直近20日安値", w20.low.min())]
    P("| 区分 | 水準 |"); P("|---|---|")
    for k, v in sorted(rows, key=lambda x: -x[1]):
        P(f"| {k} | {v:.2f} |")
    P("")

    st = ist.stats(250, convention)
    P(f"### 高値・安値の形成時刻（直近{st['n_recent']}セッション）\n")
    P("| セッション | JST | 高値形成 | 安値形成 |"); P("|---|---|---|---|")
    for name, a_, b_ in ist.BLOCKS:
        P(f"| {name} | {a_:02d}–{b_:02d} | {st['block_high_recent'].get(name,0)*100:.1f}% "
          f"| {st['block_low_recent'].get(name,0)*100:.1f}% |")
    P("")
    P(f"- アジア時間の値幅＝日中値幅の **{st['asia_share']*100:.1f}%**（中位 {st['asia_share_med']*100:.1f}%）")
    P(f"- アジア高値が日中高値として残る **{st['asia_hi_held']*100:.1f}%** / "
      f"安値が残る **{st['asia_lo_held']*100:.1f}%** / 両端を破る **{st['asia_both_broken']*100:.1f}%**\n")

    try:
        evs = cal.session_events_window(cal.fetch(), s_start, s_end)
    except Exception as e:
        evs = None
        print(f"[warn] calendar unavailable: {e}", file=sys.stderr)
    P("### イベント注記（本セッション内）\n")
    if evs:
        P("| 時刻 JST | 重要度 | 国 | 指標 | 予想 | 結果 |"); P("|---|---|---|---|---|---|")
        for e in evs:
            P(f"| {e['when']:%m/%d %H:%M} | {'★'*e['importance']} | {e['country']} | "
              f"{e['name']} | {e['forecast'] or '-'} | {e['actual'] or '-'} |")
    elif evs is None:
        P("カレンダー取得に失敗したため、イベント情報は含まれていません。")
    else:
        P("本セッション内に金相場に影響する主要指標はありません。")
    P("")
    return {"box80": f["boxes"][2], "sess": sess}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-update", action="store_true")
    ap.add_argument("--convention", default="nyclose",
                    choices=["nyclose", "utc", "both"])
    a = ap.parse_args()

    if not a.no_update:
        from update import update_history, update_recent
        update_history(); update_recent()

    convs = ["nyclose", "utc"] if a.convention == "both" else [a.convention]
    L = [f"# XAU/USD デイリーレンジ予測", ""]
    L.append(f"作成 {dt.datetime.now(JST):%Y-%m-%d %H:%M} JST / "
             f"データ Dukascopy XAU/USD bid 1時間足\n")
    if len(convs) > 1:
        L.append("業者のサーバー時間で日足の区切りが異なるため、方式別に算出しています。"
                 "直近250セッションでは高安が両方式で一致するのは54.0%のみです。\n")
    info = {}
    for c in convs:
        info[c] = render(c, L)
        L.append("---\n")

    L.append("## 制約事項\n")
    for c in convs:
        if info.get(c):
            b = info[c]["box80"]
            L.append(f"- {BROKERS[c][0]}：80%箱の幅は ${b['high']-b['low']:.0f}。"
                     "平均的な1日はその4割強しか使いません。エントリー根拠ではなく"
                     "「この外側で逆張りしない」線として使ってください。")
    L.append("- 当データは **bid**。MT4/MT5のチャートもbid表示なので一致しますが、"
             "買いの決済・逆指値は **ask** で約定するため、上側は実効的に "
             "`高値 + スプレッド` になります。業者のゴールドのスプレッドを加味してください。")
    L.append("- 22:00 UTC はロールオーバー休止でフィードが歯抜けになります。")
    L.append("- 本レポートは定量分析であり、投資助言ではありません。")

    txt = "\n".join(L)
    tag = a.convention if a.convention != "both" else "both"
    sess = next((i["sess"] for i in info.values() if i), dt.date.today())
    out = REPORTS / f"XAUUSD_{sess:%Y%m%d}_{tag}.md"
    out.write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\n[saved] {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
