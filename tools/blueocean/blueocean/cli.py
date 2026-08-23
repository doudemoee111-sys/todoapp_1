"""コマンドライン。

    python -m blueocean.cli axis1 --candidates data/candidates.csv --out plan.csv
    python -m blueocean.cli axis2 --observations data/observations.csv
    python -m blueocean.cli margin --price 200 --market ebay_us
"""
from __future__ import annotations

import argparse
import sys
import unicodedata

from .bundle import compare as compare_bundle
from .bundle import load_items
from .discovery import (
    GENRES,
    Mode,
    Opening,
    ScanPolicy,
    load_genres,
    load_keywords,
    scan_all,
    scan_genre,
    scan_one,
    write_candidate_template,
)
from .history import ChangeKind, history_of, load_snapshots
from .pricing import (
    breakeven_duty_rate,
    breakeven_fx,
    list_price_for_margin,
    offer_ladder,
    return_impact,
)
from .models import Market, SellerLevel, TaxProfile, Verdict
from .pipeline import (
    attach_titles,
    load_candidates,
    load_observations,
    run_axis1,
    run_axis1_with_history,
    run_axis2,
    write_listing_plan,
)
from .profit import DEFAULT_PROFILES, compute, max_cost_for_margin, required_multiple
from .models import Candidate
from .scoring import ScoringPolicy, score_one
from .shipping import (
    MARKET_ZONE,
    Carrier,
    Parcel,
    cheapest,
    load_rate_table_csv,
    quote_all,
    shipping_jpy_for,
)
from .sources import MockSource

_ICON = {
    Verdict.BLUE: "BLUE ", Verdict.PROBE: "PROBE", Verdict.THIN: "THIN ",
    Verdict.RED: "RED  ", Verdict.EXCLUDE: "EXCL ",
}

# 表示幅を揃えるため、すべて全角4文字にしてある
_OPENING_ICON = {
    Opening.OPEN: "空き  ", Opening.PROBE: "要検証", Opening.CROWDED: "過密  ",
    Opening.LOW_VALUE: "低単価", Opening.NO_DATA: "取得失敗",
}

_CHANGE_ICON = {
    ChangeKind.DOWNGRADE: "判定悪化", ChangeKind.CAP_BREACH: "採算割れ",
    ChangeKind.UPGRADE: "判定改善", ChangeKind.CAP_ROOM: "採算回復",
    ChangeKind.COMPETITORS: "競合変動", ChangeKind.PRICE: "相場変動",
    ChangeKind.NEW: "新規追加", ChangeKind.GONE: "候補消滅",
}


def _pad(text: str, width: int, *, right: bool = False) -> str:
    """全角を2桁として揃える。日本語の見出しを含む表がずれるのを防ぐ。"""
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    fill = " " * max(0, width - w)
    return fill + text if right else text + fill


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
    kw = dict(
        market=Market(args.market),
        policy=ScoringPolicy(
            target_margin=args.target_margin,
            dynamic_shipping=not args.flat_shipping,
            carrier=Carrier(args.carrier) if args.carrier else None,
            rate_tables=_rate_tables(args),
        ),
        level=SellerLevel(args.level),
        tax=TaxProfile(is_taxable_entity=not args.no_tax_refund),
        refresh=args.refresh,
    )
    changes, stale = [], None
    if args.history:
        scored, changes, stale = run_axis1_with_history(
            candidates, _source(args), args.history, record=not args.no_record, **kw
        )
    else:
        scored = run_axis1(candidates, _source(args), **kw)

    if stale:
        print(f"\n[鮮度の警告] {stale}")

    if args.history:
        actionable = [c for c in changes if c.is_actionable]
        others = [c for c in changes if not c.is_actionable]
        print(f"\n=== 前回からの変化（{len(changes)}件 / うち要対応 {len(actionable)}件）===\n")
        if not changes:
            print("  変化なし。")
        for c in actionable + others:
            print(f"[{_CHANGE_ICON[c.kind]}] {c.sku:<12} {c.detail}")
            if c.action:
                print(f"             → {c.action}")
        if args.changes_only:
            return 0

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


_ACTION_GUIDE = [
    ("PROMOTE", "当たり。無在庫をやめて手元に仕入れ、発送を1〜2日に縮める"),
    ("REPRICE", "見られてはいる。価格が合っていないので下げるか送料込みにする"),
    ("RETITLE", "そもそも見られていない。英語の検索語を組み直す"),
    ("DROP   ", "反応が無い。出品を畳んで枠を空ける"),
    ("KEEP   ", "まだ判断できない。観察を続ける"),
]


def cmd_axis2(args) -> int:
    obs = load_observations(args.observations)
    if args.candidates:
        n = attach_titles(obs, load_candidates(args.candidates))
        if n:
            print(f"[情報] 候補CSVから商品名を {n}件 結合しました。", file=sys.stderr)

    decisions, alert = run_axis2(
        obs, total_orders=args.total_orders,
        seller_cancellations=args.seller_cancellations,
    )

    print("\n=== 軸2：出品後の判定 ===")
    print("\n出品した商品の反応から「次の一手」を決めます。まだ出品していない商品は対象外です。")
    print("上から順に、対応が必要なものが並びます。\n")
    for label, meaning in _ACTION_GUIDE:
        print(f"  {label}  {meaning}")

    print(f"\n--- 判定（{len(decisions)}件）---\n")
    for d in decisions:
        print(f"[{d.action.value.upper():7}] {d.label}")
        print(f"          SKU {d.sku} / 出品から{d.days_listed}日 / "
              f"閲覧{d.views} / ウォッチ{d.watchers} / 販売{d.sold}")
        print(f"          {d.reason}")
        if d.delta:
            mark = "  ← 停滞" if d.delta.is_stalled else ""
            print(f"          {d.delta.as_text()}{mark}")
        print()
    if not any(d.title for d in decisions):
        print("[ヒント] 商品名が出ていません。観測CSVに title 列を足すか、"
              "--candidates で候補CSVを渡すと商品名で表示されます。")
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


def _policy(args) -> ScoringPolicy:
    return ScoringPolicy(
        target_margin=args.target_margin,
        dynamic_shipping=not args.flat_shipping,
        carrier=Carrier(args.carrier) if args.carrier else None,
        rate_tables=_rate_tables(args),
    )


def _genres(args) -> dict:
    g = dict(GENRES)
    if args.genre_file:
        g.update(load_genres(args.genre_file))
    return g


def cmd_scan(args) -> int:
    """キーワード空間を走査し、eBayに出ていない型番を洗い出す。

    候補リストを前提にしないので、「リストに無いものは見つからない」問題が起きない。
    ジャンルを指定した場合は、シリーズ×形態に展開してから走査する。
    """
    if args.list_genres:
        print("\n=== 使えるジャンル ===\n")
        for k, g in _genres(args).items():
            print(f"  {k:<14} {g.label}")
            print(f"                 展開後 {len(g.expand(Mode.BOTH))}クエリ"
                  f"（単品 {len(g.expand(Mode.SINGLE))} / セット {len(g.expand(Mode.SET))}）")
        return 0

    genre = None
    if args.genre:
        gs = _genres(args)
        if args.genre not in gs:
            print(f"ジャンル {args.genre} は未定義です。--list-genres で一覧を見てください。",
                  file=sys.stderr)
            return 1
        genre = gs[args.genre]
        keywords = None
    else:
        keywords = load_keywords(args.keywords) if args.keywords else args.keyword
        if not keywords:
            print("--keywords / --keyword / --genre のいずれかを指定してください。",
                  file=sys.stderr)
            return 1

    market = Market(args.market)
    assume = Parcel(args.assume_weight_g, args.assume_length_cm,
                    args.assume_width_cm, args.assume_height_cm)
    common = dict(
        policy=ScanPolicy.from_scoring(_policy(args)),
        level=SellerLevel(args.level),
        tax=TaxProfile(is_taxable_entity=not args.no_tax_refund),
        assume=assume,
    )

    if genre is not None:
        report = scan_genre(
            genre, _source(args), DEFAULT_PROFILES[market],
            common.pop("policy"), mode=Mode(args.mode), limit=args.limit, **common,
        )
        results = report.results
        print(f"\n=== ジャンル走査：{genre.label} ===")
        print(f"\n展開したクエリ {len(results)}本（{args.mode}）。"
              f"ジャンル全体の出品数は {report.total_listings:,}件ですが、"
              f"**この数字は判定に使えません**。")
        print("広い語では自分の1点が埋もれるかどうか分からないので、"
              "掛け合わせて粒度を落としたクエリ1本ずつの競合数を見ます。")
        for c in genre.cautions:
            print(f"\n  [このジャンルの注意] {c}")
        if report.set_results:
            sw = [r for r in report.set_results if r.is_hunt_worthy]
            print(f"\n  まとめ売り側のスライス {len(report.set_results)}本 "
                  f"（うち探す価値あり {len(sw)}本）。"
                  f"採算は bundle サブコマンドで確かめてください。")
    else:
        results = scan_all(
            keywords, _source(args), DEFAULT_PROFILES[market], **common
        )

    worthy = [r for r in results if r.is_hunt_worthy]
    print(f"\n=== 走査結果（{len(results)}件 / 探す価値あり {len(worthy)}件）===")
    print(f"送料の仮定: {assume.weight_g}g"
          f"{f' / {assume.length_cm:.0f}x{assume.width_cm:.0f}x{assume.height_cm:.0f}cm' if assume.has_dimensions else '（寸法なし）'}\n")
    print(f"{_pad('', 8)}{_pad('競合', 6, right=True)} {_pad('相場', 9, right=True)} "
          f"{_pad('仕入上限', 11, right=True)} {_pad('倍率', 7, right=True)}  キーワード")
    shown = results if args.all else results[:args.top]
    for r in shown:
        price = f"${r.median_price_usd:>7.0f}" if r.median_price_usd else "        -"
        cap = f"{r.max_cost_jpy:>10,.0f}円" if r.max_cost_jpy else "         -"
        mult = f"{r.required_multiple:>6.2f}倍" if r.required_multiple != float("inf") else "      -"
        print(f"[{_OPENING_ICON[r.opening]}]{r.competitor_count:>6} {price} {cap} {mult}  {r.keyword}")
    if len(shown) < len(results):
        print(f"  … 他 {len(results) - len(shown)}件（--all で全件、--top N で件数指定）")

    print("\n--- 探す価値がある上位 ---")
    for r in worthy[:8]:
        print(f"  {r.keyword}")
        print(f"    予算 {r.max_cost_jpy:,.0f}円まで（この額を超える値札は、その場で見送れる）")
        print(f"    {r.note}")
    if not worthy:
        print("  該当なし。キーワードの粒度を変えてください（型番まで絞る／ブランド単位に広げる）")

    if args.out:
        n = write_candidate_template(results, args.out)
        print(f"\n候補CSVの雛形 {n}件 を {args.out} に書き出しました。")
        print("国内で現物を見つけたら cost_incl_tax_jpy / weight_g / 寸法 を書き足して axis1 に流してください。")
    return 0


def cmd_check(args) -> int:
    """1件だけをその場で判定する。候補CSVも履歴も要らない。

    店頭やフリマアプリを見ている最中に「これは買いか」を即答するための口。
    バッチ判定にはどうしてもタイムラグが出るが、こちらは問い合わせた瞬間の値で判定する。
    """
    market = Market(args.market)
    c = Candidate(
        sku=args.sku or "CHECK",
        title_ja=args.title,
        source_url=args.url or "",
        cost_incl_tax_jpy=args.cost,
        weight_g=args.weight_g,
        length_cm=args.length_cm,
        width_cm=args.width_cm,
        height_cm=args.height_cm,
        category=args.category or "",
        market_price_usd=args.price_usd,
        competitor_count=args.competitors,
        has_demand_signal=args.demand,
        demand_note=args.demand_note or "",
    )
    if c.market_price_usd is None or c.competitor_count is None:
        snap = _source(args).snapshot(args.title)
        if c.competitor_count is None:
            c.competitor_count = snap.competitor_count
        if c.market_price_usd is None:
            c.market_price_usd = snap.median_price_usd

    s_ = score_one(
        c, DEFAULT_PROFILES[market], _policy(args),
        level=SellerLevel(args.level),
        tax=TaxProfile(is_taxable_entity=not args.no_tax_refund),
    )

    price = f"${c.market_price_usd:.0f}" if c.market_price_usd else "取得できず"
    print(f"\n=== {c.title_ja} ===")
    print(f"\n  判定       [{_ICON[s_.verdict].strip()}]")
    print(f"  eBay相場   {price} / 競合 {c.competitor_count}件")
    print(f"  仕入上限   {s_.max_cost_jpy:,.0f}円（税込）")
    if args.cost:
        room = s_.max_cost_jpy - args.cost
        # ここは採算だけの話。競合や規制で見送りになることは判定の側に出る
        label = "採算は取れる" if room >= 0 else "採算割れ"
        print(f"  仕入 {args.cost:,.0f}円 → {label}（上限まで {room:+,.0f}円）")
    print()
    for r in s_.reasons:
        print(f"  - {r}")
    if s_.profit:
        print("\n  --- 内訳 ---")
        for k, v in s_.profit.as_row().items():
            print(f"    {_pad(k, 10)} {v:>12}")
    for w in s_.shipping_warnings:
        print(f"\n  [送料の注意] {w}")
    return 0


def cmd_price(args) -> int:
    """仕入れた後の値決め。出品価格・値下げ耐性・感度・返品の影響をまとめて出す。"""
    profile = DEFAULT_PROFILES[Market(args.market)]
    level = SellerLevel(args.level)
    tax = TaxProfile(is_taxable_entity=not args.no_tax_refund)

    ship = None
    ship_note = "プロファイル既定の概算値"
    if args.weight_g:
        parcel = Parcel(args.weight_g, args.length_cm, args.width_cm, args.height_cm)
        q = cheapest(parcel, MARKET_ZONE[Market(args.market)], tables=_rate_tables(args))
        if q is None:
            print("この重量・寸法で使える配送手段がありません。", file=sys.stderr)
            return 1
        ship, ship_note = q.jpy, f"{q.carrier.value} / 課金重量 {q.chargeable_weight_g}g"

    kw = dict(fx_jpy_per_usd=args.fx, level=level, tax=tax, shipping_jpy=ship)
    listed = args.price_usd or list_price_for_margin(
        args.cost, args.target_margin, profile, **kw
    )
    if listed == float("inf"):
        print("手数料＋関税＋目標利益率が100%を超えています。目標を下げてください。",
              file=sys.stderr)
        return 1

    b = compute(listed, args.cost, profile, **kw)
    print(f"\n=== 値決め（仕入 {args.cost:,.0f}円 / {args.market}）===")
    print(f"\n送料 {b.shipping_jpy:,.0f}円（{ship_note}） / 為替 {args.fx:.0f}円")
    if args.price_usd:
        print(f"\n  出品価格（指定）      ${listed:,.2f}  → 利益 {b.profit_jpy:,.0f}円"
              f"（利益率 {b.margin*100:.1f}%）")
    else:
        print(f"\n  出品価格              ${listed:,.2f}"
              f"（目標利益率 {args.target_margin*100:.0f}%）")

    print("\n--- Best Offer をどこまで受けられるか ---\n")
    print(f"{_pad('利益率', 8)}{_pad('受諾価格', 12, right=True)}"
          f"{_pad('手取り', 12, right=True)}{_pad('値引き', 10, right=True)}")
    # 出品価格より高い段は Best Offer の文脈では意味がないので落とす
    for st in offer_ladder(args.cost, profile, list_price_usd=listed, **kw):
        if st.discount_from_list is not None and st.discount_from_list < -1e-9:
            continue
        disc = f"{st.discount_from_list*100:>6.0f}%" if st.discount_from_list is not None else "     -"
        profit = 0.0 if abs(st.profit_jpy) < 0.5 else st.profit_jpy
        print(f"{_pad(f'{st.margin*100:.0f}%', 8)}{_pad(f'${st.price_usd:,.2f}', 12, right=True)}"
              f"{_pad(f'{profit:,.0f}円', 12, right=True)}{_pad(disc, 10, right=True)}")
    print("\n  出品時にこの表を控えておくと、Best Offer にその場で返事ができます。")

    fx0 = breakeven_fx(listed, args.cost, profile, level=level, tax=tax, shipping_jpy=ship)
    d0 = breakeven_duty_rate(listed, args.cost, profile, **kw)
    print("\n--- どこまで環境が悪化しても耐えられるか ---\n")
    print(f"  為替    {fx0:,.1f}円/USD を下回ると赤字"
          f"（いま {args.fx:.0f}円。あと {args.fx - fx0:,.1f}円の余裕）")
    print(f"  関税    {d0*100:.1f}% を超えると赤字"
          f"（いま {profile.duty_rate*100:.1f}%。あと {(d0 - profile.duty_rate)*100:.1f}ポイントの余裕）")

    r = return_impact(
        listed, args.cost, profile,
        return_shipping_jpy=args.return_shipping_jpy,
        seller_pays_return=not args.buyer_pays_return,
        item_recovered=not args.item_lost, **kw,
    )
    print("\n--- 返品されたら ---\n")
    print(f"  1件あたりの損失      {r.loss_per_return_jpy:,.0f}円"
          f"（往復の送料＋梱包＋注文ごと固定費{'' if r.item_recovered else '＋戻らない原価'}）")
    print(f"  売れた1件の利益      {r.profit_per_sale_jpy:,.0f}円")
    if r.tolerable_one_in == float("inf"):
        print("  許容できる返品率      0%（この出品はそもそも赤字）")
    else:
        print(f"  許容できる返品率      {r.tolerable_rate*100:.1f}%"
              f"（{r.tolerable_one_in:.1f}件に1件まで）")
    if r.is_fragile:
        print("\n  [注意] 返品1件で売上2件分以上の利益が消えます。"
              "説明文と状態表記を厚くして、返品そのものを減らすほうが早い。")
    return 0


def cmd_bundle(args) -> int:
    """セット販売（まとめ売り）の採算を、個別売却と並べて出す。"""
    items = load_items(args.items)
    if not items:
        print("構成品がありません。", file=sys.stderr)
        return 1

    packing = None
    if args.pack_weight_g:
        packing = Parcel(args.pack_weight_g, args.pack_length_cm,
                         args.pack_width_cm, args.pack_height_cm)
    profile = DEFAULT_PROFILES[Market(args.market)]
    c = compare_bundle(
        items, args.set_price, profile,
        packing=packing, extra_weight_g=args.extra_weight_g,
        fx_jpy_per_usd=150.0, level=SellerLevel(args.level),
        tax=TaxProfile(is_taxable_entity=not args.no_tax_refund),
        tables=_rate_tables(args),
        carrier=Carrier(args.carrier) if args.carrier else None,
    )

    print(f"\n=== セット販売の採算（{len(items)}点 / {args.market}）===\n")
    print(f"{_pad('構成品', 34)}{_pad('仕入', 10, right=True)}"
          f"{_pad('重量', 8, right=True)}{_pad('単品相場', 11, right=True)}")
    for it in items:
        solo = f"${it.solo_price_usd:>7.0f}" if it.sells_alone else "  単品不可"
        print(f"{_pad(it.name, 34)}{it.cost_incl_tax_jpy:>9,.0f}円"
              f"{it.weight_g:>6,}g {solo:>10}")

    print()
    keys = list(c.separate.as_row().keys())
    print(f"{_pad('', 12)}" + "".join(_pad(k, 11, right=True) for k in keys))
    for res in (c.separate, c.bundled):
        row = res.as_row()
        print(f"{_pad(res.label, 12)}"
              + "".join(_pad(f"{v:,}" if isinstance(v, (int, float)) else str(v), 11, right=True)
                        for v in row.values()))

    sign = "＋" if c.delta_profit_jpy >= 0 else "−"
    print(f"\n  セットにすると利益が {sign}{abs(c.delta_profit_jpy):,.0f}円")
    print(f"  損益分岐のセット売価  ${c.breakeven_usd:,.0f}"
          f"（これを下回るならセットにする意味がない）")
    if c.solo_total_usd:
        d = c.discount_vs_solo or 0.0
        print(f"  単品売価の合計        ${c.solo_total_usd:,.0f}"
              f"（いまの ${c.set_price_usd:,.0f} は {d*100:+.0f}% の割引）")
    print(f"  判定                  {'セットにする価値あり' if c.worth_bundling else 'セットにする意味がない'}")

    print()
    for n in c.notes:
        print(f"  - {n}")
    return 0


def cmd_history(args) -> int:
    """1つのSKU、または全体の推移を表示する。"""
    snaps = load_snapshots(args.history)
    if not snaps:
        print(f"履歴がありません（{args.history}）。"
              f"axis1 に --history を付けて実行すると作られます。", file=sys.stderr)
        return 1
    if args.sku:
        rows = history_of(snaps, args.sku)
        if not rows:
            print(f"SKU {args.sku} の履歴がありません。", file=sys.stderr)
            return 1
        print(f"\n=== {args.sku} の推移（{len(rows)}件）===\n")
        print(f"{_pad('日付', 12)} {_pad('判定', 7)} {_pad('競合', 5, right=True)} "
              f"{_pad('相場', 8, right=True)} {_pad('仕入上限', 10, right=True)} "
              f"{_pad('利益率', 7, right=True)}")
        for r in rows:
            comp = f"{r.competitor_count:>5}" if r.competitor_count is not None else "    -"
            price = f"${r.market_price_usd:>7.0f}" if r.market_price_usd else "       -"
            margin = f"{r.margin*100:>6.1f}%" if r.margin is not None else "      -"
            print(f"{r.taken_on:<12} {r.verdict.upper():<7} {comp} {price} "
                  f"{r.max_cost_jpy:>10,.0f} {margin}")
        return 0

    dates = sorted({s.taken_on for s in snaps})
    print(f"\n=== 履歴の概要 ===\n")
    print(f"取得日: {len(dates)}回（{dates[0]} 〜 {dates[-1]}）")
    print(f"SKU数 : {len({s.sku for s in snaps})}")
    print(f"記録数: {len(snaps)}\n")
    print("直近の取得日ごとの判定内訳:")
    for d in dates[-5:]:
        counts: dict[str, int] = {}
        for s_ in snaps:
            if s_.taken_on == d:
                counts[s_.verdict] = counts.get(s_.verdict, 0) + 1
        line = " / ".join(f"{k.upper()} {v}" for k, v in sorted(counts.items()))
        print(f"  {d}  {line}")
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
    a1.add_argument("--history", default=None,
                    help="履歴JSONL。指定すると前回からの変化を出し、今回の結果を追記する")
    a1.add_argument("--refresh", action="store_true",
                    help="CSVに値があってもeBay側を取り直す（定期更新はこれを使う）")
    a1.add_argument("--no-record", action="store_true",
                    help="履歴に追記せず、差分の確認だけを行う")
    a1.add_argument("--changes-only", action="store_true",
                    help="変化だけを表示し、全件の判定は省く")
    a1.set_defaults(func=cmd_axis1)

    sc = sub.add_parser("scan", help="キーワード空間を走査して、eBayに出ていない型番を洗い出す")
    sc.add_argument("--keywords", default=None, help="キーワード一覧ファイル（1行1件、#でコメント）")
    sc.add_argument("--keyword", action="append", default=[], help="キーワードを直接渡す（複数可）")
    sc.add_argument("--out", default=None, help="候補CSVの雛形を書き出す")
    sc.add_argument("--assume-weight-g", type=int, default=500, help="送料の仮定（実重量）")
    sc.add_argument("--assume-length-cm", type=float, default=0.0)
    sc.add_argument("--assume-width-cm", type=float, default=0.0)
    sc.add_argument("--assume-height-cm", type=float, default=0.0)
    sc.add_argument("--genre", default=None,
                    help="ジャンルを展開して走査する（--list-genres で一覧）")
    sc.add_argument("--genre-file", default=None, help="独自のジャンル定義JSON")
    sc.add_argument("--list-genres", action="store_true")
    sc.add_argument("--mode", default="both", choices=[m.value for m in Mode],
                    help="single=単品 / set=まとめ売り / both")
    sc.add_argument("--limit", type=int, default=None, help="展開するクエリ数の上限")
    sc.add_argument("--top", type=int, default=25, help="表示件数")
    sc.add_argument("--all", action="store_true", help="全件表示する")
    sc.set_defaults(func=cmd_scan)

    pr = sub.add_parser("price", help="仕入れた後の値決め（出品価格・値下げ耐性・感度・返品）")
    pr.add_argument("--cost", type=float, required=True, help="仕入価格（円・税込）")
    pr.add_argument("--price-usd", type=float, default=None,
                    help="出品価格を指定する（省略時は目標利益率から順算）")
    pr.add_argument("--fx", type=float, default=150.0)
    pr.add_argument("--weight-g", type=int, default=0)
    pr.add_argument("--length-cm", type=float, default=0.0)
    pr.add_argument("--width-cm", type=float, default=0.0)
    pr.add_argument("--height-cm", type=float, default=0.0)
    pr.add_argument("--return-shipping-jpy", type=float, default=None,
                    help="返送料（省略時は往路と同額とみなす）")
    pr.add_argument("--buyer-pays-return", action="store_true",
                    help="返送料をバイヤーが負担する前提で計算する")
    pr.add_argument("--item-lost", action="store_true",
                    help="商品が戻らない前提（紛失・破損）で計算する")
    pr.set_defaults(func=cmd_price)

    bu = sub.add_parser("bundle", help="セット販売の採算を個別売却と並べる")
    bu.add_argument("--items", required=True, help="構成品CSV")
    bu.add_argument("--set-price", type=float, required=True, help="セットの想定売価（USD）")
    bu.add_argument("--pack-weight-g", type=int, default=0, help="梱包後のセット全体の実重量")
    bu.add_argument("--pack-length-cm", type=float, default=0.0)
    bu.add_argument("--pack-width-cm", type=float, default=0.0)
    bu.add_argument("--pack-height-cm", type=float, default=0.0)
    bu.add_argument("--extra-weight-g", type=int, default=0,
                    help="梱包材の重量（実測を渡さない場合の上乗せ）")
    bu.set_defaults(func=cmd_bundle)

    ck = sub.add_parser("check", help="1件だけをその場で判定する")
    ck.add_argument("--title", required=True, help="eBayでの検索語（英語）")
    ck.add_argument("--cost", type=float, default=0.0, help="仕入価格（円・税込）")
    ck.add_argument("--weight-g", type=int, default=500)
    ck.add_argument("--length-cm", type=float, default=0.0)
    ck.add_argument("--width-cm", type=float, default=0.0)
    ck.add_argument("--height-cm", type=float, default=0.0)
    ck.add_argument("--price-usd", type=float, default=None, help="相場を手で指定する（省略時はAPI）")
    ck.add_argument("--competitors", type=int, default=None, help="競合数を手で指定する")
    ck.add_argument("--demand", action="store_true", help="需要の裏付けがある")
    ck.add_argument("--demand-note", default=None)
    ck.add_argument("--sku", default=None)
    ck.add_argument("--url", default=None)
    ck.add_argument("--category", default=None)
    ck.set_defaults(func=cmd_check)

    hi = sub.add_parser("history", help="履歴を表示する")
    hi.add_argument("--history", required=True)
    hi.add_argument("--sku", default=None, help="指定するとそのSKUの推移を表示する")
    hi.set_defaults(func=cmd_history)

    a2 = sub.add_parser("axis2", help="出品後の反応から次の一手を決める")
    a2.add_argument("--observations", required=True)
    a2.add_argument("--candidates", default=None,
                    help="候補CSV。SKUで結合して商品名を表示する")
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
