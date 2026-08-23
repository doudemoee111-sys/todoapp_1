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
                    cost_incl_tax_jpy=float(row["cost_incl_tax_jpy"]),
                    weight_g=int(row["weight_g"]),
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
                )
            )
    return out


# ---------- 軸1 ----------

def enrich(candidates: list[Candidate], source: MarketDataSource, *, query_of=None) -> None:
    """eBay側の観測を候補に書き込む（破壊的に更新する）。"""
    query_of = query_of or (lambda c: c.title_ja)
    for c in candidates:
        if c.competitor_count is not None and c.market_price_usd is not None:
            continue  # CSVで両方与えられている場合は問い合わせない
        snap = source.snapshot(query_of(c))
        if c.competitor_count is None:
            c.competitor_count = snap.competitor_count
        if c.market_price_usd is None:
            c.market_price_usd = snap.median_price_usd


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
) -> list[ScoredCandidate]:
    profile = profile or DEFAULT_PROFILES[market]
    enrich(candidates, source, query_of=query_of)
    return score_all(candidates, profile, policy, level=level, tax=tax)


def write_listing_plan(scored: list[ScoredCandidate], path: str | Path) -> int:
    """出品対象（BLUE / PROBE）をCSVに書き出す。出品ツールへの受け渡し口。"""
    rows = [s for s in scored if s.verdict in (Verdict.BLUE, Verdict.PROBE)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["sku", "verdict", "score", "title_ja", "price_usd", "cost_jpy",
             "max_cost_jpy", "margin", "shipping_jpy", "shipping_note",
             "competitors", "reasons"]
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
            ])
    return len(rows)


# ---------- 軸2 ----------

def run_axis2(
    observations: list[Observation],
    *,
    policy: PromotionPolicy | None = None,
    total_orders: int = 0,
    seller_cancellations: int = 0,
) -> tuple[list[Decision], str | None]:
    decisions = decide_all(observations, policy)
    alert = stockout_alert(stockout_rate(total_orders, seller_cancellations))
    return decisions, alert
