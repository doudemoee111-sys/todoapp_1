"""キーワード走査の検証。

バッチ判定は「候補リストにあるものしか評価できない」という構造的な限界を持つ。
リストの作り方が分からなければツール全体が動かないので、
**リストを作る側**をここで担保する。
"""
import pytest

from blueocean.discovery import (
    KeywordResult,
    Opening,
    ScanPolicy,
    load_keywords,
    scan_all,
    scan_one,
    write_candidate_template,
)
from blueocean.models import Market
from blueocean.profit import DEFAULT_PROFILES
from blueocean.scoring import ScoringPolicy
from blueocean.shipping import Parcel
from blueocean.sources.base import MarketDataSource, MarketSnapshot

US = DEFAULT_PROFILES[Market.EBAY_US]


class FixedSource(MarketDataSource):
    """走査の判定だけを見たいので、返り値を固定する。"""

    def __init__(self, table: dict[str, MarketSnapshot]):
        self.table = table
        self.calls: list[str] = []

    def snapshot(self, query: str) -> MarketSnapshot:
        self.calls.append(query)
        return self.table[query]


def snap(q, n, price):
    return MarketSnapshot(q, n, price, price and price * 0.8, price and price * 1.3)


def src(**kw):
    return FixedSource({q: snap(q, n, p) for q, (n, p) in kw.items()})


# --- キーワードの読み込み ---------------------------------------------------

def test_keywords_file_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "k.txt"
    p.write_text("# コメント\n\nNikon Ai-s 50mm  # 行末コメント\n  \nPilot 823\n", encoding="utf-8")
    assert load_keywords(p) == ["Nikon Ai-s 50mm", "Pilot 823"]


# --- 判定 -------------------------------------------------------------------

def test_few_competitors_is_open():
    s = src(A=(3, 200.0))
    r = scan_one("A", s, US)
    assert r.opening is Opening.OPEN
    assert r.is_hunt_worthy


def test_zero_competitors_is_probe_not_open():
    """競合ゼロを「空き」と言い切らないこと。

    誰も出していないのは、需要が無いからかもしれない。ここを OPEN にすると
    売れないものを探しに行くことになる。軸1と同じ扱いに揃えてある。
    """
    r = scan_one("A", src(A=(0, 200.0)), US)
    assert r.opening is Opening.PROBE
    assert r.is_hunt_worthy  # 探す価値はある。ただし少量で試す前提


def test_many_competitors_is_crowded():
    r = scan_one("A", src(A=(45, 200.0)), US)
    assert r.opening is Opening.CROWDED
    assert not r.is_hunt_worthy


def test_low_price_is_rejected_before_competition():
    """低単価は競合が少なくても対象外。手数料と送料に食われる。"""
    r = scan_one("A", src(A=(1, 12.0)), US)
    assert r.opening is Opening.LOW_VALUE
    assert not r.is_hunt_worthy


def test_missing_price_is_reported_not_guessed():
    r = scan_one("A", FixedSource({"A": MarketSnapshot("A", 4, None, None, None)}), US)
    assert r.opening is Opening.NO_DATA
    assert r.max_cost_jpy == 0.0


# --- 予算（走査の実用上の中心） ---------------------------------------------

def test_budget_is_the_purchase_cap():
    """走査の出力で最も使うのは「国内でいくらまで出せるか」。"""
    r = scan_one("A", src(A=(3, 200.0)), US)
    assert r.max_cost_jpy > 0
    assert r.required_multiple > 1.0


def test_heavier_assumption_lowers_the_budget():
    """荷姿の仮定が重いほど予算は下がること。送料が効いている証拠。"""
    light = scan_one("A", src(A=(3, 200.0)), US, assume=Parcel(300, 15, 10, 6))
    heavy = scan_one("A", src(A=(3, 200.0)), US, assume=Parcel(1800, 30, 25, 15))
    assert heavy.max_cost_jpy < light.max_cost_jpy


def test_assumption_is_disclosed_in_the_note():
    """仮定であることを隠さない。現物が見つかったら実寸で引き直す。"""
    r = scan_one("A", src(A=(3, 200.0)), US, assume=Parcel(400, 20, 15, 10))
    assert "仮定" in r.note


# --- 並び順と出力 -----------------------------------------------------------

def test_worthy_keywords_come_first_ordered_by_budget():
    """競合が少なく予算が大きいものが最良の狩り場。それが先頭に来ること。"""
    s = src(SMALL=(2, 60.0), BIG=(2, 400.0), CROWD=(50, 400.0))
    rs = scan_all(["SMALL", "BIG", "CROWD"], s, US)
    assert [r.keyword for r in rs] == ["BIG", "SMALL", "CROWD"]


def test_every_keyword_is_queried_once():
    s = src(A=(2, 200.0), B=(2, 200.0))
    scan_all(["A", "B"], s, US)
    assert sorted(s.calls) == ["A", "B"]


def test_template_feeds_axis1(tmp_path):
    """走査の出力が、そのまま軸1の入力として読めること。

    ここが繋がっていないと「探す」と「判定する」が分断される。
    """
    from blueocean.pipeline import load_candidates

    rs = scan_all(["A", "B"], src(A=(2, 200.0), B=(50, 200.0)), US)
    out = tmp_path / "cand.csv"
    n = write_candidate_template(rs, out)
    assert n == 1  # 過密のBは落ちる

    cands = load_candidates(out)
    assert cands[0].title_ja == "A"
    assert cands[0].market_price_usd == 200.0
    assert cands[0].competitor_count == 2
    assert cands[0].cost_incl_tax_jpy == 0.0  # 仕入値は国内で見つけてから埋める


def test_template_can_include_everything(tmp_path):
    rs = scan_all(["A", "B"], src(A=(2, 200.0), B=(50, 200.0)), US)
    assert write_candidate_template(rs, tmp_path / "c.csv", only_worthy=False) == 2


# --- 軸1との整合 ------------------------------------------------------------

def test_policy_is_derived_from_the_axis1_policy():
    """走査と判定で閾値がずれないこと。ずれると走査の結果が判定で覆る。"""
    sp = ScoringPolicy(target_margin=0.25, blue_max_competitors=8,
                       red_min_competitors=40, min_price_usd=50.0)
    p = ScanPolicy.from_scoring(sp)
    assert (p.target_margin, p.open_max_competitors, p.crowded_min_competitors,
            p.min_price_usd) == (0.25, 8, 40, 50.0)


def test_scan_budget_matches_axis1_cap():
    """走査で出した予算と、軸1の仕入上限が一致すること。"""
    from blueocean.models import Candidate
    from blueocean.scoring import score_one

    r = scan_one("A", src(A=(3, 200.0)), US, assume=Parcel(400, 20, 15, 10))
    c = Candidate(sku="A", title_ja="A", source_url="", cost_incl_tax_jpy=1000,
                  weight_g=400, length_cm=20, width_cm=15, height_cm=10,
                  category="", market_price_usd=200.0, competitor_count=3,
                  has_demand_signal=True)
    assert score_one(c, US).max_cost_jpy == pytest.approx(r.max_cost_jpy, abs=1.0)


# --- 雛形をそのまま判定に流したときの安全性 ---------------------------------

def test_template_row_never_becomes_blue():
    """仕入値が空のまま BLUE になってはいけない。

    仕入値0を「タダで買える」と解釈すると、実体のない候補が最優先で並ぶ。
    """
    from blueocean.models import Candidate, Verdict
    from blueocean.scoring import score_one

    c = Candidate(sku="SCAN-001", title_ja="A", source_url="", cost_incl_tax_jpy=0,
                  weight_g=0, category="", market_price_usd=200.0,
                  competitor_count=2, has_demand_signal=True)
    s = score_one(c, US)
    assert s.verdict is Verdict.PROBE
    assert any("仕入値が未入力" in r for r in s.reasons)
    assert any("重量が未入力" in r for r in s.reasons)
