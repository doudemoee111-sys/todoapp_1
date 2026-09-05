"""Affiliate links for the description and the pinned comment.

Kept in assets/affiliate_links.json rather than in code or an environment
variable. These URLs are published in every description, so there is nothing to
hide — what matters instead is that they are easy to swap when a programme ends,
reviewable in a diff, and impossible to ship half-finished.

Three rules are enforced here rather than trusted to whoever edits the JSON:

  * A link with no URL is dropped, so a heading never appears above nothing.
  * Nothing is emitted at all unless at least one link survives — an empty
    "▼ 関連リンク" block reads as a broken video.
  * Labels go through the same 薬機法 dictionary as the narration. The label is
    the one line of ad copy on the page, and it is written by hand, which makes
    it the likeliest place for a claim to slip past the generated-script gate.

The disclosure line is emitted first and is not optional: under the 2023
ステマ規制 an affiliate placement has to be identifiable as advertising, and the
affiliate — not the advertiser — is the one sanctioned for it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LINKS_FILE = Path(__file__).resolve().parent / "assets" / "affiliate_links.json"


class AffiliateError(RuntimeError):
    """The link file exists but would publish something it should not."""


def _load() -> dict:
    if not LINKS_FILE.exists():
        return {}
    try:
        return json.loads(LINKS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AffiliateError(f"assets/affiliate_links.json が壊れています: {e}") from e


def check_axis_map(data: dict | None = None) -> None:
    """Verify every link's axes still point at the topic it was chosen for.

    "axes" is a list of positions in config.GENRES["sleep"]["topic_axes"]. That
    is a fragile thing to store: inserting one line into the axis list shifts
    every index below it, and nothing about the resulting mismatch is visible —
    the run succeeds, the description renders, and a mattress link quietly
    appears under a video about talking to a reluctant partner. Nobody reviews
    a description that looks fine.

    So each index is stored alongside a word that must appear in the axis text.
    The index can drift; the wording cannot drift the same way by accident. When
    they disagree we stop before uploading, because a mis-targeted advertisement
    on a medical channel is a compliance problem, not a cosmetic one.

    Raises AffiliateError. Called from run.py's preflight.
    """
    from config import GENRES
    axes = GENRES["sleep"]["topic_axes"]
    data = _load() if data is None else data
    problems: list[str] = []
    for link in data.get("links") or []:
        name = link.get("program") or link.get("label") or link.get("url", "")[:40]
        idxs = link.get("axes")
        if idxs is None:
            continue
        keys = link.get("axis_keys")
        if keys is None:
            problems.append(f"{name}: axes はあるが axis_keys が無い（照合できない）")
            continue
        if len(keys) != len(idxs):
            problems.append(
                f"{name}: axes {len(idxs)}件 と axis_keys {len(keys)}件 の数が合わない")
            continue
        for i, key in zip(idxs, keys):
            if not 0 <= i < len(axes):
                problems.append(f"{name}: 切り口 {i} は存在しない（切り口は0〜{len(axes)-1}）")
            elif key not in axes[i]:
                problems.append(
                    f"{name}: 切り口 {i} に「{key}」が無い。"
                    f"現在の切り口{i}は「{axes[i][:28]}…」。"
                    "切り口を並べ替えたなら axes を直すこと")
    if problems:
        raise AffiliateError(
            "アフィリエイトリンクの切り口指定が、config.py の topic_axes とずれています。"
            "このまま投稿すると、無関係な回に広告が出ます:\n  - " + "\n  - ".join(problems))


def active_links(axis: int | None = None, data: dict | None = None) -> list[dict]:
    """Links allowed under this video's topic axis (see config.py topic_axes).

    A link with no "axes" key runs everywhere. A link WITH one runs only on the
    axes it names, and is withheld when the axis is unknown — a hand-picked topic
    or an ambient video. Withholding is the safe default: the whole reason a link
    is gated is that it is wrong somewhere, and "somewhere" is exactly what an
    unknown axis cannot rule out.
    """
    data = _load() if data is None else data
    out = []
    for link in data.get("links") or []:
        if not link.get("enabled"):
            continue
        allowed = link.get("axes")
        if allowed is not None and (axis is None or axis not in allowed):
            continue
        if not (link.get("url") or "").strip():
            print(f"  [affiliate] URL未設定のため出力しません: {link.get('label', '')}")
            continue
        # A URL with no heading is the other half of the same mistake: a bare
        # link under no explanation is worse than no link, and it cannot be
        # checked for 薬機法 because there is no copy to check.
        if not (link.get("label") or "").strip():
            print(f"  [affiliate] 見出し未設定のため出力しません: {link['url'][:48]}…")
            continue
        out.append(link)
    return out


_MEDIA_ID = re.compile(r"[?&]a8mat=([A-Za-z0-9]+)")
_ACCOUNT_PREFIX_LEN = 5


def media_id(url: str) -> str:
    """The first a8mat block, which identifies the registered site (media).

    A8 issues a link per registered site. Posting a link that was issued for a
    different site breaks the tracking and the terms, and the conversions are
    simply not credited — the failure is silent, which is why it is checked here
    rather than left to be noticed in a report months later.
    """
    m = _MEDIA_ID.search(url or "")
    return m.group(1) if m else ""


def _check_media(links: list[dict], data: dict) -> None:
    """Stop a link that came from a different A8 account from being published.

    The first a8mat block was initially read here as the registered site's ID,
    and the check was an exact allowlist. Three links later the blocks read
    4BABTD, 4BABTE, 4BABTF — incrementing in the order the links were created —
    so the trailing characters are a per-link counter, not the site. An exact
    allowlist would therefore reject every new link the account holder generates.

    What is stable across all of them is the leading run, so that is what is
    compared. This still catches the failure worth catching — a link pasted from
    a different A8 account, whose prefix differs from the first character — while
    staying quiet about a difference that carries no meaning.
    """
    expected = data.get("account_prefix") or ""
    if not expected:
        prefixes = {media_id(l["url"])[:_ACCOUNT_PREFIX_LEN] for l in links}
        if len(prefixes) > 1:
            print(f"  [affiliate] 警告: リンクの先頭が一致しません {sorted(prefixes)}。"
                  "別アカウントのリンクが混ざっていないか確認してください。")
        return
    wrong = [l for l in links if not media_id(l["url"]).startswith(expected)]
    if wrong:
        detail = "\n".join(
            f"  - {l.get('program') or l.get('label')}: {media_id(l['url'])}" for l in wrong)
        raise AffiliateError(
            f"別アカウントと思われるリンクが有効になっています（想定の先頭: {expected}）。\n"
            f"{detail}\n"
            "A8で『睡眠・安眠チャンネル2』のアカウントから発行し直すか、"
            "正しいものなら assets/affiliate_links.json の account_prefix を見直してください。")


def _warn_crowded(links: list[dict], axis: int | None) -> None:
    """Three links is a recommendation; five is a shop.

    Not enforced — dropping a link silently would lose revenue in a way nobody
    would notice — but said out loud, because the crowding happens gradually as
    programmes are added one at a time and no single addition looks wrong.
    """
    if len(links) > 3:
        names = "、".join(l.get("program", l["label"]).split("（")[0] for l in links)
        print(f"  [affiliate] 警告: 切り口{axis} にリンクが{len(links)}件あります（{names}）。"
              "概要欄が物販に見えるため、2〜3件に絞ることを検討してください。")


def _check_labels(links: list[dict]) -> None:
    """Reuse the narration's 薬機法 dictionary on the hand-written ad copy."""
    try:
        from compliance import scan
    except ImportError:
        return
    findings = []
    for link in links:
        findings += scan(link.get("label", ""), "アフィリエイトリンクの見出し")
    if findings:
        detail = "\n".join(f"  - {f.excerpt}（{f.reason}）" for f in findings)
        raise AffiliateError(
            "アフィリエイトリンクの見出しが薬機法チェックに触れました。\n"
            f"{detail}\n"
            "assets/affiliate_links.json の label を直してください。"
            "（生成台本と違い、ここは自動リライトしません）")


def description_block(axis: int | None = None) -> str:
    """The block to place near the top of a description. '' when unconfigured."""
    data = _load()
    links = active_links(axis, data)
    if not links:
        return ""
    _check_media(links, data)
    _check_labels(links)
    _warn_crowded(links, axis)
    lines = [data.get("disclosure", "※本動画には広告（アフィリエイトリンク）を含みます。"), ""]
    lines.append("▼ 関連リンク")
    for link in links:
        lines.append(f"・{link['label']}")
        lines.append(f"  {link['url'].strip()}")
    if data.get("footer"):
        lines += ["", data["footer"]]
    return "\n".join(lines)


def comment_block(axis: int | None = None) -> str:
    """The same links for a pinned comment, where the fold does not apply."""
    block = description_block(axis)
    return f"{block}\n\n（リンクは予告なく変更・終了することがあります）" if block else ""


if __name__ == "__main__":
    import sys
    from config import GENRES
    axes = GENRES["sleep"]["topic_axes"]
    wanted = [int(a) for a in sys.argv[1:]] or list(range(len(axes)))
    for i in wanted:
        out = description_block(i)
        print(f"\n=== 切り口 {i}: {axes[i]} ===")
        print(out or "（この回に出すリンクはありません）")
