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
    ProfitBreakdown,
    ScoredCandidate,
    SellerLevel,
    TaxProfile,
    Verdict,
)
from .profit import compute, max_cost_for_margin


@dataclass(frozen=True)
class ScoringPolicy:
    """判定の閾値。事業の性格をここに集約する。"""
    target_margin: float = 0.20
    blue_max_competitors: int = 5     # これ以下なら実質ブルーオーシャン
    red_min_competitors: int = 30     # これ以上は価格競争。見送る
    max_weight_g: int = 2000          # 重量物は送料で利益が消える
    min_price_usd: float = 30.0       # 低単価は手数料と送料に食われる
    fx_jpy_per_usd: float = 150.0


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

    # --- 1. 除外判定を最優先で行う（利益より先に安全性を見る） ---
    if c.is_restricted:
        reasons.append(f"除外：{c.restricted_reason or '輸出規制・禁止品'}")
        return ScoredCandidate(c, Verdict.EXCLUDE, 0.0, None, 0.0, reasons)

    if c.weight_g > policy.max_weight_g:
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

    # --- 2. 採算判定 ---
    cap = max_cost_for_margin(
        c.market_price_usd, policy.target_margin, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax,
    )
    profit = compute(
        c.market_price_usd, c.cost_incl_tax_jpy, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax,
    )

    if c.cost_incl_tax_jpy > cap:
        over = c.cost_incl_tax_jpy - cap
        reasons.append(
            f"採算割れ：仕入 {c.cost_incl_tax_jpy:,.0f}円 が上限 {cap:,.0f}円 を "
            f"{over:,.0f}円 超過（実績利益率 {profit.margin*100:.1f}%）"
        )
        return ScoredCandidate(c, Verdict.THIN, 0.0, profit, cap, reasons)

    # --- 3. 競合環境の判定（ここが軸1の核心） ---
    n = c.competitor_count
    if n is None:
        reasons.append("競合数が未取得のため PROBE に分類")
        verdict = Verdict.PROBE
    elif n >= policy.red_min_competitors:
        reasons.append(f"競合 {n}件。価格競争に巻き込まれるため見送り")
        return ScoredCandidate(c, Verdict.RED, 0.0, profit, cap, reasons)
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

    if c.has_demand_signal and c.demand_note:
        reasons.append(f"需要の裏付け：{c.demand_note}")

    # --- 4. スコア（並べ替え用の連続値） ---
    margin_term = min(profit.margin / policy.target_margin, 2.0) * 50.0
    comp_term = 50.0 / (1.0 + (n or 0))
    demand_term = 20.0 if c.has_demand_signal else 0.0
    weight_penalty = (c.weight_g / policy.max_weight_g) * 10.0
    score = max(0.0, margin_term + comp_term + demand_term - weight_penalty)

    return ScoredCandidate(c, verdict, round(score, 1), profit, cap, reasons)


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
