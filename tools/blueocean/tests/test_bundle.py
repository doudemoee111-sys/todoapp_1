"""セット販売の採算検証。

セット化が効く理由は「比較されない」だけではなく、原価構造が変わること。
注文・送料・梱包・注文ごと固定費が1回にまとまる。**送料が1回で済むのが最大の効き目**で、
単価の低い商品ほど効く。ここが正しく計算できないと、軸5は絵に描いた餅になる。
"""
import pytest

from blueocean.bundle import (
    BundleItem,
    breakeven_set_price_usd,
    compare,
    load_items,
    pack_bundle,
    sell_as_bundle,
    sell_separately,
)
from blueocean.models import Market, SellerLevel, TaxProfile
from blueocean.profit import DEFAULT_PROFILES
from blueocean.shipping import Parcel

US = DEFAULT_PROFILES[Market.EBAY_US]
SEA = DEFAULT_PROFILES[Market.SHOPEE_SEA]


def item(name, cost, g, solo=None, dims=(10, 10, 10)):
    return BundleItem(name, cost, g, dims[0], dims[1], dims[2], solo)


def cheap_five():
    """単価の低いアニメグッズ5点。うち2点は単品では売れない見込み。"""
    return [
        item("ねんどろいど", 1800, 150, 45.0),
        item("figma", 1500, 150, 38.0),
        item("一番くじ", 900, 300, 32.0, (15, 12, 12)),
        item("アクスタ3点", 500, 60, None, (15, 10, 2)),
        item("缶バッジ詰め合わせ", 300, 120, None, (22, 16, 2)),
    ]


PACK = Parcel(1100, 32, 24, 18)


# --- 個別売却 ---------------------------------------------------------------

def test_unsellable_items_are_counted_as_unsold_cost():
    """単品では売れない品を「いつか売れる」と数えないこと。

    ここを甘く見ると、セット化の効果を過小評価する。
    """
    r = sell_separately(cheap_five(), US)
    assert r.orders == 3
    assert len(r.unsold) == 2
    # 売れ残りの原価（500+300）が利益から引かれている
    assert r.cost_jpy == 5000


def test_shipping_is_charged_per_order():
    r = sell_separately(cheap_five(), US)
    single = sell_separately([cheap_five()[0]], US)
    assert r.shipping_jpy == pytest.approx(single.shipping_jpy * 3, rel=0.3)


# --- セット売却 -------------------------------------------------------------

def test_bundle_pays_shipping_once():
    items = cheap_five()
    sep = sell_separately(items, US)
    bun = sell_as_bundle(items, 110.0, US, packing=PACK)
    assert bun.orders == 1
    assert bun.shipping_jpy < sep.shipping_jpy
    assert bun.packaging_jpy == US.packaging_jpy


def test_bundle_turns_a_loss_into_a_profit():
    """低単価のまとめ売りが成立する根拠。

    単品では送料と手数料に食われて赤字でも、セットなら採算に乗ることがある。
    """
    items = cheap_five()
    sep = sell_separately(items, US)
    bun = sell_as_bundle(items, 110.0, US, packing=PACK)
    assert sep.profit_jpy < 0
    assert bun.profit_jpy > 0
    assert bun.margin > 0.20


def test_weights_are_summed_for_the_bundle():
    parcel = pack_bundle(cheap_five())
    assert parcel.weight_g == 150 + 150 + 300 + 60 + 120


def test_packing_material_can_be_added():
    assert pack_bundle(cheap_five(), extra_weight_g=200).weight_g == 980


def test_measured_packing_wins_over_the_sum():
    assert pack_bundle(cheap_five(), packing=PACK) is PACK


# --- 損益分岐 ---------------------------------------------------------------

def test_breakeven_reproduces_the_separate_profit():
    """損益分岐の売価で売ると、個別売却とちょうど同じ利益になること。"""
    items = cheap_five()
    be = breakeven_set_price_usd(items, US, packing=PACK)
    sep = sell_separately(items, US)
    bun = sell_as_bundle(items, be, US, packing=PACK)
    assert bun.profit_jpy == pytest.approx(sep.profit_jpy, abs=1.0)


def test_breakeven_is_below_the_solo_total_when_bundling_helps():
    """セット化が効いているなら、割引しても個別より儲かること。"""
    items = cheap_five()
    be = breakeven_set_price_usd(items, US, packing=PACK)
    solo_total = sum(i.solo_price_usd or 0 for i in items)
    assert be < solo_total


def test_breakeven_respects_the_market():
    """関税と手数料が低い市場ほど、分岐点は上がる（個別でも稼げるため）。"""
    items = cheap_five()
    assert (breakeven_set_price_usd(items, SEA, packing=PACK)
            > breakeven_set_price_usd(items, US, packing=PACK))


# --- 比較 -------------------------------------------------------------------

def test_comparison_flags_a_price_above_the_solo_total():
    """単品合計を超える値付けは、買い手が動かないので警告すること。"""
    c = compare(cheap_five(), 200.0, US, packing=PACK)
    assert any("単品合計" in n for n in c.notes)
    assert c.discount_vs_solo < 0


def test_comparison_reports_the_shipping_saving():
    c = compare(cheap_five(), 110.0, US, packing=PACK)
    assert c.shipping_saved_jpy > 0
    assert any("送料が" in n for n in c.notes)
    assert c.worth_bundling


def test_comparison_warns_when_the_bundle_cannot_be_quoted():
    """束ねた結果が料金表の範囲を超えたら、固定値に落ちたことを必ず言う。

    黙って固定値（3,000円）を使うと、**重いセットほど送料が安く見える**。
    セット化の効果を過大評価する最悪の外し方になる。
    """
    heavy = [item(f"H{i}", 2000, 1900, 120.0, (25, 20, 15)) for i in range(3)]
    c = compare(heavy, 300.0, US, packing=Parcel(5900, 45, 35, 30))
    assert not c.shipping_quotable
    assert any("料金表に無い" in n for n in c.notes)
    assert not any("送料が" in n and "浮く" in n for n in c.notes)


def test_comparison_warns_when_shipping_does_not_shrink():
    """段が上がって節約が消える場合は、そう言うこと。"""
    two = [item("A", 3000, 1400, 150.0, (20, 15, 12)),
           item("B", 3000, 1400, 150.0, (20, 15, 12))]
    c = compare(two, 280.0, US, packing=Parcel(2900, 30, 22, 18))
    assert c.shipping_quotable
    if c.shipping_saved_jpy <= 0:
        assert any("段が上がって" in n for n in c.notes)


def test_missing_dimensions_are_disclosed():
    """まとめ売りは箱が大きくなり容積課金されやすい。仮定のままにしない。"""
    c = compare(cheap_five(), 110.0, US)
    assert any("寸法が未入力" in n for n in c.notes)


def test_bundle_is_reminded_to_be_watched_by_axis2():
    """セットは検索にかかりにくい。軸2の必要性を必ず出す。"""
    c = compare(cheap_five(), 110.0, US)
    assert any("軸2" in n for n in c.notes)


def test_below_standard_hurts_bundles_too():
    items = cheap_five()
    ok = sell_as_bundle(items, 110.0, US, packing=PACK,
                        level=SellerLevel.ABOVE_STANDARD).profit_jpy
    bad = sell_as_bundle(items, 110.0, US, packing=PACK,
                         level=SellerLevel.BELOW_STANDARD).profit_jpy
    assert bad < ok


def test_tax_exemption_lowers_the_bundle_profit():
    items = cheap_five()
    taxable = sell_as_bundle(items, 110.0, US, packing=PACK).profit_jpy
    exempt = sell_as_bundle(items, 110.0, US, packing=PACK,
                            tax=TaxProfile(is_taxable_entity=False)).profit_jpy
    assert exempt < taxable


# --- 入出力 -----------------------------------------------------------------

def test_load_items_treats_blank_price_as_unsellable(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text(
        "name,cost_incl_tax_jpy,weight_g,length_cm,width_cm,height_cm,solo_price_usd\n"
        "売れる,1000,100,10,10,10,50\n"
        "死に筋,300,50,10,10,2,\n",
        encoding="utf-8",
    )
    items = load_items(p)
    assert items[0].sells_alone
    assert not items[1].sells_alone
    assert items[1].solo_price_usd is None
