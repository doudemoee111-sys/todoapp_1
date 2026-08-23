"""現物照合（写真と検索URL）の検証。

型番だけを頼りに国内を回ると、世代違い・マイナーチェンジ違いを掴む事故が起きる。
買ってから気づいたのでは遅いので、探しに行く前に見た目を確かめる導線を必ず持たせる。
"""
from blueocean.contactsheet import from_scan, from_scored, render, write
from blueocean.discovery import scan_all
from blueocean.models import Candidate, Market, Verdict
from blueocean.profit import DEFAULT_PROFILES
from blueocean.scoring import score_one
from blueocean.sources import MockSource
from blueocean.sources.base import MarketDataSource, MarketSnapshot
from blueocean.sources.ebay_browse import EbayBrowseSource, search_url

US = DEFAULT_PROFILES[Market.EBAY_US]


# --- 検索URL ----------------------------------------------------------------

def test_search_url_is_escaped():
    u = search_url("Konica Hexanon AR 40mm F1.8")
    assert u.startswith("https://www.ebay.com/sch/i.html?_nkw=")
    assert " " not in u


def test_search_url_follows_the_marketplace():
    assert "ebay.com.au" in search_url("x", "EBAY_AU")
    assert "ebay.de" in search_url("x", "EBAY_DE")
    assert "ebay.com" in search_url("x", "UNKNOWN_ID")  # 未知は米国に落とす


def test_sold_url_shows_completed_listings():
    """落札済みの写真と価格が見たい場面のほうが多い。"""
    u = search_url("x", sold=True)
    assert "LH_Sold=1" in u and "LH_Complete=1" in u


# --- 画像の抽出 -------------------------------------------------------------

def test_images_come_from_image_or_thumbnail():
    payload = {"total": 3, "itemSummaries": [
        {"price": {"value": "100"}, "image": {"imageUrl": "https://i/a.jpg"}},
        {"price": {"value": "120"}, "thumbnailImages": [{"imageUrl": "https://i/b.jpg"}]},
        {"price": {"value": "140"}},  # 画像なしの出品もある
    ]}
    snap = EbayBrowseSource._parse("q", payload)
    assert snap.image_urls == ("https://i/a.jpg", "https://i/b.jpg")
    assert snap.competitor_count == 3


def test_image_count_is_capped():
    payload = {"total": 50, "itemSummaries": [
        {"image": {"imageUrl": f"https://i/{i}.jpg"}} for i in range(20)
    ]}
    assert len(EbayBrowseSource._parse("q", payload, max_images=6).image_urls) == 6


def test_mock_source_never_invents_image_urls():
    """実在しないURLを返すと、現物照合の役に立たないどころか害になる。"""
    snap = MockSource().snapshot("何か")
    assert snap.image_urls == ()
    assert snap.search_url.startswith("https://www.ebay.com/")


# --- 判定結果への伝播 -------------------------------------------------------

class ImageSource(MarketDataSource):
    def snapshot(self, query):
        return MarketSnapshot(query, 3, 200.0, 160.0, 260.0,
                              ("https://i/1.jpg", "https://i/2.jpg"),
                              search_url(query))


def test_scan_results_carry_the_photos():
    r = scan_all(["A"], ImageSource(), US)[0]
    assert r.image_urls == ("https://i/1.jpg", "https://i/2.jpg")
    assert r.search_url


def test_enrich_fills_photos_on_candidates():
    from blueocean.pipeline import enrich

    c = [Candidate(sku="A", title_ja="t", source_url="", cost_incl_tax_jpy=8000,
                   weight_g=300, category="")]
    enrich(c, ImageSource())
    assert c[0].image_urls and c[0].search_url


def test_candidate_csv_round_trips_photos(tmp_path):
    """走査 → 候補CSV → 軸1 の間で写真の導線が切れないこと。"""
    from blueocean.discovery import write_candidate_template
    from blueocean.pipeline import load_candidates

    out = tmp_path / "c.csv"
    write_candidate_template(scan_all(["A"], ImageSource(), US), out)
    c = load_candidates(out)[0]
    assert c.image_urls == ("https://i/1.jpg",)
    assert c.search_url


# --- 照合シート -------------------------------------------------------------

def test_sheet_shows_the_budget_first():
    """店頭で見るのは予算だけ。先頭に出すこと。"""
    items = from_scan(scan_all(["A"], ImageSource(), US), worthy_only=False)
    assert "予算" in items[0].lines[0]


def test_sheet_embeds_images_and_link():
    html = render(from_scan(scan_all(["A"], ImageSource(), US), worthy_only=False))
    assert "https://i/1.jpg" in html
    assert "ebay.com/sch" in html


def test_sheet_says_so_when_there_is_no_photo():
    """写真が無いことを黙って空欄にしない。"""
    html = render(from_scan(scan_all(["A"], MockSource(), US), worthy_only=False))
    assert "写真は未取得" in html


def test_sheet_escapes_html():
    c = Candidate(sku="A", title_ja='<script>x</script>', source_url="",
                  cost_incl_tax_jpy=8000, weight_g=300, category="",
                  market_price_usd=200.0, competitor_count=2, has_demand_signal=True)
    html = render(from_scored([score_one(c, US)]))
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_sheet_skips_excluded_by_default():
    c = Candidate(sku="A", title_ja="規制品", source_url="", cost_incl_tax_jpy=8000,
                  weight_g=300, category="", market_price_usd=200.0,
                  competitor_count=2, is_restricted=True, restricted_reason="規制")
    scored = [score_one(c, US)]
    assert scored[0].verdict is Verdict.EXCLUDE
    assert from_scored(scored) == []
    assert len(from_scored(scored, include_excluded=True)) == 1


def test_sheet_warns_about_generation_differences():
    """型番が同じでも世代違いがある。買う前に見比べろと必ず書く。"""
    html = render(from_scan(scan_all(["A"], ImageSource(), US), worthy_only=False))
    assert "世代違い" in html


def test_write_returns_the_count(tmp_path):
    items = from_scan(scan_all(["A", "B"], ImageSource(), US), worthy_only=False)
    p = tmp_path / "s.html"
    assert write(items, p) == 2
    assert p.read_text(encoding="utf-8").startswith("<!doctype html>")
