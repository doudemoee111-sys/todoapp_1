"""軸2：無在庫を「需要検知センサー」として使い、当たりだけ有在庫化する。

無在庫の弱点（ハンドリング5〜10営業日・在庫切れ・低単価）は、無在庫を最終形に
しないことで回避できる。無在庫で幅広く出して需要を測り、反応が出た商品だけを
有在庫化してハンドリングを1〜2日に縮める。

このモジュールには、もう一つ重要な役割がある。
eBayの Marketplace Insights API（落札実績の取得）は主要パートナー以外には
開放されていないため、個人セラーは「何が売れているか」を外部データとして
買えない。**自分の出品の反応そのものが、唯一手に入る需要データになる。**
軸1で欠けたデータを、軸2が埋める構造になっている。
"""
from __future__ import annotations

from dataclasses import dataclass

from datetime import date

from .models import Action, Market, Observation


@dataclass(frozen=True)
class PromotionPolicy:
    """有在庫化・撤退の閾値。"""
    promote_on_sold: int = 1          # 1件でも売れたら当たりとみなす
    promote_watchers: int = 3         # ウォッチがこの数に達したら有在庫化を検討
    watch_window_days: int = 14       # ウォッチを評価する期間
    reprice_views: int = 50           # 閲覧は多いのにウォッチ0 → 価格が高い
    retitle_days: int = 30            # この日数で
    retitle_views: int = 10           # 閲覧がこれ未満 → そもそも露出していない
    drop_days: int = 90               # 無反応でこの日数を超えたら畳む


@dataclass(frozen=True)
class ObservationDelta:
    """前回の観測からの増分。

    軸2の判定そのものは累計値で行う（ルールは変えない）。だが運用では
    「先週から何件増えたか」のほうが手を打つ材料になる。
    累計142件の閲覧が、先週+3件なのか+80件なのかで意味がまるで違う。
    """
    since: date
    days: int
    views: int
    watchers: int
    sold: int

    @property
    def is_stalled(self) -> bool:
        """前回から一切動いていない。判定がKEEPでも、これが続くなら撤退を早める。"""
        return self.views == 0 and self.watchers == 0 and self.sold == 0

    def as_text(self) -> str:
        if self.is_stalled:
            return f"前回（{self.since.isoformat()}／{self.days}日前）から動きなし"
        return (
            f"前回比（{self.days}日）: 閲覧 {self.views:+d} / "
            f"ウォッチ {self.watchers:+d} / 販売 {self.sold:+d}"
        )


@dataclass
class Decision:
    sku: str
    title: str
    action: Action
    reason: str
    days_listed: int
    views: int
    watchers: int
    sold: int
    delta: ObservationDelta | None = None   # 前回の観測がある場合のみ

    @property
    def label(self) -> str:
        return self.title or self.sku


def delta_between(previous: Observation, current: Observation) -> ObservationDelta:
    """同じSKUの2つの観測から増分を作る。"""
    return ObservationDelta(
        since=previous.observed_on,
        days=max(0, (current.observed_on - previous.observed_on).days),
        views=current.views - previous.views,
        watchers=current.watchers - previous.watchers,
        sold=current.sold - previous.sold,
    )


def decide(
    obs: Observation,
    policy: PromotionPolicy | None = None,
    *,
    previous: Observation | None = None,
) -> Decision:
    """観測1件から次の一手を決める。

    ``previous`` を渡すと前回比を添える。**判定そのものは累計値で行うため、
    前回比の有無で結論は変わらない。** 表示を厚くするだけの引数。
    """
    p = policy or PromotionPolicy()
    d = obs.days_listed
    delta = delta_between(previous, obs) if previous is not None else None

    def mk(action: Action, reason: str) -> Decision:
        return Decision(obs.sku, obs.title, action, reason, d,
                        obs.views, obs.watchers, obs.sold, delta)

    # 1. 売れた = 需要が確定した。最優先で有在庫化する
    if obs.sold >= p.promote_on_sold:
        return mk(
            Action.PROMOTE,
            f"{obs.sold}件 販売済み。需要が確定したので有在庫化し、"
            f"ハンドリングを1〜2日に短縮する",
        )

    # 2. ウォッチが付いている = 買う気のある人が実在する
    if obs.watchers >= p.promote_watchers and d <= p.watch_window_days:
        return mk(
            Action.PROMOTE,
            f"{d}日で ウォッチ{obs.watchers}件。購入意欲のある層が付いている",
        )

    # 3. 見られているのに動かない = 価格が合っていない
    if obs.views >= p.reprice_views and obs.watchers == 0:
        return mk(
            Action.REPRICE,
            f"閲覧{obs.views}件に対しウォッチ0。露出はあるので価格が原因",
        )

    # 4. そもそも見られていない = 検索語が当たっていない（軸4の出番）
    if d >= p.retitle_days and obs.views < p.retitle_views:
        return mk(
            Action.RETITLE,
            f"{d}日で閲覧{obs.views}件。露出不足。"
            f"海外バイヤーが実際に打つ語彙にタイトルを組み直す",
        )

    # 5. 長期間まったく反応がない = 畳む
    if d >= p.drop_days and obs.sold == 0 and obs.watchers == 0:
        return mk(Action.DROP, f"{d}日間 無反応。出品を終了して枠を空ける")

    return mk(Action.KEEP, f"観察継続（{d}日目）")


def decide_all(
    observations: list[Observation],
    policy: PromotionPolicy | None = None,
    *,
    previous: dict[str, Observation] | None = None,
) -> list[Decision]:
    """観測群を処理し、対応が必要なものを先頭に並べる。"""
    previous = previous or {}
    decisions = [decide(o, policy, previous=previous.get(o.sku)) for o in observations]
    order = {
        Action.PROMOTE: 0,
        Action.REPRICE: 1,
        Action.RETITLE: 2,
        Action.DROP: 3,
        Action.KEEP: 4,
    }
    return sorted(decisions, key=lambda x: (order[x.action], -x.sold, -x.watchers))


def stockout_rate(total_orders: int, seller_cancellations: int) -> float:
    """在庫切れ率。Below Standard の主因なので、毎週これを見る。

    eBayは在庫切れによるセラー都合キャンセルをセラーレベルに反映する。
    Below Standard に落ちると落札手数料に6ポイント上乗せされ、検索順位も下がる。
    """
    if total_orders <= 0:
        return 0.0
    return seller_cancellations / total_orders


def stockout_alert(
    rate: float, threshold: float = 0.02, *, market: "Market | None" = None
) -> str | None:
    """在庫切れ率が閾値を超えたら警告を返す。

    **罰の効き方が市場でまるで違う。** eBayは手数料に効くので採算が悪化するだけだが、
    Shopeeはペナルティポイントが露出とキャンペーン参加資格に効く。
    3点を超えると検索順位が落ち、6点を超えると露出そのものが絞られ、
    15点で停止。**採算が悪くなるのではなく、売上が立たなくなる。**
    """
    if rate <= threshold:
        return None
    head = f"在庫切れ率 {rate*100:.1f}% が閾値 {threshold*100:.0f}% を超過。"
    if market is not None and market.is_shopee:
        return (
            head
            + "Shopeeは出荷遅延・キャンセルにペナルティポイントが付き、3点超で検索順位が落ち、"
            "6点超で露出が絞られ、15点で停止する。メガセール（9.9 / 11.11 など）の参加資格も失う。"
            "**手数料の話ではなく、売上がゼロになる話**なので、eBayより早く手を打つこと"
        )
    return (
        head
        + "Below Standard に落ちると手数料が6ポイント上がり、必要な仕入倍率が "
        "2.35倍→2.79倍に悪化する（米国・売価$200・送料3,000円の前提。"
        "実際の倍率は荷姿と市場で変わる）。出品数を減らし、在庫連動の頻度を上げること"
    )
