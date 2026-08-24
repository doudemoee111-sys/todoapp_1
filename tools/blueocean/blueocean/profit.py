"""利益計算エンジン。

提案④ §4 の式をそのまま実装する。

    利益 = 売価 − 手数料 − 関税 − 送料 − 梱包 − 仕入 + 消費税還付

このモジュールの目的は「いくらで仕入れれば目標利益率に届くか」を機械的に出すこと。
仕入判断を勘でやらないための、事業の心臓部にあたる。
"""
from __future__ import annotations

from .models import (
    FeeProfile,
    Market,
    ProfitBreakdown,
    SellerLevel,
    TaxProfile,
)

# 市場ごとの既定値。2026年8月時点の調査に基づく。
# 関税は流動的なため、必ず config で上書きして運用すること（README 参照）。
DEFAULT_PROFILES: dict[Market, FeeProfile] = {
    # eBay手数料 合計18%（FVF + 注文手数料 + 国際取引1.35% + Payoneer為替2%）
    # 米国は DDP。対日追加関税 12.5%（MFNとの合算方式）がセラー負担
    Market.EBAY_US: FeeProfile(Market.EBAY_US, 0.18, 60, 0.125, 3000, 200),
    # 欧州・豪州は現地VATがバイヤー負担のため、セラー側の関税負担は 0 として扱う
    Market.EBAY_EU: FeeProfile(Market.EBAY_EU, 0.18, 60, 0.0, 3000, 200),
    Market.EBAY_AU: FeeProfile(Market.EBAY_AU, 0.18, 60, 0.0, 3000, 200),
    # Shopee は手数料 3〜10%。保守的に 8% を既定とし、SLS 送料を想定
    # Shopee：販売手数料＋決済手数料は各国 5.3〜7.0%（VAT込み表示）。
    # そこに為替・送金の実費が乗るので、実効値として 8% を置く。
    # 注文ごとの固定費は eBay のような出品手数料が無いため 0。
    # 関税は原則購入者負担なので 0。
    # **送料はセラー負担ぶん（国内の集荷場所まで）だけ。**国際送料とラストマイルは
    # SLSが処理するのでセラーの原価には乗らない。ここを国際送料にすると、
    # プチプラ商品がすべて赤字に見えてしまう。
    Market.SHOPEE_SEA: FeeProfile(Market.SHOPEE_SEA, 0.08, 0, 0.0, 800, 200),
    Market.SHOPEE_TW: FeeProfile(Market.SHOPEE_TW, 0.08, 0, 0.0, 800, 200),
    Market.SHOPEE_SG: FeeProfile(Market.SHOPEE_SG, 0.08, 0, 0.0, 800, 200),
    Market.SHOPEE_MY: FeeProfile(Market.SHOPEE_MY, 0.08, 0, 0.0, 800, 200),
    Market.SHOPEE_PH: FeeProfile(Market.SHOPEE_PH, 0.08, 0, 0.0, 800, 200),
}

# セラーレベルによる手数料の増減
_LEVEL_ADJUST: dict[SellerLevel, float] = {
    SellerLevel.TOP_RATED: -0.02,       # 落札手数料 10%割引 ≒ 実効 2ポイント減
    SellerLevel.ABOVE_STANDARD: 0.0,
    SellerLevel.BELOW_STANDARD: +0.06,  # 翌月から 6ポイント上乗せ
}


def effective_fee_rate(profile: FeeProfile, level: SellerLevel) -> float:
    """セラーレベルを織り込んだ実効手数料率。

    在庫切れキャンセルで Below Standard に落ちると、ここが 6ポイント跳ね上がる。
    無在庫のリスクが利益率に効く経路は、この一行に集約されている。
    """
    return max(0.0, profile.fee_rate + _LEVEL_ADJUST[level])


def compute(
    price_usd: float,
    cost_incl_tax_jpy: float,
    profile: FeeProfile,
    *,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
    shipping_note: str = "",
) -> ProfitBreakdown:
    """1件あたりの損益を計算する。

    ``shipping_jpy`` を渡すと、市場ごとの固定値ではなく実際の重量・寸法から
    出した送料で計算する（shipping モジュール参照）。渡さない場合は
    プロファイルの固定値にフォールバックするが、それは概算にすぎない。
    """
    tax = tax or TaxProfile()
    ship = profile.shipping_jpy if shipping_jpy is None else shipping_jpy
    price_jpy = price_usd * fx_jpy_per_usd

    fees = price_jpy * effective_fee_rate(profile, level) + profile.per_order_fee_jpy
    duty = price_jpy * profile.duty_rate

    # 輸出免税。課税事業者のみ、仕入に含まれる消費税が還付される。
    # 税込仕入 × 10/110 が還付額（税率10%の場合）。
    if tax.is_taxable_entity:
        r = tax.consumption_tax_rate
        vat_refund = cost_incl_tax_jpy * r / (1.0 + r)
    else:
        vat_refund = 0.0

    profit = (
        price_jpy
        - fees
        - duty
        - ship
        - profile.packaging_jpy
        - cost_incl_tax_jpy
        + vat_refund
    )
    margin = profit / price_jpy if price_jpy else 0.0

    return ProfitBreakdown(
        price_jpy=price_jpy,
        fees_jpy=fees,
        duty_jpy=duty,
        shipping_jpy=ship,
        packaging_jpy=profile.packaging_jpy,
        cost_jpy=cost_incl_tax_jpy,
        vat_refund_jpy=vat_refund,
        profit_jpy=profit,
        margin=margin,
        shipping_note=shipping_note,
    )


def max_cost_for_margin(
    price_usd: float,
    target_margin: float,
    profile: FeeProfile,
    *,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
) -> float:
    """目標利益率を満たす仕入上限（税込）を逆算する。

    これが仕入判断の基準線になる。国内の売値がこの額を超えていたら、
    どれだけ魅力的に見えても手を出さない。

        利益 = R − F − D − S − P − C + C·k   （k は還付係数）
        利益 = R·m  とおくと
        C = (R·(1 − m) − F − D − S − P) / (1 − k)
    """
    tax = tax or TaxProfile()
    ship = profile.shipping_jpy if shipping_jpy is None else shipping_jpy
    price_jpy = price_usd * fx_jpy_per_usd

    fees = price_jpy * effective_fee_rate(profile, level) + profile.per_order_fee_jpy
    duty = price_jpy * profile.duty_rate
    k = (
        tax.consumption_tax_rate / (1.0 + tax.consumption_tax_rate)
        if tax.is_taxable_entity
        else 0.0
    )

    numerator = (
        price_jpy * (1.0 - target_margin)
        - fees
        - duty
        - ship
        - profile.packaging_jpy
    )
    return max(0.0, numerator / (1.0 - k))


def required_multiple(
    price_usd: float,
    target_margin: float,
    profile: FeeProfile,
    **kw,
) -> float:
    """「売価 ÷ 仕入」で何倍が必要かを返す。市場間の難易度比較に使う。"""
    cap = max_cost_for_margin(price_usd, target_margin, profile, **kw)
    if cap <= 0:
        return float("inf")
    fx = kw.get("fx_jpy_per_usd", 150.0)
    return (price_usd * fx) / cap
