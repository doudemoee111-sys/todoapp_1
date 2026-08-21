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


def promote_everywhere(title: str, video_id: str, pkg: dict | None = None,
                       genre_key: str | None = None, publish_at_jst=None) -> dict:
    """Called from the generation run. Because uploads are SCHEDULED (private +
    publishAt), the YouTube link is not live yet — so we do NOT post now; the
    publish-time promo routine posts once the video is public. Returns the
    deferral note (or posts immediately if the pipeline is set to public)."""
    from config import UPLOAD_PRIVACY
    if UPLOAD_PRIVACY == "public":
        return promote_published(title, video_id, pkg,
                                 is_short="#Shorts" in (title or ""))
    return {"threads": "deferred: 公開時トリガーで投稿（予約投稿のためリンク未公開）"}


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
