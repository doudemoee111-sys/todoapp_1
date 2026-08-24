"""Shopee専用の一括運用の検証。

「数千点を一括出品する」という設計はShopeeでは載らない。出品枠の上限
（新規は台湾500点／他1,000点、うちプレオーダーは100点程度）が先に来るためで、
**作るべきは「少ない枠に何を置くかを選び続ける」道具**になる。
"""
from datetime import date

import pytest

from blueocean.models import Action, Candidate, Market, Observation, Verdict
from blueocean.profit import DEFAULT_PROFILES
from blueocean.promotion import decide
from blueocean.scoring import ScoringPolicy, score_one
from blueocean.shopee import (
    LISTING_LIMITS,
    Listing,
    RepriceAction,
    RepricePolicy,
    load_listings,
    plan_reprice,
    plan_slots,
    write_mass_upload,
    write_reprice_plan,
)

TW = DEFAULT_PROFILES[Market.SHOPEE_TW]


# --- 出品枠 -----------------------------------------------------------------

def test_taiwan_has_half_the_slots_of_other_markets():
    """台湾は日本製の主戦場なのに、新規開店時の枠が最も狭い。"""
    assert LISTING_LIMITS[Market.SHOPEE_TW].new_shop == 500
    assert LISTING_LIMITS[Market.SHOPEE_SG].new_shop == 1000


def test_thousands_of_listings_do_not_fit():
    """「数千点を一括出品」が成立しないことを、数字で示せること。"""
    plan = plan_slots(Market.SHOPEE_TW, listed=0, preorder_listed=0, tier="new")
    assert plan.limit == 500
    assert plan.preorder_limit == 100


def test_room_and_preorder_room():
    plan = plan_slots(Market.SHOPEE_SG, listed=800, preorder_listed=60, tier="new")
    assert plan.room == 200 and plan.preorder_room == 40


def test_exceeding_the_preorder_limit_is_flagged_as_forced_removal():
    """自分で落とさなければ、残すものをShopeeに選ばれる。"""
    plan = plan_slots(Market.SHOPEE_TW, listed=400, preorder_listed=130)
    assert plan.forced_removals == 30
    assert any("自動削除" in n for n in plan.notes)


def test_full_shop_says_one_in_one_out():
    plan = plan_slots(Market.SHOPEE_TW, listed=500, preorder_listed=50)
    assert plan.room == 0
    assert any("1つ入れるには1つ落とす" in n for n in plan.notes)


def test_tier_raises_the_limit():
    kw = dict(listed=0, preorder_listed=0)
    assert (plan_slots(Market.SHOPEE_TW, tier="preferred", **kw).limit
            > plan_slots(Market.SHOPEE_TW, tier="new", **kw).limit)
    assert plan_slots(Market.SHOPEE_TW, tier="max", **kw).limit == 20000


def test_drop_and_add_come_from_the_two_axes():
    """入れ替え候補は、軸2のDROPと軸1のBLUE/PROBEを突き合わせて出す。"""
    dropped = decide(Observation("OLD", date(2026, 1, 1), date(2026, 8, 23), 21, 0, 0))
    assert dropped.action is Action.DROP

    c = Candidate(sku="NEW", title_ja="新しい候補", source_url="",
                  cost_incl_tax_jpy=600, weight_g=120, length_cm=12, width_cm=6,
                  height_cm=4, category="", market_price_usd=15.0,
                  competitor_count=3, has_demand_signal=True)
    scored = score_one(c, TW, ScoringPolicy.for_market(Market.SHOPEE_TW))
    assert scored.verdict in (Verdict.BLUE, Verdict.PROBE)

    plan = plan_slots(Market.SHOPEE_TW, listed=100, preorder_listed=10,
                      decisions=[dropped], scored=[scored])
    assert plan.drop == ["OLD"]
    assert plan.add == ["新しい候補"]


def test_cannot_add_more_than_the_room_plus_drops():
    scored = []
    for i in range(30):
        c = Candidate(sku=f"S{i}", title_ja=f"候補{i}", source_url="",
                      cost_incl_tax_jpy=600, weight_g=120, length_cm=12, width_cm=6,
                      height_cm=4, category="", market_price_usd=15.0,
                      competitor_count=3, has_demand_signal=True)
        scored.append(score_one(c, TW, ScoringPolicy.for_market(Market.SHOPEE_TW)))
    plan = plan_slots(Market.SHOPEE_TW, listed=495, preorder_listed=10, scored=scored)
    assert plan.can_add == 5
    assert any("スコアの高い順に絞って" in n for n in plan.notes)


def test_non_shopee_market_is_rejected():
    with pytest.raises(ValueError):
        plan_slots(Market.EBAY_US, listed=0, preorder_listed=0)


# --- 価格差の確認 -----------------------------------------------------------

def li(**kw):
    base = dict(sku="A", title="商品", current_price_usd=20.0,
                cost_incl_tax_jpy=1000, weight_g=200, length_cm=15,
                width_cm=10, height_cm=5)
    base.update(kw)
    return Listing(**base)


def test_out_of_stock_stops_the_listing_whatever_the_margin():
    """無在庫で最も高くつくのは、買えないものが売れること。"""
    rows = plan_reprice([li(available=False, current_price_usd=60.0)], TW)
    assert rows[0].action is RepriceAction.STOP
    assert rows[0].margin_now > 0.3          # 採算は良くても止める
    assert "在庫が無い" in rows[0].reason


def test_a_cost_increase_that_turns_the_listing_red_stops_it():
    """仕入元の値上げに気づかず据え置くと、赤字のまま売れ続ける。"""
    rows = plan_reprice([li(cost_incl_tax_jpy=3000, previous_cost_jpy=1000)], TW)
    assert rows[0].action is RepriceAction.STOP
    assert rows[0].cost_change_jpy == 2000


def test_a_thin_margin_becomes_a_raise():
    rows = plan_reprice([li(cost_incl_tax_jpy=1900)], TW,
                        RepricePolicy(min_margin=0.10))
    assert rows[0].action is RepriceAction.RAISE
    assert rows[0].required_price_usd > 20.0


def test_a_fat_margin_becomes_a_lower_opportunity():
    rows = plan_reprice([li(cost_incl_tax_jpy=200, current_price_usd=40.0)], TW)
    assert rows[0].action is RepriceAction.LOWER
    assert rows[0].required_price_usd < 40.0


def test_a_healthy_listing_is_held():
    rows = plan_reprice([li(cost_incl_tax_jpy=1000, current_price_usd=17.0)], TW)
    assert rows[0].action is RepriceAction.HOLD


def test_urgent_rows_come_first():
    """放置すると損が出るものだけ見れば足りる形にする。"""
    rows = plan_reprice([
        li(sku="OK", cost_incl_tax_jpy=1000, current_price_usd=17.0),
        li(sku="DEAD", available=False),
        li(sku="THIN", cost_incl_tax_jpy=2000),
    ], TW)
    assert rows[0].is_urgent
    assert rows[-1].action is RepriceAction.HOLD


def test_required_price_actually_hits_the_target_margin():
    """出す値上げ額が、狙った利益率をちょうど満たすこと。"""
    from blueocean.profit import compute
    from blueocean.shipping import Carrier, Parcel, estimate, MARKET_ZONE

    listing = li(cost_incl_tax_jpy=1900)
    rows = plan_reprice([listing], TW, RepricePolicy(target_margin=0.20, min_margin=0.10))
    ship = estimate(listing.parcel, MARKET_ZONE[Market.SHOPEE_TW], Carrier.SLS).jpy
    b = compute(rows[0].required_price_usd, 1900, TW, shipping_jpy=ship)
    assert b.margin == pytest.approx(0.20, abs=1e-6)


def test_load_listings_reads_availability_and_previous_cost(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text(
        "sku,title,current_price_usd,cost_incl_tax_jpy,weight_g,available,previous_cost_jpy\n"
        "A,あり,20,1000,200,yes,900\n"
        "B,なし,20,1000,200,no,\n",
        encoding="utf-8",
    )
    rows = load_listings(p)
    assert rows[0].available and rows[0].previous_cost_jpy == 900
    assert not rows[1].available and rows[1].previous_cost_jpy is None


def test_write_reprice_plan_can_skip_the_holds(tmp_path):
    rows = plan_reprice([
        li(sku="OK", cost_incl_tax_jpy=1000, current_price_usd=17.0),
        li(sku="DEAD", available=False),
    ], TW)
    assert write_reprice_plan(rows, tmp_path / "all.csv") == 2
    assert write_reprice_plan(rows, tmp_path / "u.csv", urgent_only=True) == 1


# --- 一括出品の下書き -------------------------------------------------------

def scored_rows(n):
    out = []
    for i in range(n):
        # 仕入は揃える（採算で落ちる行を混ぜると、枠の検証にならない）
        c = Candidate(sku=f"S{i}", title_ja=f"候補{i}", source_url="",
                      cost_incl_tax_jpy=600, weight_g=120, length_cm=12,
                      width_cm=6, height_cm=4, category="", market_price_usd=15.0,
                      competitor_count=3, has_demand_signal=True)
        out.append(score_one(c, TW, ScoringPolicy.for_market(Market.SHOPEE_TW)))
    return out


def test_mass_upload_respects_the_slot_limit(tmp_path):
    """枠が100点なら100点しか書き出さない。全部出そうとしない。"""
    p = tmp_path / "m.csv"
    assert write_mass_upload(scored_rows(150), p, TW, limit=100) == 100


def test_mass_upload_prices_from_the_target_margin(tmp_path):
    import csv as _csv

    p = tmp_path / "m.csv"
    write_mass_upload(scored_rows(1), p, TW, target_margin=0.20)
    row = next(iter(_csv.DictReader(p.open(encoding="utf-8"))))
    assert float(row["price"]) > 0
    assert float(row["weight_kg"]) == pytest.approx(0.120)
    assert int(row["days_to_ship"]) >= 3      # プレオーダーは3〜30日


def test_mass_upload_skips_rejected_candidates(tmp_path):
    c = Candidate(sku="X", title_ja="規制品", source_url="", cost_incl_tax_jpy=600,
                  weight_g=120, category="", market_price_usd=15.0,
                  competitor_count=3, is_restricted=True, restricted_reason="規制")
    s = score_one(c, TW, ScoringPolicy.for_market(Market.SHOPEE_TW))
    assert s.verdict is Verdict.EXCLUDE
    assert write_mass_upload([s], tmp_path / "m.csv", TW) == 0
