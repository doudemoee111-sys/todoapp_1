"""軸1と軸2を1本に繋ぐパイプライン。

    [軸1] 国内候補を読む → eBayの競合数と相場を取る → 採算と競合で判定
                                    ↓
                          出品候補CSVを出力（出品ツールへ渡す）
                                    ↓
    [軸2] 出品後の反応を読む → 有在庫化 / 価格見直し / 撤退 を判定
                                    ↓
                          週次レポート（在庫切れ率の警告つき）
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import (
    Candidate,
    FeeProfile,
    Market,
    Observation,
    ScoredCandidate,
    SellerLevel,
    TaxProfile,
    Verdict,
)
from .history import (
    Change,
    DiffPolicy,
    Snapshot,
    append_snapshots,
    changes_since,
    latest_by_sku,
    load_snapshots,
    staleness_warning,
)
from .profit import DEFAULT_PROFILES
from .promotion import Decision, PromotionPolicy, decide_all, stockout_alert, stockout_rate
from .scoring import ScoringPolicy, score_all
from .sources.base import MarketDataSource


# ---------- 入出力 ----------

def load_candidates(path: str | Path) -> list[Candidate]:
    """国内の仕入候補をCSVから読む。

    プラットフォームのスクレイピングは規約違反になりうるため、既定は手動CSV。
    公式APIや正規のデータ提供が使える場合のみ、自動取得に差し替えること。
    """
    out: list[Candidate] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out.append(
                Candidate(
                    sku=row["sku"].strip(),
                    title_ja=row["title_ja"].strip(),
                    source_url=row.get("source_url", "").strip(),
                    # 走査で出した雛形は仕入値も重量も空。国内で現物が見つかるまで
                    # 埋まらないので、空でも読めるようにする（判定側で未入力を明示する）
                    cost_incl_tax_jpy=float(row.get("cost_incl_tax_jpy") or 0),
                    weight_g=int(float(row.get("weight_g") or 0)),
                    category=row.get("category", "").strip(),
                    # 寸法は任意だが、未入力だと容積重量を評価できない
                    length_cm=float(row.get("length_cm") or 0),
                    width_cm=float(row.get("width_cm") or 0),
                    height_cm=float(row.get("height_cm") or 0),
                    # 相場は任意。APIが使えない場合は手動調査の値をCSVで渡せる
                    market_price_usd=(
                        float(row["market_price_usd"])
                        if str(row.get("market_price_usd", "")).strip()
                        else None
                    ),
                    competitor_count=(
                        int(row["competitor_count"])
                        if str(row.get("competitor_count", "")).strip()
                        else None
                    ),
                    has_demand_signal=str(row.get("has_demand_signal", "")).strip().lower()
                    in {"1", "true", "yes", "y"},
                    demand_note=row.get("demand_note", "").strip(),
                    is_restricted=str(row.get("is_restricted", "")).strip().lower()
                    in {"1", "true", "yes", "y"},
                    restricted_reason=row.get("restricted_reason", "").strip(),
                    image_urls=tuple(
                        u.strip() for u in row.get("image_url", "").split("|") if u.strip()
                    ),
                    search_url=row.get("search_url", "").strip(),
                )
            )
    return out


def load_observations(path: str | Path) -> list[Observation]:
    """出品後の観測をCSVから読む（eBay Seller Hub のエクスポートを想定）。"""
    out: list[Observation] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out.append(
                Observation(
                    sku=row["sku"].strip(),
                    listed_on=date.fromisoformat(row["listed_on"].strip()),
                    observed_on=date.fromisoformat(row["observed_on"].strip()),
                    views=int(row.get("views", 0) or 0),
                    watchers=int(row.get("watchers", 0) or 0),
                    sold=int(row.get("sold", 0) or 0),
                    title=row.get("title", "").strip(),
                )
            )
    return out


def attach_titles(
    observations: list[Observation], candidates: list[Candidate]
) -> int:
    """候補CSVの商品名を観測に結合する。埋めた件数を返す。

    観測CSV（Seller Hubのエクスポート）にはSKUしか無いことが多い。
    SKUだけを並べても「どの商品か分からない」ので判定を読んでも動けない。
    候補CSVを持っているなら、そこから名前を引く。
    """
    names = {c.sku: c.title_ja for c in candidates if c.title_ja}
    filled = 0
    for o in observations:
        if not o.title and o.sku in names:
            o.title = names[o.sku]
            filled += 1
    return filled


# ---------- 軸1 ----------

def enrich(
    candidates: list[Candidate],
    source: MarketDataSource,
    *,
    query_of=None,
    refresh: bool = False,
) -> int:
    """eBay側の観測を候補に書き込む（破壊的に更新する）。取得件数を返す。

    既定では、CSVに競合数と相場の両方が入っている候補は問い合わせない
    （API未契約でも手動調査の値で運用できるようにするため）。

    ただしその挙動には落とし穴がある。**一度手で埋めた値は、放っておくと
    二度と更新されない。** 競合数と相場は毎日動くので、古い値のまま
    「BLUE」と表示され続けることになる。``refresh=True`` はこれを打ち消し、
    CSVの値を無視して取り直す。定期更新ではこちらを使う。
    """
    query_of = query_of or (lambda c: c.title_ja)
    fetched = 0
    for c in candidates:
        has_both = c.competitor_count is not None and c.market_price_usd is not None
        if has_both and not refresh:
            continue
        snap = source.snapshot(query_of(c))
        fetched += 1
        if refresh or c.competitor_count is None:
            c.competitor_count = snap.competitor_count
        if refresh or c.market_price_usd is None:
            c.market_price_usd = snap.median_price_usd
        # 画像と検索URLは判定に使わないが、国内で現物を探すときに要る
        if refresh or not c.image_urls:
            c.image_urls = snap.image_urls
        if refresh or not c.search_url:
            c.search_url = snap.search_url
    return fetched


def run_axis1(
    candidates: list[Candidate],
    source: MarketDataSource,
    *,
    market: Market = Market.EBAY_US,
    profile: FeeProfile | None = None,
    policy: ScoringPolicy | None = None,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    query_of=None,
    refresh: bool = False,
) -> list[ScoredCandidate]:
    profile = profile or DEFAULT_PROFILES[market]
    enrich(candidates, source, query_of=query_of, refresh=refresh)
    return score_all(candidates, profile, policy, level=level, tax=tax)


def run_axis1_with_history(
    candidates: list[Candidate],
    source: MarketDataSource,
    history_path: str | Path,
    *,
    today: date | None = None,
    diff_policy: DiffPolicy | None = None,
    record: bool = True,
    **kw,
) -> tuple[list[ScoredCandidate], list[Change], str | None]:
    """軸1を実行し、前回との差分と鮮度の警告を添えて返す。

    履歴は追記のみ。今回の結果を書く前に前回を読むので、同じ日に2回走らせても
    「前回」は前の実行日のままになる（同日の再実行で差分が消えない）。
    """
    today = today or date.today()
    past = load_snapshots(history_path)
    previous = latest_by_sku(past, before=today)

    scored = run_axis1(candidates, source, **kw)
    snapshots = [Snapshot.of(s, today) for s in scored]

    changes = changes_since(previous, snapshots, policy=diff_policy)
    warning = staleness_warning(previous, today, policy=diff_policy)

    if record:
        append_snapshots(history_path, snapshots)
    return scored, changes, warning


def write_listing_plan(scored: list[ScoredCandidate], path: str | Path) -> int:
    """出品対象（BLUE / PROBE）をCSVに書き出す。出品ツールへの受け渡し口。"""
    rows = [s for s in scored if s.verdict in (Verdict.BLUE, Verdict.PROBE)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["sku", "verdict", "score", "title_ja", "price_usd", "cost_jpy",
             "max_cost_jpy", "margin", "shipping_jpy", "shipping_note",
             "competitors", "reasons", "image_url", "search_url"]
        )
        for s in rows:
            c = s.candidate
            w.writerow([
                c.sku, s.verdict.value, s.score, c.title_ja,
                f"{c.market_price_usd:.2f}" if c.market_price_usd else "",
                round(c.cost_incl_tax_jpy), round(s.max_cost_jpy),
                f"{s.profit.margin:.3f}" if s.profit else "",
                round(s.profit.shipping_jpy) if s.profit else "",
                s.profit.shipping_note if s.profit else "",
                c.competitor_count if c.competitor_count is not None else "",
                " / ".join(s.reasons),
                "|".join(c.image_urls),
                c.search_url,
            ])
    return len(rows)


# ---------- 軸2 ----------

def split_latest(
    observations: list[Observation],
) -> tuple[list[Observation], dict[str, Observation]]:
    """SKUごとに「最新」と「その1つ前」に分ける。

    観測CSVは**追記して育てる**運用を想定している。毎週の行を足していけば、
    同じSKUの行が何本も並ぶ。そのまま判定に流すと同じ商品が何度も並び、
    どれが今の状態か分からなくなる。ここで最新だけを判定対象にし、
    1つ前は前回比の計算に使う。
    """
    by_sku: dict[str, list[Observation]] = {}
    for o in observations:
        by_sku.setdefault(o.sku, []).append(o)

    latest: list[Observation] = []
    previous: dict[str, Observation] = {}
    for sku, rows in by_sku.items():
        rows.sort(key=lambda o: o.observed_on)
        latest.append(rows[-1])
        if len(rows) >= 2:
            previous[sku] = rows[-2]
    return latest, previous


def run_axis2(
    observations: list[Observation],
    *,
    policy: PromotionPolicy | None = None,
    total_orders: int = 0,
    seller_cancellations: int = 0,
) -> tuple[list[Decision], str | None]:
    latest, previous = split_latest(observations)
    decisions = decide_all(latest, policy, previous=previous)
    alert = stockout_alert(stockout_rate(total_orders, seller_cancellations))
    return decisions, alert
