"""軸1の判定ロジックの検証。誤判定は在庫の死蔵に直結するので厳しめに見る。"""
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
