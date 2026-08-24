"""Shopeeを eBay と同じ扱いにしないことの検証。

市場を分散させるのは正しいが、**戦略まで同じにすると外す。**
価格帯・配送・罰の効き方が構造的に違うので、そこを取り違えていないかを見る。
"""
import pytest

from blueocean.models import Market
from blueocean.profit import DEFAULT_PROFILES, required_multiple
from blueocean.promotion import stockout_alert
from blueocean.scoring import ScoringPolicy, score_one
from blueocean.shipping import DEFAULT_CARRIER, MARKET_ZONE, Carrier, Parcel, Zone, estimate


# --- 市場の分割 -------------------------------------------------------------

def test_shopee_markets_are_separate():
    """国ごとに手数料もVATも配送も違う。一括りにすると採算がずれる。"""
    shopee = [m for m in Market if m.is_shopee]
    assert {m.value for m in shopee} >= {"shopee_tw", "shopee_sg", "shopee_my", "shopee_ph"}
    assert all(m in DEFAULT_PROFILES for m in shopee)
    assert all(m in MARKET_ZONE for m in shopee)


def test_ebay_markets_are_not_shopee():
    assert not Market.EBAY_US.is_shopee
    assert Market.SHOPEE_TW.is_shopee


def test_taiwan_is_zone1():
    """台湾は第1地帯（中国・韓国・台湾）。東南アジアと同じ地帯にしない。"""
    assert MARKET_ZONE[Market.SHOPEE_TW] is Zone.ZONE1
    assert MARKET_ZONE[Market.SHOPEE_SG] is Zone.ZONE2


def test_taiwan_ships_cheaper_than_southeast_asia():
    p = Parcel(400, 20, 15, 10)
    tw = estimate(p, MARKET_ZONE[Market.SHOPEE_TW], Carrier.SLS).jpy
    sg = estimate(p, MARKET_ZONE[Market.SHOPEE_SG], Carrier.SLS).jpy
    assert tw < sg


def test_shopee_has_no_per_order_fee():
    """eBayのような出品ごとの固定費が無い。低単価が成立する理由のひとつ。"""
    assert DEFAULT_PROFILES[Market.SHOPEE_TW].per_order_fee_jpy == 0
    assert DEFAULT_PROFILES[Market.EBAY_US].per_order_fee_jpy > 0


# --- 配送の仕組みが違う -----------------------------------------------------

def test_shopee_defaults_to_sls():
    """Shopeeの越境では自分で国際発送しない。SLSに載せる。

    ここを「最安を自動」にすると、実際には選べない手段で採算を出してしまう。
    """
    assert DEFAULT_CARRIER[Market.SHOPEE_TW] is Carrier.SLS
    assert Market.EBAY_US not in DEFAULT_CARRIER


def test_sls_uses_volumetric_weight():
    """SLSは倉庫で実測される。嵩張れば容積で課金される。"""
    bulky = Parcel(300, 30, 25, 20)
    q = estimate(bulky, Zone.ZONE2, Carrier.SLS)
    assert q.billed_by_volume
    assert q.chargeable_weight_g == 2500


def test_sls_is_cheaper_than_self_shipping_by_post():
    p = Parcel(400, 20, 15, 10)
    sls = estimate(p, Zone.ZONE2, Carrier.SLS).jpy
    ems = estimate(p, Zone.ZONE2, Carrier.EMS).jpy
    assert sls < ems


# --- 価格帯の前提が違う -----------------------------------------------------

def test_shopee_floor_price_is_much_lower():
    """eBayの $30 下限をShopeeに持ち込むと、売れ筋がほぼ全部落ちる。

    Shopeeの主戦場は日本のドラッグストア価格帯の新品消耗品。
    """
    assert ScoringPolicy.for_market(Market.EBAY_US).min_price_usd == 30.0
    assert ScoringPolicy.for_market(Market.SHOPEE_TW).min_price_usd < 15.0


def test_a_cheap_item_survives_on_shopee_but_not_on_ebay():
    """同じ$15の商品が、eBayでは除外、Shopeeでは判定に乗ること。"""
    from blueocean.models import Candidate, Verdict

    def c():
        return Candidate(sku="A", title_ja="プチプラ化粧品", source_url="",
                         cost_incl_tax_jpy=600, weight_g=120, length_cm=12,
                         width_cm=6, height_cm=4, category="beauty",
                         market_price_usd=15.0, competitor_count=3,
                         has_demand_signal=True)

    ebay = score_one(c(), DEFAULT_PROFILES[Market.EBAY_US],
                     ScoringPolicy.for_market(Market.EBAY_US))
    shopee = score_one(c(), DEFAULT_PROFILES[Market.SHOPEE_TW],
                       ScoringPolicy.for_market(Market.SHOPEE_TW))
    assert ebay.verdict is Verdict.EXCLUDE
    assert any("下限" in r for r in ebay.reasons)
    assert shopee.verdict is not Verdict.EXCLUDE


def test_explicit_carrier_overrides_the_market_default():
    p = ScoringPolicy.for_market(Market.SHOPEE_TW, carrier=Carrier.EMS)
    assert p.carrier is Carrier.EMS


def test_market_policy_keeps_other_overrides():
    p = ScoringPolicy.for_market(Market.SHOPEE_TW, target_margin=0.35)
    assert p.target_margin == 0.35 and p.min_price_usd < 15.0


# --- 罰の効き方が違う -------------------------------------------------------

def test_stockout_warning_differs_by_market():
    """eBayは手数料に効く。Shopeeは露出とキャンペーン資格に効く。

    後者は「採算が悪くなる」ではなく「売上が立たなくなる」なので、
    同じ文言で済ませてはいけない。
    """
    ebay = stockout_alert(0.05, market=Market.EBAY_US)
    shopee = stockout_alert(0.05, market=Market.SHOPEE_TW)
    assert "Below Standard" in ebay and "手数料が6ポイント" in ebay
    assert "ペナルティポイント" in shopee and "メガセール" in shopee
    assert "Below Standard" not in shopee


def test_no_warning_below_threshold():
    assert stockout_alert(0.01, market=Market.SHOPEE_TW) is None


def test_market_is_optional_and_defaults_to_the_ebay_wording():
    assert "Below Standard" in stockout_alert(0.05)


# --- 採算の難易度 -----------------------------------------------------------

def test_shopee_needs_a_lower_multiple_than_us_at_the_same_price():
    """関税が無く手数料も低いぶん、同じ売価なら必要倍率は下がる。"""
    us = required_multiple(50, 0.20, DEFAULT_PROFILES[Market.EBAY_US], shipping_jpy=2299)
    tw = required_multiple(50, 0.20, DEFAULT_PROFILES[Market.SHOPEE_TW], shipping_jpy=1330)
    assert tw < us


def test_low_price_makes_shipping_dominate_on_shopee():
    """低単価では送料の比重が跳ね上がる。**セット化が効く理由がここ。**"""
    from blueocean.profit import compute

    tw = DEFAULT_PROFILES[Market.SHOPEE_TW]
    cheap = compute(15, 600, tw, shipping_jpy=1330)
    dear = compute(60, 2400, tw, shipping_jpy=1330)
    share_cheap = cheap.shipping_jpy / cheap.price_jpy
    share_dear = dear.shipping_jpy / dear.price_jpy
    assert share_cheap > share_dear * 3
