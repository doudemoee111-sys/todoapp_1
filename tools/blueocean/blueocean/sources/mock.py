"""オフライン検証用のデータ源。API未契約でもパイプライン全体を通せる。"""
from __future__ import annotations

import hashlib

from .base import MarketDataSource, MarketSnapshot


class MockSource(MarketDataSource):
    """検索語から決定的に値を生成する。テストと動作確認のためだけに使う。

    実データではないので、判断には絶対に使わないこと。
    """

    def __init__(self, table: dict[str, MarketSnapshot] | None = None):
        self._table = table or {}

    def snapshot(self, query: str) -> MarketSnapshot:
        if query in self._table:
            return self._table[query]
        h = int(hashlib.sha256(query.encode()).hexdigest(), 16)
        count = h % 60
        price = 40 + (h >> 8) % 400
        # 画像は捏造しない（実在しないURLを返すと現物照合の役に立たないどころか害になる）。
        # 検索URLだけは本物を組み立てる。人がブラウザで開けば実際の写真が見られる。
        from .ebay_browse import search_url
        return MarketSnapshot(query, count, float(price), price * 0.8, price * 1.3,
                              (), search_url(query))
