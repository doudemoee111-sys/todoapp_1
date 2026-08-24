#!/usr/bin/env python3
"""2つのツール（eBay用・Shopee用）を parts/ から組み立てる。

**計算は parts/core.js にしか無い。** 両方のツールが同じファイルを取り込むので、
片方だけ式が古い、という状態が構造的に起きない。Python 側との一致は
tests/test_parity.py が node で実際に走らせて確かめている。

    python web/build.py

出力は web/ebay.html と web/shopee.html。どちらも外部への通信を一切しない
1枚のHTMLになる（フォントの読み込みを除く）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "parts"

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=IBM+Plex+Mono:wght@400;600&'
    'family=Zen+Kaku+Gothic+New:wght@400;500;700&display=swap">'
)

STEPS = [
    ("find",  "01", "探す"),
    ("pick",  "02", "選ぶ"),
    ("list",  "03", "出す"),
    ("track", "04", "追う"),
]


class Tool:
    def __init__(self, key, title, tag, accent, accent_dark, accent_soft,
                 accent_soft_dark, screens, scripts, other):
        self.key = key
        self.title = title
        self.tag = tag
        self.accent = accent
        self.accent_dark = accent_dark
        self.accent_soft = accent_soft
        self.accent_soft_dark = accent_soft_dark
        self.screens = screens
        self.scripts = scripts
        self.other = other      # もう一方のツールへの案内


TOOLS = [
    Tool(
        key="ebay",
        title="Blueocean eBay",
        tag="EBAY",
        # 濃い藍。Shopee用（橙）と並べたときに一目で違う。
        accent="#1F4B8F", accent_dark="#8FB4E4",
        accent_soft="#DEE6F2", accent_soft_dark="#1C2836",
        screens=["find.html", "pick.html", "list-ebay.html", "track.html",
                 "set.html", "how-ebay.html"],
        # boot-*.js が先。TOOL_ID を他が読むので、先に初期化されている必要がある。
        scripts=["boot-ebay.js", "core.js", "grid.js", "app.js", "find.js",
                 "pick.js", "list-ebay.js", "track.js"],
        other=("shopee.html", "Shopee用に切り替える"),
    ),
    Tool(
        key="shopee",
        title="Blueocean Shopee",
        tag="SHOPEE",
        accent="#B4521F", accent_dark="#E9A377",
        accent_soft="#F3E3D8", accent_soft_dark="#33221A",
        screens=["find.html", "pick.html", "list-shopee.html", "track.html",
                 "set.html", "how-shopee.html"],
        scripts=["boot-shopee.js", "core.js", "grid.js", "app.js", "find.js",
                 "pick.js", "list-shopee.js", "track.js"],
        other=("ebay.html", "eBay用に切り替える"),
    ),
]


def links() -> dict:
    """公開先のURLがあれば、ツール同士のリンクをそれに差し替える。

    ローカルでは相対パス（shopee.html）で動くが、1枚ずつ別のURLに公開すると
    相対パスでは辿れない。web/links.json に {"ebay": "...", "shopee": "..."}
    を置くと、そちらを使う。
    """
    f = HERE / "links.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"web/links.json が読めません：{e}")


def read(name: str) -> str:
    p = PARTS / name
    if not p.exists():
        raise SystemExit(f"部品が見つかりません：{p}")
    return p.read_text(encoding="utf-8")


def nav(tool: Tool) -> str:
    out = []
    for key, n, label in STEPS:
        out.append(
            f'<button data-sc="{key}" aria-current="false">'
            f'<span class="n">{n}</span><span class="t">{label}</span></button>'
        )
    out.append('<span class="sep"></span>')
    out.append('<button data-sc="set" aria-current="false"><span class="t">設定</span></button>')
    out.append('<button data-sc="how" aria-current="false"><span class="t">使い方</span></button>')
    return "\n    ".join(out)


def build(tool: Tool) -> str:
    css = read("shell.css")
    # アクセントだけツールごとに差し替える。3つの状態すべてに当てないと、
    # 端末の設定によっては片方の色が残る。
    accent = (
        "\n/* ---- このツールのアクセント ---- */\n"
        f":root{{--accent:{tool.accent};--accent-soft:{tool.accent_soft};"
        "--accent-ink:#FFFFFF}\n"
        "@media (prefers-color-scheme:dark){:root:not([data-theme=\"light\"]){"
        f"--accent:{tool.accent_dark};--accent-soft:{tool.accent_soft_dark};"
        "--accent-ink:#0D1218}}\n"
        f":root[data-theme=\"dark\"]{{--accent:{tool.accent_dark};"
        f"--accent-soft:{tool.accent_soft_dark};--accent-ink:#0D1218}}\n"
    )
    screens = "\n".join(read(s) for s in tool.screens)
    scripts = "\n\n".join(
        f"/* ===== {s} ===== */\n" + read(s) for s in tool.scripts
    )
    other_href, other_label = tool.other
    other_key = other_href.replace(".html", "")
    other_href = links().get(other_key, other_href)

    return f"""<title>{tool.title}</title>
{FONTS}
<style>
{css}{accent}</style>

<header class="hd">
  <div class="hd-in">
    <div class="brand"><b>Blueocean</b><span class="tag">{tool.tag}</span></div>
    <nav class="steps">
    {nav(tool)}
    </nav>
    <div class="util">
      <a class="chip" href="{other_href}">{other_label}</a>
    </div>
  </div>
  <div class="setbar"><div class="setbar-in" id="setbar"></div></div>
</header>

<main>
{screens}
  <p class="foot">Blueocean {tool.tag} ／ 計算は Python 版と同一（tests/test_parity.py で照合）／
  保存はこの端末のみ・外部送信なし</p>
</main>

<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script>
{scripts}
</script>
"""


def main() -> int:
    for tool in TOOLS:
        out = HERE / f"{tool.key}.html"
        html = build(tool)
        out.write_text(html, encoding="utf-8")
        print(f"  {out.name}  {len(html):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
