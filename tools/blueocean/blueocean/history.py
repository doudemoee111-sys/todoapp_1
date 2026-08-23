"""データ更新の履歴。「前回と何が変わったか」を出すための層。

これまでツールは毎回まっさらな一発判定だった。だが軸1が見ている数字は
**放っておいても勝手に動く**。

    競合出品数   誰かが同じ商品を出せば増える。数日で BLUE が RED に変わる
    相場         下がれば仕入上限が下がる。昨日まで買えた仕入値が今日は採算割れ
    為替・関税   全候補の採算が同時に動く
    国内在庫     売れて消える

つまり判定結果には**賞味期限**がある。一発判定を繰り返すだけでは、
その賞味期限も、前回からの変化も見えない。**変化こそが行動のトリガー**なので、
ここを持たないと「毎回全件を人間が読み直す」運用になってしまう。

このモジュールは判定結果をスナップショットとして追記保存し、
前回との差分だけを取り出す。運用上は次の3つが読めれば足りる。

    1. 判定が変わったもの（BLUE → RED、THIN → BLUE）
    2. 仕入上限を割ったもの（相場が下がって採算が消えた）
    3. データが古いもの（前回の取得からの経過日数）

保存形式は JSONL（1行1レコードの追記）。追記しかしないので、
途中でツールが落ちても過去の履歴は壊れない。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Iterable

from .models import ScoredCandidate, Verdict

# 判定の「良さ」の順序。改善／悪化を機械的に判定するために持つ。
_RANK = {
    Verdict.BLUE: 4,
    Verdict.PROBE: 3,
    Verdict.THIN: 2,
    Verdict.RED: 1,
    Verdict.EXCLUDE: 0,
}


@dataclass(frozen=True)
class Snapshot:
    """ある日の判定結果1件。履歴の最小単位。"""
    taken_on: str          # ISO日付
    sku: str
    title_ja: str
    verdict: str
    score: float
    competitor_count: int | None
    market_price_usd: float | None
    cost_incl_tax_jpy: float
    max_cost_jpy: float
    margin: float | None
    shipping_jpy: float | None

    @classmethod
    def of(cls, s: ScoredCandidate, taken_on: date) -> "Snapshot":
        c = s.candidate
        return cls(
            taken_on=taken_on.isoformat(),
            sku=c.sku,
            title_ja=c.title_ja,
            verdict=s.verdict.value,
            score=s.score,
            competitor_count=c.competitor_count,
            market_price_usd=c.market_price_usd,
            cost_incl_tax_jpy=c.cost_incl_tax_jpy,
            max_cost_jpy=round(s.max_cost_jpy, 1),
            margin=round(s.profit.margin, 4) if s.profit else None,
            shipping_jpy=round(s.profit.shipping_jpy, 1) if s.profit else None,
        )

    @property
    def date(self) -> date:
        return date.fromisoformat(self.taken_on)


class ChangeKind(str, Enum):
    NEW = "new"                  # 今回はじめて現れた候補
    GONE = "gone"                # 前回あったが今回の入力に無い（売れた・外した）
    UPGRADE = "upgrade"          # 判定が良くなった
    DOWNGRADE = "downgrade"      # 判定が悪くなった ← 最も重要
    CAP_BREACH = "cap_breach"    # 仕入値が上限を割った（採算が消えた）
    CAP_ROOM = "cap_room"        # 仕入上限に余裕が戻った
    COMPETITORS = "competitors"  # 競合数が大きく動いた
    PRICE = "price"              # 相場が大きく動いた


# 表示の優先順位。上にあるものほど先に読ませる。
_KIND_ORDER = {
    ChangeKind.DOWNGRADE: 0,
    ChangeKind.CAP_BREACH: 1,
    ChangeKind.UPGRADE: 2,
    ChangeKind.CAP_ROOM: 3,
    ChangeKind.COMPETITORS: 4,
    ChangeKind.PRICE: 5,
    ChangeKind.NEW: 6,
    ChangeKind.GONE: 7,
}


@dataclass(frozen=True)
class Change:
    """前回からの変化1件。何を見て何をすべきかまで書く。"""
    kind: ChangeKind
    sku: str
    title_ja: str
    detail: str
    action: str = ""

    @property
    def is_actionable(self) -> bool:
        """人間が手を打つべき変化か。単なる数字の揺れと区別する。"""
        return self.kind in (
            ChangeKind.DOWNGRADE, ChangeKind.CAP_BREACH,
            ChangeKind.UPGRADE, ChangeKind.CAP_ROOM,
        )


@dataclass(frozen=True)
class DiffPolicy:
    """どれくらい動いたら「変化」とみなすか。

    小さな揺れまで拾うと毎回全件が並び、履歴を持つ意味が消える。
    """
    competitor_abs: int = 5        # 競合数の変化量
    competitor_ratio: float = 0.5  # または前回比 50%
    price_ratio: float = 0.10      # 相場の変化率 10%
    stale_days: int = 7            # これを超えたら「データが古い」と警告する


# ---------- 保存と読み出し ----------

def append_snapshots(path: str | Path, snapshots: Iterable[Snapshot]) -> int:
    """スナップショットを追記する。既存の行は絶対に書き換えない。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as f:
        for s in snapshots:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
            n += 1
    return n


def load_snapshots(path: str | Path) -> list[Snapshot]:
    """履歴を読む。ファイルが無ければ空リスト（初回実行に対応する）。"""
    p = Path(path)
    if not p.exists():
        return []
    out: list[Snapshot] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Snapshot(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                # 壊れた行は落として続行する。履歴の破損で運用を止めない
                continue
    return out


def latest_by_sku(snapshots: list[Snapshot], *, before: date | None = None) -> dict[str, Snapshot]:
    """SKUごとに最新のスナップショットを返す。

    ``before`` を渡すと、その日より前の最新（＝今回の実行を除いた前回）になる。
    """
    out: dict[str, Snapshot] = {}
    for s in snapshots:
        if before is not None and s.date >= before:
            continue
        cur = out.get(s.sku)
        if cur is None or s.date >= cur.date:
            out[s.sku] = s
    return out


def history_of(snapshots: list[Snapshot], sku: str) -> list[Snapshot]:
    """1つのSKUの時系列を古い順に返す。"""
    return sorted((s for s in snapshots if s.sku == sku), key=lambda s: s.taken_on)


# ---------- 差分 ----------

def _pct(before: float, after: float) -> str:
    if before == 0:
        return "—"
    return f"{(after - before) / before * 100:+.0f}%"


def changes_since(
    previous: dict[str, Snapshot],
    current: list[Snapshot],
    *,
    policy: DiffPolicy | None = None,
) -> list[Change]:
    """前回と今回を突き合わせ、行動につながる変化だけを返す。"""
    policy = policy or DiffPolicy()
    out: list[Change] = []
    seen: set[str] = set()

    for cur in current:
        seen.add(cur.sku)
        prev = previous.get(cur.sku)
        if prev is None:
            out.append(Change(
                ChangeKind.NEW, cur.sku, cur.title_ja,
                f"新規候補。判定 {cur.verdict.upper()}",
                "初回なので、この判定がそのまま出発点になる",
            ))
            continue

        # 1. 判定の変化。これが最も重要
        pr, cr = _RANK[Verdict(prev.verdict)], _RANK[Verdict(cur.verdict)]
        if cr < pr:
            out.append(Change(
                ChangeKind.DOWNGRADE, cur.sku, cur.title_ja,
                f"{prev.verdict.upper()} → {cur.verdict.upper()}"
                f"（{prev.taken_on} → {cur.taken_on}）",
                "出品中なら価格と在庫を見直す。未出品なら見送りに回す",
            ))
        elif cr > pr:
            out.append(Change(
                ChangeKind.UPGRADE, cur.sku, cur.title_ja,
                f"{prev.verdict.upper()} → {cur.verdict.upper()}",
                "見送っていた候補が買えるようになった。仕入を再検討する",
            ))

        # 2. 仕入上限との関係。判定が変わらなくても採算は動く
        was_ok = prev.cost_incl_tax_jpy <= prev.max_cost_jpy
        now_ok = cur.cost_incl_tax_jpy <= cur.max_cost_jpy
        if was_ok and not now_ok:
            out.append(Change(
                ChangeKind.CAP_BREACH, cur.sku, cur.title_ja,
                f"仕入上限 {prev.max_cost_jpy:,.0f}円 → {cur.max_cost_jpy:,.0f}円。"
                f"仕入 {cur.cost_incl_tax_jpy:,.0f}円 が上限を超えた",
                "相場・為替・送料のどれかが動いた。仕入値を下げられないなら見送る",
            ))
        elif not was_ok and now_ok:
            out.append(Change(
                ChangeKind.CAP_ROOM, cur.sku, cur.title_ja,
                f"仕入上限 {prev.max_cost_jpy:,.0f}円 → {cur.max_cost_jpy:,.0f}円。"
                f"仕入 {cur.cost_incl_tax_jpy:,.0f}円 が上限内に戻った",
                "採算が戻った。まだ在庫があるうちに動く",
            ))

        # 3. 競合数（判定が変わる手前の予兆として拾う）
        a, b = prev.competitor_count, cur.competitor_count
        if a is not None and b is not None and a != b:
            moved = abs(b - a) >= policy.competitor_abs or (
                a > 0 and abs(b - a) / a >= policy.competitor_ratio
            )
            if moved:
                out.append(Change(
                    ChangeKind.COMPETITORS, cur.sku, cur.title_ja,
                    f"競合 {a}件 → {b}件（{_pct(a, b)}）",
                    "増えているなら早く出す。値下げ競争が始まる前が勝負"
                    if b > a else "減っている。出し直す価値がある",
                ))

        # 4. 相場
        pa, pb = prev.market_price_usd, cur.market_price_usd
        if pa and pb and abs(pb - pa) / pa >= policy.price_ratio:
            out.append(Change(
                ChangeKind.PRICE, cur.sku, cur.title_ja,
                f"相場 ${pa:.0f} → ${pb:.0f}（{_pct(pa, pb)}）",
                "出品中なら価格を追随させる",
            ))

    # 5. 今回の入力から消えたもの
    for sku, prev in previous.items():
        if sku not in seen:
            out.append(Change(
                ChangeKind.GONE, sku, prev.title_ja,
                f"今回の候補リストに無い（前回 {prev.taken_on} は {prev.verdict.upper()}）",
                "売れた・取り下げたなら正常。消し忘れなら候補CSVを確認する",
            ))

    return sorted(out, key=lambda c: (_KIND_ORDER[c.kind], c.sku))


def staleness_warning(
    previous: dict[str, Snapshot], today: date, *, policy: DiffPolicy | None = None
) -> str | None:
    """前回の取得からどれだけ経ったかを警告する。

    競合数と相場は毎日動く。古いデータで仕入れるのが最も危ない。
    """
    policy = policy or DiffPolicy()
    if not previous:
        return None
    last = max(s.date for s in previous.values())
    days = (today - last).days
    if days > policy.stale_days:
        return (
            f"前回の取得から {days}日 経っています（{last.isoformat()}）。"
            f"競合数と相場は日々動きます。--refresh を付けて取り直してください"
        )
    return None
