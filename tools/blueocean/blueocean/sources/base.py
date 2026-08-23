"""eBay側の観測を取るための抽象。

実装を差し替えられるようにしてあるのは、取得手段が制度・規約で変わるため。
たとえば落札実績（Marketplace Insights API）は主要パートナー以外に開放されて
おらず、個人は別の手段で代替する必要がある（README の「データの制約」参照）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MarketSnapshot:
    """ある検索語に対する、eBay側の現況。"""
    query: str
    competitor_count: int      # 現行の出品数
    median_price_usd: float | None
    low_price_usd: float | None
    high_price_usd: float | None


class MarketDataSource(ABC):
    @abstractmethod
    def snapshot(self, query: str) -> MarketSnapshot:
        """検索語に対する出品数と価格帯を返す。"""
        raise NotImplementedError
