"""セット販売（まとめ売り）の採算。

提案④の補論で「軸5：セット化・キュレーションで比較不能にする」として挙げたものを、
数字で判断できるようにする。

セット販売が効く理由は、実は「比較されない」だけではない。**原価構造が変わる。**

    個別に5点売る            セットで5点売る
      注文 5件                 注文 1件
      送料 5回                 送料 1回（重量は合算される）
      注文ごと固定費 5回        1回
      梱包 5回                 1回

**送料が1回で済むことが最大の効き目**で、これは単価の低い商品ほど効く。
$30の商品を単品で出すと送料と手数料で利益が消えるが、5点まとめて$150にすれば
送料は1回分になる。**単品では採算に乗らない商品が、セットでは乗る。**

もう一つ大きいのが**死に筋の処理**。単品では売れない在庫を、売れ筋に混ぜて出す。
単品売却の期待値がゼロの品は、セットに入れた時点で原価の回収が始まる。

ただし無条件に有利ではない。

1. **重量が合算されて送料の段が上がる。** 200g×5点は1,000gで、
   単品5回分より安いとは限るが、段が2つ上がれば節約は目減りする。
2. **買い手はまとめ買いに割引を期待する。** 単品合計と同額では売れない。
3. **セットは検索にかかりにくい。** 比較されない代わりに、見つけられもしない。
   だから軸2（出品後の反応を見る）が単品以上に重要になる。

このモジュールは「個別に売った場合」と「セットで売った場合」を同じ計算式で並べ、
差額と損益分岐のセット売価を出す。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .models import FeeProfile, SellerLevel, TaxProfile
from .profit import compute, effective_fee_rate
from .shipping import MARKET_ZONE, Carrier, Parcel, RateTable, Zone, cheapest


@dataclass
class BundleItem:
    """セットの構成品1点。"""
    name: str
    cost_incl_tax_jpy: float
    weight_g: int
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
    # 単品でeBayに出したときの想定売価。None は「単品では売れない見込み」を表す。
    # 死に筋をセットに混ぜる効果を測るために、この区別が要る。
    solo_price_usd: float | None = None

    @property
    def sells_alone(self) -> bool:
        return self.solo_price_usd is not None and self.solo_price_usd > 0

    @property
    def parcel(self) -> Parcel:
        return Parcel(self.weight_g, self.length_cm, self.width_cm, self.height_cm)


@dataclass
class SaleResult:
    """売り方1つぶんの結果。個別とセットを同じ形で並べるために使う。"""
    label: str
    orders: int              # 発生する注文件数
    revenue_jpy: float
    fees_jpy: float
    duty_jpy: float
    shipping_jpy: float
    packaging_jpy: float
    cost_jpy: float          # セットに入れた全点の原価（売れ残り分も含む）
    vat_refund_jpy: float
    profit_jpy: float
    unsold: list[str] = field(default_factory=list)  # 単品では売れない見込みの品

    @property
    def margin(self) -> float:
        return self.profit_jpy / self.revenue_jpy if self.revenue_jpy else 0.0

    def as_row(self) -> dict:
        return {
            "注文件数": self.orders,
            "売上": round(self.revenue_jpy),
            "手数料": -round(self.fees_jpy),
            "関税": -round(self.duty_jpy),
            "送料": -round(self.shipping_jpy),
            "梱包": -round(self.packaging_jpy),
            "仕入": -round(self.cost_jpy),
            "消費税還付": round(self.vat_refund_jpy),
            "利益": round(self.profit_jpy),
            "利益率": f"{self.margin * 100:.1f}%",
        }


def _ship(parcel: Parcel, profile: FeeProfile, tables: dict[Zone, RateTable] | None,
          carrier: Carrier | None) -> tuple[float, bool]:
    """1梱包分の送料と、実際に見積もれたかどうかを返す。

    見積もれない場合（重量・寸法が上限超過、料金表の範囲外）は
    プロファイルの固定値に落ちる。**この事実を隠すと、重いセットほど
    送料が安く見えてしまう**（固定値のほうが安いため）。だから真偽値で返す。
    """
    zone = MARKET_ZONE[profile.market]
    try:
        if carrier is not None:
            from .shipping import estimate
            return estimate(parcel, zone, carrier, tables=tables).jpy, True
        from .shipping import POSTAL_CARRIERS
        pool = (POSTAL_CARRIERS + (Carrier.SLS,)) if profile.market.is_shopee else POSTAL_CARRIERS
        q = cheapest(parcel, zone, carriers=pool, tables=tables)
        return (q.jpy, True) if q else (profile.shipping_jpy, False)
    except (ValueError, LookupError):
        return profile.shipping_jpy, False


def sell_separately(
    items: list[BundleItem],
    profile: FeeProfile,
    *,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    tables: dict[Zone, RateTable] | None = None,
    carrier: Carrier | None = None,
) -> SaleResult:
    """1点ずつ売った場合。

    単品では売れない見込みの品（``solo_price_usd`` が無い）は**売れないものとして扱う。**
    売上は立たないが原価は残る。ここを「いつか売れる」と数えると、
    セット化の効果を過小評価することになる。
    """
    tax = tax or TaxProfile()
    total = dict(revenue=0.0, fees=0.0, duty=0.0, ship=0.0, pack=0.0, refund=0.0, profit=0.0)
    orders = 0
    unsold: list[str] = []
    dead_cost = 0.0

    for it in items:
        if not it.sells_alone:
            unsold.append(it.name)
            dead_cost += it.cost_incl_tax_jpy
            continue
        ship, _ = _ship(it.parcel, profile, tables, carrier)
        b = compute(
            it.solo_price_usd, it.cost_incl_tax_jpy, profile,
            fx_jpy_per_usd=fx_jpy_per_usd, level=level, tax=tax, shipping_jpy=ship,
        )
        orders += 1
        total["revenue"] += b.price_jpy
        total["fees"] += b.fees_jpy
        total["duty"] += b.duty_jpy
        total["ship"] += b.shipping_jpy
        total["pack"] += b.packaging_jpy
        total["refund"] += b.vat_refund_jpy
        total["profit"] += b.profit_jpy

    return SaleResult(
        label="個別に売る",
        orders=orders,
        revenue_jpy=total["revenue"],
        fees_jpy=total["fees"],
        duty_jpy=total["duty"],
        shipping_jpy=total["ship"],
        packaging_jpy=total["pack"],
        cost_jpy=sum(i.cost_incl_tax_jpy for i in items),
        vat_refund_jpy=total["refund"],
        # 売れ残りの原価を引く。ここを引かないとセットとの比較が成立しない
        profit_jpy=total["profit"] - dead_cost,
        unsold=unsold,
    )


def pack_bundle(items: list[BundleItem], *, packing: Parcel | None = None,
                extra_weight_g: int = 0) -> Parcel:
    """セット全体の荷姿。

    ``packing`` を渡せば実測値を使う。渡さない場合は重量を合算し、
    寸法は評価しない（＝実重量ベースの下振れ値になる）。
    まとめ売りは箱が大きくなりやすく容積重量で課金されやすいので、
    **実測値を渡すのが望ましい。**
    """
    if packing is not None:
        return packing
    return Parcel(sum(i.weight_g for i in items) + extra_weight_g)


def sell_as_bundle(
    items: list[BundleItem],
    set_price_usd: float,
    profile: FeeProfile,
    *,
    packing: Parcel | None = None,
    extra_weight_g: int = 0,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    tables: dict[Zone, RateTable] | None = None,
    carrier: Carrier | None = None,
) -> SaleResult:
    """1つのセットとして売った場合。注文も送料も梱包も1回になる。"""
    tax = tax or TaxProfile()
    parcel = pack_bundle(items, packing=packing, extra_weight_g=extra_weight_g)
    ship, _ = _ship(parcel, profile, tables, carrier)
    cost = sum(i.cost_incl_tax_jpy for i in items)
    b = compute(
        set_price_usd, cost, profile,
        fx_jpy_per_usd=fx_jpy_per_usd, level=level, tax=tax, shipping_jpy=ship,
    )
    return SaleResult(
        label="セットで売る",
        orders=1,
        revenue_jpy=b.price_jpy,
        fees_jpy=b.fees_jpy,
        duty_jpy=b.duty_jpy,
        shipping_jpy=b.shipping_jpy,
        packaging_jpy=b.packaging_jpy,
        cost_jpy=b.cost_jpy,
        vat_refund_jpy=b.vat_refund_jpy,
        profit_jpy=b.profit_jpy,
    )


def breakeven_set_price_usd(
    items: list[BundleItem],
    profile: FeeProfile,
    *,
    packing: Parcel | None = None,
    extra_weight_g: int = 0,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    tables: dict[Zone, RateTable] | None = None,
    carrier: Carrier | None = None,
) -> float:
    """個別売却と同じ利益を出すのに必要なセット売価。

    **これを下回る価格でしか売れないなら、セットにする意味がない。**
    逆にこれが単品合計よりずっと低ければ、割引して出しても個別より儲かる
    ＝セット化が効いている。

    P を売価（円）とすると
        利益 = P − P·f − c − P·d − S − K − C + C·k
    なので、目標利益 G に対して
        P = (G + c + S + K + C − C·k) / (1 − f − d)
    """
    tax = tax or TaxProfile()
    target = sell_separately(
        items, profile, fx_jpy_per_usd=fx_jpy_per_usd, level=level, tax=tax,
        tables=tables, carrier=carrier,
    ).profit_jpy

    parcel = pack_bundle(items, packing=packing, extra_weight_g=extra_weight_g)
    ship, _ = _ship(parcel, profile, tables, carrier)
    cost = sum(i.cost_incl_tax_jpy for i in items)
    k = (tax.consumption_tax_rate / (1 + tax.consumption_tax_rate)
         if tax.is_taxable_entity else 0.0)
    f = effective_fee_rate(profile, level)
    d = profile.duty_rate

    denom = 1.0 - f - d
    if denom <= 0:
        return float("inf")
    numer = (target + profile.per_order_fee_jpy + ship + profile.packaging_jpy
             + cost - cost * k)
    return max(0.0, numer / denom / fx_jpy_per_usd)


@dataclass(frozen=True)
class BundleComparison:
    """個別とセットの比較。判断に必要なものだけを並べる。"""
    separate: SaleResult
    bundled: SaleResult
    breakeven_usd: float
    set_price_usd: float
    solo_total_usd: float          # 単品売価の合計（割引前の上限の目安）
    shipping_saved_jpy: float
    chargeable_weight_g: int
    billed_by_volume: bool
    shipping_quotable: bool = True   # セットの送料を実際に見積もれたか
    notes: list[str] = field(default_factory=list)

    @property
    def delta_profit_jpy(self) -> float:
        return self.bundled.profit_jpy - self.separate.profit_jpy

    @property
    def discount_vs_solo(self) -> float | None:
        """単品合計に対する割引率。買い手が納得する水準かを見る。"""
        if not self.solo_total_usd:
            return None
        return 1.0 - self.set_price_usd / self.solo_total_usd

    @property
    def worth_bundling(self) -> bool:
        """セット売価が分岐点を上回るか。

        送料を見積もれていない場合は、この判定自体が甘い方向に外れる。
        """
        return self.set_price_usd >= self.breakeven_usd


def compare(
    items: list[BundleItem],
    set_price_usd: float,
    profile: FeeProfile,
    *,
    packing: Parcel | None = None,
    extra_weight_g: int = 0,
    fx_jpy_per_usd: float = 150.0,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    tables: dict[Zone, RateTable] | None = None,
    carrier: Carrier | None = None,
) -> BundleComparison:
    """個別売却とセット売却を並べ、判断材料を返す。"""
    kw = dict(fx_jpy_per_usd=fx_jpy_per_usd, level=level, tax=tax,
              tables=tables, carrier=carrier)
    sep = sell_separately(items, profile, **kw)
    bun = sell_as_bundle(items, set_price_usd, profile,
                         packing=packing, extra_weight_g=extra_weight_g, **kw)
    be = breakeven_set_price_usd(items, profile, packing=packing,
                                 extra_weight_g=extra_weight_g, **kw)

    parcel = pack_bundle(items, packing=packing, extra_weight_g=extra_weight_g)
    zone = MARKET_ZONE[profile.market]
    from .shipping import POSTAL_CARRIERS
    pool = (POSTAL_CARRIERS + (Carrier.SLS,)) if profile.market.is_shopee else POSTAL_CARRIERS
    q = cheapest(parcel, zone, carriers=pool, tables=tables)
    chargeable = q.chargeable_weight_g if q else parcel.weight_g
    by_volume = bool(q and q.billed_by_volume)
    _, quotable = _ship(parcel, profile, tables, carrier)

    solo_total = sum(i.solo_price_usd or 0.0 for i in items)
    notes: list[str] = []

    if sep.unsold:
        notes.append(
            f"単品では売れない見込みの品が {len(sep.unsold)}点（{', '.join(sep.unsold)}）。"
            f"セットに混ぜた時点で原価の回収が始まる"
        )
    if not quotable:
        notes.append(
            f"このセット（課金重量 {chargeable:,}g）に使える配送手段が料金表に無いため、"
            f"送料はプロファイルの固定値 {profile.shipping_jpy:,.0f}円 で計算した。"
            f"実際はもっと高くなる。点数を減らすか、クーリエの実額を入れて計算し直すこと"
        )
    saved = sep.shipping_jpy - bun.shipping_jpy
    if saved > 0 and quotable:
        notes.append(
            f"送料が {sep.orders}回 → 1回 になり {saved:,.0f}円 浮く。"
            f"単価の低い品ほどこの効き目が大きい"
        )
    elif quotable:
        notes.append(
            f"送料は減らない（個別 {sep.shipping_jpy:,.0f}円 → セット {bun.shipping_jpy:,.0f}円）。"
            f"重量が合算されて段が上がっている。点数を減らすか、軽い品で組み直す"
        )
    if by_volume:
        notes.append(
            f"セットの送料は容積重量 {chargeable}g で課金される"
            f"（実重量 {parcel.weight_g}g）。箱を詰めれば直接効く"
        )
    if not parcel.has_dimensions:
        notes.append(
            "セットの寸法が未入力。まとめ売りは箱が大きくなり容積重量で課金されやすいので、"
            "実測値を入れて計算し直すこと"
        )
    if solo_total and set_price_usd > solo_total:
        notes.append(
            f"セット売価 ${set_price_usd:.0f} が単品合計 ${solo_total:.0f} を超えている。"
            f"買い手はまとめ買いに割引を期待するので、この価格では動かない"
        )
    notes.append(
        "セットは価格比較されない代わりに、検索にもかかりにくい。"
        "出品後は軸2で反応を見て、動かなければタイトルの語を組み直すこと"
    )

    return BundleComparison(
        separate=sep, bundled=bun, breakeven_usd=be, set_price_usd=set_price_usd,
        solo_total_usd=solo_total, shipping_saved_jpy=saved,
        chargeable_weight_g=chargeable, billed_by_volume=by_volume,
        shipping_quotable=quotable, notes=notes,
    )


def load_items(path: str | Path) -> list[BundleItem]:
    """構成品CSVを読む。``solo_price_usd`` が空なら「単品では売れない」扱い。"""
    out: list[BundleItem] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            price = str(row.get("solo_price_usd", "")).strip()
            out.append(BundleItem(
                name=row["name"].strip(),
                cost_incl_tax_jpy=float(row.get("cost_incl_tax_jpy") or 0),
                weight_g=int(float(row.get("weight_g") or 0)),
                length_cm=float(row.get("length_cm") or 0),
                width_cm=float(row.get("width_cm") or 0),
                height_cm=float(row.get("height_cm") or 0),
                solo_price_usd=float(price) if price else None,
            ))
    return out
