"""抽出の設計 ── 「何を、どんな条件で、どの項目まで採るか」を決める。

自動巡回はしない（規約上の判断。README参照）。**抽出は人がやる。**
このモジュールが担うのはその前後で、

    前：条件を決めて、開くべき検索ページのURLを組み立て、採る項目を定める
    後：採ってきたデータを検品して、軸1に流せる形に直す

国内せどりの定石は「価格安定 × セラー少ない × ランク良い × Amazon不在」。
これはよくできた基準だが、**輸出では2つ足りない。**

    1. リピート可能性   一点物か、また買えるか。
                        一点物は売れても次が無い。Shopeeのように
                        出品枠が限られる市場では、枠を一点物で埋めると詰む
    2. 課金重量         実重量ではなく、容積重量を含む課金重量。
                        軽くて嵩張るものは送料が跳ね、薄利だと丸ごと消える

この2つは「他のセラーが見ていないのに、輸出では効く」ところなので、
抽出項目でも EDGE（一歩先）として明示する。採らないと判定の精度が落ちる。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import quote_plus

from .models import Candidate, Market


class Tier(str, Enum):
    """項目の重要度。**何を落としてよくて、何を落とすと判定が成立しないか。**"""
    REQUIRED = "required"        # 無いと判定できない
    RECOMMENDED = "recommended"  # 無くても動くが精度が落ちる
    EDGE = "edge"                # 他のセラーが見ていない。輸出では効く


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    tier: Tier
    why: str            # なぜ採るのか。採る人が納得できないと項目は埋まらない
    example: str = ""


# 抽出項目。順番はそのままワークシートの列順になる。
FIELDS: tuple[Field, ...] = (
    Field("sku", "管理番号", Tier.REQUIRED,
          "自分で付ける識別子。出品後に軸2の観測と突き合わせる鍵になる", "LENS-001"),
    Field("title_ja", "商品名（eBayでの検索語）", Tier.REQUIRED,
          "英語の型番まで入れる。相場と競合数を引くときのクエリそのものになる",
          "Konica Hexanon AR 40mm F1.8"),
    Field("cost_incl_tax_jpy", "仕入価格（税込）", Tier.REQUIRED,
          "判定を動かせる唯一の変数。送料込みなら送料を抜いた額を入れる", "9800"),
    Field("weight_g", "重量（g・梱包後）", Tier.REQUIRED,
          "送料は重量区切りで階段状に上がる。梱包前の値を入れると1段ずれる", "180"),
    Field("length_cm", "縦（cm・梱包後）", Tier.EDGE,
          "★ 容積重量の計算に要る。軽くて嵩張るものは実重量では課金されない", "16"),
    Field("width_cm", "横（cm・梱包後）", Tier.EDGE, "★ 同上", "12"),
    Field("height_cm", "高さ（cm・梱包後）", Tier.EDGE, "★ 同上", "10"),
    Field("market_price_usd", "販売先の相場（USD）", Tier.REQUIRED,
          "**落札済み**の価格を見る。出品中の価格は「売れなかった価格」", "185"),
    Field("competitor_count", "競合の出品数", Tier.REQUIRED,
          "検索結果の件数。型番まで絞らないと数字が意味を持たない", "2"),
    Field("has_demand_signal", "需要の裏付け", Tier.RECOMMENDED,
          "同型の落札実績を実際に見たときだけ yes。無いと PROBE に留まる", "yes"),
    Field("demand_note", "裏付けの内容", Tier.RECOMMENDED,
          "「直近90日で12件落札」など。後から自分で検証できるように残す", ""),
    Field("repeatable", "また買えるか", Tier.EDGE,
          "★ 一点物か、再入荷するか。**一点物は売れても次が無い。**"
          "出品枠が限られる市場（Shopee）では、枠を一点物で埋めると詰む", "yes"),
    Field("source_count", "仕入元の数", Tier.EDGE,
          "★ 1箇所しか買えないと、切れた時点で終わる。無在庫では致命的", "3"),
    Field("cost_range_jpy", "仕入価格の振れ幅（円）", Tier.EDGE,
          "★ 薄利では仕入の変動が丸ごと利益を食う。"
          "9,800〜12,000円なら 2200 と書く", "2200"),
    Field("bundle_key", "セットにできる括り", Tier.EDGE,
          "★ 同シリーズ・同ブランドでまとめられるか。"
          "束ねると送料が1回で済む。低単価ほど効く", "konica-ar-lens"),
    Field("is_restricted", "輸出規制・禁止品", Tier.REQUIRED,
          "リチウム電池内蔵、化粧品、食品、ワシントン条約該当など。yes で除外", "no"),
    Field("restricted_reason", "規制の内容", Tier.RECOMMENDED, "何に該当するか", ""),
    Field("source_url", "仕入元のURL", Tier.RECOMMENDED,
          "後から現物を見に戻れるように。価格の再確認にも使う", ""),
    Field("note", "メモ", Tier.RECOMMENDED, "状態、付属品の欠品など", ""),
)

FIELD_BY_KEY = {f.key: f for f in FIELDS}


# ---------------------------------------------------------------------------
# 抽出条件
# ---------------------------------------------------------------------------

# 仕入元。**開くのは人。自動で巡回はしない。**
# ここが「規約に触れずに、探す作業だけを速くする」ための線引きになっている。
_SOURCES: dict[str, tuple[str, str]] = {
    "amazon_jp": ("Amazon.co.jp", "https://www.amazon.co.jp/s?k={q}"),
    "yahoo_shopping": ("Yahoo!ショッピング", "https://shopping.yahoo.co.jp/search?p={q}"),
    "rakuten": ("楽天市場", "https://search.rakuten.co.jp/search/mall/{q}/"),
    "mercari": ("メルカリ", "https://jp.mercari.com/search?keyword={q}"),
    "yahoo_auction": ("ヤフオク", "https://auctions.yahoo.co.jp/search/search?p={q}"),
    "surugaya": ("駿河屋", "https://www.suruga-ya.jp/search?search_word={q}"),
    "hardoff": ("ハードオフ ネットモール",
                "https://netmall.hardoff.co.jp/search/?keyword={q}"),
}

# Amazon の部門。URLの i= に載せると、その部門だけに絞れる。
_AMAZON_DEPT: dict[str, str] = {
    "おもちゃ・ホビー": "toys", "ホビー": "hobby", "ゲーム": "videogames",
    "カメラ": "photo", "家電": "electronics", "楽器": "mi",
    "ミュージック": "popular", "ビューティー": "beauty", "ドラッグストア": "hpc",
    "文房具": "stationery", "スポーツ": "sports", "ホーム＆キッチン": "kitchen",
}


@dataclass
class ExtractSpec:
    """抽出条件。**この条件でやる、と決めた内容がそのまま記録に残る。**"""
    name: str
    keywords: list[str] = field(default_factory=list)
    category: str = ""                    # Amazon の部門名（_AMAZON_DEPT のキー）
    market: Market = Market.EBAY_US
    min_cost_jpy: int = 0
    max_cost_jpy: int = 0                 # 0 なら上限なし
    max_weight_g: int = 2000
    condition: str = ""                   # "新品" / "中古" など、人が絞る目安
    exclude_words: list[str] = field(default_factory=list)
    target_margin: float = 0.20
    note: str = ""

    @property
    def department(self) -> str | None:
        return _AMAZON_DEPT.get(self.category)


@dataclass(frozen=True)
class SourceLink:
    source: str
    label: str
    keyword: str
    url: str


def source_urls(spec: ExtractSpec, *, sources: tuple[str, ...] | None = None
                ) -> list[SourceLink]:
    """開くべき検索ページのURLを組み立てる。

    **開くのは人。**価格帯や状態の絞り込みは、各サイトの画面でかけたほうが確実なので
    URLには載せない（パラメータの仕様が変わると黙って壊れる）。
    ここが担うのは「どの語で、どこを見に行くか」を漏らさないこと。
    """
    keys = sources or tuple(_SOURCES)
    out: list[SourceLink] = []
    for kw in spec.keywords or [""]:
        q = quote_plus(kw)
        for key in keys:
            if key not in _SOURCES:
                continue
            label, tmpl = _SOURCES[key]
            url = tmpl.format(q=q)
            if key == "amazon_jp" and spec.department:
                url += f"&i={spec.department}"
            out.append(SourceLink(key, label, kw, url))
    return out


def selling_side_urls(spec: ExtractSpec) -> list[SourceLink]:
    """販売先で相場と競合数を見るためのURL。落札済みも必ず出す。"""
    from .sources.ebay_browse import search_url

    mp = {"ebay_us": "EBAY_US", "ebay_eu": "EBAY_DE", "ebay_au": "EBAY_AU"}.get(
        spec.market.value, "EBAY_US")
    out: list[SourceLink] = []
    for kw in spec.keywords or [""]:
        out.append(SourceLink("ebay_active", "eBay 出品中（競合数）", kw,
                              search_url(kw, mp)))
        out.append(SourceLink("ebay_sold", "eBay 落札済み（相場）", kw,
                              search_url(kw, mp, sold=True)))
    return out


# ---------------------------------------------------------------------------
# ワークシート
# ---------------------------------------------------------------------------

def worksheet_columns(*, include: tuple[Tier, ...] | None = None) -> list[str]:
    tiers = include or (Tier.REQUIRED, Tier.RECOMMENDED, Tier.EDGE)
    return [f.key for f in FIELDS if f.tier in tiers]


def write_worksheet(
    path: str | Path, spec: ExtractSpec | None = None, *,
    include: tuple[Tier, ...] | None = None, with_legend: bool = True,
) -> int:
    """抽出用の空シートを書き出す。列の意味を2行目に入れておく。

    列だけ渡されても人は埋められない。**なぜその項目が要るのかを同じファイルに書く。**
    """
    cols = worksheet_columns(include=include)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        if with_legend:
            w.writerow([FIELD_BY_KEY[c].label for c in cols])
            w.writerow([
                ("★ " if FIELD_BY_KEY[c].tier is Tier.EDGE else "")
                + FIELD_BY_KEY[c].why for c in cols
            ])
            w.writerow([FIELD_BY_KEY[c].example for c in cols])
    return len(cols)


# ---------------------------------------------------------------------------
# 検品
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    ERROR = "error"      # このままでは判定できない
    WARN = "warn"        # 判定はできるが精度が落ちる
    INFO = "info"


@dataclass(frozen=True)
class Issue:
    row: int
    sku: str
    severity: Severity
    field_key: str
    message: str


# 規制に触れやすい語。**当たったら止めるのではなく、確認を促す。**
_RISK_WORDS: tuple[tuple[str, str], ...] = (
    ("リチウム", "リチウム電池内蔵は航空輸送規制の対象。単体・内蔵で扱いが違う"),
    ("バッテリー", "電池内蔵の可能性。航空輸送規制を確認"),
    ("充電", "充電池内蔵の可能性。航空輸送規制を確認"),
    ("化粧品", "化粧品は輸入国側の登録・成分規制がかかることがある"),
    ("コスメ", "化粧品扱いの可能性。輸入国側の規制を確認"),
    ("医薬", "医薬品・医薬部外品は輸出入とも規制対象"),
    ("食品", "食品は輸入国側の検疫・表示規制がかかる"),
    ("サプリ", "サプリメントは食品または医薬品扱い。輸入国側の規制を確認"),
    ("象牙", "ワシントン条約該当。取引禁止"),
    ("べっ甲", "ワシントン条約該当の可能性"),
    ("毛皮", "ワシントン条約該当の可能性"),
    ("ナイフ", "刃物は輸入国側の規制がかかることがある"),
    ("エアガン", "モデルガン・エアガンは多くの国で輸入禁止"),
    ("酒", "酒類は輸出入とも免許・規制の対象"),
)


def validate(rows: list[dict], spec: ExtractSpec | None = None) -> list[Issue]:
    """抽出したデータを検品する。**採ってきた直後に、埋まっていない穴を見せる。**

    軸1に流してから「相場が未取得で除外」と言われるより、
    ここで「この列が空です」と言われたほうが手戻りが小さい。
    """
    out: list[Issue] = []
    seen: dict[str, int] = {}

    for i, r in enumerate(rows, start=1):
        sku = str(r.get("sku", "")).strip()
        title = str(r.get("title_ja", "")).strip()
        ident = sku or title or f"{i}行目"

        if not sku:
            out.append(Issue(i, ident, Severity.WARN, "sku",
                             "管理番号が空。出品後に軸2の観測と突き合わせられません"))
        elif sku in seen:
            out.append(Issue(i, ident, Severity.ERROR, "sku",
                             f"管理番号が {seen[sku]}行目 と重複しています"))
        else:
            seen[sku] = i

        for key in ("title_ja", "cost_incl_tax_jpy", "market_price_usd",
                    "competitor_count", "weight_g"):
            if not str(r.get(key, "")).strip():
                f = FIELD_BY_KEY[key]
                out.append(Issue(i, ident, Severity.ERROR, key,
                                 f"{f.label} が空。{f.why}"))

        dims = [str(r.get(k, "")).strip() for k in ("length_cm", "width_cm", "height_cm")]
        if not all(dims):
            out.append(Issue(i, ident, Severity.WARN, "length_cm",
                             "寸法が空。★ 容積重量を評価できないので、"
                             "軽くて嵩張るものは送料が下振れします"))

        if not str(r.get("repeatable", "")).strip():
            out.append(Issue(i, ident, Severity.WARN, "repeatable",
                             "★「また買えるか」が空。一点物は売れても次が無いので、"
                             "出品枠が限られる市場では枠が死にます"))

        text = f"{title} {r.get('note', '')}"
        for word, why in _RISK_WORDS:
            if word in text:
                out.append(Issue(i, ident, Severity.WARN, "is_restricted",
                                 f"「{word}」を含みます。{why}"))
                break

        # 採算の当たりを、判定にかける前に粗く見る
        try:
            cost = float(str(r.get("cost_incl_tax_jpy", "") or 0))
            price = float(str(r.get("market_price_usd", "") or 0))
        except ValueError:
            out.append(Issue(i, ident, Severity.ERROR, "cost_incl_tax_jpy",
                             "仕入価格か相場が数値になっていません"))
            continue
        if spec and cost and spec.max_cost_jpy and cost > spec.max_cost_jpy:
            out.append(Issue(i, ident, Severity.WARN, "cost_incl_tax_jpy",
                             f"仕入 {cost:,.0f}円 が条件の上限 "
                             f"{spec.max_cost_jpy:,.0f}円 を超えています"))
        if cost and price and price * 150 < cost:
            out.append(Issue(i, ident, Severity.ERROR, "market_price_usd",
                             f"相場（約{price*150:,.0f}円）が仕入 {cost:,.0f}円 を"
                             f"下回っています。桁か通貨を取り違えていませんか"))

        try:
            w = int(float(str(r.get("weight_g", "") or 0)))
        except ValueError:
            w = 0
        if spec and w and w > spec.max_weight_g:
            out.append(Issue(i, ident, Severity.WARN, "weight_g",
                             f"重量 {w}g が条件の上限 {spec.max_weight_g}g を超えています"))

    return out


def summarize(issues: list[Issue]) -> dict[Severity, int]:
    out = {s: 0 for s in Severity}
    for i in issues:
        out[i.severity] += 1
    return out


def to_candidates(rows: list[dict]) -> list[Candidate]:
    """検品を通ったデータを軸1の候補に変換する。"""
    def num(v, cast=float, default=0):
        try:
            return cast(float(str(v).strip()))
        except (TypeError, ValueError):
            return default

    truthy = {"1", "true", "yes", "y", "はい", "○"}
    out: list[Candidate] = []
    for r in rows:
        out.append(Candidate(
            sku=str(r.get("sku", "")).strip(),
            title_ja=str(r.get("title_ja", "")).strip(),
            source_url=str(r.get("source_url", "")).strip(),
            cost_incl_tax_jpy=num(r.get("cost_incl_tax_jpy")),
            weight_g=num(r.get("weight_g"), int, 0),
            length_cm=num(r.get("length_cm")),
            width_cm=num(r.get("width_cm")),
            height_cm=num(r.get("height_cm")),
            category=str(r.get("category", "")).strip(),
            market_price_usd=(num(r.get("market_price_usd"))
                              if str(r.get("market_price_usd", "")).strip() else None),
            competitor_count=(num(r.get("competitor_count"), int)
                              if str(r.get("competitor_count", "")).strip() else None),
            has_demand_signal=str(r.get("has_demand_signal", "")).strip().lower() in truthy,
            demand_note=str(r.get("demand_note", "")).strip(),
            is_restricted=str(r.get("is_restricted", "")).strip().lower() in truthy,
            restricted_reason=str(r.get("restricted_reason", "")).strip(),
        ))
    return out


def _matches(row: dict, pick) -> bool:
    """埋まっている全セルが、その列の指定文字列と一致するか。"""
    filled = [(f, str(row.get(f.key, "")).strip()) for f in FIELDS]
    filled = [(f, v) for f, v in filled if v]
    return bool(filled) and all(v == pick(f) for f, v in filled)


def read_worksheet(path: str | Path) -> list[dict]:
    """記入済みのワークシートを読む。凡例の行は自動で飛ばす。

    **凡例の判定は中身ではなく位置で行う。** 記入例の `LENS-001` は実在しうるSKUで、
    実際に「例と同じ値の本物の行」を凡例と誤判定して消したことがある。
    中身だけで見分けようとすると、本物のデータと区別が付かない。

    write_worksheet が出すのは 見出し → ラベル → 説明 → 記入例 の順なので、
    **1行目がラベル行で、2行目が説明行のときに限り**、3行目を記入例として飛ばす。
    この並びが崩れているファイルには凡例が無いとみなす。
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if any(str(v).strip() for v in r.values())]

    skip = 0
    if rows and _matches(rows[0], lambda f: f.label):
        skip = 1
        if len(rows) > 1 and _matches(
            rows[1], lambda f: ("★ " + f.why) if f.tier is Tier.EDGE else f.why
        ):
            skip = 2
            if len(rows) > 2 and _matches(rows[2], lambda f: f.example):
                skip = 3
    return rows[skip:]
