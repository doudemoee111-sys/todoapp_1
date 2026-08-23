"""eBay Browse API アダプタ。

Browse API は公開APIで、個人の開発者アカウントでも利用できる。
出品中の商品を検索し、件数と価格帯を取得する用途に使う。

    GET /buy/browse/v1/item_summary/search?q=...&limit=...

注意：本APIが返すのは「現在出品中」の情報であって、落札実績ではない。
落札実績は Marketplace Insights API の管轄だが、そちらは主要パートナー以外に
開放されていない。個人が需要を知る手段は、軸2（自分の出品の反応）になる。

このモジュールは requests を使う。認証情報が無い環境では import しても
実行時まで失敗しないようにしてある。
"""
from __future__ import annotations

import base64
import time
from typing import Any

from .base import MarketDataSource, MarketSnapshot

_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayBrowseSource(MarketDataSource):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace_id: str = "EBAY_US",
        *,
        limit: int = 50,
        timeout: int = 20,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id
        self.limit = limit
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # --- 認証 ---
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        import requests  # 遅延 import（認証情報が無い環境でも読み込めるように）

        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        res = requests.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": _SCOPE},
            timeout=self.timeout,
        )
        res.raise_for_status()
        payload = res.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 7200))
        return self._token

    # --- 検索 ---
    def snapshot(self, query: str) -> MarketSnapshot:
        import requests

        res = requests.get(
            _SEARCH_URL,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            },
            params={"q": query, "limit": self.limit},
            timeout=self.timeout,
        )
        res.raise_for_status()
        return self._parse(query, res.json())

    @staticmethod
    def _parse(query: str, payload: dict[str, Any]) -> MarketSnapshot:
        total = int(payload.get("total", 0))
        prices: list[float] = []
        for item in payload.get("itemSummaries", []) or []:
            price = (item.get("price") or {}).get("value")
            if price is not None:
                try:
                    prices.append(float(price))
                except (TypeError, ValueError):
                    continue
        prices.sort()
        if not prices:
            return MarketSnapshot(query, total, None, None, None)
        mid = prices[len(prices) // 2]
        return MarketSnapshot(query, total, mid, prices[0], prices[-1])
