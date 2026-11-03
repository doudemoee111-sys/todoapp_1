"""Where in the day XAU/USD prints its session high and low (JST hours).

Needed because the 07:30 JST report is issued before the bulk of the
session's price discovery has happened.
"""
from __future__ import annotations
import pandas as pd
from duka import session_label, JST, OUT

BLOCKS = [("アジア", 7, 16), ("ロンドン", 16, 22), ("NY", 22, 7)]


def _hourly() -> pd.DataFrame:
    frames = [pd.read_csv(OUT / "hourly.csv", parse_dates=["ts"])]
    try:
        frames.append(pd.read_csv(OUT / "hourly_recent.csv", parse_dates=["ts"]))
    except FileNotFoundError:
        pass
    h = (pd.concat(frames, ignore_index=True)
           .drop_duplicates("ts", keep="last").sort_values("ts"))
    h["day"] = session_label(h["ts"])
    h["jst"] = h["ts"].dt.tz_convert(JST).dt.hour
    return h


def block_of(hr: int) -> str:
    for name, a, b in BLOCKS:
        if a < b and a <= hr < b:
            return name
        if a > b and (hr >= a or hr < b):
            return name
    return "?"


def stats(lookback: int = 250) -> dict:
    h = _hourly()
    d = pd.read_csv(OUT / "daily_clean.csv", parse_dates=["date"])
    full = set(d.loc[d.bars >= 20, "date"].dt.date)
    hh = h[h["day"].isin(full)]
    g = hh.groupby("day")
    hi = hh.loc[g["high"].idxmax(), ["day", "jst"]].set_index("day")["jst"]
    lo = hh.loc[g["low"].idxmin(), ["day", "jst"]].set_index("day")["jst"]
    recent = set(pd.Series(sorted(full)).tail(lookback))

    def prof(s, days):
        s = s[s.index.isin(days)]
        return (s.value_counts(normalize=True).reindex(range(24), fill_value=0),
                s.map(block_of).value_counts(normalize=True))

    hp_a, hb_a = prof(hi, full); lp_a, lb_a = prof(lo, full)
    hp_r, hb_r = prof(hi, recent); lp_r, lb_r = prof(lo, recent)

    # Asia block range vs the whole session, and whether its extremes survive
    tok = hh[hh.jst.isin(range(7, 16))].groupby("day").agg(th=("high", "max"), tl=("low", "min"))
    dd = d[d.bars >= 20].set_index(d.loc[d.bars >= 20, "date"].dt.date)
    j = tok.join(dd[["high", "low"]], how="inner")
    j["share"] = (j.th - j.tl) / (j.high - j.low)
    j["hi_held"] = j.th >= j.high - 1e-9
    j["lo_held"] = j.tl <= j.low + 1e-9
    k = j[j.index.isin(recent)]
    return {
        "hour_high_all": hp_a, "hour_low_all": lp_a,
        "hour_high_recent": hp_r, "hour_low_recent": lp_r,
        "block_high_all": hb_a, "block_low_all": lb_a,
        "block_high_recent": hb_r, "block_low_recent": lb_r,
        "asia_share": k.share.mean(), "asia_share_med": k.share.median(),
        "asia_hi_held": k.hi_held.mean(), "asia_lo_held": k.lo_held.mean(),
        "asia_both_broken": ((~k.hi_held) & (~k.lo_held)).mean(),
        "n_recent": len(k),
    }
