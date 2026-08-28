"""Claude APIでショート動画(雑学/都市伝説/海外の反応など)の台本を生成する"""

import difflib
import json
import random
import re
import sys

from http_retry import request_with_retry

import config

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# ジャンルリサーチ(research/genre_research.py)の平均再生数で上位だったジャンル。
# トピックおまかせ時は、この上位ジャンルから毎回ランダムに1つ選んで台本を作る。
# 2026-08-13時点の平均再生数: 海外の反応 > 雑学 > 都市伝説 > 名言。上位3ジャンルを採用。
TOP_GENRES = [
    (
        "海外の反応",
        "日本の文化・食・製品・技術・接客・マナー・自然などに対する、海外の人々の驚きや称賛の反応を紹介する。"
        "特定個人の発言を捏造せず『海外では〜と驚かれることが多い』といった一般的な傾向として描く。"
        "過度な自国礼賛や特定の国・民族を貶める表現はしない。",
    ),
    (
        "雑学",
        "意外で『へえ』となる事実を紹介する。特に実在の動物の意外な生態・行動、中でも動物どうしの関係性"
        "(捕食・寄生・共生・天敵など、ある生き物が別の生き物を利用する/助ける/出し抜く場面)は伸びやすいので優先候補。"
        "科学現象・歴史・スポーツなどの具体的で驚きのある雑学も可。",
    ),
    (
        "都市伝説",
        "ゾッとする、または不思議な都市伝説・怪談・未解明の謎を紹介する。事実と噂を区別し『〜と言われている』等の伝聞表現を使う。"
        "実在の人物・場所について過度に不安を煽る断定や、根拠のない誹謗はしない。",
    ),
]

# 類似題材の回避設定。生成した台本が既出と似すぎる場合はジャンルを選び直して作り直す。
# タイトル(既出タイトルと比較)とシナリオ全文(その日の既出台本と比較)の両面でチェックする。
MAX_SCRIPT_RETRIES = 10
TITLE_SIMILARITY_THRESHOLD = 0.72
SCENARIO_SIMILARITY_THRESHOLD = 0.78

SYSTEM_PROMPT = """あなたはYouTube Shorts/TikTok向けショート動画の台本作家です。扱うジャンルは「雑学」「都市伝説」「海外の反応」など。
視聴者が最後まで見て、フォローしたくなるような60秒以内のナレーション台本を作成します。

出力は必ず次のJSON形式のみ。前後に説明文やコードブロック記号は付けないこと。
{
  "title": "動画のタイトル(ファイル名・YouTubeタイトルにも使う短い文字列)",
  "lines": ["1行目(冒頭3秒の寸止めフック)", "2行目", "...", "最終行(寸止めCTA。核心を見せきらず本編・画面下のリンクへ誘導)"],
  "image_prompts": ["動画前半の内容を象徴する情景を英語で描写(20語程度)", "動画後半の内容を象徴する情景を英語で描写(20語程度)"],
  "youtube_description": "YouTube概要欄用の紹介文(1〜2文)+『続き・全貌は本編(長尺)で。概要欄/固定コメントのリンクから』という本編への誘導を1文+ハッシュタグ3つ程度(例: #shorts #雑学 #都市伝説 #海外の反応 から適切に選ぶ)"
}

ルール:
- lines は5〜8個。1行あたり15〜40文字程度(音声で2〜4秒相当)。テンポよく、1行ごとに必ず新情報を足すか展開を進める(冗長な前置き・接続詞での水増しは禁止)。
- 【最重要=冒頭3秒フック】1行目は「最初の3秒」で指を止めさせる。この動画は広告としても配信されるため、"広告として見られている"状態からでも思わず続きが気になる、強いインパクトの一撃にする。結論や意外性を"先に"出すこと。次のいずれかの型を使う:
  ・意外な結論を先出し(例:「実はカラスは人間の顔を7年間覚えています」)
  ・鋭い疑問(例:「なぜナマケモノは週に1回しかトイレに行かないのか」)
  ・常識の否定(例:「カタツムリが塩で溶けるというのは、実は間違いです」)
  ・数字/ランキング(例:「知らないと損する雑学トップ3」)
  「今日は〜について解説します」「みなさん〜を知っていますか」のような弱い前置きは禁止。
- 【オープンループ＋寸止め】冒頭で"答えを引っ張る問い"を提示し、途中でヒントや"さわり"を見せて価値を感じさせつつ、最も気になる核心・全貌・結末は"あえて見せきらない"。このショートは長尺本編への予告編と位置づけ、続きを本編へ送る。
- 中盤は具体的な事実・エピソード・数字で裏づけ、単調にならないよう展開に起伏をつける。
- 【締め＝寸止めCTA(最重要)】最後の1〜2行で、核心の答えを見せきらないまま"続きが見たい"という飢餓感を最大化し、画面下(概要欄／固定コメント)のリンクへ指を動かすよう具体的に誘導する。例:「その真相とは…？ 全貌は本編で。今すぐ下のリンクをタップ」。単なる『フォローしてね』では終わらせない。
- 日本語の自然な話し言葉で書く。専門用語はかみ砕く。
- 【型を毎回変える】「〜の本当の理由」など同じテンプレの連発を避け、フックの型(結論先出し/疑問/常識否定/ランキング/短い物語)を題材ごとに使い分けて、量産感を出さない。
- image_prompts は必ず2個。lines前半・後半それぞれの内容を、具体的な一場面として英語で描写する(スタイル指定は不要、情景の内容のみ)。特定の実在キャラクター・アニメ/漫画/ゲーム作品のデザインを指定しないこと(著作権保護対象の可能性があるため)。

タイトルの付け方(共通):
- 題材が自然に当てはまる場合は「〇〇な理由3選」「知らないとヤバいTOP3」のように数字を使ったリスト形式を優先する。一方、一つの驚きを「〇〇したフリして実は××」のように核心を伏せて引く単発フック型も同程度に伸びるので、題材に応じて使い分ける。
- タイトルや本文で実際の再生回数・登録者数・「話題沸騰」等の反響を断定的にうたわないこと(実績が伴わない誇張表現は避ける)。

著作権・表現に関する厳守事項:
- 特定の書籍・記事・Webページ・SNS投稿の文章を丸ごと、または一部でもそのまま引用・転載しないこと。事実は必ず自分の言葉で言い換えて説明する。
- 歌詞・詩・台詞・キャッチコピーなど、他者の創作物の文章表現を引用しないこと。
- 実在の著作物のタイトルやキャラクター名を扱う場合も、あらすじや設定を要約する程度に留め、本文を転記しない。
- 実在の人物・国・団体を扱う場合も、公表されている事実の範囲に留め、憶測・誹謗中傷・差別的表現は書かないこと。"""


def _repair_truncated_json(s: str) -> str:
    """max_tokens 切れ等で途中終了したJSONを、開いている文字列・配列・オブジェクトを
    閉じて可能な範囲で復元する。末尾の未完トークン直前のカンマも除去してパース可能にする。"""
    out = []
    stack: list[str] = []
    in_str = False
    escaped = False
    for ch in s:
        out.append(ch)
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    res = "".join(out)
    if in_str:
        res += '"'
    res = re.sub(r"[,\s]+$", "", res)  # 末尾の余分なカンマ/空白を除去
    for br in reversed(stack):
        res += "}" if br == "{" else "]"
    return res


def _extract_json(text: str) -> dict:
    text = text.strip()
    # ```json ... ``` やコードブロック・前置き文が付いていても、最初の { 以降を対象にする。
    start = text.find("{")
    if start == -1:
        raise ValueError(f"JSONが見つかりませんでした: {text[:200]}")
    frag = text[start:]
    # 1) 完全なJSON（最初の { 〜 最後の }）を素直に試す。
    end = frag.rfind("}")
    if end != -1:
        try:
            return json.loads(frag[:end + 1])
        except json.JSONDecodeError:
            pass
    # 2) max_tokens 切れ等で末尾が欠けた場合は、開いた構造を閉じて復元を試みる。
    return json.loads(_repair_truncated_json(frag))


def _normalize(s: str) -> str:
    """類似判定用に文字列を正規化する(記号・空白・改行を除去して小文字化)。"""
    return re.sub(r"[\s　、。，．！!？?｜|・…「」『』（）()\[\]【】\-—~〜:：/]+", "", str(s)).lower()


def _script_fulltext(script: dict) -> str:
    """タイトルとシナリオ(lines)を連結した、類似判定用の全文を返す。"""
    lines = script.get("lines") or []
    return str(script.get("title", "")) + "\n" + "\n".join(lines)


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _similarity_scores(
    title: str, fulltext: str, avoid_titles: list[str], avoid_texts: list[str]
) -> tuple[float, float]:
    """(タイトル最大類似度, シナリオ全文最大類似度) を返す。"""
    nt = _normalize(title)
    title_score = 0.0
    for e in avoid_titles:
        ne = _normalize(e)
        if ne and nt:
            title_score = max(title_score, _ratio(nt, ne))

    nf = _normalize(fulltext)
    scenario_score = 0.0
    for e in avoid_texts:
        ne = _normalize(e)
        if ne and nf:
            scenario_score = max(scenario_score, _ratio(nf, ne))

    return title_score, scenario_score


def _is_too_similar(title_score: float, scenario_score: float) -> bool:
    return (
        title_score >= TITLE_SIMILARITY_THRESHOLD
        or scenario_score >= SCENARIO_SIMILARITY_THRESHOLD
    )


def _build_user_content(
    topic: str | None, genre: str | None, genre_hint: str | None, avoid_titles: list[str]
) -> str:
    if topic:
        user_content = f"次のテーマで台本を作成してください: {topic}"
    else:
        user_content = (
            f"「{genre}」ジャンルで、日本の視聴者にウケそうなテーマを1つ自分で考えて、台本を作成してください。\n"
            f"このジャンルの作成方針: {genre_hint}"
        )

    if avoid_titles:
        # fetch_recent_titles() は「新しい順」で返すため、モデルに“直近で避けるべき題材”を
        # 見せるには先頭(最新)を渡す。以前は avoid_titles[-40:]（＝最も古い40件）を渡しており、
        # 最近扱った題材がモデルに伝わらず重複が再発していた。先頭60件(≒直近1か月分)に修正。
        recent = "\n".join(f"- {t}" for t in avoid_titles[:60])
        user_content += (
            "\n\n直近ですでに扱った題材は次の通りです（新しい順）。タイトルだけでなく、"
            "テーマ・題材・切り口・オチが似ているものも避け、明確に異なる題材・別の切り口にしてください:\n"
            f"{recent}"
        )
    return user_content


def _validate_script(script: dict) -> None:
    if "title" not in script or "lines" not in script or not script["lines"]:
        sys.exit(f"エラー: 台本の形式が不正です: {script}")
    if not script.get("image_prompts"):
        sys.exit(f"エラー: 台本にimage_promptsがありません: {script}")
    if not script.get("youtube_description"):
        sys.exit(f"エラー: 台本にyoutube_descriptionがありません: {script}")


def _generate_script_once(user_content: str) -> dict:
    api_key = config.load_anthropic_key()
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.ANTHROPIC_MODEL,
        # 台本JS（title/lines/image_prompts/youtube_description）が途中で切れて
        # JSON解析に失敗しないよう、十分な上限にする（1024は末尾のdescriptionが欠ける恐れ）。
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }

    resp = request_with_retry("POST", ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        sys.exit(f"エラー: Claude APIエラー ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    try:
        return _extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        sys.exit(f"エラー: 台本のJSON解析に失敗しました: {e}\n生レスポンス: {text[:300]}")


def _call_claude(system: str, user_content: str, max_tokens: int) -> dict:
    api_key = config.load_anthropic_key()
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }

    resp = request_with_retry("POST", ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        sys.exit(f"エラー: Claude APIエラー ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    try:
        return _extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        sys.exit(f"エラー: JSON解析に失敗しました: {e}\n生レスポンス: {text[:300]}")


def generate_script(
    topic: str | None,
    avoid_titles: list[str] | None = None,
    avoid_texts: list[str] | None = None,
) -> dict:
    """台本を1本生成する。

    topic 指定時はそのテーマで1回だけ生成する。
    topic 省略(おまかせ)時は上位3ジャンルからランダムに選び、既出と似すぎない台本が
    得られるまで最大 MAX_SCRIPT_RETRIES 回、ジャンルを選び直して作り直す。
    類似判定はタイトル(avoid_titles と比較)とシナリオ全文(avoid_texts と比較)の両面で行う。
    10回試しても十分に異ならない場合でも、動画本数を保つためスキップはせず「最も類似度の
    低い案」を返す(=1呼び出しにつき必ず1本の台本を返す)。
    """
    avoid_titles = list(avoid_titles or [])
    avoid_texts = list(avoid_texts or [])

    # テーマが明示指定された場合は、その題材を尊重して1回だけ生成する。
    if topic:
        user_content = _build_user_content(topic, None, None, avoid_titles)
        script = _generate_script_once(user_content)
        _validate_script(script)
        script["genre"] = "雑学"
        return script

    # おまかせ時: ジャンルをランダムに選び、類似回避のリトライを行う。
    working_titles = list(avoid_titles)
    working_texts = list(avoid_texts)
    best_script: dict | None = None
    best_score: float | None = None

    for _ in range(MAX_SCRIPT_RETRIES):
        chosen_genre, genre_hint = random.choice(TOP_GENRES)
        user_content = _build_user_content(None, chosen_genre, genre_hint, working_titles)
        script = _generate_script_once(user_content)
        _validate_script(script)
        script["genre"] = chosen_genre

        fulltext = _script_fulltext(script)
        title_score, scenario_score = _similarity_scores(
            script["title"], fulltext, working_titles, working_texts
        )
        if not _is_too_similar(title_score, scenario_score):
            return script

        # 似すぎた: 最も類似度の低い案を控えつつ、この案も避けて別ジャンル・別題材で作り直す。
        combined = max(title_score, scenario_score)
        if best_score is None or combined < best_score:
            best_score, best_script = combined, script
        working_titles = working_titles + [script["title"]]
        working_texts = working_texts + [fulltext]

    # 10回でも十分に異なる案が得られなかった場合でも、本数を保つため最も類似度の低い案を採用。
    return best_script if best_script is not None else script


def generate_image_prompts(lines: list[str]) -> list[str]:
    """既存のせりふ(lines)から、背景画像用のシーン描写を2個生成する"""
    api_key = config.load_anthropic_key()

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": 512,
        "system": (
            "与えられた日本語のナレーション台本(箇条書き)を読み、動画の前半・後半それぞれの"
            "内容を象徴する具体的な一場面を英語で描写してください(各20語程度、スタイル指定は不要)。"
            "特定の実在キャラクター・アニメ/漫画/ゲーム作品のデザインは指定しないこと(著作権保護対象の可能性があるため)。"
            '出力は必ず次のJSON形式のみ: {"image_prompts": ["前半の場面描写", "後半の場面描写"]}'
        ),
        "messages": [{"role": "user", "content": "\n".join(lines)}],
    }

    resp = request_with_retry("POST", ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        sys.exit(f"エラー: Claude APIエラー ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    result = _extract_json(text)
    if not result.get("image_prompts"):
        sys.exit(f"エラー: image_promptsの生成に失敗しました: {result}")
    return result["image_prompts"]


def translate_script(script: dict, language_name: str) -> dict:
    """日本語の台本(title/lines/youtube_description)を指定言語に翻訳・現地化する。
    image_promptsは言語に依存しないため引き継ぐ。"""
    system = (
        f"あなたは動画字幕・ナレーションのローカライズ翻訳者です。"
        f"与えられた日本語のJSON台本を{language_name}に翻訳してください。"
        "直訳ではなく、その言語のショート動画ナレーションとして自然で、フックの強さや"
        "テンポ感が伝わる表現にすること。行数・意味・事実内容は変えないこと。\n"
        '出力は必ず次のJSON形式のみ: {"title": "...", "lines": ["...", ...], '
        '"youtube_description": "..."}\n'
        "youtube_descriptionには、その言語圏で一般的なハッシュタグ(#shorts含む)を3つ程度含めること。"
    )
    user_content = json.dumps(
        {
            "title": script["title"],
            "lines": script["lines"],
            "youtube_description": script["youtube_description"],
        },
        ensure_ascii=False,
    )

    result = _call_claude(system, user_content, max_tokens=1024)

    if not result.get("title") or not result.get("lines"):
        sys.exit(f"エラー: 翻訳結果の形式が不正です: {result}")

    return {
        "title": result["title"],
        "lines": result["lines"],
        "youtube_description": result.get("youtube_description", script["youtube_description"]),
        "image_prompts": script["image_prompts"],
        "genre": script.get("genre", "雑学"),
    }
