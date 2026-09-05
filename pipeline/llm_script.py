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


def _axis_index(genre: dict, offset: int = 0) -> int | None:
    """Which sub-territory this run is steered onto, or None if the genre has none.

    Returned rather than kept local because the affiliate links are gated on it:
    a supplement belongs under "the sleep you are losing", never under "how to
    get an apnea diagnosis". See assets/affiliate_links.json.
    """
    axes = genre.get("topic_axes")
    if not axes:
        return None
    return (date.today().toordinal() + offset) % len(axes)


def _axis_block(genre: dict, offset: int = 0) -> str:
    """Steer topic selection onto one of the genre's sub-territories.

    Without this the same seed prompt is asked every run and the model returns
    the same handful of topics, so _is_duplicate rejects them until the retry
    budget is spent. Rotation is by calendar day, not random: consecutive runs
    (Tue/Thu/Sat) land on different axes and the cycle walks the whole list over
    several weeks, which a random pick does not guarantee. offset lets a retry
    move to the next axis instead of re-asking the same one.
    """
    idx = _axis_index(genre, offset)
    if idx is None:
        return ""
    axis = genre["topic_axes"][idx]
    return (f"\n\n【今回の切り口】今回は特に次の観点から題材を選んでください: {axis}\n"
            "視聴者像（いびきをかく本人ではなく、隣で寝ている家族・パートナー）は変えないこと。")


def _pick_topic(genre: dict, avoid_titles: list[str] | None = None, offset: int = 0) -> str:
    axis_block = _axis_block(genre, offset)
    idx = _axis_index(genre, offset)
    if axis_block and idx is not None:
        print(f"  [topic] 切り口({idx}): {genre['topic_axes'][idx]}")
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


def _outline(genre: dict, topic: str, shape: dict | None = None) -> dict:
    from originality import editorial_note, avoid_bookends_block

    # Chapter count varies per video. A catalogue where every entry has exactly
    # eight chapters reads as a template even when each one is fine on its own.
    n_ch = (shape or {}).get("chapters", 8)
    note = editorial_note()
    rules = ""
    if genre.get("compliance") == "medical":
        from compliance import writing_rules
        rules = "\n\n" + writing_rules()
    voice = (f"\n\n【このチャンネルの人が書いた方針】以下は運営者本人の言葉です。"
             f"構成と語り口はこれに従ってください。一般論に流れそうになったら、"
             f"ここに書かれている立場に戻ること。\n{note}" if note else "")

    user = f"""日本のYouTube長尺解説動画の構成案をJSONで作成してください。

テーマ: {topic}
ジャンル: {genre['label']}
トーン: {genre['narration_style']}{voice}{rules}{avoid_bookends_block()}

要件:
- chapters は{n_ch}個。導入(フック)→本編→まとめ→締めの流れ。
- 各chapterは heading(短い見出し) と summary(その章で語る内容の要点、2〜3文) を持つ。
- **各章は、この動画でしか出てこない具体を必ず1つ含むこと。** 数値、検査や器具の
  正式名称、時刻や場面の描写など。どのいびき動画にも書ける一般論だけの章を作らない。
- title: 100文字以内。テーマ固有の語を必ず入れる。次を守ること。
  ・**いびきをかく本人ではなく、隣で眠れない家族に向けて書く。**「いびき解消法」は
    本人が打つ検索語で、このチャンネルの視聴者のものではない。
  ・「知らないと危険」「衝撃の事実」のような、どの動画にも使える煽り文句は使わない。
  ・「〜を救う」「〜地獄」のような恐怖・救済の言葉を使わない。夜に見る人が対象で、
    不安をあおらないことをチャンネルの方針にしている。
  ・「朝まで熟睡」のような、結果を約束する言葉は使わない（薬機法チェックで止まる）。
- thumbnail_text: サムネ用の大きな日本語(10文字前後、改行\\n可)。
  タイトルと同じ制約がかかる。恐怖語と結果の約束は使えない。
  視聴者が「これは自分のことだ」と思う場面の言葉にする。
- thumbnail_prompt: サムネ背景の英語画像プロンプト。この動画固有の情景にすること。
- description: 日本語200〜400文字。要約は動画の中身を具体的に書く。
- tags: 日本語のタグを12〜15個。次の3種類を混ぜること。
  ・実際に検索されそうな複数語のフレーズを半数以上（例:「いびき 家族 眠れない」「いびき 受診 何科」）。
  ・テーマ固有の語（この動画でしか使わない具体語）。
  ・ジャンルの一般語。
  「夜」「安心」のような単語だけの汎用語は、検索されないので入れない。

JSON: {{{{"title":str,"chapters":[{{{{"heading":str,"summary":str}}}}],
"thumbnail_text":str,"thumbnail_prompt":str,"description":str,"tags":[str]}}}}"""
    data = json.loads(_chat(
        [{"role": "system", "content": "構成作家。出力はJSONのみ。"},
         {"role": "user", "content": user}], json_mode=True))
    return data


def _expand_chapter(genre: dict, topic: str, title: str, idx: int, total: int,
                    heading: str, summary: str, prev_tail: str,
                    per_chars: int | None = None) -> str:
    per = per_chars or max(420, genre.get("narration_target", NARRATION_TARGET_CHARS) // total)
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
    from originality import editorial_note, TEMPLATE_TELLS
    note = editorial_note()
    # The compliance gate's own vocabulary, handed to the writer. Rewriting after
    # the fact costs a round trip each time and, three rounds in, costs the video.
    rules = ""
    if genre.get("compliance") == "medical":
        from compliance import writing_rules
        rules = "\n\n" + writing_rules()
    voice = (f"\n\nこのチャンネルの運営者本人が書いた方針:\n{note}\n"
             "一般論に流れそうになったら、ここに書かれている立場に戻ること。" if note else "")
    banned = "、".join(f"「{t}」" for t in TEMPLATE_TELLS[:12])

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
- 見出しや章番号は本文に含めない。ナレーションの読み上げ文だけを出力。

【この章に必ず入れること】
- この動画でしか出てこない具体を1つ以上。数値、検査や器具の正式名称、時刻や場面の描写など。
  どのいびき動画にも当てはまる一般論だけで章を終えない。
- 出典のある話は「〜という研究があります」「〜学会の資料では」と、根拠の所在を示す。

【使ってはいけない言い回し】{banned}
これらはどの生成動画にも出てくる言い方で、見た人にはすぐ分かる。別の言い方にすること。{voice}{rules}"""
    out = _chat([{"role": "system", "content": "プロのナレーション脚本家。"},
                 {"role": "user", "content": user}], temperature=0.85)
    return out.strip()


def _image_prompts(genre: dict, title: str, headings: list[str],
                   count: int = NUM_IMAGES) -> list[str]:
    user = f"""動画「{title}」({genre['label']})のための画像生成プロンプトを英語でちょうど{count}個、JSON配列で作成。

章の流れ: {' / '.join(headings)}

条件:
- 動画の流れ順に、情景・被写体・構図を1文で具体的に描く英語プロンプト。
- 実在人物の顔のクローズアップや特定人物の再現は避け、象徴的・情景的に。
- テキストやロゴを含めない。
JSON: {{"prompts":[str, ...]}}（要素数はちょうど{count}）"""
    data = json.loads(_chat([{"role": "system", "content": "アートディレクター。JSONのみ。"},
                             {"role": "user", "content": user}], json_mode=True))
    prompts = data.get("prompts", [])
    if len(prompts) > count:
        prompts = prompts[:count]
    while 0 < len(prompts) < count:
        prompts.append(prompts[len(prompts) % len(prompts) if prompts else 0])
    return prompts or [genre["image_style"]] * count


def _image_prompts_from_narration(genre: dict, title: str, narration: str,
                                  count: int = NUM_IMAGES) -> list[str]:
    """Image prompts for a video whose narration is supplied (not LLM-outlined)."""
    user = f"""次のナレーション本文をもとに、動画「{title}」({genre['label']})用の画像生成プロンプトを英語でちょうど{count}個、JSON配列で作成。
本文の流れ順に、各場面の情景・被写体・構図を1文の具体的な英語で描く。実在人物の顔のクローズアップや特定人物の再現は避け、象徴的・情景的に。テキストやロゴは含めない。
本文:
{narration[:6000]}
JSON: {{"prompts":[str, ...]}}（要素数はちょうど{count}）"""
    data = json.loads(_chat([{"role": "system", "content": "アートディレクター。JSONのみ。"},
                             {"role": "user", "content": user}], json_mode=True))
    prompts = data.get("prompts", [])
    if len(prompts) > count:
        prompts = prompts[:count]
    while 0 < len(prompts) < count:
        prompts.append(prompts[len(prompts) % len(prompts)])
    return prompts or [genre["image_style"]] * count


def _desc_and_tags(genre: dict, title: str, narration: str) -> tuple[str, list[str]]:
    user = f"""動画「{title}」({genre['label']})のYouTube概要欄(日本語200〜400字、内容要約＋チャンネル登録の誘導)と、日本語のタグ12〜15個をJSONで作成。
タグは次の3種類を混ぜること。
・実際に検索されそうな複数語のフレーズを半数以上（例:「いびき 家族 眠れない」「いびき 受診 何科」）。
・テーマ固有の語（この動画でしか使わない具体語）。
・ジャンルの一般語。
「夜」「安心」のような単語だけの汎用語は、検索されないので入れない。
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


def _select_topic(genre: dict, avoid_titles: list[str],
                  max_retries: int = 4) -> tuple[str, int | None]:
    """Pick a topic, re-picking if it duplicates a recent one (semantic check).

    Continues (does not abort) after max_retries so a run never fails outright —
    a slightly-close final candidate beats posting nothing for the day.
    """
    used = 0
    topic = _pick_topic(genre, avoid_titles)
    for attempt in range(1, max_retries + 1):
        if not _is_duplicate(topic, avoid_titles, genre):
            break
        used = attempt
        print(f"  [dedup] テーマ「{topic}」は最近と重複 → 再選定 ({attempt}/{max_retries})")
        # Advance the axis on each retry. Re-asking the same axis mostly returns
        # a re-skin of the topic just rejected, which is how the retry budget got
        # spent with only two videos on the channel.
        topic = _pick_topic(genre, avoid_titles, offset=attempt)
    else:
        print(f"  [dedup] {max_retries}回再選定しても重複を回避しきれず、最後の候補「{topic}」で続行します。")
    print(f"  [dedup] 採用テーマ: {topic}（回避対象 {len(avoid_titles)} 件）")
    return topic, _axis_index(genre, used)


def generate_script(genre_key: str, topic: str | None = None,
                    avoid_titles: list[str] | None = None) -> dict:
    genre = GENRES[genre_key]
    avoid_titles = avoid_titles or []
    # None when the topic was supplied by hand: the run is then outside the
    # rotation, so no link may claim it matches this video's subject.
    axis = None
    if not topic:
        topic, axis = _select_topic(genre, avoid_titles)

    # Shape this video differently from the last one. See originality.py.
    from originality import (variance, check_template_tells, record_bookends)
    shape = variance(topic, genre.get("narration_target", NARRATION_TARGET_CHARS))
    print(f"  [originality] 構成 {shape['chapters']}章 / "
          f"{shape['narration_chars']}字 / 画像{shape['num_images']}枚")

    outline = _outline(genre, topic, shape)
    title = outline.get("title", topic)[:100]
    chapters_meta = outline.get("chapters", [])
    total = len(chapters_meta)

    chapters, prev_tail = [], ""
    for i, cm in enumerate(chapters_meta):
        narration = _expand_chapter(genre, topic, title, i, total,
                                    cm.get("heading", ""), cm.get("summary", ""), prev_tail,
                                    per_chars=max(420, shape["narration_chars"] // max(1, total)))
        chapters.append({"heading": cm.get("heading", ""), "narration": narration})
        prev_tail = narration

    full_narration = "\n".join(c["narration"] for c in chapters).strip()
    headings = [c["heading"] for c in chapters]
    image_prompts = _image_prompts(genre, title, headings, shape["num_images"])

    # A stock phrase is not an error, so this does not abort — but it should be
    # visible in the log, because the fix is a prompt change, not a retry.
    tells = check_template_tells(full_narration)
    if tells:
        print(f"  [originality] 警告: 定型句が残っています → {'、'.join(tells)}")
    record_bookends(title, full_narration)

    return {
        "topic": topic,
        "axis": axis,
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
    g = sys.argv[1] if len(sys.argv) > 1 else "sleep"
    pkg = generate_script(g)
    print("title:", pkg["title"])
    print("chapters:", len(pkg["chapters"]))
    print("narration chars:", len(pkg["narration"]))
    print("image prompts:", len(pkg["image_prompts"]))
