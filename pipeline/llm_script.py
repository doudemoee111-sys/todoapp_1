"""Generate a full long-form video script package with OpenAI.

Length is the hard part of long-form: a single "write ~3200 chars" request is
unreliable, so we build the script in stages —
  1. outline: title, 7-9 chapter headings+summaries, thumbnail, description, tags
  2. per-chapter expansion: each chapter narration to ~500-600 JP chars
  3. image prompts: exactly NUM_IMAGES English prompts aligned to the narrative
This reliably yields 3500-5000 narration chars (~9-13 min of speech).

Returns a dict:
{ "topic","title","chapters":[{"heading","narration"}],"narration",
  "image_prompts":[...],"thumbnail_text","thumbnail_prompt","description","tags" }
"""
from __future__ import annotations
import json
from datetime import date
import os
from openai import OpenAI

from config import (SCRIPT_MODEL, NUM_IMAGES, NARRATION_TARGET_CHARS, GENRES,
                    SHORT_NUM_IMAGES, TEASER_TARGET_CHARS)

_client = None


def _c() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def _chat(messages, temperature=0.85, json_mode=False):
    kw = {"model": SCRIPT_MODEL, "temperature": temperature, "messages": messages}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    return _c().chat.completions.create(**kw).choices[0].message.content


def _avoid_block(avoid_titles: list[str] | None) -> str:
    if not avoid_titles:
        return ""
    joined = "\n".join(f"- {t}" for t in avoid_titles[:20])
    return ("\n\n【重要】次は最近このチャンネルで既に扱ったテーマ/タイトルです。"
            "これらと本質的に同じ題材・切り口は避け、明確に異なる新規テーマにしてください:\n"
            + joined)


def _axis_block(genre: dict, offset: int = 0) -> str:
    """Steer topic selection onto one of the genre's sub-territories.

    Without this the same seed prompt is asked every run and the model returns
    the same handful of topics, so _is_duplicate rejects them until the retry
    budget is spent. Rotation is by calendar day, not random: consecutive runs
    (Tue/Thu/Sat) land on different axes and the cycle walks the whole list over
    several weeks, which a random pick does not guarantee. offset lets a retry
    move to the next axis instead of re-asking the same one.
    """
    axes = genre.get("topic_axes")
    if not axes:
        return ""
    axis = axes[(date.today().toordinal() + offset) % len(axes)]
    return (f"\n\n【今回の切り口】今回は特に次の観点から題材を選んでください: {axis}\n"
            "視聴者像（いびきをかく本人ではなく、隣で寝ている家族・パートナー）は変えないこと。")


def _pick_topic(genre: dict, avoid_titles: list[str] | None = None, offset: int = 0) -> str:
    axis_block = _axis_block(genre, offset)
    if axis_block:
        print(f"  [topic] 切り口: {genre['topic_axes'][(date.today().toordinal() + offset) % len(genre['topic_axes'])]}")
    out = _chat(
        [{"role": "system", "content": "あなたは日本のYouTubeで大人気の動画作家です。"},
         {"role": "user", "content": genre["topic_seed_prompt"] + axis_block + _avoid_block(avoid_titles)
          + "\nテーマ名だけを1行で出力。"}],
        temperature=1.0)
    return out.strip().splitlines()[0].strip("　 「」\"'")


def _is_duplicate(topic: str, avoid_titles: list[str], genre: dict | None = None) -> bool:
    """Ask the model whether `topic` is essentially the same video as a recent one.

    The judge used to be told that a shared central subject means duplicate. On a
    single-genre channel the central subject is the genre, so once a few videos
    existed everything read as a duplicate: five distinct axes (伝え方 / 受診 /
    治療 / 生活習慣 / 姿勢) were all rejected against three titles, and only one
    of those rejections was right. The test is now whether a viewer would see the
    same video, not whether the subject matches.
    """
    if not avoid_titles:
        return False
    joined = "\n".join(f"- {t}" for t in avoid_titles[:20])
    label = (genre or {}).get("label", "")
    preamble = (f"このチャンネルは「{label}」の単一ジャンルです。すべての動画が同じ大テーマを扱うのは"
                "前提であり、それ自体は重複ではありません。\n\n") if label else ""
    user = (preamble
            + f"新しい動画テーマ案: 「{topic}」\n\n最近の動画タイトル:\n{joined}\n\n"
            "このテーマ案は、上のいずれかと『視聴者にとって同じ動画』になりますか？\n"
            "- true: 扱う切り口・視聴者が得る情報がほぼ同じで、両方見る意味がない。\n"
            "- false: 大テーマは同じでも切り口や場面が異なり、両方見る価値がある。\n"
            'JSONで {"duplicate": true または false} のみ出力。')
    try:
        data = json.loads(_chat(
            [{"role": "system", "content": "重複判定器。出力はJSONのみ。"},
             {"role": "user", "content": user}], temperature=0.0, json_mode=True))
        return bool(data.get("duplicate", False))
    except Exception:  # noqa: BLE001
        return False  # 判定に失敗したら重複扱いにせず続行(生成を止めない)


def _outline(genre: dict, topic: str) -> dict:
    n_ch = 8
    user = f"""日本のYouTube長尺解説動画の構成案をJSONで作成してください。

テーマ: {topic}
ジャンル: {genre['label']}
トーン: {genre['narration_style']}

要件:
- chapters は{n_ch}個。導入(フック)→本編→まとめ→締め(登録誘導)の流れ。
- 各chapterは heading(短い見出し) と summary(その章で語る内容の要点、2〜3文) を持つ。
- title: 100文字以内のクリックしたくなる日本語（虚偽・過度な煽りは避ける）。
- thumbnail_text: サムネ用の大きな日本語(10文字前後、改行\\n可)。
- thumbnail_prompt: サムネ背景の英語画像プロンプト。
- description: 日本語200〜400文字（要約＋登録誘導）。
- tags: 日本語中心のキーワード10〜15個。

JSON: {{"title":str,"chapters":[{{"heading":str,"summary":str}}],
"thumbnail_text":str,"thumbnail_prompt":str,"description":str,"tags":[str]}}"""
    data = json.loads(_chat(
        [{"role": "system", "content": "構成作家。出力はJSONのみ。"},
         {"role": "user", "content": user}], json_mode=True))
    return data


def _expand_chapter(genre: dict, topic: str, title: str, idx: int, total: int,
                    heading: str, summary: str, prev_tail: str) -> str:
    per = max(420, genre.get("narration_target", NARRATION_TARGET_CHARS) // total)
    ctx = f"直前の章の終わり: {prev_tail[-120:]}" if prev_tail else "これは最初の章です。"
    # The opening instruction belongs to chapter 1 only. It used to live in
    # narration_style, which is injected into every chapter prompt, so all 8
    # chapters opened with the same sentence (7-8 identical hooks per video).
    if idx == 0:
        role = ("最初の章。挨拶や自己紹介は一切せず、テーマの核心や結末の一部をチラ見せする強いフックから入り、"
                "『この続きは最後まで見たくなる』引きを作る。" + genre.get("opening_style", ""))
    elif idx < total - 1:
        role = ("自然に前の章から続ける。この章は動画の途中なので、動画全体の導入・問題提起・"
                "視聴者への呼びかけをやり直さない。第1章で提示した場面や問いかけを言い直さず、"
                "この章の内容そのものから始める。")
    else:
        role = ("動画のまとめと、チャンネル登録・高評価のお願いで締める。"
                "冒頭の問題提起を再現せず、ここまでで語った内容を受けてまとめる。")
    user = f"""次の動画の第{idx+1}章のナレーション本文だけを書いてください。

動画タイトル: {title}
テーマ: {topic}
この章の見出し: {heading}
この章で語る要点: {summary}
{ctx}

条件:
- 日本語で{per}文字前後（最低{int(per*0.8)}文字）。
- 話し言葉で、耳で聞いて自然に分かる文体。{genre['narration_style']}
- 箇条書き記号・見出し・「※」・絵文字は使わない。地の文の連続した語りにする。
- {role}
- 見出しや章番号は本文に含めない。ナレーションの読み上げ文だけを出力。"""
    out = _chat([{"role": "system", "content": "プロのナレーション脚本家。"},
                 {"role": "user", "content": user}], temperature=0.85)
    return out.strip()


def _image_prompts(genre: dict, title: str, headings: list[str]) -> list[str]:
    user = f"""動画「{title}」({genre['label']})のための画像生成プロンプトを英語でちょうど{NUM_IMAGES}個、JSON配列で作成。

章の流れ: {' / '.join(headings)}

条件:
- 動画の流れ順に、情景・被写体・構図を1文で具体的に描く英語プロンプト。
- 実在人物の顔のクローズアップや特定人物の再現は避け、象徴的・情景的に。
- テキストやロゴを含めない。
JSON: {{"prompts":[str, ...]}}（要素数はちょうど{NUM_IMAGES}）"""
    data = json.loads(_chat([{"role": "system", "content": "アートディレクター。JSONのみ。"},
                             {"role": "user", "content": user}], json_mode=True))
    prompts = data.get("prompts", [])
    if len(prompts) > NUM_IMAGES:
        prompts = prompts[:NUM_IMAGES]
    while 0 < len(prompts) < NUM_IMAGES:
        prompts.append(prompts[len(prompts) % len(prompts) if prompts else 0])
    return prompts or [genre["image_style"]] * NUM_IMAGES


def _image_prompts_from_narration(genre: dict, title: str, narration: str) -> list[str]:
    """Image prompts for a video whose narration is supplied (not LLM-outlined)."""
    user = f"""次のナレーション本文をもとに、動画「{title}」({genre['label']})用の画像生成プロンプトを英語でちょうど{NUM_IMAGES}個、JSON配列で作成。
本文の流れ順に、各場面の情景・被写体・構図を1文の具体的な英語で描く。実在人物の顔のクローズアップや特定人物の再現は避け、象徴的・情景的に。テキストやロゴは含めない。
本文:
{narration[:6000]}
JSON: {{"prompts":[str, ...]}}（要素数はちょうど{NUM_IMAGES}）"""
    data = json.loads(_chat([{"role": "system", "content": "アートディレクター。JSONのみ。"},
                             {"role": "user", "content": user}], json_mode=True))
    prompts = data.get("prompts", [])
    if len(prompts) > NUM_IMAGES:
        prompts = prompts[:NUM_IMAGES]
    while 0 < len(prompts) < NUM_IMAGES:
        prompts.append(prompts[len(prompts) % len(prompts)])
    return prompts or [genre["image_style"]] * NUM_IMAGES


def _desc_and_tags(genre: dict, title: str, narration: str) -> tuple[str, list[str]]:
    user = f"""動画「{title}」({genre['label']})のYouTube概要欄(日本語200〜400字、内容要約＋チャンネル登録の誘導)と、日本語中心のタグ10〜15個をJSONで作成。
本文冒頭: {narration[:800]}
JSON: {{"description": str, "tags": [str, ...]}}"""
    try:
        data = json.loads(_chat([{"role": "system", "content": "YouTube運用のプロ。JSONのみ。"},
                                 {"role": "user", "content": user}], json_mode=True))
        return data.get("description", ""), (data.get("tags") or genre["tags"])[:15]
    except Exception:  # noqa: BLE001
        return "", genre["tags"]


def build_from_narration(genre_key: str, narration: str, title: str | None = None) -> dict:
    """Build a full script package around a PROVIDED narration text.

    Used when a hand-written script is supplied (e.g. the intro video): the
    narration is taken as-is, and only the image prompts / description / tags
    are generated to match it. Same return shape as generate_script().
    """
    genre = GENRES[genre_key]
    narration = narration.strip()
    if not title:
        title = narration.split("\n", 1)[0][:60]
    title = title.strip()
    image_prompts = _image_prompts_from_narration(genre, title, narration)
    description, tags = _desc_and_tags(genre, title, narration)
    return {
        "topic": title,
        "title": title[:100],
        "chapters": [{"heading": "", "narration": narration}],
        "narration": narration,
        "image_prompts": image_prompts,
        "thumbnail_text": title[:24],
        "thumbnail_prompt": f"{title}. {genre['image_style']}",
        "description": description,
        "tags": tags,
    }


def generate_teaser(genre_key: str, source_topic: str, source_narration: str) -> dict:
    """Build a vertical teaser-short script ('CM') for a long-form video.

    The short teases the long-form's biggest hook/mystery, withholds the payoff
    (寸止め), and drives viewers to the full video — like a trailer before a film.
    Returns: {narration, title, image_prompts, hashtags, tags}.
    """
    from config import teaser_profile

    genre = GENRES[genre_key]
    prof = teaser_profile(genre_key)
    user = f"""次の{prof["framing"]}の「予告編ショート(縦型・約{TEASER_TARGET_CHARS}文字)」の台本をJSONで作成してください。CM＋映画のように、続きを本編で見たくさせるのが目的です。

長尺のテーマ: {source_topic}
長尺の内容(冒頭抜粋): {source_narration[:1200]}

要件:
- narration: 話し言葉のナレーション。合計{TEASER_TARGET_CHARS}文字前後(約45〜55秒)。
  ・{prof["hook"]}
  ・{prof["withhold"]}
  ・{prof["cta_spoken"]}
- title: 25文字前後のフックの効いた日本語タイトル。末尾に半角スペース+『#Shorts』を付ける。
- image_prompts: 縦型(9:16)用の英語画像プロンプトをちょうど{SHORT_NUM_IMAGES}個。{prof["image_hint"]}テキスト/ロゴは含めない。
- hashtags: 日本語中心のハッシュタグ5個前後(#Shorts を必ず含む)。
JSON: {{"narration": str, "title": str, "image_prompts": [str, ...], "hashtags": [str, ...]}}"""
    data = json.loads(_chat([{"role": "system", "content": "YouTube予告編(CM)の脚本家。出力はJSONのみ。"},
                             {"role": "user", "content": user}], temperature=0.9, json_mode=True))
    prompts = (data.get("image_prompts") or [])[:SHORT_NUM_IMAGES]
    while 0 < len(prompts) < SHORT_NUM_IMAGES:
        prompts.append(prompts[len(prompts) % len(prompts)])
    teaser = {
        "narration": (data.get("narration") or "").strip(),
        "title": (data.get("title") or source_topic)[:100],
        "image_prompts": prompts or [genre["image_style"]] * SHORT_NUM_IMAGES,
        "hashtags": data.get("hashtags") or prof["hashtags"],
        "tags": (genre["tags"] + ["Shorts", "予告編"])[:15],
    }

    # The long-form script is gated for 薬機法; the teaser was not, so a claim the
    # gate would have caught could still be published in the short that fronts it.
    # enforce() is a no-op for genres that do not declare compliance.
    import compliance
    gated = compliance.enforce({"narration": teaser["narration"],
                                "title": teaser["title"]}, genre)
    teaser["narration"] = gated["narration"]
    teaser["title"] = gated["title"][:100]
    return teaser


def _select_topic(genre: dict, avoid_titles: list[str], max_retries: int = 4) -> str:
    """Pick a topic, re-picking if it duplicates a recent one (semantic check).

    Continues (does not abort) after max_retries so a run never fails outright —
    a slightly-close final candidate beats posting nothing for the day.
    """
    topic = _pick_topic(genre, avoid_titles)
    for attempt in range(1, max_retries + 1):
        if not _is_duplicate(topic, avoid_titles, genre):
            break
        print(f"  [dedup] テーマ「{topic}」は最近と重複 → 再選定 ({attempt}/{max_retries})")
        # Advance the axis on each retry. Re-asking the same axis mostly returns
        # a re-skin of the topic just rejected, which is how the retry budget got
        # spent with only two videos on the channel.
        topic = _pick_topic(genre, avoid_titles, offset=attempt)
    else:
        print(f"  [dedup] {max_retries}回再選定しても重複を回避しきれず、最後の候補「{topic}」で続行します。")
    print(f"  [dedup] 採用テーマ: {topic}（回避対象 {len(avoid_titles)} 件）")
    return topic


def generate_script(genre_key: str, topic: str | None = None,
                    avoid_titles: list[str] | None = None) -> dict:
    genre = GENRES[genre_key]
    avoid_titles = avoid_titles or []
    if not topic:
        topic = _select_topic(genre, avoid_titles)

    outline = _outline(genre, topic)
    title = outline.get("title", topic)[:100]
    chapters_meta = outline.get("chapters", [])
    total = len(chapters_meta)

    chapters, prev_tail = [], ""
    for i, cm in enumerate(chapters_meta):
        narration = _expand_chapter(genre, topic, title, i, total,
                                    cm.get("heading", ""), cm.get("summary", ""), prev_tail)
        chapters.append({"heading": cm.get("heading", ""), "narration": narration})
        prev_tail = narration

    full_narration = "\n".join(c["narration"] for c in chapters).strip()
    headings = [c["heading"] for c in chapters]
    image_prompts = _image_prompts(genre, title, headings)

    return {
        "topic": topic,
        "title": title,
        "chapters": chapters,
        "narration": full_narration,
        "image_prompts": image_prompts,
        "thumbnail_text": (outline.get("thumbnail_text") or title)[:24],
        "thumbnail_prompt": outline.get("thumbnail_prompt", genre["image_style"]),
        "description": outline.get("description", ""),
        "tags": (outline.get("tags") or genre["tags"])[:15],
    }


if __name__ == "__main__":
    import sys
    g = sys.argv[1] if len(sys.argv) > 1 else "space"
    pkg = generate_script(g)
    print("title:", pkg["title"])
    print("chapters:", len(pkg["chapters"]))
    print("narration chars:", len(pkg["narration"]))
    print("image prompts:", len(pkg["image_prompts"]))
