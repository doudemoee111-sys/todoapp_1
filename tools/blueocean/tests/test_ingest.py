"""eBayレポートの取り込みの検証。

軸2の観測CSVに必要な列は、Seller Hub の「All active listings」レポートに全部入っている。
手で詰め替える作業は本来いらない。ただし列名は環境や時期で揺れ、日付は
``Aug-23-2026 10:12:33 PDT`` のような形で来るので、そこを吸収できているかを見る。
"""
from datetime import date

import pytest

from blueocean.ingest import (
    from_ebay_report,
    merge_observations,
    parse_date,
    read_report,
    write_observations,
)
from blueocean.models import Observation
from blueocean.pipeline import load_observations, split_latest

TODAY = date(2026, 8, 23)


def row(**kw):
    base = {"Item number": "396012345678", "Title": "商品", "Custom label": "SKU-1",
            "Start Date": "Jul-20-2026 10:12:33 PDT", "Views": "142",
            "Watchers": "5", "Sold quantity": "1"}
    base.update(kw)
    return base


# --- 列名の揺れ -------------------------------------------------------------

def test_standard_columns_map_straight_through():
    o = from_ebay_report([row()], observed_on=TODAY).observations[0]
    assert (o.sku, o.title, o.views, o.watchers, o.sold) == ("SKU-1", "商品", 142, 5, 1)
    assert o.listed_on == date(2026, 7, 20)
    assert o.observed_on == TODAY
    assert o.days_listed == 34


@pytest.mark.parametrize("sku_col", ["Custom label", "Custom Label (SKU)", "customlabel", "SKU"])
def test_sku_column_aliases(sku_col):
    r = {k: v for k, v in row().items() if k != "Custom label"}
    r[sku_col] = "SKU-9"
    assert from_ebay_report([r], observed_on=TODAY).observations[0].sku == "SKU-9"


@pytest.mark.parametrize("col,alias", [
    ("Views", "View count"), ("Watchers", "Watch count"), ("Sold quantity", "Quantity sold"),
    ("Start Date", "Start time"),
])
def test_other_column_aliases(col, alias):
    r = {k: v for k, v in row().items() if k != col}
    r[alias] = row()[col]
    assert from_ebay_report([r], observed_on=TODAY).observations


def test_item_number_is_used_when_there_is_no_custom_label():
    """SKUを付けていない出品でも取り込めること。突き合わせは効かなくなるが落とさない。"""
    o = from_ebay_report([row(**{"Custom label": ""})], observed_on=TODAY).observations[0]
    assert o.sku == "396012345678"


def test_rows_without_any_identifier_are_reported_not_silently_dropped():
    r = from_ebay_report([row(**{"Custom label": "", "Item number": ""})], observed_on=TODAY)
    assert r.observations == []
    assert r.skipped_no_sku == 1
    assert any("カスタムラベル" in w for w in r.warnings)


def test_missing_columns_are_reported():
    """列が無いことを黙って0で埋めない。取り直せと言う。"""
    r = from_ebay_report([{"Item number": "1", "Title": "t", "Start Date": "2026-08-01"}],
                         observed_on=TODAY)
    assert "Views" in r.missing_columns and "Watchers" in r.missing_columns
    assert any("All active listings" in w for w in r.warnings)


# --- 日付 -------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Jul-20-2026 10:12:33 PDT", date(2026, 7, 20)),
    ("2026-07-20", date(2026, 7, 20)),
    ("07/20/2026", date(2026, 7, 20)),
    ("Jul 20, 2026", date(2026, 7, 20)),
    ("20-Jul-2026", date(2026, 7, 20)),
    ("2026-07-20T10:12:33", date(2026, 7, 20)),
])
def test_date_formats(text, expected):
    assert parse_date(text) == expected


def test_unreadable_date_is_skipped_and_counted():
    r = from_ebay_report([row(**{"Start Date": "いつか"})], observed_on=TODAY)
    assert r.observations == [] and r.skipped_no_date == 1


def test_blank_date_is_not_guessed():
    assert parse_date("") is None


# --- 数値 -------------------------------------------------------------------

def test_thousand_separators_and_blanks():
    o = from_ebay_report([row(Views="1,234", Watchers="", **{"Sold quantity": "2.0"})],
                         observed_on=TODAY).observations[0]
    assert (o.views, o.watchers, o.sold) == (1234, 0, 2)


# --- ファイル読み込み -------------------------------------------------------

def test_preamble_lines_are_skipped(tmp_path):
    """Seller Hub のCSVは先頭に注記行が入ることがある。"""
    p = tmp_path / "r.csv"
    p.write_text(
        '"eBay Seller Hub: All active listings report."\n'
        "Item number,Title,Custom label,Views,Watchers,Sold quantity,Start Date\n"
        "1,商品,SKU-1,10,2,0,2026-08-01\n",
        encoding="utf-8",
    )
    assert read_report(p, observed_on=TODAY).observations[0].sku == "SKU-1"


def test_bom_is_handled(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text(
        "Item number,Title,Custom label,Views,Watchers,Sold quantity,Start Date\n"
        "1,商品,SKU-1,10,2,0,2026-08-01\n",
        encoding="utf-8-sig",
    )
    assert read_report(p, observed_on=TODAY).observations


# --- 追記 -------------------------------------------------------------------

def obs(sku, day, views):
    return Observation(sku, date(2026, 7, 1), date.fromisoformat(day), views, 0, 0)


def test_same_sku_and_day_is_overwritten_not_duplicated():
    """取り直しても行が二重にならないこと。"""
    merged = merge_observations([obs("A", "2026-08-23", 10)], [obs("A", "2026-08-23", 30)])
    assert len(merged) == 1 and merged[0].views == 30


def test_a_different_day_is_kept_as_a_new_row():
    """日付が違えば残す。それが前回比の材料になる。"""
    merged = merge_observations([obs("A", "2026-08-16", 10)], [obs("A", "2026-08-23", 30)])
    assert len(merged) == 2
    latest, previous = split_latest(merged)
    assert latest[0].views == 30 and previous["A"].views == 10


def test_merge_is_sorted_by_date_then_sku():
    merged = merge_observations(
        [obs("B", "2026-08-23", 1), obs("A", "2026-08-16", 1)],
        [obs("A", "2026-08-23", 1)],
    )
    assert [(o.sku, o.observed_on.isoformat()) for o in merged] == [
        ("A", "2026-08-16"), ("A", "2026-08-23"), ("B", "2026-08-23")]


# --- 往復 -------------------------------------------------------------------

def test_written_file_is_readable_by_axis2(tmp_path):
    """書き出した観測CSVを、軸2がそのまま読めること。ここが繋がらないと意味がない。"""
    r = from_ebay_report([row(), row(**{"Custom label": "SKU-2", "Title": "別の商品"})],
                         observed_on=TODAY)
    p = tmp_path / "obs.csv"
    assert write_observations(r.observations, p) == 2

    back = load_observations(p)
    assert {o.sku for o in back} == {"SKU-1", "SKU-2"}
    assert back[0].title == "商品"           # 商品名が残る（SKUだけでは動けない）
    assert back[0].observed_on == TODAY


def test_weekly_append_produces_deltas(tmp_path):
    """毎週取り込むと、前回比が出せる形になること。"""
    p = tmp_path / "obs.csv"
    week1 = from_ebay_report([row(Views="100", Watchers="2")], observed_on=date(2026, 8, 16))
    write_observations(week1.observations, p)

    week2 = from_ebay_report([row(Views="142", Watchers="5")], observed_on=date(2026, 8, 23))
    write_observations(merge_observations(load_observations(p), week2.observations), p)

    from blueocean.pipeline import run_axis2

    decisions, _ = run_axis2(load_observations(p))
    d = decisions[0]
    assert d.delta is not None
    assert (d.delta.views, d.delta.watchers, d.delta.days) == (42, 3, 7)
