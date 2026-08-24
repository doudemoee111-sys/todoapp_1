"""コマンドライン。

    python -m blueocean.cli axis1 --candidates data/candidates.csv --out plan.csv
    python -m blueocean.cli axis2 --observations data/observations.csv
    python -m blueocean.cli margin --price 200 --market ebay_us
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

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
from .extract import (
    FIELDS,
    ExtractSpec,
    Severity,
    Tier,
    read_worksheet,
    selling_side_urls,
    source_urls,
    summarize,
    to_candidates,
    validate,
    write_worksheet,
)
from . import domestic as dom
from .history import ChangeKind, history_of, load_snapshots
from .ingest import merge_observations, read_report, write_observations
from .jobs import JobError, load_jobs, run_job
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
from .shopee import (
    LISTING_LIMITS,
    RepriceAction,
    RepricePolicy,
    load_listings,
    plan_reprice,
    plan_slots,
    write_mass_upload,
    write_reprice_plan,
)
from .shipping import (
    DEFAULT_CARRIER,
    MARKET_ZONE,
    SLS_NOTICE,
    Carrier,
    Parcel,
    cheapest,
    estimate,
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


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int, *, right: bool = False, trunc: bool = False) -> str:
    """全角を2桁として揃える。日本語の見出しを含む表がずれるのを防ぐ。

    ``trunc=True`` なら幅を超えた分を切る。商品名のように長さが読めないものは
    切らないと列が崩れる。
    """
    if trunc and _width(text) > width:
        out, used = "", 0
        for ch in text:
            w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
            if used + w > width - 1:
                break
            out, used = out + ch, used + w
        text = out + "…"
    w = _width(text)
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


def _carrier(args) -> Carrier | None:
    """使う配送手段。Shopeeは自分で国際発送しないので SLS に固定する。

    ここを「最安を自動」のままにすると、実際には選べない手段（eパケット等）で
    採算を出してしまう。
    """
    if args.carrier:
        return Carrier(args.carrier)
    return DEFAULT_CARRIER.get(Market(args.market))


def cmd_axis1(args) -> int:
    candidates = load_candidates(args.candidates)
    kw = dict(
        market=Market(args.market),
        policy=_policy(args),
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
        if s.flip_hint:
            print(f"           ↕ {s.flip_hint}")
        if c.search_url:
            print(f"           ▸ 写真で照合: {c.search_url}")
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
    if args.sheet:
        from .contactsheet import from_scored, write as write_sheet
        n = write_sheet(
            from_scored(scored), args.sheet,
            title="出品候補の現物照合シート",
            note="国内で探すときに、この写真と見比べてください。型番が同じでも世代違いがあります。",
        )
        print(f"現物照合シート {n}件 を {args.sheet} に書き出しました（ブラウザで開いてください）。")
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
        market=Market(args.market),
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
        want = _carrier(args)
        chosen = next((q for q in quotes if want and q.carrier is want), quotes[0])
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
        if chosen.carrier is Carrier.SLS:
            print(f"   [注意] {SLS_NOTICE}")

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
    """市場ごとの既定値から作る。下限価格や配送手段が市場で違うため。"""
    kw = dict(
        target_margin=args.target_margin,
        dynamic_shipping=not args.flat_shipping,
        rate_tables=_rate_tables(args),
    )
    if args.carrier:
        kw["carrier"] = Carrier(args.carrier)
    return ScoringPolicy.for_market(Market(args.market), **kw)


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
        if r.search_url:
            print(f"    写真で照合: {r.search_url}")
    if not worthy:
        print("  該当なし。キーワードの粒度を変えてください（型番まで絞る／ブランド単位に広げる）")

    if args.sheet:
        from .contactsheet import from_scan, write as write_sheet
        n = write_sheet(
            from_scan(results), args.sheet,
            title="探しに行く型番の現物照合シート",
            note="予算を超える値札はその場で見送れます。写真と見比べてから買ってください。",
        )
        print(f"\n現物照合シート {n}件 を {args.sheet} に書き出しました（ブラウザで開いてください）。")
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
        want = _carrier(args)
        zone = MARKET_ZONE[Market(args.market)]
        try:
            q = (estimate(parcel, zone, want, tables=_rate_tables(args))
                 if want else cheapest(parcel, zone, tables=_rate_tables(args)))
        except (ValueError, LookupError):
            q = None
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
        print(f"{_pad(it.name, 34, trunc=True)}{it.cost_incl_tax_jpy:>9,.0f}円"
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


_REPRICE_ICON = {
    RepriceAction.STOP: "止める", RepriceAction.RAISE: "値上げ",
    RepriceAction.LOWER: "下げ余地", RepriceAction.HOLD: "据え置き",
}


_SEV_ICON = {Severity.ERROR: "要修正", Severity.WARN: "注意  ", Severity.INFO: "情報  "}
_TIER_ICON = {Tier.REQUIRED: "必須", Tier.RECOMMENDED: "推奨", Tier.EDGE: "★一歩先"}


def _spec(args) -> ExtractSpec:
    return ExtractSpec(
        name=args.name or "extract",
        keywords=args.keyword or [],
        category=args.category or "",
        market=Market(args.market),
        max_cost_jpy=args.max_cost,
        max_weight_g=args.max_weight_g,
        target_margin=args.target_margin,
    )


def cmd_extract(args) -> int:
    """抽出の設計と受け皿。**巡回はしない。人が開いて、人が採る。**"""
    if args.what == "fields":
        print("\n=== 抽出する項目 ===\n")
        for tier in (Tier.REQUIRED, Tier.RECOMMENDED, Tier.EDGE):
            group = [f for f in FIELDS if f.tier is tier]
            print(f"--- {_TIER_ICON[tier]}（{len(group)}項目）---\n")
            for f in group:
                print(f"  {_pad(f.label, 26, trunc=True)} {f.key}")
                print(f"    {f.why}")
                if f.example:
                    print(f"    例: {f.example}")
                print()
        print("★ の項目は、国内せどりの定石（価格安定×セラー少ない×ランク良い×Amazon不在）に")
        print("   入っていないもの。輸出では効くのに、採っている人が少ないところです。")
        return 0

    if args.what == "urls":
        spec = _spec(args)
        if not spec.keywords:
            print("--keyword を1つ以上指定してください。", file=sys.stderr)
            return 1
        print(f"\n=== 開く検索ページ（{len(spec.keywords)}語）===")
        print("\n  自動では開きません。**人が開いて、人が採ります。**")
        if spec.category:
            print(f"  Amazonは「{spec.category}」部門に絞ってあります。")
        print("  価格帯・状態の絞り込みは、各サイトの画面でかけてください"
              "（URLに載せると仕様変更で黙って壊れます）。")
        for kw in spec.keywords:
            print(f"\n  --- {kw} ---")
            print("  [仕入側]")
            for link in source_urls(spec):
                if link.keyword == kw:
                    print(f"    {_pad(link.label, 22, trunc=True)} {link.url}")
            print("  [販売側]")
            for link in selling_side_urls(spec):
                if link.keyword == kw:
                    print(f"    {_pad(link.label, 22, trunc=True)} {link.url}")
        return 0

    if args.what == "sheet":
        tiers = ((Tier.REQUIRED, Tier.RECOMMENDED, Tier.EDGE) if not args.minimal
                 else (Tier.REQUIRED,))
        n = write_worksheet(args.out or "extract-sheet.csv", _spec(args), include=tiers)
        path = args.out or "extract-sheet.csv"
        print(f"\n抽出用シート（{n}列）を {path} に書き出しました。")
        print("2〜4行目に「列の意味・なぜ要るか・記入例」を入れてあります。")
        print("そのまま残して埋めても、消して埋めても構いません（読み込み時に飛ばします）。")
        return 0

    # --- check ---
    rows = read_worksheet(args.sheet)
    if not rows:
        print(f"{args.sheet} に記入済みの行がありません。", file=sys.stderr)
        return 1
    issues = validate(rows, _spec(args))
    counts = summarize(issues)
    print(f"\n=== 検品（{len(rows)}行）===\n")
    print(f"  要修正 {counts[Severity.ERROR]}件 / 注意 {counts[Severity.WARN]}件\n")
    shown = [i for i in issues if args.all or i.severity is Severity.ERROR]
    for i in shown[:args.top]:
        print(f"[{_SEV_ICON[i.severity]}] {_pad(i.sku, 16, trunc=True)} {i.message}")
    if len(shown) > args.top:
        print(f"  … 他 {len(shown) - args.top}件（--top N で増やせます）")
    if not issues:
        print("  問題は見つかりませんでした。")

    if args.out:
        cands = to_candidates(rows)
        from .pipeline import Candidate  # noqa: F401  型の確認用
        import csv as _csv

        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["sku", "title_ja", "source_url", "cost_incl_tax_jpy", "weight_g",
                        "length_cm", "width_cm", "height_cm", "category",
                        "market_price_usd", "competitor_count", "has_demand_signal",
                        "demand_note", "is_restricted", "restricted_reason"])
            for c in cands:
                w.writerow([c.sku, c.title_ja, c.source_url, round(c.cost_incl_tax_jpy),
                            c.weight_g, c.length_cm or "", c.width_cm or "",
                            c.height_cm or "", c.category,
                            f"{c.market_price_usd:.2f}" if c.market_price_usd else "",
                            c.competitor_count if c.competitor_count is not None else "",
                            "yes" if c.has_demand_signal else "no", c.demand_note,
                            "yes" if c.is_restricted else "no", c.restricted_reason])
        print(f"\n  候補CSV {len(cands)}件 を {args.out} に書き出しました。")
        print(f"    python -m blueocean.cli axis1 --candidates {args.out} で判定できます。")
    return 1 if counts[Severity.ERROR] else 0


def cmd_shopee(args) -> int:
    """Shopee専用の一括運用。枠の管理と価格差の定期確認。"""
    market = Market(args.market)
    if not market.is_shopee:
        print(f"--market に Shopee の市場を指定してください"
              f"（{', '.join(m.value for m in LISTING_LIMITS)}）", file=sys.stderr)
        return 1
    profile = DEFAULT_PROFILES[market]
    tax = TaxProfile(is_taxable_entity=not args.no_tax_refund)
    level = SellerLevel(args.level)

    if args.what == "slots":
        decisions = []
        if args.observations:
            obs = load_observations(args.observations)
            decisions, _ = run_axis2(obs, market=market)
        scored = []
        if args.candidates:
            scored = run_axis1(load_candidates(args.candidates), _source(args),
                               market=market, policy=_policy(args),
                               level=level, tax=tax)
        plan = plan_slots(
            market, listed=args.listed, preorder_listed=args.preorder_listed,
            decisions=decisions, scored=scored, tier=args.tier,
        )
        print(f"\n=== 出品枠（{market.label} / {args.tier}）===\n")
        print(f"  出品枠            {plan.listed:>6,} / {plan.limit:,}点"
              f"（残り {plan.room:,}点）")
        print(f"  プレオーダー枠    {plan.preorder_listed:>6,} / {plan.preorder_limit:,}点"
              f"（残り {plan.preorder_room:,}点）")
        if plan.forced_removals:
            print(f"  自動削除される数  {plan.forced_removals:>6,}点  ← 自分で選ばないと機械に選ばれます")
        print(f"\n  落とす候補（軸2のDROP）  {len(plan.drop):>4}点")
        for t in plan.drop[:8]:
            print(f"    - {t}")
        print(f"  入れる候補（軸1）        {len(plan.add):>4}点 / 入れられるのは {plan.can_add}点まで")
        for t in plan.add[:8]:
            print(f"    + {t}")
        for n in plan.notes:
            print(f"\n  [注意] {n}")
        return 0

    # --- reprice ---
    listings = load_listings(args.listings)
    rows = plan_reprice(
        listings, profile,
        RepricePolicy(target_margin=args.target_margin,
                      min_margin=args.min_margin, fx_jpy_per_usd=args.fx),
        level=level, tax=tax, tables=_rate_tables(args),
        carrier=Carrier(args.carrier) if args.carrier else None,
    )
    urgent = [r for r in rows if r.is_urgent]
    print(f"\n=== 価格差の確認（{market.label} / {len(rows)}点）===\n")
    print(f"  いま動かすべき  {len(urgent)}点"
          f"（止める {sum(1 for r in rows if r.action is RepriceAction.STOP)} / "
          f"値上げ {sum(1 for r in rows if r.action is RepriceAction.RAISE)}）")
    print(f"  下げ余地あり    {sum(1 for r in rows if r.action is RepriceAction.LOWER)}点")
    print(f"  据え置き        {sum(1 for r in rows if r.action is RepriceAction.HOLD)}点\n")
    for r in (rows if args.all else urgent)[:args.top]:
        li = r.listing
        newp = (f" → ${r.required_price_usd:,.2f}"
                if r.action in (RepriceAction.RAISE, RepriceAction.LOWER) else "")
        print(f"[{_pad(_REPRICE_ICON[r.action], 8)}] "
              f"{_pad(li.title or li.sku, 30, trunc=True)} "
              f"利益率{r.margin_now*100:>6.1f}%  ${li.current_price_usd:>7.2f}{newp}")
        print(f"             {r.reason}")
    if args.out:
        n = write_reprice_plan(rows, args.out, urgent_only=not args.all)
        print(f"\n  改定リスト {n}件 を {args.out} に書き出しました。")
    return 0


def cmd_ingest(args) -> int:
    """eBay Seller Hub のレポートを、軸2の観測CSVに取り込む。

    手で列を詰め替える作業は本来いらない。レポートに全部入っている。
    """
    from datetime import date as _date

    observed = _date.fromisoformat(args.observed_on) if args.observed_on else _date.today()
    r = read_report(args.report, observed_on=observed)
    if not r.observations:
        print("読み取れる行がありませんでした。Seller Hub の Downloads で "
              "『All active listings』を選んでダウンロードし直してください。", file=sys.stderr)
        for w in r.warnings:
            print(f"  [注意] {w}", file=sys.stderr)
        return 1

    existing = load_observations(args.observations) if Path(args.observations).exists() else []
    merged = merge_observations(existing, r.observations)
    added = len(merged) - len(existing)
    n = write_observations(merged, args.observations)

    print(f"\n=== 取り込み（観測日 {observed.isoformat()}）===\n")
    print(f"  レポートから {len(r.observations)}件 を読み取りました")
    print(f"  観測CSV: 既存 {len(existing)}行 → {n}行（新規 {added}行）")
    print(f"  → {args.observations}")
    for w in r.warnings:
        print(f"\n  [注意] {w}")
    print("\n  次はこれで判定します:")
    print(f"    python -m blueocean.cli axis2 --observations {args.observations} "
          f"--candidates data/candidates.csv")
    return 0


def cmd_job(args) -> int:
    """保存した抽出条件で回す。**毎回同じ条件だからこそ差分が意味を持つ。**"""
    try:
        jobs = load_jobs(args.config)
    except (JobError, ValueError) as e:
        print(f"ジョブ定義を読めません: {e}", file=sys.stderr)
        return 1

    if args.list:
        print(f"\n=== ジョブ一覧（{args.config}）===\n")
        for name, j in jobs.items():
            steps = " → ".join(x for x in ("探す" if j.scan else "", "判定" if j.judge else "") if x)
            src = (j.scan.get("genre") or
                   ("キーワード" if j.scan.get("keywords") or j.scan.get("keywords_file") else "—")
                   ) if j.scan else "—"
            print(f"  {name:<16} {j.title}")
            print(f"                   {j.market} / 目標{j.target_margin*100:.0f}% / "
                  f"{steps or '—'} / 抽出元 {src}")
        return 0

    targets = list(jobs.values()) if args.all else (
        [jobs[args.name]] if args.name in jobs else []
    )
    if not targets:
        print(f"ジョブ {args.name} がありません。--list で一覧を見てください。", file=sys.stderr)
        return 1

    rc = 0
    for j in targets:
        print(f"\n=== {j.title}（{j.name}）===")
        print(f"  条件: {j.market} / セラーレベル {j.level} / 目標利益率 "
              f"{j.target_margin*100:.0f}% / 為替 {j.fx_jpy_per_usd:.0f}円")
        try:
            r = run_job(j, _source(args), record=not args.no_record)
        except (JobError, FileNotFoundError, ValueError) as e:
            print(f"  [失敗] {e}", file=sys.stderr)
            rc = 1
            continue

        if r.stale_warning:
            print(f"\n  [鮮度の警告] {r.stale_warning}")
        if j.scan:
            print(f"\n  走査 {r.scanned}件 → 探す価値あり {r.hunt_worthy}件")
        if j.judge:
            print(f"  判定 {r.judged}件 → 出品対象 {r.listable}件")
        if r.changes:
            act = r.actionable_changes
            print(f"\n  前回からの変化 {len(r.changes)}件（うち要対応 {len(act)}件）")
            for c in (act or r.changes)[:8]:
                print(f"    [{_CHANGE_ICON[c.kind]}] {c.sku:<12} {c.detail}")
        elif j.judge:
            print("\n  前回からの変化なし。")
        for w in r.written:
            print(f"\n  書き出し: {w}")
    return rc


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



_SOURCE_HELP = """\
  楽天市場          RAKUTEN_APP_ID     https://webservice.rakuten.co.jp/
  Yahoo!ショッピング YAHOO_CLIENT_ID    https://e.developer.yahoo.co.jp/register
"""


def cmd_domestic(args) -> int:
    """国内ショップの公式APIから仕入れ候補を採る。**巡回はしない。**"""
    if args.what == "keys":
        print("\n=== 鍵の登録状況 ===\n")
        for src in dom.Source:
            prov = dom.provider_for(src)
            try:
                key = dom.credentials_from_env(src)
                state = f"設定済み（末尾 …{key[-4:]}）"
            except dom.ApiError:
                state = "未設定"
            print(f"  {_pad(prov.source.label, 20)} {_pad(prov.key_env, 18)} {state}")
            print(f"    発行： {prov.signup_url}")
            print(f"    上限： 1クエリ {prov.window:,}件 / 間隔 {prov.min_interval}秒\n")
        print("  鍵は環境変数からしか読みません。CSVにもコードにも書きません。")
        print("  例： export RAKUTEN_APP_ID='...'\n")
        return 0

    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    for s_ in sources:
        dom.provider_for(s_)          # 未対応ならここで落とす

    q = dom.Query(
        keyword=args.keyword or "",
        ng_keyword=args.ng_keyword or "",
        genre_id=args.genre_id or "",
        jan=args.jan or "",
        shop=args.shop or "",
        min_price=args.min_price,
        max_price=args.max_price,
        condition=dom.Condition(args.condition),
        in_stock_only=not args.include_out_of_stock,
        postage_included_only=args.postage_included,
        sort=args.sort,
        max_items=args.max_items,
    )

    if args.dry_run:
        print("\n=== 送るリクエスト（実際には叩きません） ===\n")
        for s_ in sources:
            prov = dom.provider_for(s_)
            params = prov.params(q, "＜鍵＞", 1, prov.page_size)
            print(f"  {prov.source.label}  {prov.endpoint}")
            for k, v in sorted(params.items()):
                print(f"      {_pad(k, 22)} {v}")
            print()
        return 0

    keys: dict[str, str] = {}
    for s_ in sources:
        prov = dom.provider_for(s_)
        try:
            keys[prov.source.value] = dom.credentials_from_env(prov.source)
        except dom.ApiError as e:
            print(f"\n{e}\n", file=sys.stderr)
    if not keys:
        print("使える鍵がありません。`domestic keys` で登録先を確認してください。",
              file=sys.stderr)
        return 1

    print(f"\n条件： {q.describe()}")
    if args.split_price > 1:
        print(f"価格帯を {args.split_price} 分割して窓の上限を跨ぎます。")
    print()

    result = dom.search_all(
        sources, q, keys, split_price=args.split_price,
        on_progress=lambda t: print(f"  取得中… {t}", flush=True),
    )

    print(f"\n=== 取得 {len(result.items):,}件"
          f"（該当 {result.total_available:,}件 / {result.pages_fetched} ページ）===\n")

    if result.warnings:
        print("--- 注意 ---")
        for w in result.warnings:
            print(f"  ! {w}")
        print()

    if not result.items:
        return 1

    head = result.items[:args.show]
    print(f"{_pad('価格', 9, right=True)} {_pad('推定重量', 9, right=True)} "
          f"{_pad('元', 5)} {_pad('店', 14, trunc=True)} 商品名")
    for it in head:
        hint = dom.weight_hint(it.title, it.genre_name)
        mark = "" if hint.basis is dom.WeightBasis.TITLE else "?"
        wt = f"{hint.grams:,}g{mark}" if hint.grams else "不明"
        tax = "" if it.tax_included else "＋税"
        post = "" if it.postage_included is not False else "＋送"
        print(f"{_pad(f'{it.cost_incl_tax_jpy:,}円{tax}{post}', 9, right=True)} "
              f"{_pad(wt, 9, right=True)} "
              f"{_pad(it.source.value[:4], 5)} "
              f"{_pad(it.shop_name, 14, trunc=True)} "
              f"{_pad(it.title, 46, trunc=True)}")
    if len(result.items) > len(head):
        print(f"  … 他 {len(result.items) - len(head):,}件")
    print()

    if args.out:
        n = dom.write_items(args.out, result.items)
        print(f"  抽出結果 {n:,}件 を {args.out} に書き出しました。")

    if args.candidates_out:
        cands, warns = dom.to_candidates(
            result.items, domestic_shipping_jpy=args.domestic_shipping)
        usable = [c for c in cands if c.weight_g > 0]
        import csv as _csv
        path = Path(args.candidates_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["sku", "title_ja", "source_url", "cost_incl_tax_jpy",
                        "weight_g", "length_cm", "width_cm", "height_cm",
                        "category", "market_price_usd", "competitor_count",
                        "has_demand_signal", "demand_note",
                        "is_restricted", "restricted_reason", "image_url",
                        "weight_is_estimate", "cost_is_estimate", "estimate_note"])
            for c in usable:
                w.writerow([c.sku, c.title_ja, c.source_url,
                            round(c.cost_incl_tax_jpy), c.weight_g, "", "", "",
                            c.category, "", "", "no", "", "no", "",
                            c.image_urls[0] if c.image_urls else "",
                            "yes" if c.weight_is_estimate else "no",
                            "yes" if c.cost_is_estimate else "no",
                            c.estimate_note])
        print(f"  候補CSV {len(usable):,}件 を {args.candidates_out} に書き出しました。")
        if len(usable) < len(cands):
            print(f"    （重量が出せなかった {len(cands) - len(usable):,}件は除外。"
                  f"{args.out or '抽出結果CSV'} には残っています）")
        for w_ in warns:
            print(f"    ! {w_}")
        print(f"\n    次： python -m blueocean.cli axis1 "
              f"--candidates {args.candidates_out}")
        print("    ただし market_price_usd と competitor_count は空です。")
        print("    eBay側の相場を入れないと採算判定は出ません（scan / check を先に）。")
    print()
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
    a1.add_argument("--sheet", default=None,
                    help="商品写真つきの現物照合シート（HTML）を書き出す")
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
    sc.add_argument("--sheet", default=None,
                    help="商品写真つきの現物照合シート（HTML）を書き出す")
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

    ex = sub.add_parser("extract", help="抽出の設計と受け皿（巡回はしない。人が採る）")
    ex.add_argument("what", choices=["fields", "urls", "sheet", "check"],
                    help="fields=項目一覧 / urls=開く検索ページ / "
                         "sheet=抽出用シート / check=記入済みシートの検品")
    ex.add_argument("--name", default=None)
    ex.add_argument("--keyword", action="append", default=[], help="検索語（複数可）")
    ex.add_argument("--category", default=None, help="Amazonの部門名（例：カメラ）")
    ex.add_argument("--max-cost", type=int, default=0, help="仕入の上限（円）")
    ex.add_argument("--max-weight-g", type=int, default=2000)
    ex.add_argument("--sheet", default=None, help="記入済みシート（check用）")
    ex.add_argument("--out", default=None, help="書き出し先")
    ex.add_argument("--minimal", action="store_true", help="必須項目だけのシートにする")
    ex.add_argument("--top", type=int, default=30)
    ex.add_argument("--all", action="store_true", help="注意も含めて全部出す")
    ex.set_defaults(func=cmd_extract)

    sp = sub.add_parser("shopee", help="Shopee専用：出品枠の管理と価格差の定期確認")
    sp.add_argument("what", choices=["slots", "reprice"],
                    help="slots=枠の残りと入れ替え候補 / reprice=価格差の確認")
    sp.add_argument("--listed", type=int, default=0, help="いまの出品数")
    sp.add_argument("--preorder-listed", type=int, default=0,
                    help="うちプレオーダー（無在庫）の数")
    sp.add_argument("--tier", default="new", choices=["new", "preferred", "max"],
                    help="new=新規開店時 / preferred=Preferred Seller / max=実績上限")
    sp.add_argument("--observations", default=None, help="軸2の観測CSV（落とす候補を出す）")
    sp.add_argument("--candidates", default=None, help="軸1の候補CSV（入れる候補を出す）")
    sp.add_argument("--listings", default=None, help="出品中の一覧CSV（reprice用）")
    sp.add_argument("--min-margin", type=float, default=0.05, help="値上げに動く下限利益率")
    sp.add_argument("--fx", type=float, default=150.0)
    sp.add_argument("--top", type=int, default=25)
    sp.add_argument("--all", action="store_true", help="据え置きも含めて全件出す")
    sp.add_argument("--out", default=None, help="改定リストの書き出し先")
    sp.set_defaults(func=cmd_shopee)

    dm = sub.add_parser("domestic",
                        help="国内ショップの公式APIから仕入れ候補を採る（巡回はしない）")
    dm.add_argument("what", choices=["search", "keys"])
    dm.add_argument("--source", default="rakuten,yahoo",
                    help="取得元をカンマ区切りで（rakuten / yahoo）")
    dm.add_argument("--keyword", default="")
    dm.add_argument("--ng-keyword", default="", help="除外語（楽天のみ有効）")
    dm.add_argument("--genre-id", default="", help="ジャンルID／カテゴリID")
    dm.add_argument("--jan", default="", help="JANコード（Yahoo!は完全一致で引ける）")
    dm.add_argument("--shop", default="", help="店舗コード／セラーID")
    dm.add_argument("--min-price", type=int, default=None)
    dm.add_argument("--max-price", type=int, default=None)
    dm.add_argument("--condition", default="any", choices=["any", "new", "used"],
                    help="新品／中古（Yahoo!のみ。楽天は絞れない）")
    dm.add_argument("--include-out-of-stock", action="store_true",
                    help="在庫切れも含める（既定は在庫ありのみ）")
    dm.add_argument("--postage-included", action="store_true",
                    help="送料込みの商品だけに絞る（原価が確定する。楽天のみ）")
    dm.add_argument("--sort", default="price_asc",
                    choices=["price_asc", "price_desc", "review_desc", "standard"])
    dm.add_argument("--max-items", type=int, default=300)
    dm.add_argument("--split-price", type=int, default=0,
                    help="価格帯をN分割して窓の上限を跨ぐ（数千件を採るときに使う）")
    dm.add_argument("--domestic-shipping", type=int, default=0,
                    help="送料別の商品に乗せる国内送料（円）")
    dm.add_argument("--show", type=int, default=20, help="画面に出す件数")
    dm.add_argument("--out", default=None, help="抽出結果CSVの書き出し先")
    dm.add_argument("--candidates-out", default=None,
                    help="判定用の候補CSVの書き出し先")
    dm.add_argument("--dry-run", action="store_true",
                    help="実際には叩かず、送るパラメータだけ出す")
    dm.set_defaults(func=cmd_domestic)

    ig = sub.add_parser("ingest", help="eBayのレポートを軸2の観測CSVに取り込む")
    ig.add_argument("--report", required=True,
                    help="Seller Hub の『All active listings』レポート（CSV）")
    ig.add_argument("--observations", required=True, help="観測CSV（無ければ作る／あれば追記）")
    ig.add_argument("--observed-on", default=None,
                    help="観測日（既定は今日）。過去のレポートを入れるときに指定する")
    ig.set_defaults(func=cmd_ingest)

    jb = sub.add_parser("job", help="保存した抽出条件で回す（毎回同じ条件で差分を出す）")
    jb.add_argument("--config", required=True, help="ジョブ定義JSON")
    jb.add_argument("--name", default=None, help="実行するジョブ名")
    jb.add_argument("--all", action="store_true", help="定義された全ジョブを回す")
    jb.add_argument("--list", action="store_true", help="ジョブ一覧を表示する")
    jb.add_argument("--no-record", action="store_true", help="履歴に追記しない")
    jb.set_defaults(func=cmd_job)

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
