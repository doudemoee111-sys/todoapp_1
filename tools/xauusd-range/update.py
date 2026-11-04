"""Incremental data refresh. Safe to run daily, and cheap after the first run.

The price history lives in the repository as `data_archive/hourly_<YYYY>.csv.gz`
(about 1.5 MB in total, ~150 KB a year). A fresh container therefore starts
with ten years already on disk and fetches only what is missing: whole months
that have closed since the archive was written, and the hours since the last
run for the current month.

Without the archive every run re-fetched all 120 monthly files, which is what
made the scheduled runs take over ten minutes.

Only the current year's file changes as months close, so the repository grows
by roughly 150 KB a month rather than by a copy of everything.
"""
from __future__ import annotations
import datetime as dt
import gzip
from pathlib import Path
import pandas as pd
from duka import fetch_months, UTC, OUT
from recent import hourly_from_ticks

ARCHIVE = Path(__file__).parent / "data_archive"
ARCHIVE.mkdir(exist_ok=True)
RECENT = ARCHIVE / "hourly_recent.csv"
YEARS = 10
COLS = ["ts", "open", "high", "low", "close", "vol"]


def _months(a: dt.date, b: dt.date) -> list[tuple[int, int]]:
    y, m, out = a.year, a.month, []
    while (y, m) <= (b.year, b.month):
        out.append((y, m)); m += 1
        if m > 12: y, m = y + 1, 1
    return out


def read_archive() -> pd.DataFrame:
    frames = [pd.read_csv(p, parse_dates=["ts"])
              for p in sorted(ARCHIVE.glob("hourly_*.csv.gz"))]
    if not frames:
        return pd.DataFrame(columns=COLS)
    return (pd.concat(frames, ignore_index=True)
              .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))


def write_archive(df: pd.DataFrame) -> list[str]:
    """One gzip per year. mtime=0 keeps an unchanged year byte-identical, so
    git sees no change and the repository does not grow for nothing."""
    touched = []
    for y, g in df.groupby(df["ts"].dt.year):
        p = ARCHIVE / f"hourly_{int(y)}.csv.gz"
        blob = gzip.compress(g.sort_values("ts").to_csv(index=False).encode(),
                             compresslevel=9, mtime=0)
        if not p.exists() or p.read_bytes() != blob:
            p.write_bytes(blob)
            touched.append(p.name)
    return touched


def update_history(today: dt.date | None = None) -> pd.DataFrame:
    today = today or dt.datetime.now(UTC).date()
    start = dt.date(today.year - YEARS, today.month, 1)
    last_complete = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)

    arch = read_archive()
    have = set(zip(arch["ts"].dt.year, arch["ts"].dt.month)) if len(arch) else set()
    missing = [ym for ym in _months(start, last_complete) if ym not in have]

    if missing:
        print(f"[history] {len(missing)} month(s) missing: {missing[0]} .. {missing[-1]}")
        new = fetch_months(missing)
        arch = (pd.concat([arch, new], ignore_index=True)
                  .drop_duplicates("ts", keep="last").sort_values("ts"))
    else:
        print(f"[history] archive already covers {len(have)} months - nothing to fetch")

    arch = arch[arch["ts"].dt.date >= start].reset_index(drop=True)
    touched = write_archive(arch)
    if touched:
        print(f"[history] archive files rewritten: {', '.join(touched)}")
    arch.to_csv(OUT / "hourly.csv", index=False)
    return arch


def update_recent() -> pd.DataFrame:
    """Current month from tick files, resuming from the last bar on disk.

    The window reaches back to the start of the previous month so nothing is
    lost in the days before Dukascopy publishes that month's candle file.
    """
    now = dt.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    this_month = now.replace(day=1, hour=0)
    prev_month = (this_month - dt.timedelta(days=1)).replace(day=1, hour=0)

    old = None
    start = prev_month
    if RECENT.exists():
        old = pd.read_csv(RECENT, parse_dates=["ts"])
        old = old[old["ts"] >= prev_month]
        if len(old):
            start = old["ts"].max().to_pydatetime() + dt.timedelta(hours=1)
    # re-pull the last few hours: the newest tick files are often incomplete
    start = max(prev_month, start - dt.timedelta(hours=3))

    hours = int((now - start).total_seconds() // 3600) + 1
    print(f"[recent] {start} -> {now}  ({hours} hour file(s))")
    new = hourly_from_ticks(start, now + dt.timedelta(hours=1))

    frames = [f for f in (old, new) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=COLS)
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True))
    m.to_csv(RECENT, index=False)
    m.to_csv(OUT / "hourly_recent.csv", index=False)
    return m


if __name__ == "__main__":
    h = update_history()
    r = update_recent()
    print(f"history bars {len(h):,} -> {h.ts.max()}")
    print(f"recent  bars {len(r):,} -> {r.ts.max() if len(r) else '-'}")
