"""Medical-claim / 薬機法 gate for generated scripts.

Runs between script generation and TTS, and only for genres that opt in with
``"compliance": "medical"``. A genre without that key is never
touch it, so their runs are byte-for-byte unchanged.

Why this exists: the sleep channel talks about snoring and sleep apnea, which
is a medical subject and a regulated advertising surface. An affiliate who
writes "治ります" is the party that gets sanctioned — not the advertiser. A
生成 pipeline that posts unreviewed medical claims every night is a liability,
so the check has to be a stage in the pipeline rather than a human habit.

Two passes, cheapest first:
  1. ``scan()``  — a deterministic NG-phrase dictionary. No API call. Catches
     the blunt violations (断定的効能, 最上級表現, 医師の推奨を騙る等).
  2. ``adjudicate()`` — an LLM pass for the phrasing a dictionary cannot see
     ("これで朝までぐっすりです" reads as an efficacy guarantee without using
     any listed word).

``enforce()`` runs both, and when something is flagged it asks the model to
rewrite *only* the offending sentences and re-checks — the topic, structure and
length of the script survive, which is why this is a rewrite loop rather than a
regenerate loop. After ``MAX_ROUNDS`` it raises, and the caller is expected to
abort the run and report. Never silently publish a script that failed here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

MAX_ROUNDS = 3

# The disclaimer is appended to every narration and description of a medical
# genre. It is not optional and not LLM-generated, so it cannot drift.
DISCLAIMER_SPOKEN = (
    "この動画は一般的な情報の紹介であり、医師の診断や治療に代わるものではありません。"
    "気になる症状がある場合は医療機関にご相談ください。"
)
DISCLAIMER_TEXT = (
    "※本動画は一般的な情報提供を目的としたものであり、医学的な診断・治療に代わるものでは"
    "ありません。症状が続く場合は医療機関にご相談ください。"
)

# ---- Pass 1: deterministic dictionary ---------------------------------------
# Each entry is (regex, why it is a problem). Kept as plain patterns so the list
# is reviewable by a non-programmer — a compliance list nobody can read is a
# compliance list nobody maintains.
NG_PATTERNS: list[tuple[str, str]] = [
    # 断定的な効能・効果（薬機法66条）
    (r"治(る|り|ります|ります|せます|療できます)", "疾患が治ると読める断定表現"),
    (r"完治", "完治の断定"),
    (r"改善(します|されます|できます)", "効果の断定（『改善が報告されています』等に）"),
    (r"効果があ(る|ります)", "効果の断定"),
    (r"(解消|根治|克服)(します|できます)", "効果の断定"),
    (r"予防(できます|します)", "予防効果の断定"),
    # 結果の約束。商品名も症状名も出さずに、買った先の結果だけを言う形。
    # サムネイルの数文字に収まるぶん、いちばん使われやすい。
    (r"朝まで(熟睡|ぐっすり)", "結果の約束"),
    (r"ぐっすり眠れ(る|ます)", "結果の約束"),
    (r"もう[^。、]{0,8}(悩まない|困らない|起こされない)", "結果の約束"),
    (r"(いびき|無呼吸|不眠)(解消法|撃退|完全攻略)", "効果の断定（解消の約束）"),
    (r"[^。、]{0,6}を救う", "過度な訴求"),
    # An adverb between が and the verb is exactly what strengthens the claim,
    # and the bare form let 「いびきが完全になくなります」 through. Bounded and
    # punctuation-stopped so it does not reach across clauses.
    (r"(症状|いびき|無呼吸)が[^。、]{0,4}(なくな|消え)", "症状消失の断定"),
    # 最上級・唯一性（景表法）
    (r"(日本|世界)一", "最上級表現"),
    (r"No\.?1|ナンバーワン", "最上級表現（根拠の併記なしでは不可）"),
    (r"最強|最高の効果|絶対に", "最上級・絶対表現"),
    (r"必ず(治|効|良くな)", "効果の保証"),
    (r"誰でも(必ず|確実に)", "効果の保証"),
    # 安全性の断定
    (r"副作用(は|が)(ありません|ない)", "安全性の断定"),
    (r"(絶対|100%)安全", "安全性の断定"),
    # 医療関係者の推奨を騙る
    (r"医師(も|が)(推奨|認め)", "医師の推奨表示（広告では原則不可）"),
    (r"(病院|クリニック)公認", "権威づけの断定"),
    # 診断・治療の指示（YMYL：視聴者を診断してはいけない）
    (r"あなたは(.{0,8})(症|病)です", "視聴者に対する診断"),
    (r"(薬|通院)は(いりません|不要です)", "受診・治療の中断を促す表現"),
    (r"病院に行(く必要はありません|かなくて)", "受診回避の推奨"),
]

_COMPILED = [(re.compile(p), why) for p, why in NG_PATTERNS]


@dataclass
class Finding:
    where: str          # "narration" / "title" / "description"
    excerpt: str
    reason: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def describe(self) -> str:
        if self.ok:
            return "指摘なし"
        return "\n".join(f"  - [{f.where}] 「{f.excerpt}」 … {f.reason}"
                         for f in self.findings)


def _excerpt(text: str, m: re.Match, span: int = 24) -> str:
    a = max(0, m.start() - span)
    b = min(len(text), m.end() + span)
    return text[a:b].replace("\n", " ")


# A claim that is immediately negated is a disclaimer, not a claim — and the
# medical genre is told to write exactly these. Without this guard the dictionary
# flagged 「すべての方に同じ効果があるわけではない」 as 効果の断定; every rewrite
# produced the same correct hedge, so the run burned all three rounds and aborted.
# Kept to the fixed disclaimer idioms and a short window so a real claim followed
# much later by an unrelated negative is still caught; the LLM pass sees it too.
_NEGATOR = re.compile(
    r"(わけ|もの)では(ない|なく|ありま)|とは限(らない|りません)|"
    r"保証(する|できる)ものでは|というわけでは"
)
_NEGATION_WINDOW = 14


def _is_negated(text: str, m: re.Match) -> bool:
    return bool(_NEGATOR.search(text[m.end():m.end() + _NEGATION_WINDOW]))


def scan(text: str, where: str) -> list[Finding]:
    """Dictionary pass. Deterministic, free, and runs first."""
    out: list[Finding] = []
    for rx, why in _COMPILED:
        for m in rx.finditer(text):
            if _is_negated(text, m):
                continue
            out.append(Finding(where, _excerpt(text, m), why))
    return out


# ---- Pass 2: LLM adjudication -----------------------------------------------
_ADJUDICATE_SYSTEM = (
    "あなたは薬機法・景表法・医療広告ガイドラインに精通した広告審査担当です。"
    "アフィリエイト媒体（YouTube動画）の原稿を審査します。出力はJSONのみ。"
)

_ADJUDICATE_USER = """次のYouTube動画原稿を、日本の薬機法・景表法の観点で審査してください。

【審査基準】
- 医薬品・医療機器でないものについて、疾患の治療・予防・症状改善を断定していないか。
- 効果や安全性を保証していないか（「必ず」「絶対」「副作用なし」等）。
- 最上級表現を根拠なく使っていないか。
- 視聴者を診断していないか。受診をやめるよう促していないか。
- 体験談を効果の証明として提示していないか。

【許容されるもの】（これらは指摘しないこと）
- 「〜という研究report があります」「〜と報告されています」等の出典付きの伝聞。
- 「気になる場合は医療機関へ」という受診の推奨。
- 仕組み・メカニズムの中立的な説明。

原稿:
---
{body}
---

問題のある表現だけをJSONで列挙してください。問題がなければ空配列。
JSON: {{"findings": [{{"excerpt": "問題の該当箇所をそのまま抜粋", "reason": "なぜ問題か(30字以内)"}}]}}"""


def adjudicate(text: str, where: str) -> list[Finding]:
    """LLM pass. Catches efficacy claims the dictionary cannot see.

    A failure here (API error, malformed JSON) returns no findings rather than
    raising: pass 1 has already run and is deterministic, so a transient API
    problem must not take the whole night's run down. The dictionary is the
    floor; this pass is the ceiling.
    """
    from llm_script import _chat  # imported lazily: keeps this module API-free
    try:
        raw = _chat([{"role": "system", "content": _ADJUDICATE_SYSTEM},
                     {"role": "user", "content": _ADJUDICATE_USER.format(body=text[:12000])}],
                    temperature=0.0, json_mode=True)
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        print(f"  [compliance] LLM審査を実行できませんでした（辞書判定のみで続行）: {e}")
        return []
    out = []
    for f in (data.get("findings") or [])[:20]:
        ex = str(f.get("excerpt", "")).strip()
        if ex:
            out.append(Finding(where, ex[:60], str(f.get("reason", ""))[:40]))
    return out


def review(pkg: dict, use_llm: bool = True) -> Report:
    """Check every viewer-facing field of a script package."""
    rep = Report()
    for where, key in (("title", "title"), ("narration", "narration"),
                       ("description", "description"),
                       ("thumbnail_text", "thumbnail_text")):
        text = (pkg.get(key) or "").strip()
        if not text:
            continue
        rep.findings.extend(scan(text, where))
    if use_llm:
        rep.findings.extend(adjudicate(pkg.get("narration", ""), "narration"))
    return rep


# ---- Rewrite ----------------------------------------------------------------
_REWRITE_SYSTEM = (
    "あなたは薬機法に配慮した医療系コンテンツのリライターです。"
    "原稿の主旨・構成・長さを保ったまま、指摘された表現だけを修正します。"
)

_REWRITE_USER = """次の原稿には、薬機法・景表法上の問題がある表現が含まれています。

【指摘】
{findings}

【修正方針】
- 断定的な効能表現は「〜と報告されています」「〜という研究があります」等の伝聞・出典ベースに置き換える。
- 効果・安全性の保証は削除する。
- 最上級表現は削除するか、客観的な事実に置き換える。
- 視聴者への診断は「気になる場合は医療機関にご相談ください」に置き換える。
- 指摘された箇所以外は一切変更しない。文字数を大きく減らさない。
- 見出し・箇条書き記号・絵文字は使わない。読み上げ用の地の文のまま。

原稿:
---
{body}
---

修正後の原稿本文のみを出力してください。前置きや説明は不要です。"""


def rewrite(text: str, findings: list[Finding]) -> str:
    from llm_script import _chat
    listed = "\n".join(f"- 「{f.excerpt}」 … {f.reason}" for f in findings[:20])
    out = _chat([{"role": "system", "content": _REWRITE_SYSTEM},
                 {"role": "user", "content": _REWRITE_USER.format(findings=listed, body=text)}],
                temperature=0.3)
    return out.strip()


class ComplianceError(RuntimeError):
    """The script could not be brought into compliance. Abort the run."""


def enforce(pkg: dict, genre: dict, use_llm: bool = True) -> dict:
    """Gate a script package. Returns the (possibly rewritten) package.

    Raises ComplianceError when the script still fails after MAX_ROUNDS. The
    caller must abort — publishing a flagged medical script is worse than
    missing a day's upload.
    """
    if genre.get("compliance") != "medical":
        return pkg

    for attempt in range(1, MAX_ROUNDS + 1):
        rep = review(pkg, use_llm=use_llm)
        if rep.ok:
            print(f"  [compliance] 審査通過（{attempt}回目のチェック）")
            break
        print(f"  [compliance] {len(rep.findings)}件の指摘 ({attempt}/{MAX_ROUNDS}):\n{rep.describe()}")
        if attempt == MAX_ROUNDS:
            raise ComplianceError(
                f"薬機法チェックを{MAX_ROUNDS}回のリライトで通過できませんでした。"
                f"投稿を中断します。指摘内容:\n{rep.describe()}")
        narration_findings = [f for f in rep.findings if f.where == "narration"]
        if narration_findings:
            pkg["narration"] = rewrite(pkg["narration"], narration_findings)
        for where, key in (("title", "title"), ("description", "description"),
                           ("thumbnail_text", "thumbnail_text")):
            fs = [f for f in rep.findings if f.where == where]
            if fs and pkg.get(key):
                pkg[key] = rewrite(pkg[key], fs)
        print("  [compliance] 指摘箇所をリライトして再審査します")

    return attach_disclaimer(pkg)


def attach_disclaimer(pkg: dict) -> dict:
    """Append the fixed disclaimer to the spoken script and the description.

    Appended after the gate, never before, so the disclaimer's own wording is
    not something the rewriter can erode.
    """
    narration = (pkg.get("narration") or "").rstrip()
    # An L2 masking-noise video has no narration at all — there is nothing to
    # read the disclaimer into, so only the description carries it.
    if narration and DISCLAIMER_SPOKEN not in narration:
        pkg["narration"] = f"{narration}\n{DISCLAIMER_SPOKEN}"
    desc = (pkg.get("description") or "").rstrip()
    if DISCLAIMER_TEXT not in desc:
        pkg["description"] = f"{desc}\n\n{DISCLAIMER_TEXT}".strip()
    return pkg


if __name__ == "__main__":
    # Dictionary-only smoke test (no API key needed).
    sample = {
        "title": "このいびきは必ず治る方法",
        "narration": "毎晩のいびきが完治します。医師も推奨する方法で、副作用はありません。"
                     "病院に行かなくても大丈夫です。",
        "description": "日本一のいびき解消法を紹介します。",
    }
    rep = review(sample, use_llm=False)
    print(f"findings: {len(rep.findings)}")
    print(rep.describe())
