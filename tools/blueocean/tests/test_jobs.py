"""抽出条件の保存と再実行の検証。

条件をそのつど手で打っていると、何の条件で抜いたのか思い出せず、
1文字違えば前回と比較できなくなる。**同じ条件で回すからこそ差分が意味を持つ**ので、
条件がファイルに固定されていることを担保する。
"""
import json
from datetime import date

import pytest

from blueocean.history import ChangeKind, load_snapshots
from blueocean.jobs import Job, JobError, load_jobs, run_job
from blueocean.sources import MockSource
from blueocean.sources.base import MarketDataSource, MarketSnapshot


class Fixed(MarketDataSource):
    """競合数を差し替えられる情報源。2回目の実行で環境が変わった状況を作る。"""

    def __init__(self, n=3, price=200.0):
        self.n, self.price = n, price

    def snapshot(self, query):
        return MarketSnapshot(query, self.n, self.price, self.price * .8, self.price * 1.3)


def write_cfg(tmp_path, cfg) -> str:
    p = tmp_path / "jobs.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return str(p)


def candidates_csv(tmp_path, cost=9800, comp=3) -> str:
    p = tmp_path / "c.csv"
    p.write_text(
        "sku,title_ja,cost_incl_tax_jpy,weight_g,length_cm,width_cm,height_cm,"
        "market_price_usd,competitor_count,has_demand_signal\n"
        f"A,テスト品,{cost},180,16,12,10,200,{comp},yes\n",
        encoding="utf-8",
    )
    return str(p)


# --- 読み込み ---------------------------------------------------------------

def test_dict_form_uses_the_key_as_the_name(tmp_path):
    path = write_cfg(tmp_path, {"my-job": {"label": "テスト"}})
    jobs = load_jobs(path)
    assert list(jobs) == ["my-job"]
    assert jobs["my-job"].title == "テスト"


def test_list_form_is_accepted(tmp_path):
    path = write_cfg(tmp_path, [{"name": "a"}, {"name": "b"}])
    assert set(load_jobs(path)) == {"a", "b"}


def test_single_job_form_is_accepted(tmp_path):
    assert list(load_jobs(write_cfg(tmp_path, {"name": "solo"}))) == ["solo"]


def test_unknown_key_is_an_error_not_a_silent_default(tmp_path):
    """綴り違いを黙って無視すると、意図と違う条件で抽出し続けることになる。"""
    path = write_cfg(tmp_path, {"a": {"target_margins": 0.3}})
    with pytest.raises(JobError) as e:
        load_jobs(path)
    assert "target_margins" in str(e.value)


def test_missing_name_is_an_error(tmp_path):
    with pytest.raises(JobError):
        load_jobs(write_cfg(tmp_path, [{"label": "名無し"}]))


def test_label_falls_back_to_name(tmp_path):
    assert load_jobs(write_cfg(tmp_path, {"name": "x"}))["x"].title == "x"


# --- 走査 -------------------------------------------------------------------

def test_scan_writes_the_template_and_the_sheet(tmp_path):
    out, sheet = tmp_path / "o.csv", tmp_path / "s.html"
    job = Job(name="j", scan={"genre": "anime_figure", "mode": "set", "limit": 6,
                              "out": str(out), "sheet": str(sheet)})
    r = run_job(job, MockSource())
    assert r.scanned == 6
    assert out.exists() and sheet.exists()
    assert [str(out), str(sheet)] == r.written


def test_scan_creates_missing_directories(tmp_path):
    out = tmp_path / "deep" / "dir" / "o.csv"
    run_job(Job(name="j", scan={"keywords": ["A"], "out": str(out)}), MockSource())
    assert out.exists()


def test_scan_needs_a_source_of_keywords(tmp_path):
    with pytest.raises(JobError) as e:
        run_job(Job(name="j", scan={"out": str(tmp_path / "o.csv")}), MockSource())
    assert "keywords" in str(e.value)


def test_unknown_genre_is_an_error():
    with pytest.raises(JobError):
        run_job(Job(name="j", scan={"genre": "存在しない"}), MockSource())


def test_assume_parcel_flows_into_the_budget():
    """荷姿の仮定が効いていること。重いほど予算は下がる。"""
    light = run_job(Job(name="j", scan={"keywords": ["A"],
                                        "assume": {"weight_g": 300}}), Fixed())
    heavy = run_job(Job(name="j", scan={"keywords": ["A"],
                                        "assume": {"weight_g": 1900}}), Fixed())
    assert light.scanned == heavy.scanned == 1


# --- 判定と履歴 -------------------------------------------------------------

def test_judge_writes_the_plan(tmp_path):
    job = Job(name="j", judge={"candidates": candidates_csv(tmp_path),
                               "out": str(tmp_path / "plan.csv")})
    r = run_job(job, Fixed(n=3))
    assert r.judged == 1 and r.listable == 1
    assert (tmp_path / "plan.csv").exists()


def test_listable_is_only_counted_when_a_plan_is_written(tmp_path):
    """出力先を指定しなければ書き出さないし、件数も数えない。"""
    r = run_job(Job(name="j", judge={"candidates": candidates_csv(tmp_path)}), Fixed(n=3))
    assert r.judged == 1 and r.listable == 0 and r.written == []


def test_judge_needs_candidates():
    with pytest.raises(JobError) as e:
        run_job(Job(name="j", judge={"out": "x.csv"}), MockSource())
    assert "candidates" in str(e.value)


def test_second_run_reports_only_what_changed(tmp_path):
    """同じ条件で回すからこそ、2回目に差分だけが出る。"""
    hist = tmp_path / "h.jsonl"
    job = Job(name="j", judge={"candidates": candidates_csv(tmp_path, comp=3),
                               "history": str(hist), "refresh": True})

    first = run_job(job, Fixed(n=3), today=date(2026, 8, 1))
    assert [c.kind for c in first.changes] == [ChangeKind.NEW]
    assert first.stale_warning is None

    second = run_job(job, Fixed(n=45), today=date(2026, 8, 20))
    kinds = {c.kind for c in second.changes}
    assert ChangeKind.DOWNGRADE in kinds
    assert second.actionable_changes
    assert second.stale_warning is not None      # 19日空いた
    assert len(load_snapshots(hist)) == 2


def test_no_record_leaves_the_history_alone(tmp_path):
    hist = tmp_path / "h.jsonl"
    job = Job(name="j", judge={"candidates": candidates_csv(tmp_path),
                               "history": str(hist)})
    run_job(job, MockSource(), today=date(2026, 8, 1), record=False)
    assert load_snapshots(hist) == []


def test_refresh_flag_overrides_the_csv_values(tmp_path):
    """CSVに競合数が入っていても、refresh なら取り直すこと。

    これが無いと、一度書いた値のまま何度回しても結果が変わらない。
    """
    csv_path = candidates_csv(tmp_path, comp=3)
    stale = run_job(Job(name="j", judge={"candidates": csv_path,
                                         "out": str(tmp_path / "a.csv")}), Fixed(n=45))
    fresh = run_job(Job(name="j", judge={"candidates": csv_path, "refresh": True,
                                         "out": str(tmp_path / "b.csv")}), Fixed(n=45))
    assert stale.listable == 1     # 競合3件のまま判定される
    assert fresh.listable == 0     # 45件に取り直されて見送りになる


# --- 条件そのもの -----------------------------------------------------------

def test_policy_comes_from_the_job(tmp_path):
    job = load_jobs(write_cfg(tmp_path, {"a": {"target_margin": 0.35,
                                               "fx_jpy_per_usd": 130.0}}))["a"]
    p = job.policy()
    assert p.target_margin == 0.35
    assert p.fx_jpy_per_usd == 130.0


def test_tax_exemption_is_part_of_the_saved_condition(tmp_path):
    job = load_jobs(write_cfg(tmp_path, {"a": {"taxable": False}}))["a"]
    assert job.common()["tax"].is_taxable_entity is False


def test_both_phases_run_in_order(tmp_path):
    job = Job(name="j",
              scan={"keywords": ["A"], "out": str(tmp_path / "t.csv")},
              judge={"candidates": candidates_csv(tmp_path)})
    r = run_job(job, MockSource())
    assert r.scanned == 1 and r.judged == 1
