"""データ構造。すべてのモジュールが共有する型を定義する。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class SellerLevel(str, Enum):
    """eBayのセラーレベル。手数料と検索順位に直結する。"""
    TOP_RATED = "top_rated"            # 落札手数料 10%割引
    ABOVE_STANDARD = "above_standard"  # 標準
    BELOW_STANDARD = "below_standard"  # 落札手数料に6%上乗せ


class Market(str, Enum):
    """販売先。関税と手数料の体系が丸ごと変わるため、市場は第一級の概念として扱う。"""
    EBAY_US = "ebay_us"    # DDP。対日追加関税がセラー負担
    EBAY_EU = "ebay_eu"    # VATはバイヤー負担が基本
    EBAY_AU = "ebay_au"
    SHOPEE_SEA = "shopee_sea"  # 手数料が低く、米国関税の影響を受けない


class Verdict(str, Enum):
    """軸1のスコアリング結果。"""
    BLUE = "blue"        # 競合が少なく需要の裏付けもある。最優先
    PROBE = "probe"      # 競合ゼロだが需要が未確認。少量で試す
    RED = "red"          # 競合過多。見送り
    THIN = "thin"        # 利益率が閾値に届かない
    EXCLUDE = "exclude"  # 輸出規制・重量超過などで対象外


class Action(str, Enum):
    """軸2の判定結果。出品後の観測から次の一手を決める。"""
    PROMOTE = "promote"    # 有在庫化する（当たり）
    KEEP = "keep"          # 継続観察
    REPRICE = "reprice"    # 閲覧はあるが動かない → 価格を見直す
    RETITLE = "retitle"    # 露出そのものが足りない → 検索語を見直す
    DROP = "drop"          # 反応なし。出品を畳む


@dataclass(frozen=True)
class FeeProfile:
    """市場ごとの手数料・関税・送料の前提。config で上書きできる。"""
    market: Market
    fee_rate: float           # 販売手数料の合計（決済・為替を含む実効値）
    per_order_fee_jpy: float  # 注文ごとの固定費
    duty_rate: float          # セラー負担の関税率（DDPでない市場は 0）
    shipping_jpy: float       # 想定国際送料
    packaging_jpy: float      # 梱包資材


@dataclass(frozen=True)
class TaxProfile:
    """消費税の扱い。課税事業者でなければ還付は受けられない。"""
    is_taxable_entity: bool = True  # 課税事業者か
    consumption_tax_rate: float = 0.10


@dataclass
class Candidate:
    """出品候補。国内の仕入れ元と、eBay側の観測値を持つ。"""
    sku: str
    title_ja: str
    source_url: str
    cost_incl_tax_jpy: float          # 国内の仕入価格（税込）
    weight_g: int                     # 梱包後の実重量
    category: str
    # --- 寸法（梱包後）。容積重量の判定に使う ---
    # 未入力（0）でも動くが、その場合は実重量だけで送料を出すため、
    # 嵩張る商品では見積もりが下振れする。軽くて大きいものほど必ず入れること。
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
    # --- eBay 側の観測（Browse API で取得） ---
    competitor_count: Optional[int] = None   # 同一/類似商品の現行出品数
    market_price_usd: Optional[float] = None # 競合の中央値価格
    # --- 需要の裏付け ---
    has_demand_signal: bool = False   # 類似品の落札実績・自分の販売実績など
    demand_note: str = ""
    # --- 除外フラグ ---
    is_restricted: bool = False       # 輸出規制・プラットフォーム禁止品
    restricted_reason: str = ""


@dataclass
class Observation:
    """出品後の観測。軸2の入力になる。"""
    sku: str
    listed_on: date
    observed_on: date
    views: int = 0
    watchers: int = 0
    sold: int = 0

    @property
    def days_listed(self) -> int:
        return max(0, (self.observed_on - self.listed_on).days)


@dataclass
class ProfitBreakdown:
    """利益計算の内訳。どこで利益が消えたかを必ず開示する。"""
    price_jpy: float
    fees_jpy: float
    duty_jpy: float
    shipping_jpy: float
    packaging_jpy: float
    cost_jpy: float
    vat_refund_jpy: float
    profit_jpy: float
    margin: float
    shipping_note: str = ""   # 送料の根拠（手段・課金重量・容積課金かどうか）

    def as_row(self) -> dict:
        return {
            "売価": round(self.price_jpy),
            "手数料": -round(self.fees_jpy),
            "関税": -round(self.duty_jpy),
            "送料": -round(self.shipping_jpy),
            "梱包": -round(self.packaging_jpy),
            "仕入": -round(self.cost_jpy),
            "消費税還付": round(self.vat_refund_jpy),
            "利益": round(self.profit_jpy),
            "利益率": f"{self.margin * 100:.1f}%",
        }


@dataclass
class ScoredCandidate:
    """軸1の判定結果。"""
    candidate: Candidate
    verdict: Verdict
    score: float
    profit: Optional[ProfitBreakdown]
    max_cost_jpy: float           # 目標利益率を満たす仕入上限
    reasons: list[str] = field(default_factory=list)
    # 送料の注意書き（米国宛ての引受停止など）。候補ごとではなく市場全体に効くため、
    # 判定理由とは分けて持ち、レポート末尾で1回だけ出す。
    shipping_warnings: list[str] = field(default_factory=list)
