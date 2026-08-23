"""軸1の判定ロジックの検証。誤判定は在庫の死蔵に直結するので厳しめに見る。"""
import pytest

from blueocean.models import Candidate, Market, Verdict
from blueocean.profit import DEFAULT_PROFILES
from blueocean.scoring import ScoringPolicy, score_all, score_one

US = DEFAULT_PROFILES[Market.EBAY_US]
P = ScoringPolicy()


def mk(**kw) -> Candidate:
    base = dict(sku="S1", title_ja="テスト品", source_url="", cost_incl_tax_jpy=8000,
                weight_g=500, category="camera", competitor_count=3,
                market_price_usd=200.0, has_demand_signal=True)
    base.update(kw)
    return Candidate(**base)


def test_blue_requires_low_competition_and_demand():
    s = score_one(mk(competitor_count=3, has_demand_signal=True), US, P)
    assert s.verdict is Verdict.BLUE


def test_zero_competitors_without_demand_is_probe_not_blue():
    """競合ゼロを安易に BLUE にしないこと。売れないから誰も出していない可能性がある。"""
    s = score_one(mk(competitor_count=0, has_demand_signal=False), US, P)
    assert s.verdict is Verdict.PROBE
    assert any("需要の裏付けが無い" in r for r in s.reasons)


def test_low_competition_without_demand_stays_probe():
    s = score_one(mk(competitor_count=2, has_demand_signal=False), US, P)
    assert s.verdict is Verdict.PROBE


def test_crowded_is_red():
    s = score_one(mk(competitor_count=45), US, P)
    assert s.verdict is Verdict.RED


def test_over_budget_is_thin():
    """仕入が上限を超えたら、競合が少なくても採算割れとして弾くこと。"""
    s = score_one(mk(cost_incl_tax_jpy=20000, competitor_count=1), US, P)
    assert s.verdict is Verdict.THIN
    assert s.profit is not None and s.profit.margin < P.target_margin


def test_restricted_is_excluded_before_anything_else():
    """規制品は採算より先に落とすこと。"""
    s = score_one(mk(is_restricted=True, restricted_reason="リチウム電池内蔵"), US, P)
    assert s.verdict is Verdict.EXCLUDE
    assert "リチウム電池内蔵" in s.reasons[0]


def test_heavy_item_excluded():
    s = score_one(mk(weight_g=5000), US, P)
    assert s.verdict is Verdict.EXCLUDE


def test_cheap_item_excluded():
    s = score_one(mk(market_price_usd=15.0), US, P)
    assert s.verdict is Verdict.EXCLUDE


def test_missing_market_price_excluded():
    s = score_one(mk(market_price_usd=None), US, P)
    assert s.verdict is Verdict.EXCLUDE


def test_ordering_puts_blue_first():
    items = [mk(sku="red", competitor_count=50), mk(sku="blue", competitor_count=2),
             mk(sku="excl", is_restricted=True)]
    out = score_all(items, US, P)
    assert out[0].candidate.sku == "blue"
    assert out[-1].candidate.sku == "excl"


def test_fewer_competitors_scores_higher():
    a = score_one(mk(sku="a", competitor_count=1), US, P)
    b = score_one(mk(sku="b", competitor_count=20), US, P)
    assert a.score > b.score


def test_every_result_explains_itself():
    """判定には必ず理由が付くこと。ブラックボックスにしない。"""
    for c in [mk(), mk(competitor_count=50), mk(is_restricted=True), mk(cost_incl_tax_jpy=99999)]:
        assert score_one(c, US, P).reasons


# --- 送料が採算に効くこと -----------------------------------------------------

def test_bulky_light_candidate_is_excluded_by_volumetric_weight():
    """実重量は軽いが嵩張る商品は、容積重量で除外されること。

    実重量だけを見ていると通ってしまい、送料で利益が消える。
    """
    c = Candidate(
        sku="BULK-1", title_ja="外箱付きフィギュア", source_url="",
        cost_incl_tax_jpy=8000, weight_g=900,
        length_cm=30, width_cm=25, height_cm=20,  # 容積重量 2,500g
        category="figure", market_price_usd=210, competitor_count=2,
        has_demand_signal=True,
    )
    s = score_one(c, US)
    assert s.verdict is Verdict.EXCLUDE
    assert any("容積重量" in r for r in s.reasons)


def test_heavier_candidate_gets_a_lower_purchase_cap():
    """同じ売価でも重い方が仕入上限は下がること。送料が採算に効いている証拠。"""
    def cap(weight_g: int) -> float:
        c = Candidate(
            sku="W", title_ja="t", source_url="", cost_incl_tax_jpy=1000,
            weight_g=weight_g, length_cm=15, width_cm=10, height_cm=6,
            category="x", market_price_usd=200, competitor_count=2,
            has_demand_signal=True,
        )
        return score_one(c, US).max_cost_jpy

    assert cap(1500) < cap(300)


# --- 何がこの判定を分けているか -----------------------------------------------

def test_headroom_names_the_three_variables():
    """軸1の判定を動かす変数は3つだけ。仕入値・競合数・相場。

    このうち自分で動かせるのは仕入値だけで、あとの2つは他人が決める。
    """
    s = score_one(mk(cost_incl_tax_jpy=8000, competitor_count=4), US)
    h = s.headroom
    assert h is not None
    assert h.cost_room_jpy == pytest.approx(s.max_cost_jpy - 8000)
    assert h.competitor_room == P.red_min_competitors - 4
    assert h.price_floor_usd is not None and h.price_room_usd > 0


def test_price_floor_is_the_point_where_the_cost_stops_fitting():
    """相場がこの値まで下がると、いまの仕入値では採算に乗らなくなる。"""
    from blueocean.profit import max_cost_for_margin

    s = score_one(mk(cost_incl_tax_jpy=8000), US)
    floor = s.headroom.price_floor_usd
    cap_at_floor = max_cost_for_margin(
        floor, P.target_margin, US, shipping_jpy=s.profit.shipping_jpy
    )
    assert cap_at_floor == pytest.approx(8000, abs=1.0)


def test_flip_hint_tells_you_what_to_change():
    """「なぜこの判定か」より「何が変われば変わるか」のほうが行動につながる。"""
    assert "競合があと" in score_one(mk(competitor_count=3), US).flip_hint
    assert "仕入をあと" in score_one(mk(cost_incl_tax_jpy=60000), US).flip_hint
    assert "自分では動かせない" in score_one(mk(competitor_count=40), US).flip_hint
    assert "軸2で確かめる" in score_one(mk(competitor_count=2, has_demand_signal=False),
                                        US).flip_hint


def test_excluded_candidates_have_no_headroom():
    """除外品に「あといくら下げれば」は無意味なので出さない。"""
    s = score_one(mk(is_restricted=True, restricted_reason="規制"), US)
    assert s.headroom is None
    assert s.flip_hint == ""
