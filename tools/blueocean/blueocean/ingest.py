"""eBayのレポートを、そのまま軸2の入力にする。

軸2の観測CSV（sku / listed_on / observed_on / views / watchers / sold）は、
**eBay Seller Hub の「All active listings」レポートに全部入っている。**

    Custom label      → sku
    Title             → title
    Start Date        → listed_on
    Views             → views
    Watchers          → watchers
    Sold quantity     → sold
    （ダウンロードした日）→ observed_on

つまり手で詰め替える作業は本来いらない。だが列名は環境や時期で揺れるし
（``Custom label`` / ``Custom label (SKU)`` / ``customlabel``）、日付の書式も
``Aug-23-2026 10:12:33 PDT`` のような形で来る。ここを吸収する。

**毎週の運用で効くのは追記できること。** 観測CSVは追記して育てる前提なので、
同じSKU・同じ観測日の行は上書きし、それ以外は足す。取り直しても行が二重にならない。
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .models import Observation

# 列名の揺れを吸収する。左が正、右が受け付ける表記。
_ALIASES: dict[str, tuple[str, ...]] = {
    "sku": ("customlabel", "customlabelsku", "sku", "customlabelsku2"),
    "item_id": ("itemnumber", "itemid", "item"),
    "title": ("title", "itemtitle"),
    "listed_on": ("startdate", "starttime", "startdatetime", "listeddate"),
    "views": ("views", "viewcount", "pageviews"),
    "watchers": ("watchers", "watchcount", "watchers1"),
    "sold": ("soldquantity", "quantitysold", "sold", "totalsold"),
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
    "%b-%d-%Y", "%b %d, %Y", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S",
)


def _norm(name: str) -> str:
    """列名を突き合わせ用に潰す（大小・空白・記号を無視）。"""
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


def _pick(row: dict[str, str], key: str) -> str:
    """別名を辿って値を取る。"""
    normed = {_norm(k): v for k, v in row.items() if k}
    for alias in _ALIASES[key]:
        if alias in normed and str(normed[alias]).strip():
            return str(normed[alias]).strip()
    return ""


def parse_date(text: str) -> date | None:
    """eBayの日付表記を吸収する。時刻とタイムゾーンは落とす。

    ``Aug-23-2026 10:12:33 PDT`` のような形で来るので、先頭のトークンだけ見る。
    """
    text = (text or "").strip()
    if not text:
        return None
    head = text.split()[0].rstrip(",")
    for candidates in (head, text):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidates, fmt).date()
            except ValueError:
                continue
    return None


def _int(text: str) -> int:
    """``1,234`` や空欄を数値にする。読めなければ0。"""
    text = (text or "").replace(",", "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


@dataclass
class IngestResult:
    """取り込みの結果。何を落としたかを必ず返す。"""
    observations: list[Observation]
    skipped_no_sku: int = 0
    skipped_no_date: int = 0
    missing_columns: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.missing_columns is None:
            self.missing_columns = []

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.missing_columns:
            out.append(
                f"レポートに見つからなかった列: {', '.join(self.missing_columns)}。"
                f"該当する値は0として扱いました。"
                f"Seller Hub の Downloads で『All active listings』を選び直してください"
            )
        if self.skipped_no_sku:
            out.append(
                f"{self.skipped_no_sku}件を飛ばしました（Custom label も Item number も空）。"
                f"出品にカスタムラベル（SKU）を付けると、軸1の候補と突き合わせられます"
            )
        if self.skipped_no_date:
            out.append(f"{self.skipped_no_date}件を飛ばしました（出品日が読めない）")
        return out


def from_ebay_report(
    rows: list[dict[str, str]], *, observed_on: date | None = None
) -> IngestResult:
    """Seller Hub のレポート行を観測に変換する。"""
    observed_on = observed_on or date.today()
    out: list[Observation] = []
    no_sku = no_date = 0

    header = set()
    for r in rows[:1]:
        header = {_norm(k) for k in r if k}
    missing = [
        label
        for key, label in (("views", "Views"), ("watchers", "Watchers"),
                           ("sold", "Sold quantity"), ("listed_on", "Start date"))
        if header and not (set(_ALIASES[key]) & header)
    ]

    for r in rows:
        sku = _pick(r, "sku") or _pick(r, "item_id")
        if not sku:
            no_sku += 1
            continue
        listed = parse_date(_pick(r, "listed_on"))
        if listed is None:
            no_date += 1
            continue
        out.append(Observation(
            sku=sku,
            listed_on=listed,
            observed_on=observed_on,
            views=_int(_pick(r, "views")),
            watchers=_int(_pick(r, "watchers")),
            sold=_int(_pick(r, "sold")),
            title=_pick(r, "title"),
        ))
    return IngestResult(out, no_sku, no_date, missing)


def read_report(path: str | Path, *, observed_on: date | None = None) -> IngestResult:
    """レポートCSVを読む。

    Seller Hub のCSVは先頭に注記行が入ることがあるので、
    見出しらしい行を探してからDictReaderに渡す。
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines[:12]):
        cells = {_norm(c) for c in line.split(",")}
        if cells & set(_ALIASES["title"]) or cells & set(_ALIASES["item_id"]):
            start = i
            break
    reader = csv.DictReader(lines[start:])
    return from_ebay_report(list(reader), observed_on=observed_on)


_OBS_COLS = ["sku", "title", "listed_on", "observed_on", "views", "watchers", "sold"]


def merge_observations(
    existing: list[Observation], new: list[Observation]
) -> list[Observation]:
    """観測を追記する。同じSKU・同じ観測日は上書きする。

    取り直しても行が二重にならないようにするため。日付が違えば別の行として残す
    （それが前回比の材料になる）。
    """
    by_key: dict[tuple[str, str], Observation] = {
        (o.sku, o.observed_on.isoformat()): o for o in existing
    }
    for o in new:
        by_key[(o.sku, o.observed_on.isoformat())] = o
    return sorted(by_key.values(), key=lambda o: (o.observed_on, o.sku))


def write_observations(observations: list[Observation], path: str | Path) -> int:
    """観測CSVを書き出す。軸2がそのまま読める形。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(_OBS_COLS)
        for o in observations:
            w.writerow([o.sku, o.title, o.listed_on.isoformat(),
                        o.observed_on.isoformat(), o.views, o.watchers, o.sold])
    return len(observations)
