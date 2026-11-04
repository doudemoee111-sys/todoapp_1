"""Dukascopy XAU/USD loader -> NY-close daily bars (DST aware) + intraday bars."""
from __future__ import annotations
import datetime as dt, lzma, struct, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd

OUT = Path(__file__).parent / "data"; OUT.mkdir(exist_ok=True)
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
BASE = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
NY, JST, UTC = ZoneInfo("America/New_York"), ZoneInfo("Asia/Tokyo"), dt.timezone.utc
SCALE = 1e3
REC = ">5if"   # (sec_offset, open, close, low, high, volume)


def _get(url: str, timeout: int = 45, tries: int = 5) -> bytes | None:
    import time
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if getattr(e, "code", None) == 404:
                return None
            time.sleep(1.5 * (2 ** i))
    return None


def _decode(blob: bytes | None, base: dt.datetime) -> list[tuple]:
    if not blob:
        return []
    try:
        d = lzma.LZMADecompressor().decompress(blob)
    except Exception:
        return []
    out = []
    for off in range(0, len(d) - 23, 24):
        t, o, c, lo, hi, v = struct.unpack(REC, d[off:off + 24])
        if o == 0:
            continue
        out.append((base + dt.timedelta(seconds=t),
                    o / SCALE, hi / SCALE, lo / SCALE, c / SCALE, float(v)))
    return out


def fetch_months(months: list[tuple[int, int]], workers: int = 3) -> pd.DataFrame:
    """Fetch exactly these (year, month) pairs. One request each; month is
    0-indexed in the URL."""
    def job(ym):
        y, m = ym
        url = f"{BASE}/{y}/{m-1:02d}/BID_candles_hour_1.bi5"
        return _decode(_get(url), dt.datetime(y, m, 1, tzinfo=UTC))

    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(job, months):
            rows += r
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol"])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def fetch_hourly(start: dt.date, end: dt.date, workers: int = 3) -> pd.DataFrame:
    """One request per calendar month over a contiguous range."""
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m)); m += 1
        if m > 12: y, m = y + 1, 1

    def job(ym):
        y, m = ym
        url = f"{BASE}/{y}/{m-1:02d}/BID_candles_hour_1.bi5"
        return _decode(_get(url), dt.datetime(y, m, 1, tzinfo=UTC))

    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(job, months):
            rows += r
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol"])
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df.to_csv(OUT / "hourly.csv", index=False)
    return df


def fetch_minutes(days: list[dt.date], workers: int = 4) -> pd.DataFrame:
    """One request per day of 1-minute candles. URL month is 0-indexed."""
    def job(d: dt.date):
        url = f"{BASE}/{d.year}/{d.month-1:02d}/{d.day:02d}/BID_candles_min_1.bi5"
        return _decode(_get(url), dt.datetime(d.year, d.month, d.day, tzinfo=UTC))
    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(job, days):
            rows += r
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol"])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


#: Daily-bar boundary per broker server clock.
#:   nyclose -- server GMT+2/+3 with US DST (Axiory and most MT4/MT5 brokers):
#:              server midnight == NY 17:00, the standard FX day.
#:   utc     -- server GMT+0 fixed, no DST (Exness): boundary at 00:00 UTC,
#:              which is 09:00 JST, two hours later than nyclose in winter.
CONVENTIONS = ("nyclose", "utc")


def session_label(ts_utc: pd.Series, convention: str = "nyclose") -> pd.Series:
    """Trading-day label for each bar under the chosen boundary."""
    if convention == "utc":
        return ts_utc.dt.tz_convert(UTC).dt.date
    if convention != "nyclose":
        raise ValueError(f"unknown convention {convention!r}")
    # a bar at or after NY 17:00 belongs to the NEXT trading day
    return (ts_utc.dt.tz_convert(NY) + pd.Timedelta(hours=7)).dt.date


def to_daily(hourly: pd.DataFrame, convention: str = "nyclose") -> pd.DataFrame:
    h = hourly.copy()
    h["day"] = session_label(h["ts"], convention)
    g = h.groupby("day")
    d = pd.DataFrame({
        "open":  g["open"].first(),
        "high":  g["high"].max(),
        "low":   g["low"].min(),
        "close": g["close"].last(),
        "bars":  g["open"].size(),
        "vol":   g["vol"].sum(),
    }).reset_index().rename(columns={"day": "date"})
    d["date"] = pd.to_datetime(d["date"])
    # drop stub sessions (holidays / partial feed) -- a real session has many bars
    d = d[d["bars"] >= 12].reset_index(drop=True)
    d.to_csv(OUT / "daily_nyclose.csv", index=False)
    return d


if __name__ == "__main__":
    today = dt.date.today()
    h = fetch_hourly(dt.date(today.year - 10, today.month, 1), today)
    print(f"hourly bars : {len(h):,}  {h.ts.min()} -> {h.ts.max()}")
    d = to_daily(h)
    print(f"daily bars  : {len(d):,}  {d.date.min().date()} -> {d.date.max().date()}")
    print(d.tail(6).to_string(index=False))
