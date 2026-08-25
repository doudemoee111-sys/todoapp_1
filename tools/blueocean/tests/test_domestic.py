"""国内ショップAPIの取得層。1度もネットに出ないよう fetch を差し替えて回す。"""
from __future__ import annotations

import pytest

from blueocean.domestic import (
    AmazonProvider, keep_cheapest, ApiError, Condition, DomesticItem, Query, RateLimiter,
    Request, Source, WeightBasis, credentials_from_env, price_bands,
    provider_for, read_items, search, search_all, to_candidates,
    transfer_measurements, weight_hint, write_items,
)


# --------------------------------------------------------------------------
# 応答の雛形
# --------------------------------------------------------------------------

def rakuten_item(i: int, price: int = 1200, **kw):
    d = {
        "itemName": f"商品{i} フィギュア",
        "itemCode": f"shop:item{i}",
        "itemUrl": f"https://item.rakuten.co.jp/shop/item{i}/",
        "itemPrice": price,
        "taxFlag": 0,
        "postageFlag": 0,
        "availability": 1,
        "shopName": "テスト商店",
        "shopCode": "shop",
        "genreId": "101240",
        "mediumImageUrls": [{"imageUrl": f"https://img/{i}.jpg?_ex=128x128"}],
        "reviewCount": 3,
        "reviewAverage": 4.5,
        "pointRate": 1,
        "shipOverseasFlag": 0,
    }
    d.update(kw)
    return d


def rakuten_page(n: int, *, count: int = 100, start: int = 0, **kw):
    return {"count": count, "page": 1, "pageCount": 4,
            "Items": [rakuten_item(start + i, **kw) for i in range(n)]}


def yahoo_item(i: int, price: int = 1200, **kw):
    d = {
        "name": f"商品{i} 300g",
        "code": f"store_item{i}",
        "url": f"https://store.shopping.yahoo.co.jp/store/item{i}.html",
        "price": price,
        "priceLabel": {"taxable": False, "defaultPrice": price},
        "inStock": True,
        "condition": "new",
        "janCode": f"49{i:011d}",
        "image": {"medium": f"https://img/y{i}.jpg", "small": f"https://s/y{i}.jpg"},
        "review": {"count": 5, "rate": 4.2},
        "seller": {"sellerId": "store", "name": "テストストア"},
        "genreCategory": {"id": "2498", "name": "ホビー"},
        "brand": {"name": "テストブランド"},
        "point": {"times": 1},
    }
    d.update(kw)
    return d


def yahoo_page(n: int, *, total: int = 100, start: int = 0, **kw):
    return {"totalResultsAvailable": total, "totalResultsReturned": n,
            "firstResultPosition": start + 1,
            "hits": [yahoo_item(start + i, **kw) for i in range(n)]}


class Feed:
    """ページ番号に応じて応答を返す fetch。呼ばれた中身を記録する。

    GET の取得元はクエリ、POST の取得元は JSON の本文を `calls` に積む。
    どちらも「何を送ったか」を1つの形で検証できるようにするため。
    """

    def __init__(self, pages):
        self.pages = pages
        self.calls: list[dict] = []
        self.requests: list = []

    def __call__(self, req):
        self.requests.append(req)
        self.calls.append(dict(req.json_body if req.json_body is not None else req.params))
        i = len(self.calls) - 1
        return self.pages[i] if i < len(self.pages) else self.pages[-1]


# --------------------------------------------------------------------------
# Query
# --------------------------------------------------------------------------

def test_query_requires_some_condition():
    with pytest.raises(ValueError, match="最低1つ"):
        Query()


def test_query_rejects_inverted_price_range():
    with pytest.raises(ValueError, match="超えている"):
        Query(keyword="x", min_price=5000, max_price=100)


def test_query_describe_is_readable():
    q = Query(keyword="ねんどろいど", min_price=1000, max_price=5000)
    assert "ねんどろいど" in q.describe()
    assert "1,000〜5,000円" in q.describe()


# --------------------------------------------------------------------------
# 楽天
# --------------------------------------------------------------------------

def test_rakuten_parses_core_fields():
    feed = Feed([rakuten_page(2, count=2)])
    r = search(Source.RAKUTEN, Query(keyword="フィギュア", max_items=2),
               "KEY", fetch=feed, limiter=RateLimiter(0))
    assert len(r.items) == 2
    it = r.items[0]
    assert it.source is Source.RAKUTEN
    assert it.price_jpy == 1200
    assert it.tax_included is True
    assert it.postage_included is True
    assert it.in_stock is True
    assert it.shop_name == "テスト商店"
    # サムネのサイズ指定は落として大きい画像を見に行けるようにする
    assert it.image_urls[0] == "https://img/0.jpg"


def test_rakuten_tax_flag_1_means_price_excludes_tax():
    feed = Feed([rakuten_page(1, count=1, taxFlag=1, itemPrice=1000)])
    r = search(Source.RAKUTEN, Query(keyword="x", max_items=1), "K",
               fetch=feed, limiter=RateLimiter(0))
    it = r.items[0]
    assert it.tax_included is False
    assert it.cost_incl_tax_jpy == 1100      # 税別1000円は原価1100円


def test_rakuten_postage_flag_1_is_not_free_shipping():
    feed = Feed([rakuten_page(1, count=1, postageFlag=1)])
    r = search(Source.RAKUTEN, Query(keyword="x", max_items=1), "K",
               fetch=feed, limiter=RateLimiter(0))
    assert r.items[0].postage_included is False


def test_rakuten_accepts_wrapped_format_version_1():
    feed = Feed([{"count": 1, "Items": [{"Item": rakuten_item(0)}]}])
    r = search(Source.RAKUTEN, Query(keyword="x", max_items=1), "K",
               fetch=feed, limiter=RateLimiter(0))
    assert len(r.items) == 1


def test_rakuten_error_payload_raises():
    feed = Feed([{"error": "wrong_parameter", "error_description": "applicationId"}])
    with pytest.raises(ApiError, match="wrong_parameter"):
        search(Source.RAKUTEN, Query(keyword="x"), "K",
               fetch=feed, limiter=RateLimiter(0))


def test_rakuten_missing_items_key_raises_rather_than_returning_empty():
    """形が変わったときに「0件でした」と嘘をつかない。"""
    feed = Feed([{"count": 5}])
    with pytest.raises(ApiError, match="Items が無い"):
        search(Source.RAKUTEN, Query(keyword="x"), "K",
               fetch=feed, limiter=RateLimiter(0))


def test_rakuten_params_map_to_official_names():
    feed = Feed([rakuten_page(1, count=1)])
    q = Query(keyword="カメラ", ng_keyword="ジャンク", genre_id="2000",
              min_price=3000, max_price=20000, in_stock_only=True,
              postage_included_only=True, sort="price_asc", max_items=1)
    search(Source.RAKUTEN, q, "APPID", fetch=feed, limiter=RateLimiter(0))
    p = feed.calls[0]
    assert p["applicationId"] == "APPID"
    assert p["keyword"] == "カメラ"
    assert p["NGKeyword"] == "ジャンク"
    assert p["genreId"] == "2000"
    assert p["minPrice"] == "3000"
    assert p["maxPrice"] == "20000"
    assert p["availability"] == "1"
    assert p["postageFlag"] == "1"
    assert p["sort"] == "+itemPrice"


# --------------------------------------------------------------------------
# Yahoo!
# --------------------------------------------------------------------------

def test_yahoo_parses_core_fields_including_jan():
    feed = Feed([yahoo_page(2, total=2)])
    r = search(Source.YAHOO, Query(keyword="x", max_items=2), "CID",
               fetch=feed, limiter=RateLimiter(0))
    it = r.items[0]
    assert it.source is Source.YAHOO
    assert it.jan == "4900000000000"
    assert it.condition == "new"
    assert it.brand == "テストブランド"
    assert it.genre_name == "ホビー"


def test_yahoo_taxable_true_means_price_excludes_tax():
    """priceLabel.taxable は「税別表示か」。ここを反転すると原価が1割ずれる。"""
    feed = Feed([yahoo_page(1, total=1, price=1000,
                            priceLabel={"taxable": True, "defaultPrice": 1000})])
    r = search(Source.YAHOO, Query(keyword="x", max_items=1), "C",
               fetch=feed, limiter=RateLimiter(0))
    assert r.items[0].tax_included is False
    assert r.items[0].cost_incl_tax_jpy == 1100


def test_yahoo_start_is_one_based_offset():
    feed = Feed([yahoo_page(50, total=200, start=0),
                 yahoo_page(50, total=200, start=50)])
    search(Source.YAHOO, Query(keyword="x", max_items=100), "C",
           fetch=feed, limiter=RateLimiter(0))
    assert feed.calls[0]["start"] == "1"
    assert feed.calls[1]["start"] == "51"


def test_yahoo_condition_filter_is_passed_through():
    feed = Feed([yahoo_page(1, total=1)])
    search(Source.YAHOO, Query(keyword="x", condition=Condition.USED, max_items=1),
           "C", fetch=feed, limiter=RateLimiter(0))
    assert feed.calls[0]["condition"] == "used"


def test_yahoo_missing_hits_raises():
    feed = Feed([{"totalResultsAvailable": 3}])
    with pytest.raises(ApiError, match="hits が無い"):
        search(Source.YAHOO, Query(keyword="x"), "C",
               fetch=feed, limiter=RateLimiter(0))


# --------------------------------------------------------------------------
# 取りこぼしを黙らせない（この層の一番大事なところ）
# --------------------------------------------------------------------------

def test_window_overflow_is_reported_loudly():
    """該当5万件・辿れるのは3千件、を黙って通したら判断を誤る。"""
    feed = Feed([rakuten_page(30, count=50_000, start=i * 30) for i in range(200)])
    r = search(Source.RAKUTEN, Query(keyword="フィギュア", max_items=5000),
               "K", fetch=feed, limiter=RateLimiter(0))
    assert r.truncated is True
    joined = " ".join(r.warnings)
    assert "47,000件は取れていない" in joined
    assert "分割" in joined


def test_max_items_beyond_provider_window_is_clipped_and_announced():
    feed = Feed([rakuten_page(30, count=100, start=i * 30) for i in range(200)])
    r = search(Source.RAKUTEN, Query(keyword="x", max_items=9999), "K",
               fetch=feed, limiter=RateLimiter(0))
    assert any("3,000件に切り詰めた" in w for w in r.warnings)
    assert len(r.items) <= 3000


def test_stopping_early_on_max_items_is_announced():
    feed = Feed([rakuten_page(30, count=500, start=0)])
    r = search(Source.RAKUTEN, Query(keyword="x", max_items=10), "K",
               fetch=feed, limiter=RateLimiter(0))
    assert len(r.items) == 10
    assert any("打ち切った" in w for w in r.warnings)


def test_search_stops_when_a_page_comes_back_empty():
    feed = Feed([rakuten_page(30, count=100), rakuten_page(0, count=100)])
    r = search(Source.RAKUTEN, Query(keyword="x", max_items=100), "K",
               fetch=feed, limiter=RateLimiter(0))
    assert len(r.items) == 30
    assert r.pages_fetched == 2


# --------------------------------------------------------------------------
# レート制限
# --------------------------------------------------------------------------

def test_rate_limiter_waits_between_calls():
    now = [0.0]
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    lim = RateLimiter(1.0, sleep=sleep, clock=lambda: now[0])
    lim.wait()          # 1回目は待たない
    lim.wait()          # 直後なので1秒待つ
    assert slept == [1.0]

    now[0] += 5.0
    lim.wait()          # 十分空いていれば待たない
    assert slept == [1.0]


def test_rakuten_default_interval_respects_one_request_per_second():
    assert provider_for("rakuten").min_interval >= 1.0


def test_search_paging_goes_through_the_limiter():
    now = [0.0]
    lim = RateLimiter(1.0, sleep=lambda s: now.__setitem__(0, now[0] + s),
                      clock=lambda: now[0])
    feed = Feed([rakuten_page(30, count=90, start=i * 30) for i in range(3)])
    search(Source.RAKUTEN, Query(keyword="x", max_items=90), "K",
           fetch=feed, limiter=lim)
    assert lim.waits == 2      # 3ページなら間は2回


# --------------------------------------------------------------------------
# 価格帯分割・名寄せ
# --------------------------------------------------------------------------

def test_price_bands_are_contiguous_and_cover_the_range():
    bands = price_bands(500, 50_000, 5)
    assert len(bands) == 5
    assert bands[0][0] == 500
    assert bands[-1][1] == 50_000
    for (_, a), (b, _) in zip(bands, bands[1:]):
        assert b == a + 1        # 隙間も重複も作らない


def test_price_bands_are_geometric_not_equal_width():
    """等分だと安い帯に商品が偏って分割の意味が無くなる。"""
    bands = price_bands(500, 50_000, 4)
    widths = [b - a for a, b in bands]
    assert widths == sorted(widths)      # 安い側ほど狭い
    assert widths[-1] > widths[0] * 5


def test_price_bands_floor_avoids_meaningless_low_bands():
    bands = price_bands(0, 50_000, 5)
    assert bands[0] == (0, 346)          # 0〜36円のような帯を作らない


def test_split_price_issues_one_query_per_band():
    feed = Feed([rakuten_page(1, count=1)])
    search_all(["rakuten"], Query(keyword="x", min_price=500, max_price=50_000,
                                  max_items=1),
               {"rakuten": "K"}, split_price=4, fetch=feed,
               limiters={"rakuten": RateLimiter(0)})
    assert len(feed.calls) == 4
    assert [c["minPrice"] for c in feed.calls] == ["500", "1582", "5001", "15812"]


def test_search_all_dedupes_within_a_source_not_across_them():
    """同じ取得元の重複は畳むが、取得元をまたいでは畳まない。

    同じJANでも楽天とAmazonでは値段が違う。束ねると安いほうが消えるので、
    比較の材料を残す。
    """
    both = Feed([yahoo_page(2, total=2), yahoo_page(2, total=2)])
    r = search_all(["yahoo", "yahoo"], Query(keyword="x", max_items=2),
                   {"yahoo": "C"}, fetch=both,
                   limiters={"yahoo": RateLimiter(0)})
    assert len(r.items) == 2       # 同じ取得元・同じ商品なので畳まれる


def test_search_all_skips_sources_without_a_key_and_says_so():
    feed = Feed([yahoo_page(1, total=1)])
    r = search_all(["rakuten", "yahoo"], Query(keyword="x", max_items=1),
                   {"yahoo": "C"}, fetch=feed,
                   limiters={"yahoo": RateLimiter(0)})
    assert any("楽天市場は鍵" in w for w in r.warnings)
    assert len(r.items) == 1


# --------------------------------------------------------------------------
# 鍵
# --------------------------------------------------------------------------

def test_missing_key_names_the_variable_and_the_signup_url():
    with pytest.raises(ApiError) as e:
        credentials_from_env("rakuten", env={})
    msg = str(e.value)
    assert "RAKUTEN_APP_ID" in msg
    assert "webservice.rakuten.co.jp" in msg


def test_key_is_read_from_env():
    assert credentials_from_env("yahoo", env={"YAHOO_CLIENT_ID": " abc "}) == "abc"


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match="未対応の取得元"):
        provider_for("mercari")


# --------------------------------------------------------------------------
# 重量の推定
# --------------------------------------------------------------------------

@pytest.mark.parametrize("title,grams", [
    ("日本茶 ギフト 1kg", 1120),
    ("ねんどろいど 300g", 420),
    ("化粧水 500ml", 620),
    ("お茶 2L ペットボトル", 2120),
])
def test_weight_from_title(title, grams):
    h = weight_hint(title)
    assert h.basis is WeightBasis.TITLE
    assert h.grams == grams
    assert h.is_estimate is False


@pytest.mark.parametrize("title", [
    "iPhone 15 128GB ケース",
    "モバイルバッテリー 10000mAh",
    "USB 64GB",
])
def test_weight_does_not_read_storage_sizes_as_grams(title):
    assert weight_hint(title).basis is not WeightBasis.TITLE


def test_weight_falls_back_to_genre_default():
    h = weight_hint("限定版 特撮 フィギュア", "ホビー")
    assert h.basis is WeightBasis.GENRE
    assert h.grams == 900
    assert h.is_estimate is True


def test_weight_says_unknown_rather_than_guessing_zero_silently():
    h = weight_hint("謎の物体")
    assert h.basis is WeightBasis.UNKNOWN
    assert h.grams == 0
    assert "実測" in h.note


# --------------------------------------------------------------------------
# Candidate への変換
# --------------------------------------------------------------------------

def item(**kw) -> DomesticItem:
    base = dict(source=Source.YAHOO, item_code="c1", title="フィギュア 限定",
                url="https://x/", price_jpy=1000)
    base.update(kw)
    return DomesticItem(**base)


def test_estimated_weight_marks_the_candidate():
    cands, _ = to_candidates([item()])
    assert cands[0].weight_g == 900
    assert cands[0].weight_is_estimate is True
    assert "カテゴリ既定値" in cands[0].estimate_note


def test_measured_weight_in_title_is_not_an_estimate():
    cands, _ = to_candidates([item(title="お茶 500g")])
    assert cands[0].weight_is_estimate is False


def test_tax_excluded_price_is_grossed_up_and_reported():
    cands, warns = to_candidates([item(price_jpy=1000, tax_included=False)])
    assert cands[0].cost_incl_tax_jpy == 1100
    assert any("税別表示" in w for w in warns)


def test_postage_excluded_item_without_a_shipping_figure_is_flagged():
    cands, warns = to_candidates([item(postage_included=False)])
    assert cands[0].cost_is_estimate is True
    assert any("国内送料が 0円" in w for w in warns)


def test_domestic_shipping_is_added_to_cost():
    cands, _ = to_candidates([item(price_jpy=1000, postage_included=False)],
                             domestic_shipping_jpy=600)
    assert cands[0].cost_incl_tax_jpy == 1600


def test_postage_included_item_is_not_an_estimate():
    cands, _ = to_candidates([item(postage_included=True)])
    assert cands[0].cost_is_estimate is False


def test_unknown_weight_count_is_reported():
    _, warns = to_candidates([item(title="謎の物体")])
    assert any("重量の手がかりが無く" in w for w in warns)


def test_conversion_warns_when_some_weights_are_only_estimates():
    """全部が実測なら黙る。1件でも推定なら、何件が推定かを言う。"""
    _, warns = to_candidates([item(title="お茶 500g")])          # 商品名から確定
    assert not any("推定" in w for w in warns)

    _, warns = to_candidates([item(title="お茶 500g"), item(title="謎の物体")])
    assert any("1/2件が実測" in w for w in warns)


def test_jan_becomes_the_sku_so_the_same_product_merges_across_shops():
    cands, _ = to_candidates([item(jan="4901234567890")])
    assert cands[0].sku == "jan:4901234567890"


# --------------------------------------------------------------------------
# CSV 往復
# --------------------------------------------------------------------------

def test_items_round_trip_through_csv(tmp_path):
    items = [
        item(jan="4901234567890", title="お茶 500g", tax_included=False,
             postage_included=False, in_stock=True, condition="new",
             shop_name="店", genre_name="食品", brand="B",
             image_urls=("https://i/1.jpg",), review_count=7, review_average=4.1),
        item(item_code="c2", title="謎の物体", postage_included=None),
    ]
    p = tmp_path / "items.csv"
    assert write_items(p, items) == 2
    back = read_items(p)
    assert [b.title for b in back] == ["お茶 500g", "謎の物体"]
    assert back[0].tax_included is False
    assert back[0].postage_included is False
    assert back[1].postage_included is None      # 不明を False に潰さない
    assert back[0].jan == "4901234567890"


def test_csv_records_the_weight_basis(tmp_path):
    p = tmp_path / "i.csv"
    write_items(p, [item(title="お茶 500g"), item(title="謎の物体")])
    text = p.read_text(encoding="utf-8-sig")
    assert "title" in text.splitlines()[0]
    assert ",620,title," in text
    assert ",0,unknown," in text


# --------------------------------------------------------------------------
# Amazon（Creators API）
# --------------------------------------------------------------------------

def amazon_item(i: int, price: int = 4800, *, weight=None, dims=True, **kw):
    d = {
        "asin": f"B0{i:08d}",
        "detailPageURL": f"https://www.amazon.co.jp/dp/B0{i:08d}",
        "itemInfo": {
            "title": {"displayValue": f"常滑焼 急須 {i}"},
            "byLineInfo": {"brand": {"displayValue": "テストブランド"}},
            "classifications": {"productGroup": {"displayValue": "ホーム＆キッチン"}},
            "productInfo": {"itemDimensions": {
                "weight": weight if weight is not None
                          else {"displayValue": 520, "unit": "grams"},
                **({"length": {"displayValue": 18, "unit": "centimeters"},
                    "width": {"displayValue": 14, "unit": "centimeters"},
                    "height": {"displayValue": 11, "unit": "centimeters"}} if dims else {}),
            }},
            "externalIds": {"eans": {"displayValues": [f"49{i:011d}"]}},
        },
        "offers": {"listings": [{
            "price": {"amount": price, "currency": "JPY"},
            "availability": {"message": "在庫あり"},
            "condition": "New",
            "merchantInfo": {"name": "Amazon.co.jp"},
        }]},
        "images": {"primary": {"large": {"url": f"https://m.media-amazon.com/{i}.jpg"}}},
    }
    for k, v in kw.items():
        d[k] = v
    return d


def amazon_page(n: int, *, total: int = 10, start: int = 0, **kw):
    return {"searchResult": {"totalResultCount": total,
                             "items": [amazon_item(start + i, **kw) for i in range(n)]}}


TOKEN = {"access_token": "Atza|xxx", "expires_in": 3600, "token_type": "bearer"}
CREDS = "amzn1.application-oa2-client.abc:amzn1.oa2-cs.v1.def:mytag-22"


def fresh_amazon():
    """プロバイダはモジュール全体で共有されるので、トークンの持ち回しを
    テスト間で持ち込まないよう毎回作り直す。"""
    return AmazonProvider()


class AmazonFeed(Feed):
    """1回目はトークン、以降は検索結果を返す。"""

    def __call__(self, req):
        self.requests.append(req)
        self.calls.append(dict(req.json_body or req.params))
        if req.url.endswith("/auth/o2/token"):
            return TOKEN
        i = len([c for c in self.calls if "grant_type" not in c]) - 1
        return self.pages[i] if i < len(self.pages) else self.pages[-1]


def amazon_search(q, feed, prov=None):
    prov = prov or fresh_amazon()
    from blueocean import domestic as dom
    old = dom.PROVIDERS[Source.AMAZON]
    dom.PROVIDERS[Source.AMAZON] = prov
    try:
        return search(Source.AMAZON, q, CREDS, fetch=feed, limiter=RateLimiter(0))
    finally:
        dom.PROVIDERS[Source.AMAZON] = old


def test_amazon_exchanges_credentials_for_a_bearer_token():
    feed = AmazonFeed([amazon_page(1, total=1)])
    amazon_search(Query(keyword="急須", max_items=1), feed)
    tok = feed.requests[0]
    assert tok.url.endswith("/auth/o2/token")
    assert tok.method == "POST"
    assert tok.json_body["grant_type"] == "client_credentials"
    assert tok.json_body["scope"] == "creatorsapi::default"
    # 検索は Bearer で送られる
    srch = feed.requests[1]
    assert srch.headers["Authorization"] == "Bearer Atza|xxx"
    assert srch.headers["x-marketplace"] == "www.amazon.co.jp"


def test_amazon_token_is_reused_across_queries():
    """価格帯を分割すると search が何度も走る。毎回取り直さない。"""
    prov = fresh_amazon()
    feed = AmazonFeed([amazon_page(1, total=1)])
    amazon_search(Query(keyword="急須", max_items=1), feed, prov)
    amazon_search(Query(keyword="急須", max_items=1), feed, prov)
    tokens = [r for r in feed.requests if r.url.endswith("/auth/o2/token")]
    assert len(tokens) == 1


def test_amazon_bad_credential_format_is_explained():
    with pytest.raises(ApiError, match="client_id:client_secret:partner_tag"):
        AmazonProvider.split_key("just-one-value")


def test_amazon_token_failure_names_the_likely_cause():
    class NoToken(AmazonFeed):
        def __call__(self, req):
            if req.url.endswith("/auth/o2/token"):
                return {"error": "invalid_client"}
            return super().__call__(req)

    with pytest.raises(ApiError, match="アソシエイト"):
        amazon_search(Query(keyword="x"), NoToken([amazon_page(1)]))


def test_amazon_parses_weight_and_dimensions():
    """ここがAmazonを入れる理由。他の2社は重量を返さない。"""
    feed = AmazonFeed([amazon_page(1, total=1)])
    r = amazon_search(Query(keyword="急須", max_items=1), feed)
    it = r.items[0]
    assert it.weight_g == 520
    assert (it.length_cm, it.width_cm, it.height_cm) == (18.0, 14.0, 11.0)
    assert it.jan == "4900000000000"
    assert it.brand == "テストブランド"
    assert it.in_stock is True
    assert it.condition == "new"


@pytest.mark.parametrize("value,unit,grams", [
    (520, "grams", 520),
    (1.2, "kilograms", 1200),
    (1.15, "pounds", 522),              # ポンド表記の輸入品
    (115, "hundredths_pounds", 522),    # 旧PA-APIが使っていた刻み
    (18.4, "ounces", 522),
])
def test_amazon_converts_weight_units(value, unit, grams):
    feed = AmazonFeed([amazon_page(1, total=1,
                                   weight={"displayValue": value, "unit": unit})])
    r = amazon_search(Query(keyword="x", max_items=1), feed)
    assert abs(r.items[0].weight_g - grams) <= 1


def test_amazon_rejects_weights_beyond_what_can_be_shipped():
    """520 を pounds と読むと 236kg。国際発送の対象外なので誤読とみなす。"""
    feed = AmazonFeed([amazon_page(1, total=1,
                                   weight={"displayValue": 520, "unit": "pounds"})])
    r = amazon_search(Query(keyword="x", max_items=1), feed)
    assert r.items[0].weight_g == 0


def test_amazon_refuses_unknown_weight_units_rather_than_guessing():
    """pounds を grams と読むと450倍軽くなる。知らない単位は使わない。"""
    feed = AmazonFeed([amazon_page(1, total=1,
                                   weight={"displayValue": 520, "unit": "stones"})])
    r = amazon_search(Query(keyword="x", max_items=1), feed)
    assert r.items[0].weight_g == 0
    assert any("重量が登録されていません" in w for w in r.warnings)


def test_amazon_missing_dimensions_are_reported():
    feed = AmazonFeed([amazon_page(2, total=2, weight={})])
    r = amazon_search(Query(keyword="x", max_items=2), feed)
    assert all(i.weight_g == 0 for i in r.items)
    assert any("2件は重量が登録されていません" in w for w in r.warnings)


def test_amazon_window_is_only_100_items():
    """楽天3,000・Yahoo!1,000に対してAmazonは100。面で採る用途には向かない。"""
    assert provider_for("amazon").window == 100
    feed = AmazonFeed([amazon_page(10, total=5000, start=i * 10) for i in range(20)])
    r = amazon_search(Query(keyword="フィギュア", max_items=3000), feed)
    assert r.truncated is True
    assert any("100件までしか返せない" in w for w in r.warnings)
    assert any("4,900件は取れていない" in w for w in r.warnings)


def test_amazon_body_maps_to_creators_api_field_names():
    feed = AmazonFeed([amazon_page(1, total=1)])
    amazon_search(Query(keyword="急須", genre_id="123", min_price=1000,
                        max_price=9000, condition=Condition.NEW, max_items=1),
                  feed)
    b = feed.requests[1].json_body
    assert b["keywords"] == "急須"
    assert b["browseNodeId"] == "123"
    assert b["minPrice"] == 100_000        # 通貨の最小単位
    assert b["maxPrice"] == 900_000
    assert b["condition"] == "New"
    assert b["partnerTag"] == "mytag-22"
    assert b["marketplace"] == "www.amazon.co.jp"
    assert "itemInfo.productInfo" in b["resources"]
    assert "itemInfo.externalIds" in b["resources"]


def test_amazon_missing_search_result_raises_rather_than_returning_empty():
    feed = AmazonFeed([{"somethingElse": {}}])
    with pytest.raises(ApiError, match="searchResult"):
        amazon_search(Query(keyword="x"), feed)


def test_amazon_error_payload_raises():
    feed = AmazonFeed([{"errors": [{"code": "TooManyRequests",
                                    "message": "rate exceeded"}]}])
    with pytest.raises(ApiError, match="TooManyRequests"):
        amazon_search(Query(keyword="x"), feed)


def test_amazon_key_help_names_the_three_parts():
    with pytest.raises(ApiError) as e:
        credentials_from_env("amazon", env={})
    assert "AMAZON_CREATORS_CREDS" in str(e.value)


# --------------------------------------------------------------------------
# 実測の受け渡し（Amazonを入れる一番の効き目）
# --------------------------------------------------------------------------

from blueocean.domestic import SearchResult as SearchResultLike_


def SearchResultLike(items):
    return SearchResultLike_(items=list(items))


def measured(**kw):
    base = dict(source=Source.AMAZON, item_code="B1", title="急須", url="",
                price_jpy=4800, jan="4901234567890", weight_g=520,
                length_cm=18.0, width_cm=14.0, height_cm=11.0)
    base.update(kw)
    return DomesticItem(**base)


def test_measurements_move_to_the_cheaper_row_with_the_same_jan():
    cheap = item(jan="4901234567890", price_jpy=3900)      # Yahoo!・重量なし
    out, warns = transfer_measurements([measured(), cheap])
    moved = [i for i in out if i.source is Source.YAHOO][0]
    assert moved.weight_g == 520
    assert moved.length_cm == 18.0
    assert any("Amazon の登録値から重量・寸法を移しました" in w for w in warns)


def test_transferred_measurement_says_where_it_came_from():
    """移した値を自分の登録値のように見せない。どこを疑うかが分からなくなる。"""
    out, _ = transfer_measurements([measured(), item(jan="4901234567890")])
    cands, _ = to_candidates(out)
    moved = [c for c in cands if "JAN一致" in c.estimate_note]
    assert moved and "Amazon.co.jp" in moved[0].estimate_note


def test_transferred_measurement_is_not_an_estimate():
    out, _ = transfer_measurements([measured(), item(jan="4901234567890")])
    cands, _ = to_candidates(out)
    assert all(c.weight_is_estimate is False for c in cands)


def test_rows_without_a_jan_cannot_be_matched_and_it_says_so():
    """楽天はJANを返さないので、楽天だけの行はここで埋まらない。"""
    rakuten = item(source=Source.RAKUTEN, jan="", title="謎の物体")
    out, warns = transfer_measurements([measured(), rakuten])
    assert [i for i in out if i.source is Source.RAKUTEN][0].weight_g == 0
    assert any("JANが無いため突合できませんでした" in w for w in warns)


def test_transfer_prefers_the_row_that_also_has_dimensions():
    only_weight = measured(item_code="B2", length_cm=0, width_cm=0, height_cm=0)
    full = measured(item_code="B3")
    out, _ = transfer_measurements([only_weight, full, item(jan="4901234567890")])
    moved = [i for i in out if i.source is Source.YAHOO][0]
    assert moved.length_cm == 18.0


def test_measured_dimensions_reach_the_candidate():
    cands, _ = to_candidates([measured()])
    assert cands[0].length_cm == 18.0
    assert cands[0].weight_g == 520 + 120        # 梱包ぶんを足す


def test_items_csv_round_trips_measurements(tmp_path):
    p = tmp_path / "i.csv"
    write_items(p, [measured()])
    back = read_items(p)[0]
    assert back.weight_g == 520
    assert back.length_cm == 18.0


def test_same_jan_from_two_sources_both_survive():
    """安いほうを勝手に捨てない。ここを畳むと選択肢が消える。"""
    a = measured(price_jpy=4800)
    y = item(jan="4901234567890", price_jpy=3900, item_code="y1")
    res = SearchResultLike([a]).merged_with(SearchResultLike([y]))
    assert len(res.items) == 2


def test_keep_cheapest_collapses_and_reports_the_difference():
    out, warns = keep_cheapest([measured(price_jpy=4800),
                                item(jan="4901234567890", price_jpy=3900)])
    assert len(out) == 1
    assert out[0].price_jpy == 3900
    assert any("900円 の差" in w for w in warns)


def test_keep_cheapest_carries_the_measurement_onto_the_cheaper_row():
    """安いほうに重量が無ければ、高いほうの登録値を持っていく。"""
    out, _ = keep_cheapest([measured(price_jpy=4800),
                            item(jan="4901234567890", price_jpy=3900)])
    assert out[0].weight_g == 520
    assert out[0].measured_from == "Amazon.co.jp"


def test_keep_cheapest_is_not_applied_by_default():
    """search_all は畳まない。畳むかどうかは呼び出し側が決める。"""
    feed = Feed([yahoo_page(1, total=1)])
    r = search_all(["yahoo"], Query(keyword="x", max_items=1), {"yahoo": "C"},
                   fetch=feed, limiters={"yahoo": RateLimiter(0)})
    assert not any("畳みました" in w for w in r.warnings)
