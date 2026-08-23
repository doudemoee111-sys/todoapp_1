"""キーワード空間の走査 ── 「候補が固定だと探せない」への答え。

軸1をCSVのバッチ判定として作ったのは設計の誤りだった。
**手元に候補リストがある状態を前提にすると、リストに無いものは永久に見つからない。**
そして現実の仕入れでは、候補リストのほうが後から出来る。

このモジュールは向きを1段戻す。

    バッチ判定（既存）   候補リスト → eBayを引く → 判定
    キーワード走査（本モジュール）
                         型番・ブランドの一覧 → eBayを引く
                              → 「eBayに出ていない型番」を特定
                              → その型番を国内で探しに行く

**商品は固定でも、キーワード空間は固定ではない。** そして同じキーワードでも
競合の状況は毎週変わるので、走査は繰り返す価値がある。

キーワードの作り方は人間の仕事になる。得意ジャンルの型番表（メーカーの製品一覧、
機種リスト、レンズの型番体系）を一度作れば、それが資産として残る。100〜500行あれば
毎週の走査に足りる。

出力はそのまま軸1の候補CSVの雛形になる。国内で現物を見つけたら仕入値を書き足すだけで、
バッチ判定に流せる。走査と判定が1本に繋がる。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .models import FeeProfile, SellerLevel, TaxProfile
from .profit import max_cost_for_margin, required_multiple
from .scoring import ScoringPolicy
from .shipping import MARKET_ZONE, Parcel, cheapest
from .sources.base import MarketDataSource


class Opening(str, Enum):
    """そのキーワードに「空き」があるか。"""
    OPEN = "open"          # 競合が少ない。国内で探しに行く価値がある
    PROBE = "probe"        # 競合ゼロ。空いているのか、需要が無いのか判別できない
    CROWDED = "crowded"    # 競合過多。値下げ競争に入っている
    LOW_VALUE = "low"      # 相場が低すぎる。手数料と送料に食われる
    NO_DATA = "no_data"    # 相場が取れなかった


@dataclass(frozen=True)
class KeywordResult:
    """キーワード1件の走査結果。

    ``max_cost_jpy`` が実務上いちばん重要になる。
    **これは「国内で探しに行くときの予算」** で、この額を超える値札が付いていたら
    その場で見送れる。相場を見てから電卓を叩く手間が消える。
    """
    keyword: str
    opening: Opening
    competitor_count: int
    median_price_usd: float | None
    low_price_usd: float | None
    high_price_usd: float | None
    max_cost_jpy: float
    required_multiple: float
    shipping_jpy: float | None
    note: str

    @property
    def is_hunt_worthy(self) -> bool:
        """国内で探しに行く価値があるか。"""
        return self.opening in (Opening.OPEN, Opening.PROBE)


@dataclass(frozen=True)
class ScanPolicy:
    """走査の閾値。軸1の ScoringPolicy と同じ考え方で揃えてある。"""
    target_margin: float = 0.20
    open_max_competitors: int = 5
    crowded_min_competitors: int = 30
    min_price_usd: float = 30.0
    fx_jpy_per_usd: float = 150.0

    @classmethod
    def from_scoring(cls, p: ScoringPolicy) -> "ScanPolicy":
        return cls(
            target_margin=p.target_margin,
            open_max_competitors=p.blue_max_competitors,
            crowded_min_competitors=p.red_min_competitors,
            min_price_usd=p.min_price_usd,
            fx_jpy_per_usd=p.fx_jpy_per_usd,
        )


def load_keywords(path: str | Path) -> list[str]:
    """キーワード一覧を読む。1行1件。`#` 以降と空行は無視する。"""
    out: list[str] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def scan_one(
    keyword: str,
    source: MarketDataSource,
    profile: FeeProfile,
    policy: ScanPolicy | None = None,
    *,
    level: SellerLevel = SellerLevel.ABOVE_STANDARD,
    tax: TaxProfile | None = None,
    assume: Parcel | None = None,
) -> KeywordResult:
    """キーワード1件を走査する。

    ``assume`` は送料を出すための荷姿の仮定。走査の時点では現物が手元に無く、
    重量も寸法も分からないため、仮定を置くしかない。**仮定であることは
    note に必ず書く。** 現物が見つかったら軸1で実寸から引き直す。
    """
    policy = policy or ScanPolicy()
    assume = assume or Parcel(500)
    snap = source.snapshot(keyword)

    ship = None
    q = cheapest(assume, MARKET_ZONE[profile.market])
    if q is not None:
        ship = q.jpy

    price = snap.median_price_usd
    if price is None:
        return KeywordResult(
            keyword, Opening.NO_DATA, snap.competitor_count, None, None, None,
            0.0, float("inf"), ship,
            "相場が取れなかった。検索語が具体的すぎるか、綴りが違う可能性がある",
        )

    cap = max_cost_for_margin(
        price, policy.target_margin, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax, shipping_jpy=ship,
    )
    mult = required_multiple(
        price, policy.target_margin, profile,
        fx_jpy_per_usd=policy.fx_jpy_per_usd, level=level, tax=tax, shipping_jpy=ship,
    )

    n = snap.competitor_count
    assume_note = (
        f"送料は {assume.weight_g}g"
        + (f"／{assume.length_cm:.0f}x{assume.width_cm:.0f}x{assume.height_cm:.0f}cm"
           if assume.has_dimensions else "（寸法の仮定なし）")
        + " と仮定した概算"
    )

    if price < policy.min_price_usd:
        opening = Opening.LOW_VALUE
        note = f"相場 ${price:.0f} が下限 ${policy.min_price_usd:.0f} 未満。手数料と送料に食われる"
    elif n >= policy.crowded_min_competitors:
        opening = Opening.CROWDED
        note = f"競合 {n}件。すでに値下げ競争に入っている"
    elif n == 0:
        # 競合ゼロは「空いている」と「誰も欲しがらない」の区別が付かない。
        # ここを OPEN と言い切ると、売れない在庫を探しに行くことになる。
        opening = Opening.PROBE
        note = f"競合0件。空いているのか需要が無いのか判別できない。{assume_note}"
    elif n <= policy.open_max_competitors:
        opening = Opening.OPEN
        note = f"競合 {n}件。値下げ圧力を受けにくい。{assume_note}"
    else:
        opening = Opening.PROBE
        note = f"競合 {n}件。空いてはいないが致命的でもない。{assume_note}"

    return KeywordResult(
        keyword, opening, n, price, snap.low_price_usd, snap.high_price_usd,
        cap, mult, ship, note,
    )


def scan_all(
    keywords: list[str],
    source: MarketDataSource,
    profile: FeeProfile,
    policy: ScanPolicy | None = None,
    **kw,
) -> list[KeywordResult]:
    """キーワード群を走査し、探しに行く価値がある順に返す。

    並び順は「空き → 予算の大きい順」。**競合が少なくて予算が大きい**キーワードが
    最良の狩り場になるので、それが先頭に来る。
    """
    results = [scan_one(k, source, profile, policy, **kw) for k in keywords]
    order = {
        Opening.OPEN: 0, Opening.PROBE: 1, Opening.CROWDED: 2,
        Opening.LOW_VALUE: 3, Opening.NO_DATA: 4,
    }
    return sorted(results, key=lambda r: (order[r.opening], -r.max_cost_jpy))


def write_candidate_template(
    results: list[KeywordResult], path: str | Path, *, only_worthy: bool = True
) -> int:
    """走査結果を軸1の候補CSVの雛形として書き出す。

    仕入値・重量・寸法は空にしてある。国内で現物を見つけたら、そこだけ書き足せば
    軸1にそのまま流せる。**走査と判定が1本に繋がる。**
    """
    import csv

    rows = [r for r in results if not only_worthy or r.is_hunt_worthy]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "sku", "title_ja", "source_url", "cost_incl_tax_jpy", "weight_g",
            "length_cm", "width_cm", "height_cm", "category",
            "market_price_usd", "competitor_count",
            "has_demand_signal", "demand_note", "is_restricted", "restricted_reason",
        ])
        for i, r in enumerate(rows, 1):
            w.writerow([
                f"SCAN-{i:03d}", r.keyword, "", "", "", "", "", "", "",
                f"{r.median_price_usd:.2f}" if r.median_price_usd else "",
                r.competitor_count, "", "", "", "",
            ])
    return len(rows)
