"""データ更新の検証。

軸1が見ている数字（競合数・相場・為替・送料）は放っておいても動く。
判定結果には賞味期限があり、**前回からの変化こそが行動のトリガー**になる。
ここが壊れると「古い判定のまま仕入れる」という最も高くつく失敗が起きる。
"""
from datetime import date

import pytest

from blueocean.history import (
    Change,
    ChangeKind,
    DiffPolicy,
    Snapshot,
    append_snapshots,
    changes_since,
    history_of,
    latest_by_sku,
    load_snapshots,
    staleness_warning,
)
from blueocean.models import Market, Observation, Verdict
from blueocean.pipeline import run_axis1_with_history, split_latest
from blueocean.profit import DEFAULT_PROFILES
from blueocean.scoring import score_one
from blueocean.sources import MockSource

US = DEFAULT_PROFILES[Market.EBAY_US]


def snap(sku="S1", *, day="2026-08-01", verdict="blue", comp=3, price=200.0,
         cost=8000.0, cap=13000.0) -> Snapshot:
    return Snapshot(
        taken_on=day, sku=sku, title_ja=f"{sku}の商品", verdict=verdict, score=90.0,
        competitor_count=comp, market_price_usd=price, cost_incl_tax_jpy=cost,
        max_cost_jpy=cap, margin=0.25, shipping_jpy=2299.0,
    )


# --- 保存と読み出し ---------------------------------------------------------

def test_append_is_additive(tmp_path):
    """追記しかしないこと。過去の履歴を書き換えない。"""
    p = tmp_path / "h.jsonl"
    append_snapshots(p, [snap("A", day="2026-08-01")])
    append_snapshots(p, [snap("A", day="2026-08-08")])
    rows = load_snapshots(p)
    assert [r.taken_on for r in rows] == ["2026-08-01", "2026-08-08"]


def test_missing_history_is_not_an_error(tmp_path):
    """初回実行では履歴が無い。落ちずに空を返すこと。"""
    assert load_snapshots(tmp_path / "none.jsonl") == []


def test_broken_line_does_not_stop_the_run(tmp_path):
    """履歴の1行が壊れても運用は止めない。"""
    p = tmp_path / "h.jsonl"
    append_snapshots(p, [snap("A")])
    with p.open("a", encoding="utf-8") as f:
        f.write("{壊れた行\n")
    append_snapshots(p, [snap("B")])
    assert {r.sku for r in load_snapshots(p)} == {"A", "B"}


def test_latest_by_sku_excludes_today(tmp_path):
    """同じ日に2回走らせても「前回」は前の実行日のままであること。

    これが無いと、2回目の実行で差分が全部消える。
    """
    rows = [snap("A", day="2026-08-01", verdict="blue"),
            snap("A", day="2026-08-08", verdict="red")]
    prev = latest_by_sku(rows, before=date(2026, 8, 8))
    assert prev["A"].taken_on == "2026-08-01"


def test_history_of_is_chronological():
    rows = [snap("A", day="2026-08-08"), snap("B"), snap("A", day="2026-08-01")]
    assert [r.taken_on for r in history_of(rows, "A")] == ["2026-08-01", "2026-08-08"]


# --- 差分 -------------------------------------------------------------------

def kinds(changes: list[Change]) -> set[ChangeKind]:
    return {c.kind for c in changes}


def test_verdict_downgrade_is_detected():
    """BLUE → RED を見逃さないこと。これが最も重要な変化。"""
    prev = {"A": snap("A", verdict="blue")}
    cur = [snap("A", day="2026-08-08", verdict="red", comp=40)]
    ch = changes_since(prev, cur)
    assert ChangeKind.DOWNGRADE in kinds(ch)
    assert all(c.action for c in ch if c.kind is ChangeKind.DOWNGRADE)


def test_verdict_upgrade_is_detected():
    """見送っていた候補が買えるようになったことも拾う。"""
    prev = {"A": snap("A", verdict="thin")}
    cur = [snap("A", day="2026-08-08", verdict="blue")]
    assert ChangeKind.UPGRADE in kinds(changes_since(prev, cur))


def test_cap_breach_is_detected_even_without_verdict_change():
    """判定が変わらなくても採算は消える。仕入上限との関係を別に見ること。"""
    prev = {"A": snap("A", verdict="probe", cost=12000, cap=13000)}
    cur = [snap("A", day="2026-08-08", verdict="probe", cost=12000, cap=11000)]
    ch = changes_since(prev, cur)
    assert ChangeKind.CAP_BREACH in kinds(ch)


def test_cap_recovery_is_detected():
    prev = {"A": snap("A", verdict="thin", cost=12000, cap=11000)}
    cur = [snap("A", day="2026-08-08", verdict="thin", cost=12000, cap=13000)]
    assert ChangeKind.CAP_ROOM in kinds(changes_since(prev, cur))


def test_small_movements_are_ignored():
    """小さな揺れを毎回並べると、履歴を持つ意味が消える。"""
    prev = {"A": snap("A", comp=20, price=200.0)}
    cur = [snap("A", day="2026-08-08", comp=22, price=205.0)]
    assert changes_since(prev, cur) == []


def test_large_movements_are_reported():
    prev = {"A": snap("A", comp=4, price=200.0)}
    cur = [snap("A", day="2026-08-08", comp=30, price=150.0)]
    ch = kinds(changes_since(prev, cur))
    assert ChangeKind.COMPETITORS in ch
    assert ChangeKind.PRICE in ch


def test_thresholds_are_configurable():
    prev = {"A": snap("A", comp=20)}
    cur = [snap("A", day="2026-08-08", comp=22)]
    ch = changes_since(prev, cur, policy=DiffPolicy(competitor_abs=1, competitor_ratio=0.01))
    assert ChangeKind.COMPETITORS in kinds(ch)


def test_new_and_gone():
    prev = {"OLD": snap("OLD")}
    cur = [snap("NEW", day="2026-08-08")]
    ch = changes_since(prev, cur)
    assert kinds(ch) == {ChangeKind.NEW, ChangeKind.GONE}


def test_actionable_changes_sort_first():
    """要対応が先頭に来ること。人間は上から読む。"""
    prev = {"A": snap("A", verdict="blue", comp=4), "B": snap("B", verdict="blue")}
    cur = [snap("A", day="2026-08-08", verdict="red", comp=40),
           snap("C", day="2026-08-08")]
    ch = changes_since(prev, cur)
    assert ch[0].is_actionable
    assert not ch[-1].is_actionable


# --- 鮮度 -------------------------------------------------------------------

def test_stale_data_is_flagged():
    prev = {"A": snap("A", day="2026-08-01")}
    assert staleness_warning(prev, date(2026, 8, 20)) is not None
    assert staleness_warning(prev, date(2026, 8, 5)) is None


def test_no_warning_without_history():
    assert staleness_warning({}, date(2026, 8, 20)) is None


# --- 観測の時系列 -----------------------------------------------------------

def obs(sku, day, views, watchers=0, sold=0) -> Observation:
    return Observation(sku, date(2026, 7, 1), date.fromisoformat(day),
                       views, watchers, sold)


def test_split_latest_keeps_one_row_per_sku():
    """追記して育てたCSVでも、判定対象は最新の1行だけになること。"""
    rows = [obs("A", "2026-08-01", 10), obs("A", "2026-08-08", 30),
            obs("B", "2026-08-08", 5)]
    latest, previous = split_latest(rows)
    assert {o.sku for o in latest} == {"A", "B"}
    assert len(latest) == 2
    assert previous["A"].views == 10
    assert "B" not in previous  # 1回しか観測が無いSKUには前回が無い


def test_delta_is_reported_but_does_not_change_the_verdict():
    """前回比は表示のためのもの。判定ルールは累計値のまま変えない。"""
    from blueocean.promotion import decide

    cur = obs("A", "2026-08-08", 60, watchers=0)
    with_prev = decide(cur, previous=obs("A", "2026-08-01", 10))
    without = decide(cur)
    assert with_prev.action is without.action
    assert with_prev.delta is not None and without.delta is None
    assert with_prev.delta.views == 50


def test_stalled_listing_is_flagged():
    from blueocean.promotion import decide

    cur = obs("A", "2026-08-08", 21)
    d = decide(cur, previous=obs("A", "2026-08-01", 21))
    assert d.delta.is_stalled


# --- 統合 -------------------------------------------------------------------

def test_run_axis1_with_history_records_and_diffs(tmp_path, monkeypatch):
    """1回目は全件NEW、2回目は変化だけになること。"""
    from blueocean.models import Candidate

    h = tmp_path / "h.jsonl"

    def cands(comp: int):
        return [Candidate(sku="A", title_ja="t", source_url="", cost_incl_tax_jpy=8000,
                          weight_g=300, length_cm=15, width_cm=10, height_cm=6,
                          category="x", market_price_usd=200.0, competitor_count=comp,
                          has_demand_signal=True)]

    _, ch1, warn1 = run_axis1_with_history(
        cands(2), MockSource(), h, today=date(2026, 8, 1)
    )
    assert [c.kind for c in ch1] == [ChangeKind.NEW]
    assert warn1 is None

    _, ch2, warn2 = run_axis1_with_history(
        cands(40), MockSource(), h, today=date(2026, 8, 20)
    )
    assert ChangeKind.DOWNGRADE in kinds(ch2)
    assert warn2 is not None            # 19日空いたので鮮度の警告が出る
    assert len(load_snapshots(h)) == 2  # 追記されている


def test_no_record_leaves_history_untouched(tmp_path):
    from blueocean.models import Candidate

    h = tmp_path / "h.jsonl"
    c = [Candidate(sku="A", title_ja="t", source_url="", cost_incl_tax_jpy=8000,
                   weight_g=300, category="x", market_price_usd=200.0,
                   competitor_count=2, has_demand_signal=True)]
    run_axis1_with_history(c, MockSource(), h, today=date(2026, 8, 1), record=False)
    assert load_snapshots(h) == []


# --- 取り直し ---------------------------------------------------------------

def test_manual_values_are_never_refetched_by_default():
    """既定では、CSVに両方入っている候補は問い合わせない（API未契約でも動かすため）。"""
    from blueocean.models import Candidate
    from blueocean.pipeline import enrich

    c = [Candidate(sku="A", title_ja="t", source_url="", cost_incl_tax_jpy=8000,
                   weight_g=300, category="x", market_price_usd=200.0,
                   competitor_count=2)]
    assert enrich(c, MockSource()) == 0
    assert c[0].competitor_count == 2


def test_refresh_overrides_manual_values():
    """--refresh は手入力の値を取り直す。

    これが無いと、一度手で埋めた値は二度と更新されず、
    古い数字のまま BLUE と表示され続けることになる。
    """
    from blueocean.models import Candidate
    from blueocean.pipeline import enrich

    c = [Candidate(sku="A", title_ja="固定の検索語", source_url="",
                   cost_incl_tax_jpy=8000, weight_g=300, category="x",
                   market_price_usd=200.0, competitor_count=2)]
    assert enrich(c, MockSource(), refresh=True) == 1
    fresh = MockSource().snapshot("固定の検索語")
    assert c[0].competitor_count == fresh.competitor_count
    assert c[0].market_price_usd == fresh.median_price_usd
