"""コマンドライン。

    python -m blueocean.cli axis1 --candidates data/candidates.csv --out plan.csv
    python -m blueocean.cli axis2 --observations data/observations.csv
    python -m blueocean.cli margin --price 200 --market ebay_us
"""
from __future__ import annotations

import argparse
import sys

from .models import Market, SellerLevel, TaxProfile, Verdict
from .pipeline import (
    load_candidates,
    load_observations,
    run_axis1,
    run_axis2,
    write_listing_plan,
)
from .profit import DEFAULT_PROFILES, compute, max_cost_for_margin, required_multiple
from .scoring import ScoringPolicy
from .sources import MockSource

_ICON = {
    Verdict.BLUE: "BLUE ", Verdict.PROBE: "PROBE", Verdict.THIN: "THIN ",
    Verdict.RED: "RED  ", Verdict.EXCLUDE: "EXCL ",
}


def _source(args):
    if args.ebay_client_id and args.ebay_client_secret:
        from .sources.ebay_browse import EbayBrowseSource
        return EbayBrowseSource(args.ebay_client_id, args.ebay_client_secret)
    print("[注意] eBay認証情報が無いため MockSource で実行します。判断には使えません。",
          file=sys.stderr)
    return MockSource()


def cmd_axis1(args) -> int:
    candidates = load_candidates(args.candidates)
    scored = run_axis1(
        candidates, _source(args),
        market=Market(args.market),
        policy=ScoringPolicy(target_margin=args.target_margin),
        level=SellerLevel(args.level),
        tax=TaxProfile(is_taxable_entity=not args.no_tax_refund),
    )
    print(f"\n=== 軸1：出品候補の判定（{len(scored)}件）===\n")
    for s in scored:
        c = s.candidate
        margin = f"{s.profit.margin*100:5.1f}%" if s.profit else "  n/a"
        comp = f"{c.competitor_count:>4}" if c.competitor_count is not None else "   -"
        print(f"[{_ICON[s.verdict]}] {s.score:5.1f}  競合{comp}  利益率{margin}  {c.title_ja}")
        for r in s.reasons:
            print(f"           - {r}")
    if args.out:
        n = write_listing_plan(scored, args.out)
        print(f"\n出品候補 {n}件 を {args.out} に書き出しました。")
    return 0


def cmd_axis2(args) -> int:
    obs = load_observations(args.observations)
    decisions, alert = run_axis2(
        obs, total_orders=args.total_orders,
        seller_cancellations=args.seller_cancellations,
    )
    print(f"\n=== 軸2：出品後の判定（{len(decisions)}件）===\n")
    for d in decisions:
        print(f"[{d.action.value.upper():7}] {d.sku}  "
              f"{d.days_listed:>3}日 / 閲覧{d.views:>4} / ウォッチ{d.watchers:>3} / 販売{d.sold}")
        print(f"            {d.reason}")
    if alert:
        print(f"\n[警告] {alert}")
    return 0


def cmd_margin(args) -> int:
    profile = DEFAULT_PROFILES[Market(args.market)]
    level = SellerLevel(args.level)
    tax = TaxProfile(is_taxable_entity=not args.no_tax_refund)
    cap = max_cost_for_margin(args.price, args.target_margin, profile, level=level, tax=tax)
    mult = required_multiple(args.price, args.target_margin, profile, level=level, tax=tax)
    print(f"\n市場 {args.market} / セラーレベル {args.level} / 売価 ${args.price:.2f}")
    print(f"目標利益率 {args.target_margin*100:.0f}% を満たす仕入上限（税込）: {cap:,.0f} 円")
    print(f"必要な「売価 ÷ 仕入」倍率: {mult:.2f} 倍")
    if args.cost:
        b = compute(args.price, args.cost, profile, level=level, tax=tax)
        print("\n--- 内訳 ---")
        for k, v in b.as_row().items():
            print(f"  {k:<10} {v:>12}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="blueocean", description="軸1＋軸2 統合ツール")
    p.add_argument("--market", default="ebay_us", choices=[m.value for m in Market])
    p.add_argument("--level", default="above_standard", choices=[s.value for s in SellerLevel])
    p.add_argument("--target-margin", type=float, default=0.20)
    p.add_argument("--no-tax-refund", action="store_true", help="免税事業者として計算する")
    p.add_argument("--ebay-client-id", default=None)
    p.add_argument("--ebay-client-secret", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    a1 = sub.add_parser("axis1", help="出品候補を判定する")
    a1.add_argument("--candidates", required=True)
    a1.add_argument("--out", default=None)
    a1.set_defaults(func=cmd_axis1)

    a2 = sub.add_parser("axis2", help="出品後の反応から次の一手を決める")
    a2.add_argument("--observations", required=True)
    a2.add_argument("--total-orders", type=int, default=0)
    a2.add_argument("--seller-cancellations", type=int, default=0)
    a2.set_defaults(func=cmd_axis2)

    m = sub.add_parser("margin", help="仕入上限を逆算する")
    m.add_argument("--price", type=float, required=True)
    m.add_argument("--cost", type=float, default=None)
    m.set_defaults(func=cmd_margin)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
