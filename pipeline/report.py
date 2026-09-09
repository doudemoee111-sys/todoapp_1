"""チャンネルの数値を自動取得して「管理レポート」を出力する。

目的: 日次マネジメント（別セッション）が毎回スクリーンショット待ち＝“要データ待ち”で
止まる問題を解消するため、YouTube Data API から各動画の視聴回数・高評価・コメント数を
取得し、長尺/ショートを分けて機械的にレポートする。CTR・視聴維持率・トラフィックソースは
youtubeAnalytics API（yt-analytics.readonly スコープ）が必要で、現在の refresh token には
無いため取得できない（＝別途ユーザー再同意が必要）。ここでは既存の OAuth（youtube/upload
スコープ）だけで取れる「公開統計」に限定して自動化する。

出力:
  - 標準出力に人間可読レポート
  - pipeline/output/report_latest.md （sekai の日次実行でコミット→管理セッションが git pull
    して読む、という受け渡しに使う）

使い方: cd pipeline && python3 report.py  （sekai 環境で認証情報が必要）
"""
from __future__ import annotations
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# youtube_upload の認証ヘルパを再利用（スコープ/チャンネルガードを一元化）
from youtube_upload import _service, _assert_expected_channel

JST = timezone(timedelta(hours=9))

# 長尺/ショートの分類しきい値（秒）。予告編ショートは40〜60秒、長尺は8〜10分なので
# 180秒で明確に分かれる。YouTube 的にもショートは最長180秒。
_SHORT_MAX_SEC = 180
# 「公開から N 日経っても M 再生未満」の長尺を不振として明示する基準。
_UNDERPERFORM_DAYS = 2
_UNDERPERFORM_VIEWS = 50


def _iso8601_duration_to_sec(s: str) -> int:
    """PT8M57S のような ISO8601 期間を秒に変換。失敗時は0。"""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def _fetch_uploads(yt, max_results: int = 50) -> list[str]:
    """アップロード済み（予約=private含む）動画IDを新しい順に返す。"""
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids: list[str] = []
    req = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50)
    while req is not None and len(ids) < max_results:
        resp = req.execute()
        for it in resp.get("items", []):
            vid = (it.get("contentDetails") or {}).get("videoId")
            if vid:
                ids.append(vid)
        req = yt.playlistItems().list_next(req, resp)
    return ids[:max_results]


def _fetch_video_rows(yt, ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        resp = yt.videos().list(
            part="snippet,contentDetails,statistics,status",
            id=",".join(chunk)).execute()
        for v in resp.get("items", []):
            sn = v.get("snippet") or {}
            st = v.get("statistics") or {}
            status = v.get("status") or {}
            dur = _iso8601_duration_to_sec((v.get("contentDetails") or {}).get("duration", ""))
            pub_raw = status.get("publishAt") or sn.get("publishedAt") or ""
            try:
                pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00")) if pub_raw else None
            except ValueError:
                pub_dt = None
            rows.append({
                "id": v.get("id"),
                "title": sn.get("title", ""),
                "dur": dur,
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
                "privacy": status.get("privacyStatus", "?"),
                "scheduled": bool(status.get("publishAt")),
                "pub": pub_dt,
            })
    return rows


def _age_days(pub_dt: datetime | None) -> float | None:
    if not pub_dt:
        return None
    return (datetime.now(timezone.utc) - pub_dt).total_seconds() / 86400.0


def _fmt_date(pub_dt: datetime | None) -> str:
    if not pub_dt:
        return "----/--/--"
    return pub_dt.astimezone(JST).strftime("%Y/%m/%d")


def build_report() -> str:
    yt = _service()
    # チャンネル概要（現在値）
    ch = yt.channels().list(part="snippet,statistics", mine=True).execute()
    citems = ch.get("items", [])
    ch_title = citems[0]["snippet"]["title"] if citems else "?"
    _assert_expected_channel(ch_title)  # 誤チャンネル安全装置
    cstats = (citems[0].get("statistics") if citems else {}) or {}
    subs = int(cstats.get("subscriberCount", 0) or 0)
    total_views = int(cstats.get("viewCount", 0) or 0)
    video_count = int(cstats.get("videoCount", 0) or 0)

    ids = _fetch_uploads(yt, max_results=50)
    rows = _fetch_video_rows(yt, ids)
    # 新しい順（pub 降順、Noneは末尾）
    rows.sort(key=lambda r: (r["pub"] is not None, r["pub"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)

    longs = [r for r in rows if r["dur"] > _SHORT_MAX_SEC]
    shorts = [r for r in rows if 0 < r["dur"] <= _SHORT_MAX_SEC]

    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M JST")
    L: list[str] = []
    L.append(f"# 自動レポート（{ch_title}）")
    L.append(f"生成: {now_str}")
    L.append("")
    L.append(f"- 登録者(現在): **{subs:,}**")
    L.append(f"- 総再生回数(累計): {total_views:,}　/　公開動画数: {video_count:,}")
    L.append(f"- 取得対象: 直近アップロード {len(rows)} 本（長尺 {len(longs)} / ショート {len(shorts)}）")
    L.append("")

    # ---- 長尺 ----
    L.append("## 長尺（本編）直近")
    L.append("")
    L.append("| 公開(JST) | 視聴 | 👍 | 💬 | 状態 | タイトル |")
    L.append("|---|---:|---:|---:|---|---|")
    under: list[dict] = []
    for r in longs[:15]:
        state = "予約" if r["scheduled"] else r["privacy"]
        L.append(f"| {_fmt_date(r['pub'])} | {r['views']:,} | {r['likes']} | {r['comments']} | {state} | {r['title'][:32]} |")
        age = _age_days(r["pub"])
        if (not r["scheduled"] and r["privacy"] == "public" and age is not None
                and age >= _UNDERPERFORM_DAYS and r["views"] < _UNDERPERFORM_VIEWS):
            under.append(r)
    L.append("")

    pub_longs = [r for r in longs if r["privacy"] == "public" and not r["scheduled"]]
    if pub_longs:
        recent10 = pub_longs[:10]
        avg = sum(r["views"] for r in recent10) / len(recent10)
        L.append(f"- 公開済み長尺 直近{len(recent10)}本の平均視聴: **{avg:,.0f}**")
    if under:
        L.append(f"- ⚠️ 不振長尺（公開{_UNDERPERFORM_DAYS}日+で{_UNDERPERFORM_VIEWS}再生未満）: **{len(under)}本**")
        for r in under[:8]:
            L.append(f"    - {_fmt_date(r['pub'])} 「{r['title'][:30]}」= {r['views']}回")
    L.append("")

    # ---- ショート ----
    L.append("## ショート 直近（視聴上位）")
    L.append("")
    L.append("| 公開(JST) | 視聴 | 👍 | タイトル |")
    L.append("|---|---:|---:|---|")
    pub_shorts = [r for r in shorts if r["privacy"] == "public" and not r["scheduled"]]
    for r in sorted(pub_shorts, key=lambda x: x["views"], reverse=True)[:12]:
        L.append(f"| {_fmt_date(r['pub'])} | {r['views']:,} | {r['likes']} | {r['title'][:34]} |")
    L.append("")
    if pub_shorts:
        recent_sh = sorted(pub_shorts, key=lambda x: (x["pub"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)[:12]
        avg_sh = sum(r["views"] for r in recent_sh) / len(recent_sh)
        L.append(f"- 公開済みショート 直近{len(recent_sh)}本の平均視聴: **{avg_sh:,.0f}**")
    L.append("")
    L.append("※ CTR・視聴維持率・流入元は本レポートでは取得不可（youtubeAnalytics スコープ未付与）。"
             "これらが必要な場合は yt-analytics.readonly を含めて再認可が必要。")
    return "\n".join(L)


def main() -> int:
    try:
        report = build_report()
    except Exception as e:  # noqa: BLE001
        print(f"[report] 失敗: {e}", file=sys.stderr)
        return 1
    print(report)
    out = Path(__file__).resolve().parent / "output" / "report_latest.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\n[report] 書き出し: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
