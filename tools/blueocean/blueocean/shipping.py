"""送料計算。重量と寸法から実際の課金重量を出し、配送手段を選ぶ。

これまで送料は市場ごとの固定値（米国3,000円など）で扱っていた。
実運用ではこれが最大の誤差源になる。理由は2つある。

1. **重量区切りで階段状に上がる。** 950gと1,050gでは料金が1段違う。
   梱包後に100g超えて1段上がると、そのまま利益から消える。
2. **寸法が効く。** 軽くて嵩張るもの（衣類・フィギュア・空箱付きの機材）は
   実重量ではなく **容積重量** で課金される。

    容積重量(g) = 縦cm × 横cm × 高さcm ÷ 除数 × 1000

   除数は配送手段ごとに違う（クーリエ 5,000／国際小包 6,000）。
   そして **EMSは容積重量を採らない（実重量のみ）** ため、
   「嵩張るが軽い」荷物ではEMSが逆転して最安になることがある。
   この逆転は固定値の送料では絶対に見えない。

------------------------------------------------------------------
料金値の扱いについて（重要）
------------------------------------------------------------------
このモジュールの料金テーブルは **調査時点のアンカー値と、その間の内挿** で
構成しています。各エントリの出典区分は ``RateTable.provenance`` に持たせました。

    OFFICIAL_ANCHOR : 公表値として確認できた金額
    INTERPOLATED    : アンカー間を刻み幅から内挿した推定値

**内挿値をそのまま仕入判断に使わないでください。**
日本郵便の公式料金表（https://www.post.japanpost.jp/cgi-charge/）で
実際に使う地帯・重量帯を確認し、``load_rate_table_csv()`` で差し替えて運用します。
差し替えれば、以下の計算構造（課金重量・階段料金・手段比較）はそのまま使えます。
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .models import Market


class Zone(str, Enum):
    """日本郵便の地帯区分（EMS・国際小包は5地帯）。

    2023年以降の改定で米国が独立した地帯になっている。
    米国宛てが他地域より高いのは、この構造上の理由による。
    """
    ZONE1 = "zone1"  # 中国・韓国・台湾
    ZONE2 = "zone2"  # アジア（第1地帯を除く）
    ZONE3 = "zone3"  # オセアニア・北米（米国を除く）・中近東・ヨーロッパ
    ZONE4 = "zone4"  # 米国（グアム等の海外領土を含む）
    ZONE5 = "zone5"  # 中南米・アフリカ


class Carrier(str, Enum):
    """配送手段。容積重量の扱いと上限が違うため、第一級の概念として持つ。"""
    EMS = "ems"                # 国際スピード郵便。容積重量なし（実重量のみ）
    PARCEL = "parcel"          # 国際小包（航空便）。容積重量あり（÷6,000）
    EPACKET = "epacket"        # 国際eパケット。2kgまで・小型限定だが安い
    COURIER = "courier"        # UGX / FedEx / DHL。容積重量あり（÷5,000）


# 容積重量の除数。None は「容積重量を採らない」ことを表す。
_VOLUMETRIC_DIVISOR: dict[Carrier, int | None] = {
    Carrier.EMS: None,     # ← ここが他手段との決定的な違い
    Carrier.PARCEL: 6000,
    Carrier.EPACKET: None,
    Carrier.COURIER: 5000,
}

# 手段ごとの重量上限（g）。超えたら見積もり対象から外す。
_MAX_WEIGHT_G: dict[Carrier, int] = {
    Carrier.EMS: 30000,
    Carrier.PARCEL: 30000,
    Carrier.EPACKET: 2000,
    Carrier.COURIER: 30000,
}

# 手段ごとの寸法制限（cm）。(最長辺, 長さ+胴回り, 三辺計) の順。None は制限なし。
# 嵩張る荷物は重量ではなく寸法で弾かれることが多いので、重量と同格で持つ。
_MAX_DIMS_CM: dict[Carrier, tuple[float | None, float | None, float | None]] = {
    Carrier.EMS: (150.0, 300.0, None),
    Carrier.PARCEL: (150.0, 300.0, None),
    Carrier.EPACKET: (60.0, None, 90.0),  # 小形包装物の枠。ここが一番きつい
    Carrier.COURIER: (274.0, 330.0, None),
}


class Provenance(str, Enum):
    """料金値の出典区分。推定値を実測値と混ぜないために持つ。"""
    OFFICIAL_ANCHOR = "official_anchor"
    INTERPOLATED = "interpolated"
    OPERATOR = "operator"  # 運用者が公式表から入力した値


@dataclass(frozen=True)
class Parcel:
    """発送する荷物。梱包**後**の値を入れること。

    寸法が未入力（0）の場合は容積重量を評価できないため、実重量で計算し、
    見積もりに警告を添える。黙って実重量で通すと、嵩張る商品で必ず外れる。
    """
    weight_g: int
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0

    @property
    def has_dimensions(self) -> bool:
        return min(self.length_cm, self.width_cm, self.height_cm) > 0

    @property
    def sum_dims_cm(self) -> float:
        """三辺計。小形包装物（eパケット）はこれで縛られる。"""
        return self.length_cm + self.width_cm + self.height_cm

    @property
    def longest_cm(self) -> float:
        return max(self.length_cm, self.width_cm, self.height_cm)

    @property
    def girth_cm(self) -> float:
        """長さ+胴回り。EMSは3m以内という制限がある。"""
        dims = sorted([self.length_cm, self.width_cm, self.height_cm], reverse=True)
        return dims[0] + 2 * (dims[1] + dims[2])

    def volumetric_weight_g(self, carrier: Carrier) -> int:
        """容積重量。容積重量を採らない手段では 0 を返す。"""
        divisor = _VOLUMETRIC_DIVISOR[carrier]
        if divisor is None or not self.has_dimensions:
            return 0
        cc = self.length_cm * self.width_cm * self.height_cm
        return int(math.ceil(cc / divisor * 1000.0))

    def chargeable_weight_g(self, carrier: Carrier) -> int:
        """課金重量＝実重量と容積重量の大きい方。ここが料金表の引数になる。"""
        return max(self.weight_g, self.volumetric_weight_g(carrier))


@dataclass(frozen=True)
class RateBreak:
    """重量区切り1段分。「max_weight_g まで jpy 円」を表す。"""
    max_weight_g: int
    jpy: float
    provenance: Provenance = Provenance.INTERPOLATED


@dataclass(frozen=True)
class RateTable:
    """1手段×1地帯の料金表。重量の昇順に並んだ階段。"""
    carrier: Carrier
    zone: Zone
    breaks: tuple[RateBreak, ...]

    def quote(self, chargeable_g: int) -> RateBreak | None:
        """課金重量を含む最初の段を返す。上限超過は None。"""
        for b in self.breaks:
            if chargeable_g <= b.max_weight_g:
                return b
        return None

    @property
    def max_weight_g(self) -> int:
        return self.breaks[-1].max_weight_g if self.breaks else 0


def _steps(
    anchors: dict[int, float],
    *,
    step_g: int,
    upto_g: int,
    increment: float,
) -> tuple[RateBreak, ...]:
    """アンカー値の間を一定の刻み幅で埋め、料金表を組み立てる。

    アンカーとして与えた重量は OFFICIAL_ANCHOR、埋めた分は INTERPOLATED として
    区別する。この区別を残さないと、推定値が事実として一人歩きする。
    """
    known = sorted(anchors)
    out: list[RateBreak] = []
    w = known[0]
    last_known_w, last_known_jpy = known[0], anchors[known[0]]
    while w <= upto_g:
        if w in anchors:
            last_known_w, last_known_jpy = w, anchors[w]
            out.append(RateBreak(w, anchors[w], Provenance.OFFICIAL_ANCHOR))
        else:
            n = (w - last_known_w) / step_g
            out.append(RateBreak(w, round(last_known_jpy + increment * n), Provenance.INTERPOLATED))
        w += step_g
    return tuple(out)


# ---------------------------------------------------------------------------
# 既定の料金表
#
# アンカー（公表値として確認できた金額）:
#   第2地帯 EMS  500g=2,150 / 600g=2,400 / 700g=2,650 / 800g=2,900 / 900g=3,150
#   第3地帯 EMS  500g=3,400 / 600g=3,650 / 700g=3,900 / 800g=4,150 / 900g=4,400
#                2,000g≒5,900
#   第4地帯 EMS  500g=4,180 / 600g=4,460 / 700g=4,740 / 800g=5,020
#
# 1kg超は250g刻み、アンカー間の刻み幅から内挿している。
# 運用前に公式料金表で差し替えること（load_rate_table_csv）。
# ---------------------------------------------------------------------------

def _ems_table(zone: Zone, anchors: dict[int, float], inc_100g: float, inc_250g: float) -> RateTable:
    fine = _steps(anchors, step_g=100, upto_g=1000, increment=inc_100g)
    base_1kg = fine[-1].jpy
    coarse = _steps(
        {1000: base_1kg}, step_g=250, upto_g=5000, increment=inc_250g
    )[1:]  # 1000g は fine と重複するので落とす
    # 1kg の段が内挿由来なら、その先も内挿として扱われる（_steps の既定）
    return RateTable(Carrier.EMS, zone, fine + coarse)


DEFAULT_EMS_TABLES: dict[Zone, RateTable] = {
    Zone.ZONE2: _ems_table(
        Zone.ZONE2,
        {500: 2150, 600: 2400, 700: 2650, 800: 2900, 900: 3150},
        inc_100g=250, inc_250g=200,
    ),
    Zone.ZONE3: _ems_table(
        Zone.ZONE3,
        {500: 3400, 600: 3650, 700: 3900, 800: 4150, 900: 4400},
        inc_100g=250, inc_250g=310,  # 1kg=4,650 → 2kg≒5,900 に整合する刻み
    ),
    Zone.ZONE4: _ems_table(
        Zone.ZONE4,
        {500: 4180, 600: 4460, 700: 4740, 800: 5020},
        inc_100g=280, inc_250g=350,
    ),
}
# 第1地帯は第2地帯より安いが確認できたアンカーが無いため、暫定で第2地帯を流用しない。
# 未定義の地帯は quote 時に明示的なエラーにする（黙って別地帯の値を使わない）。

# 手段ごとの倍率。EMS表を基準に、他手段の水準を相対で置く暫定値。
# これも運用前に実額で差し替える前提の値。
_CARRIER_FACTOR: dict[Carrier, float] = {
    Carrier.EMS: 1.00,
    Carrier.PARCEL: 0.80,   # 国際小包（航空）はEMSより安いが日数がかかる
    Carrier.EPACKET: 0.55,  # 2kg・小型限定
    Carrier.COURIER: 1.35,  # UGX / FedEx / DHL。米国宛ての実質的な代替手段
}


@dataclass(frozen=True)
class ShippingQuote:
    """送料見積もり1件。なぜその金額になったかを必ず開示する。"""
    carrier: Carrier
    zone: Zone
    actual_weight_g: int
    volumetric_weight_g: int
    chargeable_weight_g: int
    jpy: float
    provenance: Provenance
    warnings: tuple[str, ...] = ()

    @property
    def billed_by_volume(self) -> bool:
        """容積重量で課金されているか。ここが True の荷物は梱包を削る価値がある。"""
        return self.volumetric_weight_g > self.actual_weight_g


# 市場 → 地帯の対応
MARKET_ZONE: dict[Market, Zone] = {
    Market.EBAY_US: Zone.ZONE4,
    Market.EBAY_EU: Zone.ZONE3,
    Market.EBAY_AU: Zone.ZONE3,
    Market.SHOPEE_SEA: Zone.ZONE2,
}

# 米国宛ての引受停止と再開（2025-08 / 2026-04）。判断に効くので警告として出す。
US_POSTAL_NOTICE = (
    "米国宛て：2025年8月のデミニミス（$800免税）撤廃を受け、日本郵便は物品を含む"
    "小形包装物・国際小包・EMS(物品)の引受を一時停止した。2026年4月14日以降、"
    "米国税関が認証した事業者のアプリで関税を事前納付すれば指定郵便局で引受再開。"
    "その手当てが済んでいない間、米国宛ては UGX / FedEx / DHL で見積もること。"
)


class OverSize(ValueError):
    """寸法制限に引っかかったときのエラー。quote_all はこの手段を候補から外す。"""


def _check_dimensions(parcel: Parcel, carrier: Carrier) -> None:
    """寸法制限を検査する。未入力なら検査できないので素通しする（警告は estimate 側）。"""
    if not parcel.has_dimensions:
        return
    longest, girth, total = _MAX_DIMS_CM[carrier]
    if longest is not None and parcel.longest_cm > longest:
        raise OverSize(f"{carrier.value}: 最長辺 {parcel.longest_cm:.0f}cm が上限 {longest:.0f}cm を超過")
    if girth is not None and parcel.girth_cm > girth:
        raise OverSize(f"{carrier.value}: 長さ+胴回り {parcel.girth_cm:.0f}cm が上限 {girth:.0f}cm を超過")
    if total is not None and parcel.sum_dims_cm > total:
        raise OverSize(f"{carrier.value}: 三辺計 {parcel.sum_dims_cm:.0f}cm が上限 {total:.0f}cm を超過")


def _round_jpy(x: float) -> int:
    """円に丸める。**half-up で丸める**（Pythonの round() は偶数丸めなので使わない）。

    ブラウザ版は Math.round（half-up）なので、Pythonが偶数丸めのままだと
    ちょうど .5 になる料金で1円ずれ、その差が利益計算まで伝播する。
    実際 eパケットの倍率換算で 1182.5 のような値が出る。
    """
    return int(math.floor(x + 0.5))


class RateTableMissing(LookupError):
    """料金表が無い地帯を引いたときのエラー。別地帯の値で代用しない。"""


def estimate(
    parcel: Parcel,
    zone: Zone,
    carrier: Carrier = Carrier.EMS,
    *,
    tables: dict[Zone, RateTable] | None = None,
) -> ShippingQuote:
    """1手段の送料を見積もる。"""
    tables = tables or DEFAULT_EMS_TABLES
    table = tables.get(zone)
    if table is None:
        raise RateTableMissing(
            f"{zone.value} の料金表が未登録です。公式料金表から "
            f"load_rate_table_csv() で読み込んでください。"
        )

    _check_dimensions(parcel, carrier)
    chargeable = parcel.chargeable_weight_g(carrier)
    warnings: list[str] = []

    if not parcel.has_dimensions and _VOLUMETRIC_DIVISOR[carrier] is not None:
        warnings.append(
            "寸法が未入力のため容積重量を評価していない。嵩張る商品では実際の送料が上振れする"
        )

    limit = _MAX_WEIGHT_G[carrier]
    if chargeable > limit:
        raise ValueError(f"{carrier.value}: 課金重量 {chargeable}g が上限 {limit}g を超過")

    rb = table.quote(chargeable)
    if rb is None:
        raise ValueError(f"料金表の上限 {table.max_weight_g}g を超過（課金重量 {chargeable}g）")

    jpy = _round_jpy(rb.jpy * _CARRIER_FACTOR[carrier])
    prov = rb.provenance
    if _CARRIER_FACTOR[carrier] != 1.0 and prov is not Provenance.OPERATOR:
        prov = Provenance.INTERPOLATED  # 倍率換算した時点で推定値になる

    if zone is Zone.ZONE4 and carrier in (Carrier.EMS, Carrier.PARCEL, Carrier.EPACKET):
        warnings.append(US_POSTAL_NOTICE)

    if prov is Provenance.INTERPOLATED:
        warnings.append("料金は内挿による推定値。公式料金表で確認してから仕入判断に使うこと")

    return ShippingQuote(
        carrier=carrier,
        zone=zone,
        actual_weight_g=parcel.weight_g,
        volumetric_weight_g=parcel.volumetric_weight_g(carrier),
        chargeable_weight_g=chargeable,
        jpy=jpy,
        provenance=prov,
        warnings=tuple(warnings),
    )


def quote_all(
    parcel: Parcel,
    zone: Zone,
    *,
    carriers: tuple[Carrier, ...] = tuple(Carrier),
    tables: dict[Zone, RateTable] | None = None,
) -> list[ShippingQuote]:
    """使える手段をすべて見積もり、安い順に返す。

    嵩張る荷物では、容積重量を採らないEMSがクーリエを逆転する。
    その逆転をここで可視化するのが、この関数の目的。
    """
    out: list[ShippingQuote] = []
    for c in carriers:
        try:
            out.append(estimate(parcel, zone, c, tables=tables))
        except (ValueError, RateTableMissing):
            continue  # 重量・寸法の上限超過、料金表なしの手段は候補から外す
    return sorted(out, key=lambda q: q.jpy)


def cheapest(
    parcel: Parcel,
    zone: Zone,
    *,
    carriers: tuple[Carrier, ...] = tuple(Carrier),
    tables: dict[Zone, RateTable] | None = None,
) -> ShippingQuote | None:
    """最安の手段を返す。該当なしは None。"""
    qs = quote_all(parcel, zone, carriers=carriers, tables=tables)
    return qs[0] if qs else None


def shipping_jpy_for(
    parcel: Parcel,
    market: Market,
    *,
    carrier: Carrier | None = None,
    tables: dict[Zone, RateTable] | None = None,
) -> float | None:
    """利益計算に渡す送料を1つの数値で返す。carrier 未指定なら最安を選ぶ。"""
    zone = MARKET_ZONE[market]
    if carrier is not None:
        return estimate(parcel, zone, carrier, tables=tables).jpy
    q = cheapest(parcel, zone, tables=tables)
    return q.jpy if q else None


def load_rate_table_csv(path: str | Path, carrier: Carrier = Carrier.EMS) -> dict[Zone, RateTable]:
    """公式料金表を読み込んで既定値を差し替える。

    CSV: ``zone,max_weight_g,jpy``（1行=1段）。
    ここで読み込んだ値は Provenance.OPERATOR として扱い、推定値の警告を出さない。
    """
    buckets: dict[Zone, list[RateBreak]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            z = Zone(row["zone"].strip())
            buckets.setdefault(z, []).append(
                RateBreak(int(row["max_weight_g"]), float(row["jpy"]), Provenance.OPERATOR)
            )
    return {
        z: RateTable(carrier, z, tuple(sorted(bs, key=lambda b: b.max_weight_g)))
        for z, bs in buckets.items()
    }
