"""Threads の告知文を組み立てる。動画1本につき1投稿。

なぜ Threads なのか、という判断の記録も兼ねる。

このチャンネルには、以前「宣伝用ショート動画」と「広告出稿」の相談があり、
どちらも見送りを勧めた。理由は2つで、(1) ショートフィードと広告からの
再生時間は YPP の4,000時間に算入されない、(2) 8,390インプレッションに対して
CTR 0.7% という状態で流入だけ増やしても、同じところで離脱する。

外部SNSからの流入は事情が違う。長尺動画の外部流入による再生時間は算入される。
費用もかからない。そして直近28日の流入内訳を見ると「外部」は0%で、
関連動画が84%——つまりこの経路はまだ一度も使われていない。

ただし (2) の懸念は残る。連れてきた人が冒頭で離脱すれば、動画の評価は
むしろ下がる。だから告知文の役割は「クリックを最大化すること」ではなく、
「この動画で解決する人だけを連れてくること」に置いている。誇張しないのは
薬機法のためだけではない。

【設計上の制約】
- Threads の本文上限は500文字。超えるものは投稿できないので必ず検査する。
- リンクは1本だけ置く。複数置くとプレビューが1つしか出ず、残りは
  ただの文字列になる。
- 本文は薬機法辞書を通す。SNSの投稿文は動画本編と同じ規制を受けるうえ、
  概要欄と違って後から静かに直すことができない。
"""
from __future__ import annotations

import textwrap

import compliance

LIMIT = 500
CHANNEL_URL = "https://www.youtube.com/channel/UCrCoZaskQrz6nBkRmS1SAJQ"

# 音風景ごとの一行。件名の【…】と対応させ、投稿を見ただけで中身が分かるようにする。
SOUND_LINE = {
    "mask":   "後半は、いびきの帯域に合わせた安眠ノイズが2時間続きます。",
    "rain":   "後半は、雨音が2時間続きます。",
    "waves":  "後半は、10秒ごとにゆっくり寄せる波の音が2時間続きます。",
    "stream": "後半は、せせらぎの音が2時間続きます。",
    "drone":  "後半は、低くたゆたう持続音が2時間続きます。",
}

FOOTER = "※一般的な情報の紹介です。気になる症状が続く場合は医療機関にご相談ください。"
TAG = "#睡眠"


def watch_url(video_id: str, playlist_id: str | None = None) -> str:
    if playlist_id:
        return f"https://www.youtube.com/watch?v={video_id}&list={playlist_id}"
    return f"https://youtu.be/{video_id}"


def threads_post(hook: str, body: str, video_id: str,
                 playlist_id: str | None = None, texture: str | None = None,
                 tag: str = TAG) -> str:
    """1投稿を組み立てる。500文字に収まらなければ本文側を削る。

    削るのが本文なのは、フック・リンク・免責のどれも削れないから。フックが
    無ければ読まれず、リンクが無ければ告知にならず、免責は医療の話題を
    扱う以上つけない選択肢がない。
    """
    parts = [hook.strip(), body.strip()]
    if texture and texture in SOUND_LINE:
        parts.append(SOUND_LINE[texture])
    tail = "\n\n".join([watch_url(video_id, playlist_id), FOOTER, tag])

    post = "\n\n".join(parts) + "\n\n" + tail
    if len(post) > LIMIT:
        room = LIMIT - len(post) + len(body.strip())
        body = textwrap.shorten(body.strip(), width=max(20, room - 1), placeholder="…")
        parts[1] = body
        post = "\n\n".join(parts) + "\n\n" + tail
    return post


def check(post: str) -> list[str]:
    """投稿してよいかを判定する。問題があれば理由を返す。"""
    problems = []
    if len(post) > LIMIT:
        problems.append(f"{len(post)}文字（上限{LIMIT}）")
    for f in compliance.scan(post, "description"):
        problems.append(f"薬機法「{f.match}」… {f.reason}")
    if post.count("http") > 1:
        problems.append("リンクが2本以上あります（プレビューは1本しか出ません）")
    return problems


def render(hook: str, body: str, video_id: str, playlist_id: str | None = None,
           texture: str | None = None) -> tuple[str, list[str]]:
    post = threads_post(hook, body, video_id, playlist_id, texture)
    return post, check(post)


def from_package(pkg: dict, video_id: str, playlist_id: str | None = None,
                 texture: str | None = None) -> tuple[str, list[str]]:
    """A post drafted from the script package, for the operator to edit and send.

    Deliberately not auto-posted. Threads has no API here, and more importantly
    a good announcement is written to one person — the generator produces a
    serviceable draft, and thirty seconds of editing makes it worth reading.

    The hook is the video's own thumbnail line, which is already written as the
    moment a viewer recognises themselves in; the body is the topic. Both have
    passed the 薬機法 gate before reaching here, and the assembled post is
    checked again because the joining text is new.
    """
    hook = (pkg.get("thumbnail_text") or pkg.get("title", "")).replace("\n", "")
    if not hook.endswith(("。", "？", "！")):
        hook += "。"
    body = (pkg.get("topic") or pkg.get("description", ""))[:110]
    return render(hook, body, video_id, playlist_id, texture)
