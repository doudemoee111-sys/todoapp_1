"""送料エンジンの検証。

固定送料をやめた理由は「重量で階段状に上がる」「嵩張ると容積で課金される」の
2点なので、その2点が実際に効いていることを最優先で確かめる。
"""
import csv

import pytest

from blueocean.models import Market
from blueocean.shipping import (
    DEFAULT_EMS_TABLES,
    MARKET_ZONE,
    Carrier,
    OverSize,
    Parcel,
    Provenance,
    RateTableMissing,
    Zone,
    cheapest,
    estimate,
    load_rate_table_csv,
    quote_all,
    shipping_jpy_for,
)


# --- 課金重量 ---------------------------------------------------------------

def test_ems_ignores_volumetric_weight():
    """EMSは容積重量を採らない。ここが他手段との決定的な違い。"""
    bulky = Parcel(500, 40, 30, 25)  # 30,000cc
    assert bulky.volumetric_weight_g(Carrier.EMS) == 0
    assert bulky.chargeable_weight_g(Carrier.EMS) == 500


def test_courier_and_parcel_use_volumetric_weight():
    """クーリエは÷5,000、国際小包は÷6,000。同じ箱でも課金重量が変わる。"""
    bulky = Parcel(500, 40, 30, 25)  # 30,000cc
    assert bulky.chargeable_weight_g(Carrier.COURIER) == 6000   # 30000/5000*1000
    assert bulky.chargeable_weight_g(Carrier.PARCEL) == 5000    # 30000/6000*1000


def test_dimensions_missing_falls_back_to_actual_weight():
    """寸法未入力では容積重量を評価できない。黙って通さず 0 を返す。"""
    p = Parcel(800)
    assert not p.has_dimensions
    assert p.volumetric_weight_g(Carrier.COURIER) == 0
    assert p.chargeable_weight_g(Carrier.COURIER) == 800


def test_missing_dimensions_produce_a_warning():
    q = estimate(Parcel(800), Zone.ZONE3, Carrier.COURIER)
    assert any("寸法が未入力" in w for w in q.warnings)


# --- 階段料金 ---------------------------------------------------------------

def test_rate_is_a_step_function():
    """100g超えただけで1段上がること。梱包の詰めが利益に直結する根拠。"""
    a = estimate(Parcel(500), Zone.ZONE3, Carrier.EMS).jpy
    b = estimate(Parcel(501), Zone.ZONE3, Carrier.EMS).jpy
    assert b > a
    assert estimate(Parcel(600), Zone.ZONE3, Carrier.EMS).jpy == b


def test_rate_is_monotonic_in_weight():
    """重くなって安くなる段があってはいけない。"""
    prev = 0.0
    for w in range(500, 5001, 50):
        jpy = estimate(Parcel(w), Zone.ZONE3, Carrier.EMS).jpy
        assert jpy >= prev
        prev = jpy


def test_us_zone_is_more_expensive_than_europe():
    """米国は独立地帯で最も高い。固定値ではこの差が消えていた。"""
    us = estimate(Parcel(500), Zone.ZONE4, Carrier.EMS).jpy
    eu = estimate(Parcel(500), Zone.ZONE3, Carrier.EMS).jpy
    asia = estimate(Parcel(500), Zone.ZONE2, Carrier.EMS).jpy
    assert us > eu > asia


def test_official_anchor_values_are_preserved():
    """公表値として確認できた金額が、内挿で上書きされていないこと。"""
    table = DEFAULT_EMS_TABLES[Zone.ZONE3]
    anchors = {b.max_weight_g: b for b in table.breaks
               if b.provenance is Provenance.OFFICIAL_ANCHOR}
    assert anchors[500].jpy == 3400
    assert anchors[900].jpy == 4400
    assert estimate(Parcel(450), Zone.ZONE3, Carrier.EMS).provenance is Provenance.OFFICIAL_ANCHOR


def test_interpolated_values_are_flagged_as_estimates():
    """推定値には必ず警告が付くこと。推定を事実として使わせない。"""
    q = estimate(Parcel(1400), Zone.ZONE3, Carrier.EMS)
    assert q.provenance is Provenance.INTERPOLATED
    assert any("推定値" in w for w in q.warnings)


def test_unknown_zone_raises_instead_of_substituting():
    """料金表の無い地帯は、別地帯の値で代用せずエラーにする。"""
    with pytest.raises(RateTableMissing):
        estimate(Parcel(500), Zone.ZONE5, Carrier.EMS)


# --- 手段の選択 -------------------------------------------------------------

def test_bulky_light_parcel_makes_ems_win():
    """軽くて嵩張る荷物では、容積重量を採らないEMSが逆転する。

    固定送料ではこの逆転が見えず、常に誤った手段を前提に採算を組むことになる。
    """
    bulky = Parcel(900, 60, 50, 40)
    quotes = quote_all(bulky, Zone.ZONE3)
    assert quotes, "使える手段が1つも無いのはおかしい"
    assert quotes[0].carrier is Carrier.EMS


def test_small_dense_parcel_prefers_epacket():
    """小さくて軽いものは小形包装物が最安になる。"""
    small = Parcel(300, 20, 15, 5)
    assert cheapest(small, Zone.ZONE3).carrier is Carrier.EPACKET


def test_epacket_is_dropped_when_over_size():
    """eパケットは三辺計90cmで縛られる。超えたら候補から外れる。"""
    big = Parcel(500, 50, 30, 20)  # 三辺計 100cm
    with pytest.raises(OverSize):
        estimate(big, Zone.ZONE3, Carrier.EPACKET)
    assert all(q.carrier is not Carrier.EPACKET for q in quote_all(big, Zone.ZONE3))


def test_epacket_is_dropped_when_over_weight():
    with pytest.raises(ValueError):
        estimate(Parcel(2500, 20, 15, 5), Zone.ZONE3, Carrier.EPACKET)


def test_billed_by_volume_flag():
    """容積課金かどうかを見積もり自身が答えられること（梱包改善の判断材料）。"""
    q = estimate(Parcel(500, 30, 25, 20), Zone.ZONE3, Carrier.COURIER)
    assert q.billed_by_volume
    assert q.chargeable_weight_g == 3000
    assert not estimate(Parcel(500, 10, 8, 5), Zone.ZONE3, Carrier.COURIER).billed_by_volume


# --- 市場との接続 -----------------------------------------------------------

def test_market_zone_mapping():
    assert MARKET_ZONE[Market.EBAY_US] is Zone.ZONE4
    assert MARKET_ZONE[Market.EBAY_EU] is Zone.ZONE3
    assert MARKET_ZONE[Market.SHOPEE_SEA] is Zone.ZONE2


def test_us_postal_suspension_is_surfaced():
    """米国宛ての郵便引受停止は、握りつぶさず見積もりに出す。"""
    q = estimate(Parcel(500, 20, 15, 10), Zone.ZONE4, Carrier.EMS)
    assert any("米国宛て" in w for w in q.warnings)
    # クーリエは対象外
    assert not any("米国宛て" in w for w in
                   estimate(Parcel(500, 20, 15, 10), Zone.ZONE4, Carrier.COURIER).warnings)


def test_shipping_jpy_for_picks_cheapest_by_default():
    p = Parcel(400, 20, 15, 10)
    auto = shipping_jpy_for(p, Market.EBAY_EU)
    ems = shipping_jpy_for(p, Market.EBAY_EU, carrier=Carrier.EMS)
    assert auto <= ems


# --- 公式料金表による差し替え -----------------------------------------------

def test_operator_table_overrides_estimates(tmp_path):
    """公式料金表を読み込んだら、推定値の警告が消えること。"""
    path = tmp_path / "rates.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zone", "max_weight_g", "jpy"])
        w.writerow(["zone3", "1000", "4650"])
        w.writerow(["zone3", "2000", "5900"])
    tables = load_rate_table_csv(path)
    q = estimate(Parcel(1400), Zone.ZONE3, Carrier.EMS, tables=tables)
    assert q.jpy == 5900
    assert q.provenance is Provenance.OPERATOR
    assert not any("推定値" in w for w in q.warnings)
