"""利益エンジンの検証。ここが狂うと仕入判断が全部狂うので、最も厚くテストする。"""
import pytest

from blueocean.models import Market, SellerLevel, TaxProfile
from blueocean.profit import (
    DEFAULT_PROFILES, compute, effective_fee_rate, max_cost_for_margin, required_multiple,
)

US = DEFAULT_PROFILES[Market.EBAY_US]
EU = DEFAULT_PROFILES[Market.EBAY_EU]
SEA = DEFAULT_PROFILES[Market.SHOPEE_SEA]


def test_max_cost_is_self_consistent():
    """逆算した仕入上限で計算すると、狙った利益率がちょうど出ること。"""
    for margin in (0.10, 0.15, 0.20, 0.30):
        cap = max_cost_for_margin(200, margin, US)
        assert compute(200, cap, US).margin == pytest.approx(margin, abs=1e-9)


def test_us_required_multiple_matches_report():
    """提案④の試算（米国 2.34倍）を再現すること。"""
    assert required_multiple(200, 0.20, US) == pytest.approx(2.34, abs=0.02)


def test_market_ordering_of_difficulty():
    """米国 > 欧州 > 東南アジア の順に難易度が下がること。関税と手数料の差。"""
    us = required_multiple(200, 0.20, US)
    eu = required_multiple(200, 0.20, EU)
    sea = required_multiple(200, 0.20, SEA)
    assert us > eu > sea
    assert eu == pytest.approx(1.77, abs=0.03)
    # Shopeeは関税が購入者負担で、セラーが負担する送料も国内ぶんだけなので大きく下がる
    assert sea == pytest.approx(1.32, abs=0.05)


def test_below_standard_raises_required_multiple():
    """Below Standard に落ちると必要倍率が跳ね上がること（手数料+6ポイント）。"""
    normal = required_multiple(200, 0.20, US, level=SellerLevel.ABOVE_STANDARD)
    bad = required_multiple(200, 0.20, US, level=SellerLevel.BELOW_STANDARD)
    assert bad > normal
    assert bad == pytest.approx(2.79, abs=0.03)


def test_top_rated_discount_helps():
    top = required_multiple(200, 0.20, US, level=SellerLevel.TOP_RATED)
    normal = required_multiple(200, 0.20, US, level=SellerLevel.ABOVE_STANDARD)
    assert top < normal


def test_effective_fee_rate_never_negative():
    assert effective_fee_rate(US, SellerLevel.TOP_RATED) >= 0


def test_tax_refund_matters():
    """免税事業者は還付が無いぶん、仕入上限が下がること。"""
    taxable = max_cost_for_margin(200, 0.20, US, tax=TaxProfile(is_taxable_entity=True))
    exempt = max_cost_for_margin(200, 0.20, US, tax=TaxProfile(is_taxable_entity=False))
    assert taxable > exempt
    b = compute(200, 12000, US, tax=TaxProfile(is_taxable_entity=False))
    assert b.vat_refund_jpy == 0.0


def test_refund_formula_is_tax_inclusive():
    """還付額は税込仕入 × 10/110 であること（税抜 × 10% ではない）。"""
    b = compute(200, 11000, US)
    assert b.vat_refund_jpy == pytest.approx(1000.0, abs=0.01)


def test_breakdown_adds_up():
    b = compute(200, 12000, US)
    total = (b.price_jpy - b.fees_jpy - b.duty_jpy - b.shipping_jpy
             - b.packaging_jpy - b.cost_jpy + b.vat_refund_jpy)
    assert b.profit_jpy == pytest.approx(total)


def test_weak_yen_helps_margin():
    """円安のほうが利益率が高くなること（同じ仕入・同じドル建て売価なら）。"""
    weak = compute(200, 12000, US, fx_jpy_per_usd=150).margin
    strong = compute(200, 12000, US, fx_jpy_per_usd=120).margin
    assert weak > strong
