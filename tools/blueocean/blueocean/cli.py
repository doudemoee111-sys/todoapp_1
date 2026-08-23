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
from .shipping import (
    MARKET_ZONE,
    Carrier,
    Parcel,
    load_rate_table_csv,
    quote_all,
    shipping_jpy_for,
)
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


def _rate_tables(args):
    return load_rate_table_csv(args.rates) if args.rates else None


def cmd_axis1(args) -> int:
    candidates = load_candidates(args.candidates)
    scored = run_axis1(
        candidates, _source(args),
        market=Market(args.market),
        policy=ScoringPolicy(
            target_margin=args.target_margin,
            dynamic_shipping=not args.flat_shipping,
            carrier=Carrier(args.carrier) if args.carrier else None,
            rate_tables=_rate_tables(args),
        ),
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
    advisories: list[str] = []
    for s_ in scored:
        for w in s_.shipping_warnings:
            if w not in advisories:
                advisories.append(w)
    for w in advisories:
        print(f"\n[送料の注意] {w}")
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
    market = Market(args.market)
    level = SellerLevel(args.level)
    tax = TaxProfile(is_taxable_entity=not args.no_tax_refund)

    # 重量が指定されていれば、固定値ではなく実際の課金重量で送料を出す。
    ship = None
    note = ""
    if args.weight_g:
        parcel = Parcel(args.weight_g, args.length_cm, args.width_cm, args.height_cm)
        zone = MARKET_ZONE[market]
        quotes = quote_all(parcel, zone, tables=_rate_tables(args))
        if not quotes:
            print("この重量・寸法で使える配送手段がありません。", file=sys.stderr)
            return 1
        chosen = next(
            (q for q in quotes if args.carrier and q.carrier.value == args.carrier), quotes[0]
        )
        ship = chosen.jpy
        note = f"{chosen.carrier.value} / 課金重量 {chosen.chargeable_weight_g}g"
        print(f"\n--- 送料の比較（{zone.value}／実重量 {parcel.weight_g}g） ---")
        for q in quotes:
            mark = "*" if q is chosen else " "
            vol = f" 容積{q.volumetric_weight_g}g" if q.volumetric_weight_g else ""
            print(f" {mark} {q.carrier.value:<8} {q.jpy:>8,.0f}円  "
                  f"課金{q.chargeable_weight_g:>6}g{vol}")
        for w in chosen.warnings:
            print(f"   [注意] {w}")

    cap = max_cost_for_margin(
        args.price, args.target_margin, profile, level=level, tax=tax, shipping_jpy=ship
    )
    mult = required_multiple(
        args.price, args.target_margin, profile, level=level, tax=tax, shipping_jpy=ship
    )
    print(f"\n市場 {args.market} / セラーレベル {args.level} / 売価 ${args.price:.2f}")
    if ship is None:
        print("送料: プロファイル既定の概算値（--weight-g を渡すと実際の課金重量で計算します）")
    else:
        print(f"送料: {ship:,.0f} 円（{note}）")
    print(f"目標利益率 {args.target_margin*100:.0f}% を満たす仕入上限（税込）: {cap:,.0f} 円")
    print(f"必要な「売価 ÷ 仕入」倍率: {mult:.2f} 倍")
    if args.cost:
        b = compute(
            args.price, args.cost, profile, level=level, tax=tax,
            shipping_jpy=ship, shipping_note=note,
        )
        print("\n--- 内訳 ---")
        for k, v in b.as_row().items():
            print(f"  {k:<10} {v:>12}")
    return 0


def cmd_ship(args) -> int:
    """重量・寸法から送料を比較する。"""
    parcel = Parcel(args.weight_g, args.length_cm, args.width_cm, args.height_cm)
    zone = MARKET_ZONE[Market(args.market)]
    quotes = quote_all(parcel, zone, tables=_rate_tables(args))
    print(f"\n=== 送料見積もり（{args.market} = {zone.value}）===")
    print(f"実重量 {parcel.weight_g}g / 寸法 "
          f"{parcel.length_cm:.0f}x{parcel.width_cm:.0f}x{parcel.height_cm:.0f}cm"
          f"{'（未入力）' if not parcel.has_dimensions else ''}\n")
    if not quotes:
        print("使える配送手段がありません（重量または寸法の上限超過）。")
        return 1
    for q in quotes:
        vol = f"（容積 {q.volumetric_weight_g}g）" if q.volumetric_weight_g else ""
        flag = " ← 容積課金" if q.billed_by_volume else ""
        print(f"  {q.carrier.value:<8} {q.jpy:>8,.0f}円   課金重量 "
              f"{q.chargeable_weight_g:>6}g{vol}{flag}")
    seen = set()
    for w in quotes[0].warnings:
        if w not in seen:
            seen.add(w)
            print(f"\n  [注意] {w}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="blueocean", description="軸1＋軸2 統合ツール")
    p.add_argument("--market", default="ebay_us", choices=[m.value for m in Market])
    p.add_argument("--level", default="above_standard", choices=[s.value for s in SellerLevel])
    p.add_argument("--target-margin", type=float, default=0.20)
    p.add_argument("--no-tax-refund", action="store_true", help="免税事業者として計算する")
    p.add_argument("--ebay-client-id", default=None)
    p.add_argument("--ebay-client-secret", default=None)
    p.add_argument("--carrier", default=None, choices=[c.value for c in Carrier],
                   help="配送手段を固定する（既定は最安を自動選択）")
    p.add_argument("--rates", default=None,
                   help="公式料金表CSV（zone,max_weight_g,jpy）で既定の推定値を差し替える")
    p.add_argument("--flat-shipping", action="store_true",
                   help="送料を市場ごとの固定値で概算する（旧挙動）")
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
    m.add_argument("--weight-g", type=int, default=0, help="梱包後の実重量")
    m.add_argument("--length-cm", type=float, default=0.0)
    m.add_argument("--width-cm", type=float, default=0.0)
    m.add_argument("--height-cm", type=float, default=0.0)
    m.set_defaults(func=cmd_margin)

    sh = sub.add_parser("ship", help="重量・寸法から送料を比較する")
    sh.add_argument("--weight-g", type=int, required=True, help="梱包後の実重量")
    sh.add_argument("--length-cm", type=float, default=0.0)
    sh.add_argument("--width-cm", type=float, default=0.0)
    sh.add_argument("--height-cm", type=float, default=0.0)
    sh.set_defaults(func=cmd_ship)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
