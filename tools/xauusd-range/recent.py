"""Fill the current month from Dukascopy hourly TICK files (monthly candle
files are not published for the in-progress month)."""
from __future__ import annotations
import datetime as dt, lzma, struct, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from duka import UA, BASE, UTC, OUT

def _get(url, timeout=40, tries=9):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 404:
                return None
            time.sleep(2.0 * (1.7 ** i))   # 503 = rate limit -> back off and retry
    return None

def ticks_hour(h_utc: dt.datetime):
    url = f"{BASE}/{h_utc.year}/{h_utc.month-1:02d}/{h_utc.day:02d}/{h_utc.hour:02d}h_ticks.bi5"
    blob = _get(url)
    if not blob:
        return []
    try:
        d = lzma.LZMADecompressor().decompress(blob)
    except Exception:
        return []
    out = []
    for o in range(0, len(d) - 19, 20):
        ms, ask, bid, av, bv = struct.unpack(">iiiff", d[o:o + 20])
        out.append((h_utc + dt.timedelta(milliseconds=ms), bid / 1e3, ask / 1e3))
    return out

def hourly_from_ticks(start: dt.datetime, end: dt.datetime, workers=2) -> pd.DataFrame:
    hours, c = [], start
    while c < end:
        hours.append(c); c += dt.timedelta(hours=1)
    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(ticks_hour, hours):
            rows += r
    if not rows:
        return pd.DataFrame(columns=["ts","open","high","low","close","vol"])
    t = pd.DataFrame(rows, columns=["ts","bid","ask"]).set_index("ts").sort_index()
    o = t["bid"].resample("1h").ohlc().dropna().reset_index()
    o["vol"] = t["bid"].resample("1h").count().reindex(o["ts"]).values
    return o

if __name__ == "__main__":
    now = dt.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    h = hourly_from_ticks(dt.datetime(2026, 11, 1, tzinfo=UTC), now)
    print(f"recent hourly bars: {len(h)}  {h.ts.min()} -> {h.ts.max()}")
    print(h.tail(4).to_string(index=False))
