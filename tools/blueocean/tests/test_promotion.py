"""軸2の判定ロジックの検証。"""
from datetime import date, timedelta

from blueocean.models import Action, Observation
from blueocean.promotion import PromotionPolicy, decide, decide_all, stockout_alert, stockout_rate

BASE = date(2026, 1, 1)
P = PromotionPolicy()


def obs(days: int, **kw) -> Observation:
    return Observation(sku=kw.pop("sku", "S1"), listed_on=BASE,
                       observed_on=BASE + timedelta(days=days), **kw)


def test_sold_triggers_promote():
    assert decide(obs(5, sold=1), P).action is Action.PROMOTE


def test_watchers_within_window_trigger_promote():
    assert decide(obs(10, watchers=3), P).action is Action.PROMOTE


def test_watchers_outside_window_do_not_promote():
    """期間を過ぎたウォッチは購入意欲の証拠として弱いので昇格させない。"""
    assert decide(obs(40, watchers=3, views=20), P).action is not Action.PROMOTE


def test_views_without_watchers_means_reprice():
    assert decide(obs(20, views=80, watchers=0), P).action is Action.REPRICE


def test_no_views_means_retitle():
    d = decide(obs(35, views=4), P)
    assert d.action is Action.RETITLE
    assert "露出不足" in d.reason


def test_long_silence_means_drop():
    assert decide(obs(100, views=15, watchers=0), P).action is Action.DROP


def test_early_quiet_listing_is_kept():
    assert decide(obs(3, views=2), P).action is Action.KEEP


def test_sold_beats_every_other_signal():
    """販売実績は他のどのシグナルより優先されること。"""
    assert decide(obs(200, views=0, watchers=0, sold=2), P).action is Action.PROMOTE


def test_ordering_puts_promote_first():
    out = decide_all([obs(3, sku="keep"), obs(5, sku="win", sold=1),
                      obs(20, sku="rep", views=80)], P)
    assert out[0].sku == "win"
    assert out[-1].sku == "keep"


def test_stockout_rate_and_alert():
    assert stockout_rate(0, 0) == 0.0
    assert stockout_rate(100, 5) == 0.05
    assert stockout_alert(0.05) is not None
    assert stockout_alert(0.01) is None
    assert "2.79倍" in stockout_alert(0.10)
