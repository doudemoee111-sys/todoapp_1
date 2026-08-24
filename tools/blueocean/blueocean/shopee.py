"""Shopee専用の一括運用 ── 「数千点を出す」ではなく「少ない枠に何を置くか」。

イメージされていたのは、仕入元から数千件を引いて一括出品し、価格差を定期的に
見張るツールだった。**eBayを前提にすればその設計で正しい。だがShopeeでは載らない。**

    出品数の上限（新規開店時）   シンガポール/マレーシア/タイ/インドネシア 1,000点
                                 **台湾 500点**
    実績を積んだ上限             最大 20,000点（Preferred Seller で 10,000点）
    プレオーダー（無在庫）枠     市場ごとに絶対上限（例：シンガポール 100点）
                                 **超えると売上の低い商品から自動削除される**

つまりShopeeで数千点を無在庫で並べることは、そもそも構造的にできない。
新規は500〜1,000点が天井で、そのうち無在庫で置けるのは100点程度。

**だから作るべきものが変わる。**

    eBay向け      多く出す → 反応を見る → 当たりを残す
    Shopee向け    **少ない枠に何を置くかを選び続ける**
                  枠が埋まっているなら、1つ入れるには1つ落とす

そして枠を超えたときに落とすのは**Shopeeであって自分ではない**（売上の低い順に
自動削除される）。自分で選ばなければ機械に選ばれる。この入れ替え判断こそ軸2そのもので、
軸2の出力（DROP）と軸1の出力（BLUE/PROBE）を突き合わせれば自動化できる。

価格差の定期確認も、無在庫では最重要になる。仕入元の値上げに気づかず出品価格を
据え置くと、**赤字のまま売れ続ける**。ここは在庫切れの検知と同じ頻度で回す必要がある。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .models import Action, FeeProfile, Market, SellerLevel, TaxProfile, Verdict
from .pricing import list_price_for_margin
from .profit import compute
from .promotion import Decision
from .scoring import ScoredCandidate
from .shipping import MARKET_ZONE, Carrier, Parcel, RateTable, Zone, estimate


# ---------------------------------------------------------------------------
# 出品枠
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShopLimits:
    """1ショップが置ける商品数。**ここが設計の出発点になる。**"""
    new_shop: int          # 新規開店時
    preferred_seller: int  # Preferred Seller 認定後
    maximum: int           # 実績を積んだ上限
    preorder: int          # プレオーダー（無在庫）の絶対上限

    def limit_for(self, tier: str) -> int:
        return {"new": self.new_shop, "preferred": self.preferred_seller,
                "max": self.maximum}[tier]


# 台湾だけ新規枠が半分になる。日本製の主戦場なのに最も枠が狭い。
LISTING_LIMITS: dict[Market, ShopLimits] = {
    Market.SHOPEE_TW: ShopLimits(500, 10000, 20000, 100),
    Market.SHOPEE_SG: ShopLimits(1000, 10000, 20000, 100),
    Market.SHOPEE_MY: ShopLimits(1000, 10000, 20000, 100),
    Market.SHOPEE_PH: ShopLimits(1000, 10000, 20000, 100),
    Market.SHOPEE_SEA: ShopLimits(1000, 10000, 20000, 100),
}


@dataclass
class SlotPlan:
    """枠の使い方。**入れる前に、落とすものを決める。**"""
    market: Market
    tier: str
    limit: int
    preorder_limit: int
    listed: int
    preorder_listed: int
    drop: list[str] = field(default_factory=list)   # 落とす候補（軸2のDROP）
    add: list[str] = field(default_factory=list)    # 入れる候補（軸1のBLUE/PROBE）
    notes: list[str] = field(default_factory=list)

    @property
    def room(self) -> int:
        return self.limit - self.listed

    @property
    def preorder_room(self) -> int:
        return self.preorder_limit - self.preorder_listed

    @property
    def forced_removals(self) -> int:
        """自分で落とさなければ、Shopeeが売上の低い順に消す件数。"""
        return max(0, self.preorder_listed - self.preorder_limit)

    @property
    def can_add(self) -> int:
        """落とす候補を全部落としたあと、実際に入れられる件数。"""
        return max(0, self.room + len(self.drop))


def plan_slots(
    market: Market,
    *,
    listed: int,
    preorder_listed: int,
    decisions: list[Decision] | None = None,
    scored: list[ScoredCandidate] | None = None,
    tier: str = "new",
) -> SlotPlan:
    """枠の残りと、入れ替えの候補を出す。

    軸2で `DROP` が出た商品と、軸1で `BLUE` / `PROBE` になった候補を突き合わせる。
    **枠が埋まっているなら、1つ入れるには1つ落とすしかない。**
    """
    limits = LISTING_LIMITS.get(market)
    if limits is None:
        raise ValueError(f"{market.value} は Shopee の市場ではありません")

    plan = SlotPlan(
        market=market, tier=tier,
        limit=limits.limit_for(tier), preorder_limit=limits.preorder,
        listed=listed, preorder_listed=preorder_listed,
        drop=[d.label for d in (decisions or []) if d.action is Action.DROP],
        add=[s.candidate.title_ja for s in (scored or [])
             if s.verdict in (Verdict.BLUE, Verdict.PROBE)],
    )

    if plan.forced_removals:
        plan.notes.append(
            f"プレオーダーが上限 {plan.preorder_limit}点 を {plan.forced_removals}点 超えています。"
            f"**超過分はShopeeが売上の低い順に自動削除します。**"
            f"自分で落とさなければ、残すものを機械に選ばれることになります"
        )
    if plan.room <= 0:
        plan.notes.append(
            f"出品枠 {plan.limit}点 が埋まっています。1つ入れるには1つ落とすしかありません。"
            f"実績を積むか Preferred Seller を取ると枠が増えます"
        )
    elif plan.room < plan.limit * 0.1:
        plan.notes.append(f"出品枠の残りが {plan.room}点。入れ替えの準備を始めてください")

    if len(plan.add) > plan.can_add:
        plan.notes.append(
            f"入れたい候補 {len(plan.add)}点 に対して、入れられるのは {plan.can_add}点 まで。"
            f"**スコアの高い順に絞ってください。**枠が少ない市場では"
            f"「全部出す」ができないので、選ぶこと自体が仕事になります"
        )
    if market is Market.SHOPEE_TW and tier == "new":
        plan.notes.append(
            "台湾は新規開店時の枠が500点で、他市場（1,000点）の半分です。"
            "日本製の主戦場なのに最も枠が狭いので、置くものの選別が効きます"
        )
    return plan


# ---------------------------------------------------------------------------
# 価格差の定期確認
# ---------------------------------------------------------------------------

class RepriceAction(str, Enum):
    STOP = "stop"      # 出品を止める（在庫切れ、または赤字）
    RAISE = "raise"    # 値上げ（仕入か送料が上がった）
    LOWER = "lower"    # 値下げの余地（任意）
    HOLD = "hold"      # 据え置き


@dataclass
class Listing:
    """いま出している1点。仕入元の現在価格と突き合わせる。"""
    sku: str
    title: str
    current_price_usd: float
    cost_incl_tax_jpy: float          # 仕入元の**現在**価格
    weight_g: int = 0
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
    available: bool = True            # 仕入元に在庫があるか
    previous_cost_jpy: float | None = None  # 前回確認したときの仕入価格

    @property
    def parcel(self) -> Parcel:
        return Parcel(self.weight_g, self.length_cm, self.width_cm, self.height_cm)


@dataclass(frozen=True)
class RepriceRow:
    """1点ぶんの改定判断。"""
    listing: Listing
    action: RepriceAction
    margin_now: float
    required_price_usd: float
    delta_usd: float
    cost_change_jpy: float
    reason: str

    @property
    def is_urgent(self) -> bool:
        """放置すると損が出るもの。**ここだけ見れば足りる。**"""
        return self.action in (RepriceAction.STOP, RepriceAction.RAISE)


@dataclass(frozen=True)
class RepricePolicy:
    """改定の閾値。全件を毎回動かすと、Shopeeの検索順位にも響く。"""
    target_margin: float = 0.20
    min_margin: float = 0.05      # これを下回ったら値上げする
    lower_slack: float = 0.10     # 必要価格より10%以上高ければ値下げ余地とみなす
    fx_jpy_per_usd: float = 150.0


def plan_reprice(
    listings: list[Listing],
    profile: FeeProfile,
    policy: RepricePolicy | None = None,
    *,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    tables: dict[Zone, RateTable] | None = None,
    carrier: Carrier | None = None,
) -> list[RepriceRow]:
    """出品中の全点を突き合わせ、動かすべきものだけを返す。

    無在庫でいちばん高くつくのは**仕入元の値上げに気づかず売れ続けること**。
    在庫切れの検知と同じ頻度で回す前提で作ってある。
    """
    policy = policy or RepricePolicy()
    tax = tax or TaxProfile()
    carrier = carrier or (Carrier.SLS if profile.market.is_shopee else None)
    zone = MARKET_ZONE[profile.market]

    out: list[RepriceRow] = []
    for li in listings:
        ship = None
        if li.weight_g > 0:
            try:
                q = estimate(li.parcel, zone, carrier or Carrier.EMS, tables=tables)
                ship = q.jpy
            except (ValueError, LookupError):
                ship = None

        kw = dict(fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax,
                  shipping_jpy=ship)
        b = compute(li.current_price_usd, li.cost_incl_tax_jpy, profile, **kw)
        need = list_price_for_margin(li.cost_incl_tax_jpy, policy.target_margin,
                                     profile, **kw)
        need = 0.0 if need == float("inf") else need
        change = (li.cost_incl_tax_jpy - li.previous_cost_jpy
                  if li.previous_cost_jpy is not None else 0.0)

        if not li.available:
            action = RepriceAction.STOP
            reason = ("仕入元に在庫が無い。**出品を止める。**"
                      "無在庫で最も高くつくのは、買えないものが売れること")
        elif b.margin < 0:
            action = RepriceAction.STOP
            reason = (f"いまの価格では赤字（利益率 {b.margin*100:.1f}%）。"
                      f"${need:,.2f} まで上げるか、出品を止める")
        elif b.margin < policy.min_margin:
            action = RepriceAction.RAISE
            reason = (f"利益率 {b.margin*100:.1f}% が下限 {policy.min_margin*100:.0f}% 未満。"
                      f"${need:,.2f} へ値上げする"
                      + (f"（仕入が {change:+,.0f}円 動いた）" if change else ""))
        elif need and li.current_price_usd > need * (1 + policy.lower_slack):
            action = RepriceAction.LOWER
            reason = (f"目標利益率を満たす価格は ${need:,.2f}。"
                      f"いまは ${li.current_price_usd:,.2f} なので下げ余地がある")
        else:
            action = RepriceAction.HOLD
            reason = f"利益率 {b.margin*100:.1f}%。据え置き"

        out.append(RepriceRow(
            listing=li, action=action, margin_now=b.margin,
            required_price_usd=need,
            delta_usd=(need - li.current_price_usd) if need else 0.0,
            cost_change_jpy=change, reason=reason,
        ))

    order = {RepriceAction.STOP: 0, RepriceAction.RAISE: 1,
             RepriceAction.LOWER: 2, RepriceAction.HOLD: 3}
    return sorted(out, key=lambda r: (order[r.action], r.margin_now))


def load_listings(path: str | Path) -> list[Listing]:
    """出品中の一覧を読む。仕入元の現在価格と在庫有無を持たせる。"""
    out: list[Listing] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            avail = str(row.get("available", "yes")).strip().lower()
            prev = str(row.get("previous_cost_jpy", "")).strip()
            out.append(Listing(
                sku=row["sku"].strip(),
                title=row.get("title", "").strip(),
                current_price_usd=float(row.get("current_price_usd") or 0),
                cost_incl_tax_jpy=float(row.get("cost_incl_tax_jpy") or 0),
                weight_g=int(float(row.get("weight_g") or 0)),
                length_cm=float(row.get("length_cm") or 0),
                width_cm=float(row.get("width_cm") or 0),
                height_cm=float(row.get("height_cm") or 0),
                available=avail not in {"no", "false", "0", "n"},
                previous_cost_jpy=float(prev) if prev else None,
            ))
    return out


def write_reprice_plan(rows: list[RepriceRow], path: str | Path, *,
                       urgent_only: bool = False) -> int:
    """改定リストを書き出す。Shopeeの一括更新にかける前の確認用。"""
    target = [r for r in rows if not urgent_only or r.is_urgent]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "title", "action", "current_price_usd", "new_price_usd",
                    "margin_now", "cost_change_jpy", "reason"])
        for r in target:
            w.writerow([
                r.listing.sku, r.listing.title, r.action.value,
                f"{r.listing.current_price_usd:.2f}",
                f"{r.required_price_usd:.2f}" if r.action in (
                    RepriceAction.RAISE, RepriceAction.LOWER) else "",
                f"{r.margin_now:.3f}", round(r.cost_change_jpy), r.reason,
            ])
    return len(target)


# ---------------------------------------------------------------------------
# 一括出品用の書き出し
# ---------------------------------------------------------------------------

_MASS_COLS = [
    "sku", "product_name", "description", "price", "stock",
    "weight_kg", "length_cm", "width_cm", "height_cm", "days_to_ship", "note",
]


def write_mass_upload(
    scored: list[ScoredCandidate],
    path: str | Path,
    profile: FeeProfile,
    *,
    target_margin: float = 0.20,
    fx_jpy_per_usd: float = 150.0,
    days_to_ship: int = 5,
    limit: int | None = None,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
) -> int:
    """一括出品の下書きを書き出す。**価格は目標利益率から順算した値を入れる。**

    Shopeeの公式テンプレートは市場ごとに列名が違い、xlsx形式で配布される。
    ここで出すのは**中身のCSV**で、公式テンプレートに貼り付けて使う前提。
    列名をこちらで決め打ちすると、テンプレートが変わった瞬間に壊れる。

    ``days_to_ship`` はプレオーダーの発送期限（3〜30日で設定可、決済から最大10日
    延ばせる）。無在庫で出すなら、仕入から発送までの実際の日数より短くしないこと。
    """
    rows = [s for s in scored if s.verdict in (Verdict.BLUE, Verdict.PROBE)]
    rows.sort(key=lambda s: -s.score)
    if limit is not None:
        rows = rows[:limit]

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(_MASS_COLS)
        for s in rows:
            c = s.candidate
            ship = s.profit.shipping_jpy if s.profit else None
            price = list_price_for_margin(
                c.cost_incl_tax_jpy, target_margin, profile,
                fx_jpy_per_usd=fx_jpy_per_usd, level=level, tax=tax, shipping_jpy=ship,
            )
            w.writerow([
                c.sku, c.title_ja, "", "" if price == float("inf") else f"{price:.2f}",
                1, f"{c.weight_g / 1000:.3f}",
                c.length_cm or "", c.width_cm or "", c.height_cm or "",
                days_to_ship, s.verdict.value,
            ])
    return len(rows)
