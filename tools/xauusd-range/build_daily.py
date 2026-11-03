"""Build the clean NY-close daily series from hourly bars (history + recent)."""
import sys, pandas as pd
sys.path.insert(0, '.')
from duka import session_label, OUT

def build() -> pd.DataFrame:
    frames = [pd.read_csv(OUT / "hourly.csv", parse_dates=["ts"])]
    try:
        frames.append(pd.read_csv(OUT / "hourly_recent.csv", parse_dates=["ts"]))
    except FileNotFoundError:
        pass
    h = (pd.concat(frames, ignore_index=True)
           .drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True))
    h["day"] = session_label(h["ts"])
    g = h.groupby("day")
    d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                      "low": g["low"].min(), "close": g["close"].last(),
                      "bars": g["open"].size(), "vol": g["vol"].sum()}).reset_index()
    d = d.rename(columns={"day": "date"})
    d["date"] = pd.to_datetime(d["date"])
    # real sessions only: Mon-Fri label, non-zero range, non-zero activity
    d = d[(d["date"].dt.dayofweek < 5) & (d["high"] > d["low"]) & (d["vol"] > 0)]
    d = d.sort_values("date").reset_index(drop=True)
    d.to_csv(OUT / "daily_clean.csv", index=False)
    return d, h

if __name__ == "__main__":
    d, h = build()
    print(f"hourly  : {len(h):,}  -> {h.ts.max()}")
    print(f"sessions: {len(d):,}  {d.date.min().date()} -> {d.date.max().date()}")
    print("\nlast 8 sessions (NY-close convention):")
    print(d.tail(8)[["date","open","high","low","close","bars"]].assign(
        rng=(d.high-d.low).round(2)).to_string(index=False))
