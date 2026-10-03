"""実測データ — the one thing in this pipeline that a machine did not produce.

Why this module exists
----------------------
In August this channel received an AI judgment from YouTube. The policy it sits
under is not about whether a machine helped; it is about catalogues where every
entry is interchangeable with every other entry. Synthesised narration over
procedurally generated audio, written from nothing but a topic string, is
exactly that catalogue — and no amount of prompt engineering fixes it, because
the problem is that nothing in the video came from anywhere.

A measured number does come from somewhere. "枕元から30cmで、0時から1時まで1分
ごとに測った中央値は42デシベル" cannot be generated; it can only be recorded. It
is reproducible by the viewer, it dates the video, it names the instrument, and
it is wrong in ways that are interesting — which is the whole difference between
a document and a template.

So the room genre is built around an input the channel owner supplies by hand:
fifteen minutes a week with a meter and a notebook. Everything else in the
pipeline stays automated.

What this module refuses to do
------------------------------
It never invents a reading, and it never lets the pipeline invent one. There is
no default, no placeholder, no "approximately". If no measurement is pending,
the video is built WITHOUT one and is marked as such everywhere it can be
marked — runlog, result.json, the report. A fabricated measurement would be
worse than none: it would be a fabricated primary source published under the
channel's name, and it would be indistinguishable from the honest ones.

It also never blocks the day's post. Aborting the run was tried on the medical
gate and the cost is known: a day with no video, and a pipeline the owner stops
trusting. A gap in the stock is a thing to report, not a thing to crash on.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

MEAS_FILE = Path(__file__).resolve().parent / "assets" / "measurements.json"

# Below this, say so out loud in preflight. Two is one week of lead time at the
# current cadence, which is the point at which asking still helps.
LOW_STOCK = 2

REQUIRED = ("id", "date", "subject", "where", "device", "method", "readings", "finding")


class MeasurementError(RuntimeError):
    """The measurement file exists but would publish something it should not."""


def load() -> dict:
    if not MEAS_FILE.exists():
        return {"records": []}
    try:
        return json.loads(MEAS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MeasurementError(f"assets/measurements.json が壊れています: {e}") from e


def _records(data: dict | None = None) -> list[dict]:
    return (data or load()).get("records") or []


def check(data: dict | None = None) -> None:
    """Validate every record. Called from preflight, so a typo surfaces early.

    A malformed record is caught here rather than at the moment it is consumed,
    because the moment it is consumed is twenty minutes into a render.
    """
    data = data or load()
    problems: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(_records(data)):
        name = r.get("id") or f"（{i}番目・idなし）"
        if not isinstance(r, dict):
            problems.append(f"{name}: レコードが辞書ではありません")
            continue
        for key in REQUIRED:
            if not r.get(key):
                problems.append(f"{name}: 「{key}」が空です")
        if r.get("id") in seen:
            problems.append(f"{name}: id が重複しています")
        seen.add(r.get("id"))
        readings = r.get("readings")
        if readings is not None and not isinstance(readings, list):
            problems.append(f"{name}: readings は配列にしてください")
        elif isinstance(readings, list):
            for j, v in enumerate(readings):
                if not isinstance(v, dict) or not v.get("label") or not v.get("value"):
                    problems.append(f"{name}: readings[{j}] に label か value がありません")
        if r.get("used_in") is not None and not isinstance(r["used_in"], list):
            problems.append(f"{name}: used_in は配列にしてください")
    if problems:
        raise MeasurementError(
            "assets/measurements.json の記入に不足があります。"
            "このままでは測定データの無い回になります:\n  - " + "\n  - ".join(problems))


def pending(data: dict | None = None) -> list[dict]:
    """Records that are filled in, marked ready, and not yet used in a video."""
    out = []
    for r in _records(data):
        if not r.get("ready"):
            continue
        if r.get("used_in"):
            continue
        if any(not r.get(k) for k in REQUIRED):
            continue
        out.append(r)
    out.sort(key=lambda r: str(r.get("date", "")))
    return out


def take(data: dict | None = None) -> dict | None:
    """The measurement this video should use: the oldest unused one.

    Oldest first, not newest: a reading has a date on it and the date is
    published, so holding one back while publishing a fresher one makes the
    series read out of order.
    """
    p = pending(data)
    return p[0] if p else None


def mark_used(rec_id: str, video_id: str) -> None:
    """Record which video consumed this measurement, so it is never reused.

    Written straight back to the file. The container is ephemeral and the push
    may not land, in which case the same measurement would be offered again —
    so the published description is the real record, and this is the convenience
    copy. Reuse is caught on review rather than prevented absolutely, which is
    the honest level of guarantee available here.
    """
    data = load()
    for r in data.get("records") or []:
        if r.get("id") == rec_id:
            r.setdefault("used_in", []).append(
                {"video_id": video_id, "date": date.today().isoformat()})
            break
    else:
        print(f"  [measurement] 使用記録を書けません（id {rec_id} が見つかりません）")
        return
    MEAS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")


def axis_hint(rec: dict | None) -> int | None:
    """The topic axis this measurement was taken for, when it names one."""
    if not rec:
        return None
    a = rec.get("axis")
    return a if isinstance(a, int) else None


def _readings_lines(rec: dict) -> list[str]:
    return [f"・{v['label']}: {v['value']}" for v in rec.get("readings") or []]


def script_block(rec: dict | None) -> str:
    """Handed to the script writer. The numbers are not optional in the output.

    Phrased as data plus a hard instruction, because a model given a figure as
    context will paraphrase it away ("およそ40デシベル程度") and the paraphrase
    destroys the only property that matters: that the number is checkable.
    """
    if not rec:
        return ""
    lines = "\n".join(_readings_lines(rec))
    out = [
        "\n\n【この回の実測データ — 運営者が実際に測った値です】",
        f"測定日: {rec['date']}",
        f"測ったもの: {rec['subject']}",
        f"場所: {rec['where']}",
        f"機材: {rec['device']}",
        f"方法: {rec['method']}",
        f"結果:\n{lines}",
        f"測って分かったこと（運営者の言葉）: {rec['finding']}",
    ]
    if rec.get("limits"):
        out.append(f"この測定で分からないこと: {rec['limits']}")
    out.append(
        "\n守ること:\n"
        "- 上の数値を、単位までそのまま本文で言うこと。"
        "「およそ」「程度」「約」で丸めない。丸めた時点で、この動画の価値が消える。\n"
        "- 測った条件（日付・場所・機材・方法）を本文のどこかで必ず述べること。"
        "条件の無い数値は、視聴者には確かめようがない。\n"
        "- 上に無い数値を新しく作らない。推定値・平均値・一般的な目安を、"
        "測った値と並べて書かない。\n"
        "- 「測って分かったこと」は運営者本人の見解なので、言い換えてよいが趣旨を変えない。\n"
        "- この数値から言えないことは「これは分かりません」とそのまま言う。"
        "数値を体への効果の根拠に使わない。")
    return "\n".join(out)


def guard_block(rec: dict | None) -> str:
    """The short version, for chapters that are not reporting the measurement.

    The full block in every chapter prompt makes the model recite the readings
    eight times. Omitting it entirely does something worse: a chapter with no
    numbers in front of it invents plausible ones, and an invented number sitting
    beside a measured one is indistinguishable to the viewer. So the other
    chapters get the figures as a fence rather than as material.
    """
    if not rec:
        return ""
    vals = "、".join(f"{v['label']} {v['value']}" for v in rec.get("readings") or [])
    return ("\n\n【数値について】この動画で出してよい実測値は次のものだけです: "
            f"{vals}。\nこの章ではこれらを繰り返す必要はありません。"
            "ただし、ここに無い数値を新しく作らないこと。"
            "推定値・平均値・一般的な目安を、測った値のように書かないこと。")


def description_block(rec: dict | None) -> str:
    """The provenance block appended to the description.

    This is the part a viewer — or a reviewer — can act on. It goes near the
    end rather than the top because it is reference material, not a hook, but
    it is never omitted: a measurement whose conditions are not published is
    just a number somebody typed.
    """
    if not rec:
        return ""
    lines = ["▼ この回の測定について",
             f"測定日: {rec['date']}",
             f"測ったもの: {rec['subject']}",
             f"場所: {rec['where']}",
             f"機材: {rec['device']}",
             f"方法: {rec['method']}",
             "結果:"]
    lines += _readings_lines(rec)
    if rec.get("limits"):
        lines.append(f"この測定で分からないこと: {rec['limits']}")
    lines.append("同じ条件なら、ご自宅でも確かめられます。")
    return "\n".join(lines)


def headline_number(rec: dict | None) -> str:
    """The first reading, for a thumbnail. '' when there is nothing to show."""
    if not rec:
        return ""
    readings = rec.get("readings") or []
    return str(readings[0].get("value", "")) if readings else ""


def stock_warning() -> str:
    """'' when the stock is fine; otherwise what to say in preflight."""
    try:
        n = len(pending())
    except MeasurementError as e:
        return str(e)
    if n == 0:
        return ("実測データの在庫が 0 件です。次の回は測定値なしで作ります。\n"
                "  このジャンルの価値は実測値にあるので、1件だけでも入れてください。"
                "書き方は pipeline/assets/measurement_guide.md にあります。")
    if n <= LOW_STOCK:
        return (f"実測データの在庫が残り {n} 件です。"
                "切れると、ただの調べもの動画に戻ります。")
    return ""


if __name__ == "__main__":
    check()
    p = pending()
    print(f"使える実測データ: {len(p)}件")
    for r in p:
        print(f"  - [{r['date']}] {r['id']}: {r['subject']}")
    rec = take()
    if rec:
        print("\n--- 次の回に使うもの ---")
        print(description_block(rec))
    w = stock_warning()
    if w:
        print(f"\n[警告] {w}")
