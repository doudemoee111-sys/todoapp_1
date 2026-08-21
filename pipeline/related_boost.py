"""Make our video more likely to surface as a *suggested / related* video next
to popular videos on the same topic.

YouTube's suggested-video system clusters videos by topic, co-viewership and
metadata. We can't fake co-viewership, but we CAN align our metadata to the
cluster of top-performing videos for the topic: harvest the salient keywords
from their (public) titles and channels, then fold matching tags + description
phrasing into our upload so YouTube associates our video with that cluster —
raising the odds of appearing in the "次のおすすめ" rail of those videos.

Uses the authenticated YouTube Data API (the same OAuth credential as upload —
no extra key needed) to read competitor titles, and the OpenAI model already in
the pipeline to synthesize the tags. Best-effort throughout: any failure returns
empty extras so a run is never blocked by this optimisation.
"""
from __future__ import annotations
import json

from config import GENRES


def _top_context(query: str, max_results: int = 25) -> dict:
    """Public titles + channel names of the currently top-viewed videos for the
    topic (the cluster we want to be suggested alongside). Tags of other
    channels' videos are NOT returned by the API, so we align on titles."""
    try:
        from youtube_upload import _service
        yt = _service()
        resp = yt.search().list(
            part="snippet", q=query, type="video", regionCode="JP",
            relevanceLanguage="ja", order="viewCount", maxResults=max_results,
        ).execute()
        titles, channels = [], []
        for it in resp.get("items", []):
            sn = it.get("snippet", {})
            if sn.get("title"):
                titles.append(sn["title"])
            if sn.get("channelTitle"):
                channels.append(sn["channelTitle"])
        return {"titles": titles, "channels": channels}
    except Exception as e:  # noqa: BLE001
        print(f"  [related] 上位動画の取得に失敗（メタデータ最適化はスキップ）: {e}")
        return {"titles": [], "channels": []}


def _synth_tags(genre: dict, topic: str, our_title: str, competitor_titles: list[str]) -> dict:
    """Ask the model for tags/keywords that place us in the same cluster as the
    top videos, plus a couple of natural description keyword-phrases."""
    from llm_script import _chat
    joined = "\n".join(f"- {t}" for t in competitor_titles[:25]) or "(取得なし)"
    user = f"""あなたはYouTube SEOの専門家です。次の新規動画を、同じ題材の「人気動画の関連動画（次のおすすめ）」に表示されやすくするためのメタデータを作ります。

新規動画のタイトル: {our_title}
ジャンル: {genre['label']} / テーマ: {topic}

同じ題材で今よく見られている人気動画のタイトル一覧（この“クラスタ”に寄せたい）:
{joined}

上のクラスタと視聴者・文脈が重なるように、次をJSONで出力:
- tags: 日本語中心のタグ12〜15個。人気動画群に共通して現れる語・固有名詞・シリーズ名・関連トピックを反映し、本動画の内容と矛盾しない範囲で“同じ視聴者が検索/回遊する語”を優先。誇大・無関係な釣り語は禁止。
- desc_keywords: 概要欄の冒頭〜中盤に自然に織り込む日本語キーフレーズ3〜5個（各10〜20字）。関連づけを強めるが、日本語として自然な語にする。
JSON: {{"tags": [str,...], "desc_keywords": [str,...]}}"""
    try:
        data = json.loads(_chat(
            [{"role": "system", "content": "YouTube SEO最適化器。出力はJSONのみ。"},
             {"role": "user", "content": user}], temperature=0.5, json_mode=True))
        tags = [t.strip() for t in (data.get("tags") or []) if t and t.strip()]
        kw = [k.strip() for k in (data.get("desc_keywords") or []) if k and k.strip()]
        return {"tags": tags[:15], "desc_keywords": kw[:5]}
    except Exception as e:  # noqa: BLE001
        print(f"  [related] タグ合成に失敗（スキップ）: {e}")
        return {"tags": [], "desc_keywords": []}


def build_related_boost(genre_key: str, topic: str, title: str) -> dict:
    """Return {'tags': [...], 'desc_keywords': [...]} to merge into the upload so
    the video aligns with the popular-video cluster for this topic. Never raises."""
    genre = GENRES[genre_key]
    # Query the cluster with the topic plus the genre's core term.
    query = f"{topic} {genre['label']}".strip()
    ctx = _top_context(query)
    if not ctx["titles"]:
        # Fall back to a genre-level query so we still align to the broad cluster.
        ctx = _top_context(genre["label"])
    boost = _synth_tags(genre, topic, title, ctx["titles"])
    if boost["tags"]:
        print(f"  [related] 上位{len(ctx['titles'])}本のクラスタに寄せたタグ {len(boost['tags'])}個を付与")
    return boost


def merge_boost(pkg: dict, boost: dict, max_tags: int = 15) -> dict:
    """Merge boost tags/description keywords into a script package in place."""
    if not boost:
        return pkg
    # Tags: keep the video's own tags first, then add cluster tags, dedup, cap.
    seen, merged = set(), []
    for t in (pkg.get("tags") or []) + (boost.get("tags") or []):
        key = t.strip().lower()
        if t.strip() and key not in seen:
            seen.add(key)
            merged.append(t.strip())
    pkg["tags"] = merged[:max_tags]
    # Description: append a natural "関連トピック" line with the keyword phrases,
    # which reinforces topical association without harming readability.
    kws = boost.get("desc_keywords") or []
    if kws:
        line = "関連トピック: " + " / ".join(kws)
        desc = (pkg.get("description") or "").rstrip()
        if line not in desc:
            pkg["description"] = f"{desc}\n\n{line}"
    return pkg
