"""外部流入（Threads中心）のクローズドループ。

方針: 動画の「公開時」に自分の Threads へ自動投稿し、Threads 公式インサイトで
「どの投稿が伸びたか（=YouTube視聴に効いたか）」を計測して、次の投稿の型を改善する。
他人の投稿を分析するAPIは制約が大きいため、"自分の投稿の実測データで学習する" のが
現実的で継続可能。

必要な環境変数（未設定なら全て best-effort でスキップ）:
  THREADS_USER_ID      … Threads（Meta）のユーザーID
  THREADS_ACCESS_TOKEN … Threads Graph API の長期アクセストークン

APIリファレンス: https://developers.facebook.com/docs/threads
投稿は2ステップ（コンテナ作成 → publish）。
"""
from __future__ import annotations
import os

from http_retry import request_with_retry

THREADS_API = "https://graph.threads.net/v1.0"


def threads_enabled() -> bool:
    return bool(os.environ.get("THREADS_ACCESS_TOKEN") and os.environ.get("THREADS_USER_ID"))


# ---- posting -----------------------------------------------------------------
def _threads_post(text: str, link: str | None = None) -> str:
    """Publish a text post (optionally with a link attachment). Returns media id."""
    uid = os.environ["THREADS_USER_ID"]
    tok = os.environ["THREADS_ACCESS_TOKEN"]
    data = {"media_type": "TEXT", "text": text[:490], "access_token": tok}
    if link:
        data["link_attachment"] = link
    r = request_with_retry("POST", f"{THREADS_API}/{uid}/threads", data=data, timeout=30)
    r.raise_for_status()
    creation_id = r.json()["id"]
    r2 = request_with_retry("POST", f"{THREADS_API}/{uid}/threads_publish",
                            data={"creation_id": creation_id, "access_token": tok}, timeout=30)
    r2.raise_for_status()
    return r2.json().get("id", "")


def craft_threads_text(title: str, url: str, pkg: dict | None = None,
                       is_short: bool = False) -> str:
    """A curiosity-first Threads post: hook → 寸止め → link. Kept template-based
    (no LLM dependency) so promotion never fails on a model hiccup."""
    hook = title.replace(" #Shorts", "").strip()
    teaser = ""
    if pkg and pkg.get("narration"):
        first = pkg["narration"].split("。")[0].strip()
        if 8 <= len(first) <= 60:
            teaser = first + "…"
    tags = pkg.get("hashtags") if pkg else None
    if not tags:
        tags = ["#雑学", "#ミステリー", "#都市伝説", "#宇宙"]
    tagline = " ".join(t for t in tags if t.startswith("#"))[:60]
    body = hook
    if teaser:
        body += f"\n\n{teaser}"
    body += f"\n\n▶ 続きはこちら\n{url}"
    if tagline:
        body += f"\n\n{tagline}"
    return body


def promote_published(title: str, video_id: str, pkg: dict | None = None,
                      is_short: bool = False) -> dict:
    """Post an ALREADY-PUBLIC video to Threads. Meant to be called at/after the
    video's publish time (so the link is live). Best-effort."""
    url = f"https://youtu.be/{video_id}"
    if not threads_enabled():
        return {"threads": "skip: THREADS_ACCESS_TOKEN/USER_ID 未設定"}
    try:
        text = craft_threads_text(title, url, pkg, is_short)
        mid = _threads_post(text, link=url)
        print(f"  [threads] 投稿しました id={mid}")
        return {"threads": "posted", "media_id": mid, "url": url}
    except Exception as e:  # noqa: BLE001
        print(f"  [threads] 投稿に失敗（best-effort）: {e}")
        return {"threads": f"error: {e}"}


def _fmt_when(publish_at_jst) -> str:
    """publish_at を『YYYY-MM-DD HH:MM JST』の一言に整える（不明なら空文字）。"""
    if publish_at_jst is None:
        return ""
    try:
        return publish_at_jst.strftime("%Y-%m-%d %H:%M JST")
    except Exception:  # noqa: BLE001  (str や isoformat 済みが来た場合)
        return str(publish_at_jst)


def build_draft(title: str, video_id: str, pkg: dict | None = None,
                is_short: bool = False, publish_at_jst=None) -> dict:
    """公開時に『手動で』投稿するための Threads 下書きを作って返す（投稿はしない）。
    ユーザー方針: 自動投稿ではなく、都度この下書きを確認して自分でThreadsへ貼る。"""
    url = f"https://youtu.be/{video_id}"
    return {
        "kind": "予告編ショート" if is_short else "長尺",
        "draft_text": craft_threads_text(title, url, pkg, is_short),
        "url": url,
        "publish_at_jst": _fmt_when(publish_at_jst),
        "is_short": is_short,
    }


def format_draft_block(draft: dict) -> str:
    """トリガーの最終報告にそのまま貼れる、コピペ用の下書きブロックを整形する。"""
    when = draft.get("publish_at_jst") or "公開時刻はYouTube Studioで確認"
    return (
        f"\n=========== THREADS 下書き（{draft.get('kind', '')}）===========\n"
        f"公開予定: {when} ／ ★リンクが有効になる“公開後”に投稿してください\n"
        f"--- ここからコピー ---\n"
        f"{draft['draft_text']}\n"
        f"--- ここまで ---\n"
        f"===============================================================\n"
    )


def promote_everywhere(title: str, video_id: str, pkg: dict | None = None,
                       genre_key: str | None = None, publish_at_jst=None) -> dict:
    """Called from the generation run. Uploads are SCHEDULED (private + publishAt),
    so the YouTube link is not live yet. ユーザー方針＝『自動投稿はせず、毎回Threads
    下書きを作ってユーザーが手動投稿』。よってここでは投稿せず、下書きを返す
    （UPLOAD_PRIVACY=public の即時公開時のみ、従来どおり自動投稿も行える）。"""
    from config import UPLOAD_PRIVACY
    is_short = "#Shorts" in (title or "")
    draft = build_draft(title, video_id, pkg, is_short=is_short,
                        publish_at_jst=publish_at_jst)
    if UPLOAD_PRIVACY == "public":
        posted = promote_published(title, video_id, pkg, is_short=is_short)
        return {**posted, **draft}  # 自動投稿の結果に下書きも同梱
    return {"threads": "draft", **draft}


# ---- analysis loop -----------------------------------------------------------
def threads_recent_insights(limit: int = 25) -> list[dict]:
    """Our recent Threads posts with their insight metrics, newest first. Used by
    the weekly analysis to learn which post styles drove the most reach/clicks.
    Returns [] on any error (never blocks)."""
    if not threads_enabled():
        return []
    uid = os.environ["THREADS_USER_ID"]
    tok = os.environ["THREADS_ACCESS_TOKEN"]
    try:
        r = request_with_retry(
            "GET", f"{THREADS_API}/{uid}/threads",
            params={"fields": "id,text,permalink,timestamp,media_type",
                    "limit": limit, "access_token": tok}, timeout=30)
        r.raise_for_status()
        out = []
        for it in r.json().get("data", []):
            metrics = {}
            try:
                ri = request_with_retry(
                    "GET", f"{THREADS_API}/{it['id']}/insights",
                    params={"metric": "views,likes,replies,reposts,quotes",
                            "access_token": tok}, timeout=30)
                if ri.status_code == 200:
                    for m in ri.json().get("data", []):
                        vals = m.get("values") or [{}]
                        metrics[m.get("name")] = vals[0].get("value", 0)
            except Exception:  # noqa: BLE001
                pass
            out.append({"text": (it.get("text") or "")[:80],
                        "permalink": it.get("permalink"),
                        "timestamp": it.get("timestamp"),
                        **metrics})
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  [threads] インサイト取得に失敗: {e}")
        return []
