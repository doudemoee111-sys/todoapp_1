"""現物照合シート ── 「探しに行く前に、見た目を確かめる」ための一覧。

型番だけを頼りに国内を回ると事故が起きる。世代違い、マイナーチェンジ違い、
海外向けと国内向けの型番違い。**買ってから気づいたのでは遅い。**

このモジュールは走査・判定の結果を、**商品写真つきの1枚のHTML**に落とす。
印刷して持って行くか、スマホで開いて店頭で照合する使い方を想定している。

写真は eBay の出品画像（Browse API が返す `image.imageUrl`）を参照する。
**ダウンロードして再配布はしない**（他人の出品写真なので）。手元で開く1枚の
HTMLから参照するだけに留めてある。

なぜブラウザ版ではなくローカルHTMLなのか：
公開ページ（Artifact）は外部ホストへの画像リクエストを遮断する仕組みの上で
動いているため、eBayの画像を表示できない。ローカルに書き出したファイルなら
その制約がかからない。**ブラウザ版では代わりに検索URLへのリンクを出す。**
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from .discovery import KeywordResult
from .models import ScoredCandidate, Verdict

_VERDICT_LABEL = {
    Verdict.BLUE: ("BLUE", "#0F6E76"), Verdict.PROBE: ("PROBE", "#B98216"),
    Verdict.THIN: ("THIN", "#7A6A55"), Verdict.RED: ("RED", "#B33A1A"),
    Verdict.EXCLUDE: ("EXCL", "#8C99A4"),
}


@dataclass(frozen=True)
class SheetItem:
    """シート1枚に並べるカード1件。走査結果と判定結果の共通形。"""
    title: str
    badge: str
    badge_color: str
    lines: list[str]
    image_urls: tuple[str, ...]
    search_url: str


def from_scan(results: list[KeywordResult], *, worthy_only: bool = True) -> list[SheetItem]:
    """走査結果をカードにする。**予算を大きく出す** ── 店頭で見るのはそこだけ。"""
    _c = {"open": ("空き", "#0F6E76"), "probe": ("要検証", "#B98216"),
          "crowded": ("過密", "#B33A1A"), "low": ("低単価", "#7A6A55"),
          "no_data": ("取得失敗", "#8C99A4")}
    out: list[SheetItem] = []
    for r in results:
        if worthy_only and not r.is_hunt_worthy:
            continue
        label, color = _c[r.opening.value]
        price = f"${r.median_price_usd:,.0f}" if r.median_price_usd else "—"
        out.append(SheetItem(
            title=r.keyword, badge=label, badge_color=color,
            lines=[
                f"予算 {r.max_cost_jpy:,.0f}円まで",
                f"eBay相場 {price} / 競合 {r.competitor_count}件",
                r.note,
            ],
            image_urls=r.image_urls, search_url=r.search_url,
        ))
    return out


def from_scored(scored: list[ScoredCandidate], *, include_excluded: bool = False) -> list[SheetItem]:
    """軸1の判定結果をカードにする。"""
    out: list[SheetItem] = []
    for s in scored:
        if not include_excluded and s.verdict is Verdict.EXCLUDE:
            continue
        label, color = _VERDICT_LABEL[s.verdict]
        c = s.candidate
        price = f"${c.market_price_usd:,.0f}" if c.market_price_usd else "—"
        lines = [
            f"仕入 {c.cost_incl_tax_jpy:,.0f}円 / 上限 {s.max_cost_jpy:,.0f}円",
            f"eBay相場 {price} / 競合 "
            f"{c.competitor_count if c.competitor_count is not None else '—'}件",
        ]
        lines += s.reasons[:2]
        out.append(SheetItem(
            title=c.title_ja, badge=label, badge_color=color, lines=lines,
            image_urls=c.image_urls, search_url=c.search_url,
        ))
    return out


_CSS = """
:root{color-scheme:light dark;--pa:#F2F4F6;--su:#fff;--ink:#101820;--m:#63727F;--ru:#CFD8DF;}
@media(prefers-color-scheme:dark){:root{--pa:#0D1216;--su:#151D22;--ink:#E4EBEF;--m:#8FA1AD;--ru:#2C3941;}}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--pa);color:var(--ink);
  font-family:"Zen Kaku Gothic New","Hiragino Sans","Yu Gothic UI",sans-serif;line-height:1.7;}
h1{font-size:21px;margin:0 0 4px;}
.sub{color:var(--m);font-size:13px;margin:0 0 22px;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px;}
.card{background:var(--su);border:1px solid var(--ru);border-radius:5px;overflow:hidden;
  display:flex;flex-direction:column;break-inside:avoid;}
.shots{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--ru);}
.shots img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:var(--pa);}
.noshot{padding:26px 14px;text-align:center;color:var(--m);font-size:12px;background:var(--pa);}
.bd{padding:13px 15px;display:flex;flex-direction:column;gap:6px;flex:1;}
.tp{display:flex;gap:9px;align-items:baseline;}
.bg{font-family:ui-monospace,Menlo,monospace;font-size:10px;font-weight:700;letter-spacing:.07em;
  padding:2px 7px;border-radius:2px;color:#fff;white-space:nowrap;}
.nm{font-weight:700;font-size:14px;}
.ln{font-size:12px;color:var(--m);}
.ln.k{color:var(--ink);font-weight:700;font-size:13px;}
a.go{margin-top:auto;padding:9px 15px;border-top:1px solid var(--ru);font-size:12px;
  color:inherit;text-decoration:none;display:block;}
a.go:hover{background:var(--pa);}
footer{margin-top:26px;color:var(--m);font-size:11.5px;line-height:1.8;}
@media print{body{background:#fff;padding:0}.card{border-color:#ccc}a.go{display:none}}
"""


def render(items: list[SheetItem], *, title: str = "現物照合シート",
           note: str = "") -> str:
    """カード群をHTML文字列にする。"""
    cards = []
    for it in items:
        if it.image_urls:
            shots = "".join(
                f'<img src="{html.escape(u)}" alt="{html.escape(it.title)}" loading="lazy">'
                for u in it.image_urls[:6]
            )
            shots = f'<div class="shots">{shots}</div>'
        else:
            shots = ('<div class="noshot">写真は未取得<br>'
                     '（eBay認証情報を渡すと取得します）</div>')
        lines = "".join(
            f'<div class="ln{" k" if i == 0 else ""}">{html.escape(x)}</div>'
            for i, x in enumerate(it.lines) if x
        )
        go = (f'<a class="go" href="{html.escape(it.search_url)}" target="_blank" '
              f'rel="noopener">eBayで実物の写真と価格を見る →</a>'
              if it.search_url else "")
        cards.append(
            f'<div class="card">{shots}<div class="bd">'
            f'<div class="tp"><span class="bg" style="background:{it.badge_color}">'
            f'{html.escape(it.badge)}</span><span class="nm">{html.escape(it.title)}</span></div>'
            f'{lines}</div>{go}</div>'
        )
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f'<p class="sub">{html.escape(note)}</p>'
        f'<div class="grid">{"".join(cards)}</div>'
        '<footer>写真は eBay の出品画像を参照しています（このファイルは配布用ではありません）。<br>'
        '型番が同じでも世代違い・マイナーチェンジ違いがあります。'
        '<strong>買う前に必ず実物と見比べてください。</strong></footer>'
        "</body></html>"
    )


def write(items: list[SheetItem], path: str | Path, **kw) -> int:
    """シートをファイルに書き出す。書いた件数を返す。"""
    Path(path).write_text(render(items, **kw), encoding="utf-8")
    return len(items)
