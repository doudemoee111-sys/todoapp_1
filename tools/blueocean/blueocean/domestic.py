"""国内ショップの公式APIから仕入れ候補を取る。

**巡回（スクレイピング）はしない。** ここで叩くのは、利用者自身が各社に登録して
発行を受けた公式APIだけで、鍵は利用者の環境変数から読む。HTMLを取りに行く経路は
一切用意していない。規約上の位置づけがはっきりしている経路しか使わない、という
方針は README の「データの制約」と同じ。

対応している経路は2つ。

  楽天市場   Rakuten Ichiba Item Search API
             楽天会員 → アプリID発行。**1秒1リクエスト**の制限がある。
             hits 最大30 × page 最大100 = 1クエリあたり 3,000件まで到達できる。
  Yahoo!     Yahoo!ショッピング 商品検索(v3)
             Yahoo! JAPAN ID → Client ID発行。
             results 最大50 × start 最大1000 = 1クエリあたり 1,000件まで。
             **JANコードが返る**ので、eBay側との突合に使える。

どちらも「検索結果の窓」に上限があるので、条件を広く取ると**上限の先が黙って
落ちる**。落ちたことに気づけないのが一番まずいので、上限に当たったクエリは
必ず warnings に出す。price_bands() で価格帯に割ると窓を跨げる。

取れない値についても黙らない。両APIとも**重量と寸法は返さない**。返らない値を
0のまま Candidate に流すと「軽い＝送料が安い」と読まれて判定が甘くなるので、
推定で埋めた場合は weight_is_estimate を立てて判定を PROBE で止める。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .models import Candidate

__all__ = [
    "Source", "Query", "DomesticItem", "SearchResult", "ApiError",
    "Provider", "RakutenProvider", "YahooProvider", "PROVIDERS", "provider_for",
    "credentials_from_env", "search", "search_all", "price_bands",
    "WeightHint", "WeightBasis", "weight_hint", "to_candidates",
    "write_items", "read_items", "ITEM_COLUMNS",
]


# --------------------------------------------------------------------------
# 基本型
# --------------------------------------------------------------------------

class Source(Enum):
    RAKUTEN = "rakuten"
    YAHOO = "yahoo"

    @property
    def label(self) -> str:
        return {"rakuten": "楽天市場", "yahoo": "Yahoo!ショッピング"}[self.value]


class ApiError(RuntimeError):
    """APIが異常を返した、または応答の形が想定と違う。"""


class Condition(Enum):
    ANY = "any"
    NEW = "new"
    USED = "used"


@dataclass(frozen=True)
class Query:
    """抽出条件。両社のパラメータ名の差はプロバイダ側で吸収する。"""
    keyword: str = ""
    ng_keyword: str = ""
    genre_id: str = ""          # 楽天 genreId / Yahoo genre_category_id
    jan: str = ""
    shop: str = ""              # 楽天 shopCode / Yahoo seller_id
    min_price: int | None = None
    max_price: int | None = None
    condition: Condition = Condition.ANY
    in_stock_only: bool = True
    # 「送料込みだけ」に絞ると仕入原価が確定するので、実務ではこれを立てたくなる。
    # ただし絞ると母数が大きく減るため、既定は False にして選ばせる。
    postage_included_only: bool = False
    has_image_only: bool = True
    sort: str = "price_asc"     # price_asc / price_desc / review_desc / standard
    max_items: int = 300

    def __post_init__(self) -> None:
        if not any((self.keyword, self.genre_id, self.jan, self.shop)):
            raise ValueError(
                "keyword / genre_id / jan / shop のうち最低1つは指定すること。"
                "条件なしの全件取得はどちらのAPIでもできない"
            )
        if self.min_price is not None and self.max_price is not None:
            if self.min_price > self.max_price:
                raise ValueError("min_price が max_price を超えている")
        if self.max_items <= 0:
            raise ValueError("max_items は1以上")

    def describe(self) -> str:
        bits = []
        if self.keyword:
            bits.append(f"「{self.keyword}」")
        if self.genre_id:
            bits.append(f"ジャンル{self.genre_id}")
        if self.jan:
            bits.append(f"JAN {self.jan}")
        if self.shop:
            bits.append(f"店舗 {self.shop}")
        lo = f"{self.min_price:,}" if self.min_price is not None else ""
        hi = f"{self.max_price:,}" if self.max_price is not None else ""
        if lo or hi:
            bits.append(f"{lo}〜{hi}円")
        if self.condition is not Condition.NEW and self.condition is not Condition.ANY:
            bits.append(self.condition.value)
        return " / ".join(bits) or "(条件なし)"


@dataclass(frozen=True)
class DomesticItem:
    """国内ショップの1商品。APIが返した値だけを持ち、推測はここでは足さない。"""
    source: Source
    item_code: str
    title: str
    url: str
    price_jpy: int
    # 表示価格が税込か。楽天は taxFlag、Yahoo は priceLabel.taxable。
    # ここを取り違えると消費税還付の計算が丸ごとずれる。
    tax_included: bool = True
    # 送料込みか。None は「APIが答えを返さなかった」であって「送料無料」ではない。
    postage_included: bool | None = None
    in_stock: bool | None = None
    condition: str = ""          # new / used / ""
    jan: str = ""
    shop_name: str = ""
    shop_code: str = ""
    genre_id: str = ""
    genre_name: str = ""
    brand: str = ""
    image_urls: tuple[str, ...] = ()
    review_count: int = 0
    review_average: float = 0.0
    point_rate: float = 0.0
    ships_overseas: bool | None = None   # 楽天 shipOverseasFlag
    raw: Mapping[str, object] = field(default_factory=dict, repr=False, compare=False)

    @property
    def cost_incl_tax_jpy(self) -> int:
        """税込での仕入原価。税別表示なら10%を乗せる。

        **送料は含めない。** 送料別（postage_included is False）の場合、
        実際の原価はこれより高い。呼び出し側で必ず警告すること。
        """
        if self.tax_included:
            return int(self.price_jpy)
        return int(self.price_jpy * 1.1 + 0.5)

    @property
    def key(self) -> str:
        """名寄せ用のキー。JANがあれば最優先（店をまたいで同一商品を束ねられる）。"""
        if self.jan:
            return f"jan:{self.jan}"
        return f"{self.source.value}:{self.item_code}"


@dataclass
class SearchResult:
    items: list[DomesticItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_available: int = 0     # APIが「該当あり」と言った件数
    pages_fetched: int = 0
    truncated: bool = False      # 窓の上限に当たって取りこぼした

    def merged_with(self, other: "SearchResult") -> "SearchResult":
        seen = {i.key for i in self.items}
        items = list(self.items)
        for i in other.items:
            if i.key not in seen:
                seen.add(i.key)
                items.append(i)
        return SearchResult(
            items=items,
            warnings=self.warnings + other.warnings,
            total_available=self.total_available + other.total_available,
            pages_fetched=self.pages_fetched + other.pages_fetched,
            truncated=self.truncated or other.truncated,
        )


# --------------------------------------------------------------------------
# 通信（差し替え可能にしてあるので、テストは1度もネットに出ない）
# --------------------------------------------------------------------------

Fetcher = Callable[[str, Mapping[str, str]], Mapping[str, object]]


def http_get_json(url: str, params: Mapping[str, str],
                  *, headers: Mapping[str, str] | None = None,
                  timeout: float = 20.0) -> Mapping[str, object]:
    """既定の取得口。urllib しか使わないので追加の依存が要らない。"""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v != ""})
    req = urllib.request.Request(f"{url}?{qs}", headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:400]
        except Exception:
            pass
        raise ApiError(f"HTTP {e.code} {e.reason} / {detail}") from e
    except Exception as e:
        raise ApiError(f"通信に失敗した：{e}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise ApiError(f"JSONとして読めない応答：{body[:200]}") from e


class RateLimiter:
    """最低間隔を守る。楽天は1秒1リクエストが明示されている。

    sleep と clock を差し替えられるようにしてあるのは、テストで実時間を待たない
    ためと、待った回数を検証するため。
    """

    def __init__(self, min_interval: float,
                 *, sleep: Callable[[float], None] | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self.min_interval = max(0.0, min_interval)
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._last: float | None = None
        self.waits = 0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = self._clock()
        if self._last is not None:
            gap = now - self._last
            if gap < self.min_interval:
                self._sleep(self.min_interval - gap)
                self.waits += 1
                now = self._clock()
        self._last = now


# --------------------------------------------------------------------------
# プロバイダ
# --------------------------------------------------------------------------

def _as_int(v: object, default: int = 0) -> int:
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return default


def _as_float(v: object, default: float = 0.0) -> float:
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return default


class Provider(ABC):
    source: Source
    endpoint: str
    page_size: int          # 1ページあたりの最大件数
    max_pages: int          # 到達できる最終ページ
    min_interval: float     # リクエスト間隔の下限（秒）
    key_env: str            # 鍵を読む環境変数名
    signup_url: str

    @property
    def window(self) -> int:
        """1クエリで到達できる最大件数。これを超えた分は取りこぼす。"""
        return self.page_size * self.max_pages

    @abstractmethod
    def params(self, q: Query, key: str, page: int, size: int) -> dict[str, str]:
        ...

    @abstractmethod
    def parse(self, payload: Mapping[str, object]) -> tuple[list[DomesticItem], int, list[str]]:
        """(商品, 該当総数, 警告) を返す。"""

    def headers(self, key: str) -> dict[str, str]:
        return {}


class RakutenProvider(Provider):
    source = Source.RAKUTEN
    endpoint = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
    page_size = 30
    max_pages = 100
    min_interval = 1.05      # 「1秒に1回以下」なので、少し余裕を持たせる
    key_env = "RAKUTEN_APP_ID"
    signup_url = "https://webservice.rakuten.co.jp/"

    _SORT = {
        "price_asc": "+itemPrice",
        "price_desc": "-itemPrice",
        "review_desc": "-reviewCount",
        "standard": "standard",
    }

    def params(self, q: Query, key: str, page: int, size: int) -> dict[str, str]:
        p: dict[str, str] = {
            "applicationId": key,
            "format": "json",
            "formatVersion": "2",     # Items をフラットな配列で返す形
            "hits": str(min(size, self.page_size)),
            "page": str(page),
            "sort": self._SORT.get(q.sort, "standard"),
        }
        if q.keyword:
            p["keyword"] = q.keyword
        if q.ng_keyword:
            p["NGKeyword"] = q.ng_keyword
        if q.genre_id:
            p["genreId"] = q.genre_id
        if q.shop:
            p["shopCode"] = q.shop
        if q.jan:
            # 楽天にJAN専用の引数は無いので、キーワードとして流す。
            # 完全一致は保証されないため、突合は呼び出し側の責任。
            p["keyword"] = (p.get("keyword", "") + " " + q.jan).strip()
        if q.min_price is not None:
            p["minPrice"] = str(q.min_price)
        if q.max_price is not None:
            p["maxPrice"] = str(q.max_price)
        if q.in_stock_only:
            p["availability"] = "1"
        if q.postage_included_only:
            p["postageFlag"] = "1"     # 送料込み・送料無料のみ
        if q.has_image_only:
            p["imageFlag"] = "1"
        # 中古/新品は楽天では絞り込めない（ショップの表記次第）。
        # ここで嘘の絞り込みをかけない。条件は parse 後に呼び出し側で見る。
        # 越境発送可の店を優先したいときのため、フラグ自体は素通しする。
        p["genreInformationFlag"] = "0"
        return p

    def parse(self, payload):
        if "error" in payload:
            raise ApiError(
                f"楽天API：{payload.get('error')} / "
                f"{payload.get('error_description', '')}"
            )
        raw_items = payload.get("Items")
        if raw_items is None:
            raise ApiError(f"楽天APIの応答に Items が無い：{str(payload)[:200]}")
        warnings: list[str] = []
        items: list[DomesticItem] = []
        for entry in raw_items:  # type: ignore[union-attr]
            # formatVersion=1 だと {"Item": {...}} で包まれる。両方受ける。
            it = entry.get("Item", entry) if isinstance(entry, dict) else {}
            if not isinstance(it, dict) or "itemName" not in it:
                warnings.append("楽天：商品名の無い要素を1件飛ばした")
                continue
            imgs = it.get("mediumImageUrls") or it.get("smallImageUrls") or []
            urls: list[str] = []
            for im in imgs:
                u = im.get("imageUrl") if isinstance(im, dict) else im
                if isinstance(u, str) and u:
                    # サムネの _ex=128x128 を外して大きい画像を見に行けるようにする
                    urls.append(re.sub(r"\?_ex=\d+x\d+$", "", u))
            items.append(DomesticItem(
                source=Source.RAKUTEN,
                item_code=str(it.get("itemCode", "")),
                title=str(it.get("itemName", "")),
                url=str(it.get("itemUrl", "")),
                price_jpy=_as_int(it.get("itemPrice")),
                # taxFlag: 0=税込 1=税別
                tax_included=_as_int(it.get("taxFlag"), 0) == 0,
                # postageFlag: 0=送料込み/無料 1=送料別
                postage_included=(_as_int(it.get("postageFlag"), -1) == 0
                                  if "postageFlag" in it else None),
                in_stock=(_as_int(it.get("availability"), -1) == 1
                          if "availability" in it else None),
                jan="",     # 楽天は返さない
                shop_name=str(it.get("shopName", "")),
                shop_code=str(it.get("shopCode", "")),
                genre_id=str(it.get("genreId", "")),
                image_urls=tuple(urls[:6]),
                review_count=_as_int(it.get("reviewCount")),
                review_average=_as_float(it.get("reviewAverage")),
                point_rate=_as_float(it.get("pointRate")),
                ships_overseas=(_as_int(it.get("shipOverseasFlag"), -1) == 1
                                if "shipOverseasFlag" in it else None),
                raw=it,
            ))
        total = _as_int(payload.get("count"))
        return items, total, warnings


class YahooProvider(Provider):
    source = Source.YAHOO
    endpoint = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
    page_size = 50
    max_pages = 20           # start は 1..1000 までなので 50×20
    min_interval = 0.25
    key_env = "YAHOO_CLIENT_ID"
    signup_url = "https://e.developer.yahoo.co.jp/register"

    _SORT = {
        "price_asc": "+price",
        "price_desc": "-price",
        "review_desc": "-review_count",
        "standard": "-score",
    }

    def params(self, q: Query, key: str, page: int, size: int) -> dict[str, str]:
        size = min(size, self.page_size)
        p: dict[str, str] = {
            "appid": key,
            "results": str(size),
            "start": str((page - 1) * size + 1),
            "sort": self._SORT.get(q.sort, "-score"),
        }
        if q.keyword:
            p["query"] = q.keyword
        if q.genre_id:
            p["genre_category_id"] = q.genre_id
        if q.jan:
            p["jan_code"] = q.jan
        if q.shop:
            p["seller_id"] = q.shop
        if q.min_price is not None:
            p["price_from"] = str(q.min_price)
        if q.max_price is not None:
            p["price_to"] = str(q.max_price)
        if q.in_stock_only:
            p["in_stock"] = "true"
        if q.condition is not Condition.ANY:
            p["condition"] = q.condition.value
        return p

    def headers(self, key: str) -> dict[str, str]:
        # appid をクエリで渡すので追加ヘッダは不要。UAだけ明示する。
        return {"User-Agent": "blueocean/1.0 (+personal sourcing tool)"}

    def parse(self, payload):
        if "Error" in payload or "error" in payload:
            raise ApiError(f"Yahoo!API：{str(payload)[:300]}")
        hits = payload.get("hits")
        if hits is None:
            raise ApiError(f"Yahoo!APIの応答に hits が無い：{str(payload)[:200]}")
        warnings: list[str] = []
        items: list[DomesticItem] = []
        for it in hits:  # type: ignore[union-attr]
            if not isinstance(it, dict) or "name" not in it:
                warnings.append("Yahoo!：商品名の無い要素を1件飛ばした")
                continue
            image = it.get("image") or {}
            urls = [u for u in (image.get("medium"), image.get("small"))
                    if isinstance(u, str) and u]
            label = it.get("priceLabel") or {}
            # taxable: True=税別表示 False=税込表示
            taxable = label.get("taxable")
            review = it.get("review") or {}
            seller = it.get("seller") or {}
            genre = it.get("genreCategory") or {}
            brand = it.get("brand") or {}
            point = it.get("point") or {}
            price = _as_int(it.get("price"))
            items.append(DomesticItem(
                source=Source.YAHOO,
                item_code=str(it.get("code", "")),
                title=str(it.get("name", "")),
                url=str(it.get("url", "")),
                price_jpy=price,
                tax_included=(not bool(taxable)) if taxable is not None else True,
                postage_included=None,   # v3 は送料込みかを直接は返さない
                in_stock=bool(it.get("inStock")) if "inStock" in it else None,
                condition=str(it.get("condition", "")),
                jan=str(it.get("janCode") or ""),
                shop_name=str(seller.get("name", "")),
                shop_code=str(seller.get("sellerId", "")),
                genre_id=str(genre.get("id", "")),
                genre_name=str(genre.get("name", "")),
                brand=str(brand.get("name", "")),
                image_urls=tuple(urls[:6]),
                review_count=_as_int(review.get("count")),
                review_average=_as_float(review.get("rate")),
                point_rate=_as_float(point.get("times")),
                raw=it,
            ))
        total = _as_int(payload.get("totalResultsAvailable"))
        if taxable_missing := [i for i in items if i.raw.get("priceLabel") is None]:
            warnings.append(
                f"Yahoo!：{len(taxable_missing)}件で priceLabel が空。"
                "税込／税別が判別できないので税込とみなした（原価が1割ずれうる）"
            )
        return items, total, warnings


PROVIDERS: dict[Source, Provider] = {
    Source.RAKUTEN: RakutenProvider(),
    Source.YAHOO: YahooProvider(),
}


def provider_for(source: Source | str) -> Provider:
    if isinstance(source, str):
        try:
            source = Source(source)
        except ValueError:
            raise ValueError(
                f"未対応の取得元：{source}。使えるのは "
                f"{', '.join(s.value for s in Source)}"
            ) from None
    return PROVIDERS[source]


def credentials_from_env(source: Source | str,
                         env: Mapping[str, str] | None = None) -> str:
    """鍵は環境変数からしか読まない。コードにもCSVにも置かない。"""
    prov = provider_for(source)
    env = env if env is not None else os.environ
    key = (env.get(prov.key_env) or "").strip()
    if not key:
        raise ApiError(
            f"{prov.source.label}の鍵が未設定。{prov.key_env} に入れること。\n"
            f"  発行： {prov.signup_url}\n"
            f"  例：   export {prov.key_env}='...'"
        )
    return key


# --------------------------------------------------------------------------
# 取得
# --------------------------------------------------------------------------

def search(source: Source | str, q: Query, key: str, *,
           fetch: Fetcher | None = None,
           limiter: RateLimiter | None = None) -> SearchResult:
    """1クエリぶん取る。窓の上限に当たったら truncated を立てて必ず言う。"""
    prov = provider_for(source)
    limiter = limiter or RateLimiter(prov.min_interval)
    result = SearchResult()

    want = min(q.max_items, prov.window)
    if q.max_items > prov.window:
        result.warnings.append(
            f"{prov.source.label}は1クエリ最大 {prov.window:,}件までしか辿れない。"
            f"要求 {q.max_items:,}件を {prov.window:,}件に切り詰めた"
        )

    page = 1
    while len(result.items) < want and page <= prov.max_pages:
        limiter.wait()
        params = prov.params(q, key, page, prov.page_size)
        if fetch is not None:
            payload = fetch(prov.endpoint, params)
        else:
            payload = http_get_json(prov.endpoint, params,
                                    headers=prov.headers(key))
        items, total, warns = prov.parse(payload)
        result.pages_fetched += 1
        result.warnings.extend(warns)
        if page == 1:
            result.total_available = total
        if not items:
            break
        result.items.extend(items)
        page += 1

    del result.items[want:]

    # 「該当は5万件、辿れるのは3千件」を黙って通さない。ここが一番大事。
    if result.total_available > prov.window:
        result.truncated = True
        result.warnings.append(
            f"条件『{q.describe()}』の該当は {result.total_available:,}件だが、"
            f"{prov.source.label}のAPIは {prov.window:,}件までしか返せない。"
            f"**{result.total_available - prov.window:,}件は取れていない。**"
            f"価格帯で分割して取り直すこと（--split-price）"
        )
    elif result.total_available > len(result.items):
        result.warnings.append(
            f"条件『{q.describe()}』の該当 {result.total_available:,}件のうち "
            f"{len(result.items):,}件で打ち切った（max_items の指定による）"
        )
    return result


def price_bands(low: int, high: int, bands: int) -> list[tuple[int, int]]:
    """価格帯を等比で割る。安い側ほど商品が密なので等分ではなく等比にする。

    等分（1万円ずつ）だと 0〜1万に全体の8割が入ってしまい、分割した意味が無い。
    """
    if bands < 1:
        raise ValueError("bands は1以上")
    if low < 0 or high <= low:
        raise ValueError("価格帯の指定が不正（0 <= low < high）")
    # 下限0から等比に割ると最初の帯が「0〜36円」のような無意味な幅になるので、
    # 等比の起点には床を敷く。0〜100円に商品はほぼ無い。
    lo = max(low, 100)
    if lo >= high:
        return [(low, high)]
    ratio = (high / lo) ** (1.0 / bands)
    edges = [lo]
    for i in range(1, bands):
        edges.append(int(lo * (ratio ** i)))
    edges.append(high)
    # 丸めで潰れた帯を落とす
    out: list[tuple[int, int]] = []
    for a, b in zip(edges, edges[1:]):
        if b > a:
            out.append((a if not out else out[-1][1] + 1, b))
    if out:
        out[0] = (low, out[0][1])
    return out


def search_all(sources: Sequence[Source | str], q: Query, keys: Mapping[str, str],
               *, split_price: int = 0,
               fetch: Fetcher | None = None,
               limiters: Mapping[str, RateLimiter] | None = None,
               on_progress: Callable[[str], None] | None = None) -> SearchResult:
    """複数の取得元・複数の価格帯をまとめて取り、JANで名寄せする。

    keys は {"rakuten": "...", "yahoo": "..."}。鍵の無い取得元は警告して飛ばす。
    """
    queries: list[Query] = [q]
    if split_price > 1:
        lo = q.min_price if q.min_price is not None else 0
        hi = q.max_price if q.max_price is not None else 100_000
        queries = [replace(q, min_price=a, max_price=b)
                   for a, b in price_bands(lo, hi, split_price)]

    out = SearchResult()
    for src in sources:
        prov = provider_for(src)
        name = prov.source.value
        key = (keys.get(name) or "").strip()
        if not key:
            out.warnings.append(
                f"{prov.source.label}は鍵（{prov.key_env}）が無いので飛ばした"
            )
            continue
        lim = (limiters or {}).get(name) or RateLimiter(prov.min_interval)
        for sub in queries:
            if on_progress:
                on_progress(f"{prov.source.label} {sub.describe()}")
            out = out.merged_with(search(src, sub, key, fetch=fetch, limiter=lim))
    return out


# --------------------------------------------------------------------------
# 重量の推定（APIは重量も寸法も返さないので、ここだけは推測が要る）
# --------------------------------------------------------------------------

class WeightBasis(Enum):
    TITLE = "title"          # 商品名に重量が書いてあった
    GENRE = "genre"          # カテゴリの既定値
    UNKNOWN = "unknown"      # 手がかり無し

    @property
    def label(self) -> str:
        return {"title": "商品名から", "genre": "カテゴリ既定値",
                "unknown": "不明"}[self.value]


@dataclass(frozen=True)
class WeightHint:
    grams: int
    basis: WeightBasis
    note: str = ""

    @property
    def is_estimate(self) -> bool:
        return self.basis is not WeightBasis.TITLE


# カテゴリ既定値。**梱包後**の実重量の当たりであって、実測ではない。
# 数字の根拠は「その手の物を実際に送ったときの目安」で、精度は一桁台。
# ここを信じ切らないよう、使うと必ず weight_is_estimate が立つ。
GENRE_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("フィギュア", 900), ("プラモデル", 700), ("ぬいぐるみ", 500),
    ("トレーディングカード", 120), ("カードゲーム", 200),
    ("CD", 150), ("DVD", 200), ("ブルーレイ", 200), ("レコード", 350),
    ("書籍", 400), ("コミック", 300), ("写真集", 700),
    ("腕時計", 350), ("時計", 350),
    ("カメラ", 800), ("レンズ", 700), ("三脚", 1500),
    ("ゲームソフト", 150), ("ゲーム機", 1800), ("コントローラ", 400),
    ("化粧品", 250), ("スキンケア", 300), ("香水", 400),
    ("文房具", 200), ("万年筆", 150),
    ("食品", 600), ("菓子", 400), ("茶", 300),
    ("包丁", 500), ("食器", 800), ("急須", 600),
    ("アクセサリー", 100), ("財布", 300), ("バッグ", 900),
    ("Tシャツ", 250), ("パーカー", 600), ("靴", 1100),
)

# 単位の直後に英数字が続くものは弾く。これが無いと「128GB」の GB を g と読んで
# 128g のスマホが出来上がる。長い単位から順に並べるのも同じ理由。
_WEIGHT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|ｋｇ|キロ|mg|グラム|g|ｇ)(?![a-zA-Z0-9ｇ])",
    re.IGNORECASE)
# 「1000ml」「2L」など体積表記は水と同じ比重で概算する（液体の越境は別途要確認）
_VOLUME_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ml|ｍｌ|リットル|l)(?![a-zA-Z0-9])", re.IGNORECASE)


def weight_hint(title: str, genre_name: str = "",
                *, packaging_g: int = 120) -> WeightHint:
    """商品名とカテゴリ名から梱包後重量を当てる。当てられなければ正直に言う。

    packaging_g は緩衝材と外箱のぶん。軽い物ほどこれが効くので既定を持たせる。
    """
    text = f"{title} {genre_name}"

    m = _WEIGHT_RE.search(title)
    if m:
        val = float(m.group(1).replace(",", ""))
        unit = m.group(2).lower()
        if unit in ("kg", "ｋｇ", "キロ"):
            grams = int(val * 1000)
        elif unit == "mg":
            grams = max(1, int(val / 1000))
        else:
            grams = int(val)
        if 1 <= grams <= 30_000:
            return WeightHint(grams + packaging_g, WeightBasis.TITLE,
                              f"商品名の「{m.group(0).strip()}」＋梱包 {packaging_g}g")

    m = _VOLUME_RE.search(title)
    if m:
        val = float(m.group(1).replace(",", ""))
        unit = m.group(2).lower()
        ml = val * 1000 if unit in ("l", "リットル") else val
        if 1 <= ml <= 20_000:
            return WeightHint(int(ml) + packaging_g, WeightBasis.TITLE,
                              f"商品名の「{m.group(0).strip()}」を水と同じ比重で換算"
                              f"＋梱包 {packaging_g}g")

    for needle, grams in GENRE_WEIGHTS:
        if needle in text:
            return WeightHint(grams, WeightBasis.GENRE,
                              f"「{needle}」のカテゴリ既定値（梱包込みの目安）")

    return WeightHint(0, WeightBasis.UNKNOWN,
                      "商品名にもカテゴリにも重量の手がかりが無い。実測で埋めること")


# --------------------------------------------------------------------------
# Candidate への変換
# --------------------------------------------------------------------------

def to_candidates(items: Iterable[DomesticItem], *,
                  domestic_shipping_jpy: int = 0,
                  packaging_g: int = 120,
                  category: str = "") -> tuple[list[Candidate], list[str]]:
    """国内の商品を出品候補に変換する。埋められなかった値は必ず申告する。

    domestic_shipping_jpy は「送料別」の商品に乗せる国内送料。0のままだと
    送料別の商品の原価を過小評価するので、その旨を警告に出す。
    """
    out: list[Candidate] = []
    warnings: list[str] = []
    no_postage = 0
    unknown_weight = 0
    tax_excl = 0

    for it in items:
        hint = weight_hint(it.title, it.genre_name, packaging_g=packaging_g)
        cost = it.cost_incl_tax_jpy
        notes: list[str] = []

        if not it.tax_included:
            tax_excl += 1
            notes.append("税別表示だったので10%を加算")
        if it.postage_included is False:
            no_postage += 1
            cost += domestic_shipping_jpy
            notes.append(
                f"送料別の商品。国内送料 {domestic_shipping_jpy:,}円 を原価に加算"
                if domestic_shipping_jpy else "送料別の商品だが国内送料が未設定"
            )
        elif it.postage_included is None:
            notes.append("送料込みかどうかをAPIが返さない")
        if hint.basis is WeightBasis.UNKNOWN:
            unknown_weight += 1

        cost_is_estimate = (it.postage_included is not True
                            and domestic_shipping_jpy == 0)

        out.append(Candidate(
            sku=it.key,
            title_ja=it.title,
            source_url=it.url,
            cost_incl_tax_jpy=float(cost),
            weight_g=hint.grams,
            category=category or it.genre_name or it.source.label,
            image_urls=it.image_urls,
            weight_is_estimate=hint.is_estimate,
            cost_is_estimate=cost_is_estimate,
            estimate_note="／".join([hint.note] + notes) if hint.note or notes else "",
        ))

    if unknown_weight:
        warnings.append(
            f"{unknown_weight}件は重量の手がかりが無く 0g のまま。"
            "送料が出せないので、そのままでは採算判定できない"
        )
    if no_postage and domestic_shipping_jpy == 0:
        warnings.append(
            f"{no_postage}件が送料別なのに国内送料が 0円 のまま。"
            "その分だけ原価を安く見積もっている（--domestic-shipping で指定）"
        )
    if tax_excl:
        warnings.append(f"{tax_excl}件は税別表示だったので10%を加算した")
    warnings.append(
        "重量・寸法はどちらのAPIも返さない。ここでの重量は推定なので、"
        "現物が届いたら実測で置き換えること"
    )
    return out, warnings


# --------------------------------------------------------------------------
# 保存・読み出し
# --------------------------------------------------------------------------

ITEM_COLUMNS = (
    "source", "item_code", "title", "url", "price_jpy", "cost_incl_tax_jpy",
    "tax_included", "postage_included", "in_stock", "condition", "jan",
    "shop_name", "shop_code", "genre_id", "genre_name", "brand",
    "review_count", "review_average", "point_rate", "ships_overseas",
    "weight_est_g", "weight_basis", "image_url",
)


def _flag(v: bool | None) -> str:
    return "" if v is None else ("1" if v else "0")


def write_items(path: str | Path, items: Iterable[DomesticItem],
                *, packaging_g: int = 120) -> int:
    """抽出結果をCSVに落とす。重量の推定根拠も列として残す。"""
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(ITEM_COLUMNS)
        for it in items:
            hint = weight_hint(it.title, it.genre_name, packaging_g=packaging_g)
            w.writerow([
                it.source.value, it.item_code, it.title, it.url,
                it.price_jpy, it.cost_incl_tax_jpy,
                _flag(it.tax_included), _flag(it.postage_included),
                _flag(it.in_stock), it.condition, it.jan,
                it.shop_name, it.shop_code, it.genre_id, it.genre_name, it.brand,
                it.review_count, it.review_average, it.point_rate,
                _flag(it.ships_overseas),
                hint.grams, hint.basis.value,
                it.image_urls[0] if it.image_urls else "",
            ])
            n += 1
    return n


def read_items(path: str | Path) -> list[DomesticItem]:
    """write_items が書いたCSVを読み戻す。"""
    import csv

    def flag(s: str) -> bool | None:
        s = (s or "").strip()
        return None if s == "" else s == "1"

    out: list[DomesticItem] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not (row.get("title") or "").strip():
                continue
            out.append(DomesticItem(
                source=Source(row.get("source", "rakuten")),
                item_code=row.get("item_code", ""),
                title=row.get("title", ""),
                url=row.get("url", ""),
                price_jpy=_as_int(row.get("price_jpy")),
                tax_included=flag(row.get("tax_included", "1")) is not False,
                postage_included=flag(row.get("postage_included", "")),
                in_stock=flag(row.get("in_stock", "")),
                condition=row.get("condition", ""),
                jan=row.get("jan", ""),
                shop_name=row.get("shop_name", ""),
                shop_code=row.get("shop_code", ""),
                genre_id=row.get("genre_id", ""),
                genre_name=row.get("genre_name", ""),
                brand=row.get("brand", ""),
                image_urls=tuple(u for u in [row.get("image_url", "")] if u),
                review_count=_as_int(row.get("review_count")),
                review_average=_as_float(row.get("review_average")),
                point_rate=_as_float(row.get("point_rate")),
                ships_overseas=flag(row.get("ships_overseas", "")),
            ))
    return out
