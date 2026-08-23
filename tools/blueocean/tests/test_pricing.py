"""値決めの検証。

「買っていいか」の次に来るのは「いくらで出すか」「この値下げを受けるか」で、
どちらも毎日発生する。ここが狂うと、正しく仕入れた商品を間違った値段で手放すことになる。
"""
import pytest

from blueocean.models import Market, SellerLevel, TaxProfile
from blueocean.pricing import (
    breakeven_duty_rate,
    breakeven_fx,
    list_price_for_margin,
    offer_floor,
    offer_ladder,
    return_impact,
)
from blueocean.profit import DEFAULT_PROFILES, compute, max_cost_for_margin

US = DEFAULT_PROFILES[Market.EBAY_US]
EU = DEFAULT_PROFILES[Market.EBAY_EU]
SEA = DEFAULT_PROFILES[Market.SHOPEE_SEA]
SHIP = 2299.0


# --- 出品価格の順算 ---------------------------------------------------------

def test_list_price_is_the_inverse_of_the_purchase_cap():
    """順算と逆算が完全に噛み合うこと。

    ここがずれると、仕入判断で使った前提と値付けの前提が食い違う。
    """
    for margin in (0.10, 0.20, 0.30):
        for cost in (5000, 9800, 40000):
            p = list_price_for_margin(cost, margin, US, shipping_jpy=SHIP)
            assert max_cost_for_margin(p, margin, US, shipping_jpy=SHIP) == pytest.approx(cost)


def test_list_price_actually_yields_the_target_margin():
    for margin in (0.05, 0.15, 0.25):
        p = list_price_for_margin(9800, margin, US, shipping_jpy=SHIP)
        assert compute(p, 9800, US, shipping_jpy=SHIP).margin == pytest.approx(margin)


def test_higher_target_margin_needs_a_higher_price():
    a = list_price_for_margin(9800, 0.10, US, shipping_jpy=SHIP)
    b = list_price_for_margin(9800, 0.30, US, shipping_jpy=SHIP)
    assert b > a


def test_us_needs_a_higher_price_than_other_markets():
    """関税と手数料が重い市場ほど、同じ仕入でも高く付けざるを得ない。"""
    us = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    eu = list_price_for_margin(9800, 0.20, EU, shipping_jpy=SHIP)
    sea = list_price_for_margin(9800, 0.20, SEA, shipping_jpy=SHIP)
    assert us > eu > sea


def test_impossible_margin_is_reported_not_guessed():
    """手数料＋関税＋目標利益率が100%を超えたら、無限大を返して黙らない。"""
    assert list_price_for_margin(9800, 0.95, US) == float("inf")


def test_heavier_shipping_raises_the_price():
    light = list_price_for_margin(9800, 0.20, US, shipping_jpy=1800)
    heavy = list_price_for_margin(9800, 0.20, US, shipping_jpy=6000)
    assert heavy > light


# --- 値下げ耐性 -------------------------------------------------------------

def test_offer_floor_at_zero_margin_is_breakeven():
    """利益率0の受諾ラインで売ると、利益がちょうど0になること。"""
    floor = offer_floor(9800, 0.0, US, shipping_jpy=SHIP)
    assert compute(floor, 9800, US, shipping_jpy=SHIP).profit_jpy == pytest.approx(0.0, abs=1e-6)


def test_offer_ladder_is_monotonic():
    """利益率が下がるほど受諾価格も下がること。"""
    steps = offer_ladder(9800, US, shipping_jpy=SHIP)
    prices = [s.price_usd for s in steps]
    assert prices == sorted(prices, reverse=True)
    assert [s.profit_jpy for s in steps] == sorted((s.profit_jpy for s in steps), reverse=True)


def test_offer_ladder_reports_the_discount_from_the_list_price():
    """出品価格からの値引き率が出ること。Best Offer はこの形で来る。"""
    listed = list_price_for_margin(9800, 0.30, US, shipping_jpy=SHIP)
    steps = offer_ladder(9800, US, list_price_usd=listed, shipping_jpy=SHIP)
    top = steps[0]
    assert top.margin == 0.30
    assert top.discount_from_list == pytest.approx(0.0, abs=1e-9)
    assert steps[-1].discount_from_list > 0


def test_offer_ladder_without_list_price_omits_the_discount():
    assert all(s.discount_from_list is None for s in offer_ladder(9800, US))


def test_below_standard_shrinks_the_room_to_discount():
    """セラーレベルが落ちると、値下げできる幅が狭くなる。"""
    ok = offer_floor(9800, 0.0, US, shipping_jpy=SHIP)
    bad = offer_floor(9800, 0.0, US, shipping_jpy=SHIP, level=SellerLevel.BELOW_STANDARD)
    assert bad > ok


# --- 感度（為替・関税） -----------------------------------------------------

def test_breakeven_fx_makes_the_profit_zero():
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    fx = breakeven_fx(p, 9800, US, shipping_jpy=SHIP)
    assert compute(p, 9800, US, fx_jpy_per_usd=fx,
                   shipping_jpy=SHIP).profit_jpy == pytest.approx(0.0, abs=1e-6)


def test_breakeven_fx_is_below_the_assumed_rate_when_profitable():
    """黒字なら、円高がどこまで進んだら赤字かが今のレートより下にあること。"""
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    assert breakeven_fx(p, 9800, US, shipping_jpy=SHIP) < 150.0


def test_breakeven_duty_makes_the_profit_zero():
    from dataclasses import replace

    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    d = breakeven_duty_rate(p, 9800, US, shipping_jpy=SHIP)
    assert compute(p, 9800, replace(US, duty_rate=d),
                   shipping_jpy=SHIP).profit_jpy == pytest.approx(0.0, abs=1e-6)


def test_breakeven_duty_is_above_the_current_rate_when_profitable():
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    assert breakeven_duty_rate(p, 9800, US, shipping_jpy=SHIP) > US.duty_rate


def test_breakeven_duty_never_goes_negative():
    """赤字の出品で「マイナスの関税なら黒字」と言わないこと。"""
    assert breakeven_duty_rate(35.0, 40000, US, shipping_jpy=SHIP) == 0.0


# --- 返品 -------------------------------------------------------------------

def test_return_loss_includes_both_legs_of_shipping():
    """越境ECの返品が重いのは往復送料。片道しか数えないと過小評価になる。"""
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    r = return_impact(p, 9800, US, shipping_jpy=SHIP)
    assert r.loss_per_return_jpy > SHIP * 2


def test_buyer_paid_return_is_cheaper_but_not_free():
    """バイヤーが返送料を持っても、出した分の送料は戻らない。"""
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    seller = return_impact(p, 9800, US, shipping_jpy=SHIP, seller_pays_return=True)
    buyer = return_impact(p, 9800, US, shipping_jpy=SHIP, seller_pays_return=False)
    assert 0 < buyer.loss_per_return_jpy < seller.loss_per_return_jpy


def test_unrecovered_item_adds_the_cost_to_the_loss():
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    back = return_impact(p, 9800, US, shipping_jpy=SHIP, item_recovered=True)
    lost = return_impact(p, 9800, US, shipping_jpy=SHIP, item_recovered=False)
    assert lost.loss_per_return_jpy > back.loss_per_return_jpy + 8000


def test_tolerable_rate_breaks_even_in_expectation():
    """許容返品率で回すと、期待値がちょうど0になること。"""
    p = list_price_for_margin(9800, 0.20, US, shipping_jpy=SHIP)
    r = return_impact(p, 9800, US, shipping_jpy=SHIP)
    expected = (1 - r.tolerable_rate) * r.profit_per_sale_jpy - r.tolerable_rate * r.loss_per_return_jpy
    assert expected == pytest.approx(0.0, abs=1e-6)


def test_a_loss_making_listing_tolerates_no_returns():
    r = return_impact(35.0, 40000, US, shipping_jpy=SHIP)
    assert r.profit_per_sale_jpy < 0
    assert r.tolerable_rate == 0.0
    assert r.tolerable_one_in == float("inf")


def test_fragile_flag_marks_listings_where_one_return_eats_several_sales():
    """返品1件が複数件分の利益を食う出品を、目立たせられること。"""
    thin = return_impact(list_price_for_margin(9800, 0.05, US, shipping_jpy=SHIP),
                         9800, US, shipping_jpy=SHIP)
    fat = return_impact(list_price_for_margin(9800, 0.40, US, shipping_jpy=SHIP),
                        9800, US, shipping_jpy=SHIP)
    assert thin.is_fragile
    assert not fat.is_fragile
