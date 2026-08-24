"""Python と web/parts/core.js が同じ数字を出すことを、実際に両方走らせて確かめる。

ブラウザ側は Python の式を手で移したもので、しかも eBay用・Shopee用の2つの
HTMLへビルドで配られる。**式が1箇所でもずれると、画面と CLI で違う判断が出る。**
目視では気づけないので、ここで機械的に突き合わせる。

node が無い環境ではスキップする（CI要件を増やさないため）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from blueocean.bundle import BundleItem, sell_as_bundle, sell_separately
from blueocean.models import Market, SellerLevel, TaxProfile
from blueocean.pricing import (
    breakeven_duty_rate, breakeven_fx, list_price_for_margin, return_impact,
)
from blueocean.profit import DEFAULT_PROFILES, compute, max_cost_for_margin
from blueocean.shipping import Carrier, Parcel, Zone, domestic_leg_jpy, estimate

HARNESS = Path(__file__).resolve().parents[1] / "web" / "parts" / "parity.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not HARNESS.exists(),
    reason="node か web/parts/parity.js が無い",
)

LEVELS = {
    "top_rated": SellerLevel.TOP_RATED,
    "above_standard": SellerLevel.ABOVE_STANDARD,
    "below_standard": SellerLevel.BELOW_STANDARD,
}
ZONES = {z.value: z for z in Zone}


def js_cfg(market: str, *, level="above_standard", fx=150.0, target=0.20,
           taxable=True, carrier="auto", ship=None):
    """ブラウザ側が持っている設定オブジェクトの形。"""
    m = Market(market)
    p = DEFAULT_PROFILES[m]
    zone = {"ebay_us": "zone4", "ebay_eu": "zone3", "ebay_au": "zone3",
            "shopee_sea": "zone2", "shopee_tw": "zone1", "shopee_sg": "zone2",
            "shopee_my": "zone2", "shopee_ph": "zone2"}[market]
    return {
        "market": market, "level": level, "fx": fx, "target": target,
        "fee": p.fee_rate, "duty": p.duty_rate,
        "ship": p.shipping_jpy if ship is None else ship,
        "pack": p.packaging_jpy, "per": p.per_order_fee_jpy,
        "taxable": taxable, "zone": zone, "carrier": carrier, "autoShip": True,
    }


def py_profile(c):
    """js_cfg が表している料金構成を Python 側の FeeProfile に戻す。"""
    p = DEFAULT_PROFILES[Market(c["market"])]
    return replace(p, fee_rate=c["fee"], duty_rate=c["duty"],
                   shipping_jpy=c["ship"], packaging_jpy=c["pack"],
                   per_order_fee_jpy=c["per"])


def run_js(cases: dict) -> dict:
    proc = subprocess.run(
        ["node", str(HARNESS)], input=json.dumps(cases), text=True,
        capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"core.js の実行に失敗した：\n{proc.stderr}")
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# 全部を1回のnode起動でまとめて回す（起動コストを払うのは1度でいい）
# --------------------------------------------------------------------------

PROFIT_CASES = [
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us")),
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us", level="top_rated")),
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us", level="below_standard")),
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us", taxable=False)),
    dict(price=45.0, cost=1500.0, c=js_cfg("ebay_eu", fx=163.0)),
    dict(price=12.0, cost=600.0, c=js_cfg("shopee_tw")),
    dict(price=8.5, cost=400.0, c=js_cfg("shopee_sea", fx=148.0)),
    dict(price=620.0, cost=42000.0, c=js_cfg("ebay_au", target=0.30)),
]

MAXCOST_CASES = [
    dict(price=200.0, target=0.20, c=js_cfg("ebay_us")),
    dict(price=200.0, target=0.35, c=js_cfg("ebay_us", level="below_standard")),
    dict(price=12.0, target=0.15, c=js_cfg("shopee_tw", taxable=False)),
    dict(price=620.0, target=0.25, c=js_cfg("ebay_eu", fx=161.0)),
]

SHIP_CASES = [
    dict(g=180, l=16, w=12, h=10, zone="zone4", carrier="ems"),
    dict(g=180, l=16, w=12, h=10, zone="zone4", carrier="epacket"),
    dict(g=320, l=18, w=14, h=12, zone="zone3", carrier="parcel"),
    dict(g=320, l=40, w=30, h=25, zone="zone3", carrier="parcel"),   # 容積課金
    dict(g=320, l=40, w=30, h=25, zone="zone3", carrier="ems"),      # EMSは容積を採らない
    dict(g=2500, l=30, w=25, h=20, zone="zone2", carrier="epacket"), # 重量超過
    dict(g=900, l=25, w=20, h=15, zone="zone1", carrier="courier"),
    dict(g=1400, l=30, w=22, h=18, zone="zone5", carrier="ems"),
    dict(g=600, l=20, w=15, h=10, zone="zone2", carrier="sls"),
    dict(g=600, l=0, w=0, h=0, zone="zone2", carrier="sls"),
]

DOMESTIC_CASES = [
    dict(g=600, l=20, w=15, h=10), dict(g=600, l=0, w=0, h=0),
    dict(g=1200, l=40, w=30, h=25), dict(g=3000, l=60, w=45, h=40),
    dict(g=5000, l=80, w=60, h=50),
]

LISTPRICE_CASES = [
    dict(cost=12000.0, margin=0.20, c=js_cfg("ebay_us"), ship=2400.0),
    dict(cost=600.0, margin=0.15, c=js_cfg("shopee_tw"), ship=800.0),
    dict(cost=42000.0, margin=0.30, c=js_cfg("ebay_eu", fx=161.0), ship=3100.0),
]

FX_CASES = [
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us"), ship=2400.0),
    dict(price=12.0, cost=600.0, c=js_cfg("shopee_tw"), ship=800.0),
]

DUTY_CASES = [
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us"), ship=2400.0),
    dict(price=620.0, cost=42000.0, c=js_cfg("ebay_eu"), ship=3100.0),
]

RETURN_CASES = [
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us"), ship=2400.0,
         opt=dict(sellerPays=True, recovered=True)),
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us"), ship=2400.0,
         opt=dict(sellerPays=True, recovered=False)),
    dict(price=200.0, cost=12000.0, c=js_cfg("ebay_us"), ship=2400.0,
         opt=dict(sellerPays=False, recovered=True)),
]

BUNDLE_ITEMS = [
    {"name": "A", "cost": 3000, "solo": 40, "g": 200, "l": 12, "w": 10, "h": 6},
    {"name": "B", "cost": 2000, "solo": 0, "g": 150, "l": 10, "w": 8, "h": 5},
    {"name": "C", "cost": 2500, "solo": 35, "g": 180, "l": 11, "w": 9, "h": 5},
]
BUNDLE_CASES = [
    dict(items=BUNDLE_ITEMS, setPrice=95.0,
         pack=dict(g=650, l=24, w=18, h=12), c=js_cfg("ebay_us")),
    dict(items=BUNDLE_ITEMS, setPrice=95.0,
         pack=dict(g=650, l=24, w=18, h=12), c=js_cfg("shopee_tw")),
]

def row(**kw):
    """一覧の1行。ブラウザ側は全部文字列で持つので、Python にも同じ形で渡す。"""
    base = dict(sku="S1", title_ja="テスト品", cost_incl_tax_jpy="9800",
                weight_g="320", length_cm="18", width_cm="14", height_cm="12",
                market_price_usd="185", competitor_count="2",
                has_demand_signal="yes", demand_note="", is_restricted="no",
                restricted_reason="", weight_is_estimate="", cost_is_estimate="",
                estimate_note="")
    base.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
    return base


VERDICT_CASES = [
    dict(row=row(), c=js_cfg("ebay_us")),                                  # BLUE
    dict(row=row(has_demand_signal="no"), c=js_cfg("ebay_us")),            # 需要なし→PROBE
    dict(row=row(competitor_count="40"), c=js_cfg("ebay_us")),             # RED
    dict(row=row(cost_incl_tax_jpy="30000"), c=js_cfg("ebay_us")),         # THIN
    dict(row=row(is_restricted="yes", restricted_reason="リチウム電池"),
         c=js_cfg("ebay_us")),                                             # EXCLUDE
    dict(row=row(market_price_usd=""), c=js_cfg("ebay_us")),               # 相場なし
    dict(row=row(weight_g="3000"), c=js_cfg("ebay_us")),                   # 重量超過
    dict(row=row(weight_g="320", length_cm="45", width_cm="35",
                 height_cm="30"), c=js_cfg("ebay_us")),                    # 容積で超過
    dict(row=row(cost_incl_tax_jpy=""), c=js_cfg("ebay_us")),              # 仕入値なし
    dict(row=row(competitor_count=""), c=js_cfg("ebay_us")),               # 競合なし
    dict(row=row(weight_is_estimate="yes",
                 estimate_note="カテゴリ既定値"), c=js_cfg("ebay_us")),      # 推定→BLUEにしない
    dict(row=row(market_price_usd="12", cost_incl_tax_jpy="600",
                 weight_g="200"), c=js_cfg("shopee_tw", carrier="sls")),   # Shopeeの下限
    dict(row=row(market_price_usd="12"), c=js_cfg("ebay_us")),             # eBayの下限で除外
]

CASES = {
    "profit": PROFIT_CASES, "maxCost": MAXCOST_CASES, "ship": SHIP_CASES,
    "domestic": DOMESTIC_CASES, "listPrice": LISTPRICE_CASES,
    "breakevenFx": FX_CASES, "breakevenDuty": DUTY_CASES,
    "returnImpact": RETURN_CASES, "bundle": BUNDLE_CASES,
    "verdict": VERDICT_CASES,
}


@pytest.fixture(scope="module")
def js():
    return run_js(CASES)


# --------------------------------------------------------------------------

def test_profit_matches(js):
    for want_js, x in zip(js["profit"], PROFIT_CASES):
        c = x["c"]
        got = compute(x["price"], x["cost"], py_profile(c),
                      fx_jpy_per_usd=c["fx"], level=LEVELS[c["level"]],
                      tax=TaxProfile(is_taxable_entity=c["taxable"]))
        assert round(got.profit_jpy, 2) == want_js["profit"], f"{c['market']} の利益がずれた"
        assert round(got.margin, 6) == want_js["margin"]
        assert round(got.vat_refund_jpy, 2) == want_js["refund"]


def test_max_cost_matches(js):
    for want, x in zip(js["maxCost"], MAXCOST_CASES):
        c = x["c"]
        got = max_cost_for_margin(x["price"], x["target"], py_profile(c),
                                  fx_jpy_per_usd=c["fx"], level=LEVELS[c["level"]],
                                  tax=TaxProfile(is_taxable_entity=c["taxable"]))
        assert round(got, 2) == want


def test_shipping_matches_including_the_failures(js):
    """使えない組み合わせが「使えない」で一致することまで見る。

    片方だけが送料を返すと、画面では出せるのに CLI では出せない、という
    食い違いになる。
    """
    for want, x in zip(js["ship"], SHIP_CASES):
        parcel = Parcel(x["g"], x["l"], x["w"], x["h"])
        zone, carrier = ZONES[x["zone"]], Carrier(x["carrier"])
        try:
            q = estimate(parcel, zone, carrier)
        except Exception:
            assert want.get("error"), f"{x} は Python では出せないのに JS は出した"
            continue
        assert not want.get("error"), f"{x} は JS では出せないのに Python は出した"
        assert q.jpy == want["jpy"], f"{x} の送料がずれた"
        assert q.chargeable_weight_g == want["chg"]
        assert q.billed_by_volume == want["vol"]


def test_domestic_leg_matches(js):
    for want, x in zip(js["domestic"], DOMESTIC_CASES):
        got = domestic_leg_jpy(Parcel(x["g"], x["l"], x["w"], x["h"]))
        assert got == want


def test_list_price_matches(js):
    for want, x in zip(js["listPrice"], LISTPRICE_CASES):
        c = x["c"]
        got = list_price_for_margin(
            x["cost"], x["margin"], py_profile(c), fx_jpy_per_usd=c["fx"],
            level=LEVELS[c["level"]], tax=TaxProfile(is_taxable_entity=c["taxable"]),
            shipping_jpy=x["ship"])
        assert round(got, 2) == want


def test_breakeven_fx_matches(js):
    for want, x in zip(js["breakevenFx"], FX_CASES):
        c = x["c"]
        got = breakeven_fx(x["price"], x["cost"], py_profile(c),
                           level=LEVELS[c["level"]],
                           tax=TaxProfile(is_taxable_entity=c["taxable"]),
                           shipping_jpy=x["ship"])
        assert round(got, 2) == want


def test_breakeven_duty_matches(js):
    for want, x in zip(js["breakevenDuty"], DUTY_CASES):
        c = x["c"]
        got = breakeven_duty_rate(x["price"], x["cost"], py_profile(c),
                                  fx_jpy_per_usd=c["fx"], level=LEVELS[c["level"]],
                                  tax=TaxProfile(is_taxable_entity=c["taxable"]),
                                  shipping_jpy=x["ship"])
        assert round(got, 6) == want


def test_return_impact_matches(js):
    for want, x in zip(js["returnImpact"], RETURN_CASES):
        c = x["c"]
        got = return_impact(
            x["price"], x["cost"], py_profile(c),
            seller_pays_return=x["opt"]["sellerPays"],
            item_recovered=x["opt"]["recovered"],
            fx_jpy_per_usd=c["fx"], level=LEVELS[c["level"]],
            tax=TaxProfile(is_taxable_entity=c["taxable"]),
            shipping_jpy=x["ship"])
        assert round(got.tolerable_rate, 6) == want["tolerable"]
        assert round(got.loss_per_return_jpy, 2) == want["loss"]


def test_bundle_matches(js):
    for want, x in zip(js["bundle"], BUNDLE_CASES):
        c = x["c"]
        items = [BundleItem(name=i["name"], cost_incl_tax_jpy=i["cost"],
                            solo_price_usd=(i["solo"] or None),
                            weight_g=i["g"], length_cm=i["l"],
                            width_cm=i["w"], height_cm=i["h"])
                 for i in x["items"]]
        kw = dict(fx_jpy_per_usd=c["fx"], level=LEVELS[c["level"]],
                  tax=TaxProfile(is_taxable_entity=c["taxable"]))
        sep = sell_separately(items, py_profile(c), **kw)
        pack = Parcel(x["pack"]["g"], x["pack"]["l"], x["pack"]["w"], x["pack"]["h"])
        st = sell_as_bundle(items, x["setPrice"], py_profile(c), packing=pack, **kw)
        assert round(sep.profit_jpy, 2) == want["sep"], f"{c['market']} 個別売却がずれた"
        assert round(st.profit_jpy, 2) == want["set"], f"{c['market']} セット売却がずれた"


def test_verdict_matches(js):
    """判定そのものの一致。画面が BLUE と言い、CLI が THIN と言う状態を作らない。"""
    from blueocean.models import Candidate
    from blueocean.scoring import ScoringPolicy, score_one

    def truthy(v):
        return str(v).strip().lower() in ("yes", "true", "1", "y")

    for want, x in zip(js["verdict"], VERDICT_CASES):
        r, c = x["row"], x["c"]
        cand = Candidate(
            sku=r["sku"], title_ja=r["title_ja"], source_url="",
            cost_incl_tax_jpy=float(r["cost_incl_tax_jpy"] or 0),
            weight_g=int(r["weight_g"] or 0),
            length_cm=float(r["length_cm"] or 0),
            width_cm=float(r["width_cm"] or 0),
            height_cm=float(r["height_cm"] or 0),
            category="",
            market_price_usd=(float(r["market_price_usd"]) if r["market_price_usd"] else None),
            competitor_count=(int(r["competitor_count"]) if r["competitor_count"] else None),
            has_demand_signal=truthy(r["has_demand_signal"]),
            demand_note=r["demand_note"],
            is_restricted=truthy(r["is_restricted"]),
            restricted_reason=r["restricted_reason"],
            weight_is_estimate=truthy(r["weight_is_estimate"]),
            cost_is_estimate=truthy(r["cost_is_estimate"]),
            estimate_note=r["estimate_note"],
        )
        market = Market(c["market"])
        policy = ScoringPolicy.for_market(
            market, target_margin=c["target"], fx_jpy_per_usd=c["fx"],
            carrier=(None if c["carrier"] == "auto" else Carrier(c["carrier"])),
        )
        got = score_one(cand, py_profile(c), policy, level=LEVELS[c["level"]],
                        tax=TaxProfile(is_taxable_entity=c["taxable"]))
        # 内部キーだけ綴りが違う（Python: exclude / JS: excl）。意味は同じ。
        py_v = "excl" if got.verdict.value == "exclude" else got.verdict.value
        assert py_v == want["verdict"], (
            f"{r['title_ja']} / {r} で判定がずれた："
            f"Python={py_v} JS={want['verdict']}"
        )
        assert round(got.max_cost_jpy) == want["cap"], f"{r} の仕入上限がずれた"
