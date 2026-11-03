"""Incremental data refresh. Safe to run daily.

History  : one Dukascopy monthly candle file per completed month (cached in
           data/hourly.csv -- only missing months are fetched).
Current  : the in-progress month has no monthly candle file published, so it is
           rebuilt from hourly tick files, resuming from the last bar on disk.
"""
from __future__ import annotations
import datetime as dt
import pandas as pd
from duka import fetch_hourly, UTC, OUT
from recent import hourly_from_ticks

YEARS = 10


def _months(a: dt.date, b: dt.date):
    y, m, out = a.year, a.month, []
    while (y, m) <= (b.year, b.month):
        out.append((y, m)); m += 1
        if m > 12: y, m = y + 1, 1
    return out


def update_history(today: dt.date | None = None) -> pd.DataFrame:
    today = today or dt.datetime.now(UTC).date()
    start = dt.date(today.year - YEARS, today.month, 1)
    last_complete = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)
    want = set(_months(start, last_complete))

    path = OUT / "hourly.csv"
    have, old = set(), None
    if path.exists():
        old = pd.read_csv(path, parse_dates=["ts"])
        have = set(zip(old["ts"].dt.year, old["ts"].dt.month))
    missing = sorted(want - have)
    if not missing:
        return old
    print(f"[history] fetching {len(missing)} missing month(s): "
          f"{missing[0]} .. {missing[-1]}")
    a = dt.date(missing[0][0], missing[0][1], 1)
    b = dt.date(missing[-1][0], missing[-1][1], 1)
    new = fetch_hourly(a, b)          # writes hourly.csv itself
    if old is not None:
        merged = (pd.concat([old, new], ignore_index=True)
                    .drop_duplicates("ts", keep="last").sort_values("ts"))
        merged = merged[merged["ts"].dt.date >= start]
        merged.to_csv(path, index=False)
        return merged
    return new


def update_recent() -> pd.DataFrame:
    now = dt.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0)
    path = OUT / "hourly_recent.csv"
    old = None
    start = month_start
    if path.exists():
        old = pd.read_csv(path, parse_dates=["ts"])
        old = old[old["ts"] >= month_start]
        if len(old):
            start = old["ts"].max().to_pydatetime() + dt.timedelta(hours=1)
    # re-pull the last few hours: the newest tick files are often incomplete
    start = max(month_start, start - dt.timedelta(hours=3))
    print(f"[recent] ticks {start} -> {now}")
    new = hourly_from_ticks(start, now + dt.timedelta(hours=1))
    frames = [f for f in (old, new) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "vol"])
    m = (pd.concat(frames, ignore_index=True)
           .drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True))
    m.to_csv(path, index=False)
    return m


if __name__ == "__main__":
    h = update_history()
    r = update_recent()
    print(f"history bars {len(h):,} -> {h.ts.max()}")
    print(f"recent  bars {len(r):,} -> {r.ts.max() if len(r) else '-'}")
