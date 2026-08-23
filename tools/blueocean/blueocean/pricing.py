"""値決め ── 出品者が毎日ぶつかる問いに答える。

ここまでのツールは「買っていいか」までしか答えていなかった。
だが仕入れた後、実際に毎日発生するのは次の問いのほうだ。

    いくらで出せばいい？          ← 仕入上限の逆算では答えられない（向きが逆）
    Best Offer が来た。受ける？    ← 越境ECでは毎日来る。その場で判断が要る
    円安が止まった。まだ黒字？      ← 為替は全出品の採算を同時に動かす
    関税がまた上がったら？          ← この半年で3回変わっている
    返品された。いくら損した？      ← 往復送料が効くので国内とは桁が違う

どれも既存の利益計算式の変形で出せるのに、出していなかった。
このモジュールはその穴を埋める。計算式は profit.py と同一のものを使う。

    利益 = P − P·f − P·d − Fo − S − K − C + C·k

        P  売価（円）        f  実効手数料率      d  関税率
        Fo 注文ごと固定費     S  送料             K  梱包
        C  仕入（税込）       k  消費税還付率（税込仕入 × 10/110）
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import FeeProfile, SellerLevel, TaxProfile
from .profit import compute, effective_fee_rate


def _fixed_costs(profile: FeeProfile, cost_incl_tax_jpy: float, tax: TaxProfile,
                 shipping_jpy: float | None) -> float:
    """売価に比例しない費用の合計（消費税還付を差し引いた後の仕入を含む）。"""
    ship = profile.shipping_jpy if shipping_jpy is None else shipping_jpy
    k = (tax.consumption_tax_rate / (1 + tax.consumption_tax_rate)
         if tax.is_taxable_entity else 0.0)
    return (profile.per_order_fee_jpy + ship + profile.packaging_jpy
            + cost_incl_tax_jpy * (1.0 - k))


def _variable_rate(profile: FeeProfile, level: SellerLevel) -> float:
    """売価に比例して消える割合（手数料＋関税）。"""
    return effective_fee_rate(profile, level) + profile.duty_rate


def list_price_for_margin(
    cost_incl_tax_jpy: float,
    target_margin: float,
    profile: FeeProfile,
    *,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
) -> float:
    """この仕入値で目標利益率を出すための出品価格（USD）。

    仕入上限の逆算とちょうど裏返しの計算。**仕入れた後に必要なのはこちら。**

        P(1 − f − d − m) = Fo + S + K + C(1 − k)
    """
    tax = tax or TaxProfile()
    denom = 1.0 - _variable_rate(profile, level) - target_margin
    if denom <= 0:
        return float("inf")  # 手数料＋関税＋目標利益率が100%を超えている
    fixed = _fixed_costs(profile, cost_incl_tax_jpy, tax, shipping_jpy)
    return fixed / denom / fx_jpy_per_usd


def offer_floor(
    cost_incl_tax_jpy: float,
    min_margin: float,
    profile: FeeProfile,
    **kw,
) -> float:
    """Best Offer を受けられる下限価格（USD）。

    ``min_margin=0`` なら損益分岐そのもの。実務では 0 ではなく、
    梱包の手間と返品リスクを賄える最低ラインを入れる。
    """
    return list_price_for_margin(cost_incl_tax_jpy, min_margin, profile, **kw)


@dataclass(frozen=True)
class OfferStep:
    """値下げ耐性表の1行。"""
    margin: float
    price_usd: float
    profit_jpy: float
    discount_from_list: float | None  # 出品価格からの値引き率


def offer_ladder(
    cost_incl_tax_jpy: float,
    profile: FeeProfile,
    *,
    list_price_usd: float | None = None,
    margins: tuple[float, ...] = (0.30, 0.25, 0.20, 0.15, 0.10, 0.05, 0.0),
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
) -> list[OfferStep]:
    """利益率ごとの受諾ラインを一覧にする。

    **Best Offer はその場で返事が要る。** 毎回電卓を叩くのは現実的ではないので、
    出品時にこの表を作って手元に置く前提で用意した。
    """
    tax = tax or TaxProfile()
    out: list[OfferStep] = []
    for m in margins:
        p = list_price_for_margin(
            cost_incl_tax_jpy, m, profile, fx_jpy_per_usd=fx_jpy_per_usd,
            level=level, tax=tax, shipping_jpy=shipping_jpy,
        )
        if p == float("inf"):
            continue
        b = compute(p, cost_incl_tax_jpy, profile, fx_jpy_per_usd=fx_jpy_per_usd,
                    level=level, tax=tax, shipping_jpy=shipping_jpy)
        disc = (1.0 - p / list_price_usd) if list_price_usd else None
        out.append(OfferStep(m, p, b.profit_jpy, disc))
    return out


def breakeven_fx(
    price_usd: float,
    cost_incl_tax_jpy: float,
    profile: FeeProfile,
    *,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
) -> float:
    """利益がゼロになる為替レート（円/USD）。

    **これを下回ると赤字。** 売価はドル建て、仕入と送料は円建てなので、
    円高が進むほど手取りが減る。円建ての費用は為替で動かないため、
    分岐点は1本の式で出る。
    """
    tax = tax or TaxProfile()
    if price_usd <= 0:
        return float("inf")
    denom = 1.0 - _variable_rate(profile, level)
    if denom <= 0:
        return float("inf")
    fixed = _fixed_costs(profile, cost_incl_tax_jpy, tax, shipping_jpy)
    return fixed / denom / price_usd


def breakeven_duty_rate(
    price_usd: float,
    cost_incl_tax_jpy: float,
    profile: FeeProfile,
    *,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
) -> float:
    """利益がゼロになる関税率。

    米国の制度はこの半年で3回変わった。**いま何%まで耐えられるか**を
    出品ごとに持っておくと、制度変更のニュースを見た瞬間に手が打てる。
    """
    tax = tax or TaxProfile()
    price_jpy = price_usd * fx_jpy_per_usd
    if price_jpy <= 0:
        return 0.0
    fixed = _fixed_costs(profile, cost_incl_tax_jpy, tax, shipping_jpy)
    d = (price_jpy * (1.0 - effective_fee_rate(profile, level)) - fixed) / price_jpy
    return max(0.0, d)


@dataclass(frozen=True)
class ReturnImpact:
    """返品1件の損失と、耐えられる返品率。"""
    profit_per_sale_jpy: float
    loss_per_return_jpy: float
    tolerable_rate: float          # これを超えると期待値が赤字になる
    tolerable_one_in: float        # 「何件に1件まで」の表現
    item_recovered: bool

    @property
    def is_fragile(self) -> bool:
        """返品1件が売上数件分の利益を食う状態か。"""
        return self.profit_per_sale_jpy > 0 and (
            self.loss_per_return_jpy > self.profit_per_sale_jpy * 2
        )


def return_impact(
    price_usd: float,
    cost_incl_tax_jpy: float,
    profile: FeeProfile,
    *,
    return_shipping_jpy: float | None = None,
    seller_pays_return: bool = True,
    item_recovered: bool = True,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    shipping_jpy: float | None = None,
) -> ReturnImpact:
    """返品1件でいくら失い、何件に1件までなら黒字を保てるか。

    越境ECの返品は国内と桁が違う。**往復の国際送料が丸ごと損失になる**ためで、
    利益率20%の商品なら、返品1件で数件分の利益が消える。

    前提：
    - 落札手数料は返金時に戻る（eBayの原則）。注文ごと固定費は戻らない扱い。
    - ``item_recovered=True`` なら商品は手元に戻る＝原価は在庫として残る。
      戻らない（紛失・破損）場合は原価も損失に入る。
    - ``seller_pays_return=False``（バイヤー都合でバイヤーが返送料負担）なら
      返送料は損失に入らない。ただし**出した分の送料は戻らない。**
    """
    tax = tax or TaxProfile()
    b = compute(price_usd, cost_incl_tax_jpy, profile, fx_jpy_per_usd=fx_jpy_per_usd,
                level=level, tax=tax, shipping_jpy=shipping_jpy)

    out_ship = b.shipping_jpy
    back_ship = (out_ship if return_shipping_jpy is None else return_shipping_jpy)
    loss = out_ship + profile.packaging_jpy + profile.per_order_fee_jpy
    if seller_pays_return:
        loss += back_ship
    if not item_recovered:
        loss += cost_incl_tax_jpy - b.vat_refund_jpy

    profit = b.profit_jpy
    if profit <= 0:
        rate = 0.0
    else:
        rate = profit / (profit + loss)  # (1−r)·利益 − r·損失 = 0
    return ReturnImpact(
        profit_per_sale_jpy=profit,
        loss_per_return_jpy=loss,
        tolerable_rate=rate,
        tolerable_one_in=(1.0 / rate) if rate > 0 else float("inf"),
        item_recovered=item_recovered,
    )
