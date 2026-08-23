"""軸1：リサーチの向きを逆にする。

既存ツールは「eBayの売れ筋 → 国内で探す」の逆算をするため、全員が同じ商品に
集まり価格競争になる。本モジュールは向きを逆にし、

    国内にある商品 → eBayにまだ出ていないものを判定 → 出品

という順序で候補を評価する。競合がいない商品には値下げ圧力がかからない。

ただし「競合ゼロ＝売れない」という可能性が常にある。そのため需要の裏付けが
無い候補は BLUE ではなく PROBE（少量で試す）に落とし、断定を避ける。
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Candidate,
    FeeProfile,
    Headroom,
    ProfitBreakdown,
    ScoredCandidate,
    SellerLevel,
    TaxProfile,
    Verdict,
)
from .pricing import list_price_for_margin
from .profit import compute, max_cost_for_margin
from .shipping import (
    MARKET_ZONE,
    Carrier,
    OverSize,
    Parcel,
    RateTable,
    RateTableMissing,
    Zone,
    cheapest,
    estimate,
)


@dataclass(frozen=True)
class ScoringPolicy:
    """判定の閾値。事業の性格をここに集約する。"""
    target_margin: float = 0.20
    blue_max_competitors: int = 5     # これ以下なら実質ブルーオーシャン
    red_min_competitors: int = 30     # これ以上は価格競争。見送る
    max_weight_g: int = 2000          # 重量物は送料で利益が消える
    min_price_usd: float = 30.0       # 低単価は手数料と送料に食われる
    fx_jpy_per_usd: float = 150.0
    # --- 送料の扱い ---
    # True にすると、重量・寸法から実際の送料を出して採算に反映する。
    # False（旧挙動）は市場ごとの固定値を使う概算。運用では True を使うこと。
    dynamic_shipping: bool = True
    carrier: Carrier | None = None    # None なら最安の手段を自動で選ぶ
    rate_tables: dict[Zone, RateTable] | None = None


def _quote_shipping(parcel: Parcel, profile: FeeProfile, policy: ScoringPolicy):
    """候補1件の送料を見積もる。使える手段が無ければ None。"""
    zone = MARKET_ZONE[profile.market]
    try:
        if policy.carrier is not None:
            return estimate(parcel, zone, policy.carrier, tables=policy.rate_tables)
        return cheapest(parcel, zone, tables=policy.rate_tables)
    except (OverSize, ValueError, RateTableMissing):
        return None


def score_one(
    c: Candidate,
    profile: FeeProfile,
    policy: ScoringPolicy | None = None,
    *,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
) -> ScoredCandidate:
    """候補1件を評価する。判定理由を必ず添えて返す。"""
    policy = policy or ScoringPolicy()
    reasons: list[str] = []

    cap = 0.0
    profit: ProfitBreakdown | None = None

    # 走査（discovery）が書き出した雛形は、仕入値も重量も空のまま流れてくる。
    # 仕入値0を「タダで買える」と解釈すると必ず BLUE になり、
    # 実体のない候補が最優先で並ぶ。未確定は未確定として扱う。
    cost_unknown = c.cost_incl_tax_jpy <= 0
    weight_unknown = c.weight_g <= 0

    # --- 1. 除外判定を最優先で行う（利益より先に安全性を見る） ---
    if c.is_restricted:
        reasons.append(f"除外：{c.restricted_reason or '輸出規制・禁止品'}")
        return ScoredCandidate(c, Verdict.EXCLUDE, 0.0, None, 0.0, reasons)

    # 重量の判定は「課金重量」で行う。実重量が軽くても嵩張れば送料は容積で決まる。
    parcel = Parcel(c.weight_g, c.length_cm, c.width_cm, c.height_cm)
    gate_carrier = policy.carrier or Carrier.PARCEL  # 容積を採る手段を基準に見る
    chargeable = parcel.chargeable_weight_g(gate_carrier)
    if chargeable > policy.max_weight_g:
        if chargeable > c.weight_g:
            reasons.append(
                f"除外：容積重量 {chargeable}g（実重量 {c.weight_g}g）が上限 "
                f"{policy.max_weight_g}g を超過。軽いが嵩張るため送料で採算が崩れる"
            )
        else:
            reasons.append(f"除外：重量 {c.weight_g}g が上限 {policy.max_weight_g}g を超過")
        return ScoredCandidate(c, Verdict.EXCLUDE, 0.0, None, 0.0, reasons)

    if c.market_price_usd is None:
        reasons.append("除外：eBay側の相場が未取得（Browse APIの結果が無い）")
        return ScoredCandidate(c, Verdict.EXCLUDE, 0.0, None, 0.0, reasons)

    if c.market_price_usd < policy.min_price_usd:
        reasons.append(
            f"除外：想定売価 ${c.market_price_usd:.0f} が下限 ${policy.min_price_usd:.0f} 未満"
        )
        return ScoredCandidate(c, Verdict.EXCLUDE, 0.0, None, 0.0, reasons)

    # --- 2. 送料の確定（採算より先に。送料が決まらないと採算は出せない） ---
    ship_jpy: float | None = None
    ship_note = ""
    ship_warnings: list[str] = []
    if policy.dynamic_shipping:
        quote = _quote_shipping(parcel, profile, policy)
        if quote is None:
            reasons.append(
                "除外：この重量・寸法で使える配送手段が無い（重量／寸法の上限超過）"
            )
            return ScoredCandidate(c, Verdict.EXCLUDE, 0.0, None, 0.0, reasons)
        ship_jpy = quote.jpy
        ship_note = (
            f"{quote.carrier.value} / 課金重量 {quote.chargeable_weight_g}g / "
            f"{quote.jpy:,.0f}円"
        )
        if quote.billed_by_volume:
            ship_note += f"（容積課金：実重量 {quote.actual_weight_g}g）"
            reasons.append(
                f"送料は容積重量 {quote.chargeable_weight_g}g で課金される"
                f"（実重量 {quote.actual_weight_g}g）。梱包を薄くすると直接効く"
            )
        if not parcel.has_dimensions:
            reasons.append("寸法が未入力のため送料は実重量ベースの下振れ値")
        # 見積もりに付いた注意書き（米国宛ての引受停止など）は握りつぶさないが、
        # 候補ごとに並べると読めなくなるので、判定理由とは別枠で持つ。
        ship_warnings = [w for w in quote.warnings if "寸法が未入力" not in w]

    # --- 3. 採算判定 ---
    cap = max_cost_for_margin(
        c.market_price_usd, policy.target_margin, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax,
        shipping_jpy=ship_jpy,
    )
    profit = compute(
        c.market_price_usd, c.cost_incl_tax_jpy, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax,
        shipping_jpy=ship_jpy, shipping_note=ship_note,
    )

    if cost_unknown:
        reasons.append(
            "仕入値が未入力。判定は相場と競合だけに基づく暫定値。"
            "国内で現物を見つけて cost_incl_tax_jpy を埋めるまで採算は確定しない"
        )
    elif c.cost_incl_tax_jpy > cap:
        over = c.cost_incl_tax_jpy - cap
        reasons.append(
            f"採算割れ：仕入 {c.cost_incl_tax_jpy:,.0f}円 が上限 {cap:,.0f}円 を "
            f"{over:,.0f}円 超過（実績利益率 {profit.margin*100:.1f}%）"
        )
        head = _headroom(c, cap, None, profile, policy, level, tax, ship_jpy)
        return ScoredCandidate(
            c, Verdict.THIN, 0.0, profit, cap, reasons, ship_warnings, head,
            _flip_hint(c, Verdict.THIN, head, policy, None),
        )

    # --- 4. 競合環境の判定（ここが軸1の核心） ---
    n = c.competitor_count
    if n is None:
        reasons.append("競合数が未取得のため PROBE に分類")
        verdict = Verdict.PROBE
    elif n >= policy.red_min_competitors:
        reasons.append(f"競合 {n}件。価格競争に巻き込まれるため見送り")
        head = _headroom(c, cap, n, profile, policy, level, tax, ship_jpy)
        return ScoredCandidate(
            c, Verdict.RED, 0.0, profit, cap, reasons, ship_warnings, head,
            _flip_hint(c, Verdict.RED, head, policy, n),
        )
    elif n == 0 and not c.has_demand_signal:
        # 競合ゼロは魅力的に見えるが、需要が無いだけの可能性がある。
        # ここを BLUE と誤判定すると、売れない在庫を仕入れることになる。
        reasons.append("競合0件だが需要の裏付けが無い。少量で反応を試す（軸2へ）")
        verdict = Verdict.PROBE
    elif n <= policy.blue_max_competitors:
        reasons.append(f"競合 {n}件。値下げ圧力を受けにくい")
        verdict = Verdict.BLUE if c.has_demand_signal else Verdict.PROBE
        if not c.has_demand_signal:
            reasons.append("需要の裏付けが無いため PROBE に据え置き")
    else:
        reasons.append(f"競合 {n}件。ブルーではないが致命的でもない")
        verdict = Verdict.PROBE

    # 仕入値が未確定なら BLUE と言い切らない。最良でも PROBE に留める。
    if cost_unknown and verdict is Verdict.BLUE:
        verdict = Verdict.PROBE
    if weight_unknown:
        reasons.append("重量が未入力。送料は最小重量帯の概算なので、実物が届いたら引き直すこと")

    if c.has_demand_signal and c.demand_note:
        reasons.append(f"需要の裏付け：{c.demand_note}")

    # --- 5. 何がこの判定を分けているか ---
    head = _headroom(c, cap, n, profile, policy, level, tax, ship_jpy)
    hint = _flip_hint(c, verdict, head, policy, n)

    # --- 6. スコア（並べ替え用の連続値） ---
    margin_term = min(profit.margin / policy.target_margin, 2.0) * 50.0
    comp_term = 50.0 / (1.0 + (n or 0))
    demand_term = 20.0 if c.has_demand_signal else 0.0
    weight_penalty = (chargeable / policy.max_weight_g) * 10.0
    score = max(0.0, margin_term + comp_term + demand_term - weight_penalty)

    return ScoredCandidate(c, verdict, round(score, 1), profit, cap, reasons,
                           ship_warnings, head, hint)


def _headroom(
    c: Candidate, cap: float, n: int | None, profile: FeeProfile,
    policy: ScoringPolicy, level: SellerLevel, tax: TaxProfile | None,
    ship_jpy: float | None,
) -> Headroom:
    """判定を分けている3変数の余裕を出す。

    「軸1の判定は何を基準に変わるのか」への答え。動かせるのは仕入値だけで、
    競合数と相場は他人が決める。だからこの3つを並べて見せる。
    """
    floor = list_price_for_margin(
        c.cost_incl_tax_jpy, policy.target_margin, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax, shipping_jpy=ship_jpy,
    )
    floor = None if floor == float("inf") else floor
    return Headroom(
        cost_room_jpy=cap - c.cost_incl_tax_jpy,
        competitor_room=(policy.red_min_competitors - n) if n is not None else None,
        price_floor_usd=floor,
        price_room_usd=((c.market_price_usd - floor)
                        if floor is not None and c.market_price_usd else None),
    )


def _flip_hint(
    c: Candidate, verdict: Verdict, head: Headroom, policy: ScoringPolicy, n: int | None
) -> str:
    """判定がどうすれば裏返るかを1行で返す。

    「この商品はなぜこの判定なのか」より、「何が変われば変わるのか」のほうが
    行動につながる。仕入値だけが自分で動かせる変数なので、そこを優先して書く。
    """
    if verdict is Verdict.BLUE:
        parts = []
        if head.competitor_room is not None:
            parts.append(f"競合があと{head.competitor_room}件増えると見送り")
        if head.price_room_usd is not None and head.price_floor_usd is not None:
            parts.append(f"相場が ${head.price_floor_usd:,.0f} まで下がると採算割れ")
        return "／".join(parts) if parts else "余裕あり"
    if verdict is Verdict.THIN:
        return (
            f"仕入をあと {abs(head.cost_room_jpy):,.0f}円 下げれば採算に乗る"
            + (f"／相場が ${head.price_floor_usd:,.0f} 以上に戻っても同じ"
               if head.price_floor_usd else "")
        )
    if verdict is Verdict.RED:
        if n is not None:
            return (
                f"競合が {policy.red_min_competitors - 1}件以下に減れば再評価。"
                f"ただし競合数は自分では動かせない"
            )
        return "競合数が取れれば再評価できる"
    if verdict is Verdict.PROBE:
        if not c.has_demand_signal:
            return "需要の裏付けが取れれば BLUE。少量で出して軸2で確かめる"
        if n is not None and n > policy.blue_max_competitors:
            return f"競合が {policy.blue_max_competitors}件以下に減れば BLUE"
        return "需要が確定すれば BLUE"
    return ""


def score_all(
    candidates: list[Candidate],
    profile: FeeProfile,
    policy: ScoringPolicy | None = None,
    **kw,
) -> list[ScoredCandidate]:
    """候補群を評価し、スコア降順で返す。"""
    scored = [score_one(c, profile, policy, **kw) for c in candidates]
    order = {Verdict.BLUE: 0, Verdict.PROBE: 1, Verdict.THIN: 2, Verdict.RED: 3, Verdict.EXCLUDE: 4}
    return sorted(scored, key=lambda s: (order[s.verdict], -s.score))
