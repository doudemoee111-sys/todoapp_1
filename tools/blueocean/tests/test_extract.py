"""抽出の設計と受け皿の検証。

巡回はしない。人が開いて人が採る。だからこのモジュールが担うのは
「何を、どんな条件で、どの項目まで採るか」と「採ってきたものの検品」。
**採る人が納得できない項目は埋まらない**ので、なぜ要るかまで持たせている。
"""
import pytest

from blueocean.extract import (
    FIELD_BY_KEY,
    FIELDS,
    ExtractSpec,
    Severity,
    Tier,
    read_worksheet,
    selling_side_urls,
    source_urls,
    summarize,
    to_candidates,
    validate,
    worksheet_columns,
    write_worksheet,
)
from blueocean.models import Market


def row(**kw):
    base = dict(sku="A-1", title_ja="Konica Hexanon AR 40mm F1.8",
                cost_incl_tax_jpy="9800", weight_g="180",
                length_cm="16", width_cm="12", height_cm="10",
                market_price_usd="185", competitor_count="2",
                has_demand_signal="yes", repeatable="yes", is_restricted="no")
    base.update(kw)
    return base


# --- 項目 -------------------------------------------------------------------

def test_every_field_says_why_it_is_needed():
    """列だけ渡されても人は埋められない。理由が要る。"""
    assert all(f.why for f in FIELDS)
    assert all(f.key and f.label for f in FIELDS)


def test_the_edge_fields_are_the_ones_export_needs():
    """国内せどりの定石に入っていないが、輸出では効く項目。

    容積重量（寸法）とリピート可能性がその中心。
    """
    edge = {f.key for f in FIELDS if f.tier is Tier.EDGE}
    assert {"length_cm", "width_cm", "height_cm"} <= edge   # 課金重量
    assert "repeatable" in edge                              # また買えるか
    assert "source_count" in edge                            # 仕入元の数
    assert "cost_range_jpy" in edge                          # 仕入の振れ幅
    assert "bundle_key" in edge                              # セット化の括り


def test_required_fields_are_exactly_what_axis1_needs():
    """必須は「無いと判定できない」もの。増やすと埋まらなくなる。"""
    req = {f.key for f in FIELDS if f.tier is Tier.REQUIRED}
    assert req == {"sku", "title_ja", "cost_incl_tax_jpy", "weight_g",
                   "market_price_usd", "competitor_count", "is_restricted"}


def test_minimal_worksheet_is_smaller():
    assert len(worksheet_columns(include=(Tier.REQUIRED,))) < len(worksheet_columns())


# --- URL --------------------------------------------------------------------

def test_urls_cover_both_sides():
    spec = ExtractSpec(name="t", keywords=["Nikon Ai-s 50mm"])
    buy = {l.source for l in source_urls(spec)}
    sell = {l.source for l in selling_side_urls(spec)}
    assert {"amazon_jp", "mercari", "yahoo_auction", "surugaya"} <= buy
    assert sell == {"ebay_active", "ebay_sold"}


def test_sold_url_is_always_offered():
    """出品中の価格は「売れなかった価格」。落札済みを必ず出す。"""
    links = selling_side_urls(ExtractSpec(name="t", keywords=["x"]))
    sold = next(l for l in links if l.source == "ebay_sold")
    assert "LH_Sold=1" in sold.url


def test_keywords_are_escaped():
    links = source_urls(ExtractSpec(name="t", keywords=["Konica Hexanon AR 40mm"]))
    assert all(" " not in l.url for l in links)


def test_amazon_department_narrows_the_search():
    with_dept = source_urls(ExtractSpec(name="t", keywords=["x"], category="カメラ"))
    without = source_urls(ExtractSpec(name="t", keywords=["x"]))
    a1 = next(l for l in with_dept if l.source == "amazon_jp")
    a0 = next(l for l in without if l.source == "amazon_jp")
    assert "i=photo" in a1.url and "i=" not in a0.url


def test_unknown_category_does_not_break_the_url():
    links = source_urls(ExtractSpec(name="t", keywords=["x"], category="存在しない部門"))
    assert next(l for l in links if l.source == "amazon_jp").url


def test_market_changes_the_ebay_site():
    eu = selling_side_urls(ExtractSpec(name="t", keywords=["x"], market=Market.EBAY_EU))
    assert "ebay.de" in eu[0].url


def test_urls_are_generated_per_keyword():
    spec = ExtractSpec(name="t", keywords=["a", "b"])
    assert {l.keyword for l in source_urls(spec)} == {"a", "b"}


# --- ワークシート -----------------------------------------------------------

def test_worksheet_carries_the_legend(tmp_path):
    """列の意味を同じファイルに書く。別紙にすると読まれない。"""
    p = tmp_path / "s.csv"
    write_worksheet(p)
    text = p.read_text(encoding="utf-8-sig")
    assert "管理番号" in text
    assert FIELD_BY_KEY["repeatable"].why[:12] in text


def test_legend_rows_are_skipped_on_read(tmp_path):
    p = tmp_path / "s.csv"
    write_worksheet(p)
    assert read_worksheet(p) == []


def test_a_real_row_matching_the_example_sku_is_not_dropped(tmp_path):
    """記入例の `LENS-001` は実在しうるSKU。

    1列だけ見て凡例と判定すると、本物のデータが消える（実際に消した）。
    """
    p = tmp_path / "s.csv"
    p.write_text(
        "sku,title_ja,cost_incl_tax_jpy,weight_g,market_price_usd,competitor_count\n"
        "LENS-001,Konica Hexanon AR 40mm F1.8,9800,180,185,2\n",
        encoding="utf-8",
    )
    rows = read_worksheet(p)
    assert len(rows) == 1 and rows[0]["sku"] == "LENS-001"


def test_blank_rows_are_skipped(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("sku,title_ja\nA,商品\n,\n", encoding="utf-8")
    assert len(read_worksheet(p)) == 1


# --- 検品 -------------------------------------------------------------------

def keys(issues, sev=None):
    return {i.field_key for i in issues if sev is None or i.severity is sev}


def test_a_complete_row_passes():
    assert validate([row()]) == []


def test_missing_required_fields_are_errors():
    issues = validate([row(market_price_usd="", competitor_count="")])
    assert {"market_price_usd", "competitor_count"} <= keys(issues, Severity.ERROR)


def test_missing_dimensions_is_a_warning_not_an_error():
    """寸法が無くても判定はできる。ただし送料が下振れする。"""
    issues = validate([row(length_cm="", width_cm="", height_cm="")])
    assert "length_cm" in keys(issues, Severity.WARN)
    assert not keys(issues, Severity.ERROR)


def test_missing_repeatable_is_flagged():
    """一点物かどうかは、出品枠が限られる市場で効く。"""
    issues = validate([row(repeatable="")])
    assert "repeatable" in keys(issues, Severity.WARN)


def test_duplicate_sku_is_an_error():
    issues = validate([row(sku="X"), row(sku="X")])
    assert any(i.severity is Severity.ERROR and "重複" in i.message for i in issues)


@pytest.mark.parametrize("word", ["リチウム", "化粧品", "象牙", "エアガン"])
def test_risky_words_are_flagged_for_confirmation(word):
    """当たったら止めるのではなく、確認を促す。"""
    issues = validate([row(title_ja=f"テスト {word} 入り")])
    assert any(i.field_key == "is_restricted" and word in i.message for i in issues)


def test_price_below_cost_is_caught_as_a_probable_typo():
    """相場が仕入を下回るのは、桁か通貨の取り違えがほとんど。"""
    issues = validate([row(cost_incl_tax_jpy="50000", market_price_usd="15")])
    assert any("桁か通貨" in i.message for i in issues)


def test_spec_limits_are_checked():
    spec = ExtractSpec(name="t", max_cost_jpy=5000, max_weight_g=500)
    issues = validate([row(cost_incl_tax_jpy="9800", weight_g="1800")], spec)
    assert {"cost_incl_tax_jpy", "weight_g"} <= keys(issues, Severity.WARN)


def test_non_numeric_values_are_errors():
    issues = validate([row(cost_incl_tax_jpy="約1万円")])
    assert keys(issues, Severity.ERROR)


def test_summarize_counts_by_severity():
    counts = summarize(validate([row(market_price_usd=""), row(sku="B", length_cm="")]))
    assert counts[Severity.ERROR] >= 1 and counts[Severity.WARN] >= 1


# --- 軸1への受け渡し ---------------------------------------------------------

def test_rows_become_candidates_axis1_can_judge():
    from blueocean.profit import DEFAULT_PROFILES
    from blueocean.scoring import score_one

    c = to_candidates([row()])[0]
    assert c.sku == "A-1" and c.market_price_usd == 185.0
    assert c.competitor_count == 2 and c.has_demand_signal
    assert (c.length_cm, c.width_cm, c.height_cm) == (16.0, 12.0, 10.0)
    assert score_one(c, DEFAULT_PROFILES[Market.EBAY_US]).verdict


def test_blank_optional_numbers_become_none_not_zero():
    """空欄を0にすると「相場0円」として判定に乗ってしまう。"""
    c = to_candidates([row(market_price_usd="", competitor_count="")])[0]
    assert c.market_price_usd is None and c.competitor_count is None


def test_japanese_yes_is_accepted():
    assert to_candidates([row(has_demand_signal="はい")])[0].has_demand_signal
