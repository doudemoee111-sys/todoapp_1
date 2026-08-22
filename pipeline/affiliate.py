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


def active_links(data: dict | None = None) -> list[dict]:
    data = _load() if data is None else data
    out = []
    for link in data.get("links") or []:
        if not link.get("enabled"):
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


def description_block() -> str:
    """The block to place near the top of a description. '' when unconfigured."""
    data = _load()
    links = active_links(data)
    if not links:
        return ""
    _check_labels(links)
    lines = [data.get("disclosure", "※本動画には広告（アフィリエイトリンク）を含みます。"), ""]
    lines.append("▼ 関連リンク")
    for link in links:
        lines.append(f"・{link['label']}")
        lines.append(f"  {link['url'].strip()}")
    if data.get("footer"):
        lines += ["", data["footer"]]
    return "\n".join(lines)


def comment_block() -> str:
    """The same links for a pinned comment, where the fold does not apply."""
    block = description_block()
    return f"{block}\n\n（リンクは予告なく変更・終了することがあります）" if block else ""


if __name__ == "__main__":
    out = description_block()
    print(out or "有効なリンクがありません（url を入れて enabled を true にしてください）")
