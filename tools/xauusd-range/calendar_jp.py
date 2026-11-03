"""Economic calendar for the XAU/USD session window.

Source: 外為どっとコム economic calendar (public page, JST times already).
robots.txt permits /gaikaex/mark/calendar/ (only /mark/calender_mob/ is denied).
"""
from __future__ import annotations
import datetime as dt, html, re, urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
URL = "https://www.gaikaex.com/gaikaex/mark/calendar/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

# what actually moves gold
GOLD_COUNTRIES = {"米国", "ユーロ圏", "ドイツ", "英国", "中国"}
GOLD_KEYWORDS = (
    "FOMC", "政策金利", "パウエル", "議長", "FRB", "ECB", "総裁",
    "消費者物価", "CPI", "PCE", "生産者物価", "PPI",
    "雇用統計", "非農業", "失業", "新規失業保険", "ADP", "JOLTS", "求人",
    "ISM", "GDP", "小売売上", "耐久財", "ミシガン", "消費者信頼感",
    "鉱工業生産", "住宅", "ベージュブック", "国債", "入札",
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def fetch(timeout: int = 40) -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parse(page: str, year: int | None = None) -> list[dict]:
    year = year or dt.datetime.now(JST).year
    rows, cur_md = [], None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [_clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
        if not cells or cells[0] == "発表日":
            continue
        if len(cells) >= 8:                       # row that carries the date
            m = re.match(r"(\d{1,2})/(\d{1,2})", cells[0])
            if m:
                cur_md = (int(m.group(1)), int(m.group(2)))
            cells = cells[1:]
        if cur_md is None or len(cells) < 5:
            continue
        tm, country, name, stars = cells[0], cells[1], cells[2], cells[3]
        fc, act, prev = (cells[4:] + ["", "", ""])[:3]
        hm = re.match(r"(\d{1,2}):(\d{2})", tm)
        when = None
        if hm:
            # the page uses the Japanese 24:00-27:00 convention for past-midnight
            hh, mm = int(hm.group(1)), int(hm.group(2))
            try:
                when = (dt.datetime(year, cur_md[0], cur_md[1], 0, mm, tzinfo=JST)
                        + dt.timedelta(hours=hh))
            except ValueError:
                when = None
        rows.append({"when": when, "date": cur_md, "time": tm, "country": country,
                     "name": name, "importance": stars.count("★"),
                     "forecast": fc, "actual": act, "previous": prev})
    return rows


def gold_relevant(ev: dict, min_stars: int = 2) -> bool:
    if ev["importance"] >= 3:
        return True
    hit = any(k in ev["name"] for k in GOLD_KEYWORDS)
    return hit and ev["importance"] >= min_stars and ev["country"] in GOLD_COUNTRIES


def session_events(page: str, session_date: dt.date) -> list[dict]:
    """Events inside the NY-close session: 07:00 JST on session_date -> +24h.

    (07:00 JST matches NY 17:00 under US standard time; it is 06:00 JST while
    US daylight saving is in force, so the window is derived from NY 17:00.)
    """
    NY = ZoneInfo("America/New_York")
    start_ny = dt.datetime.combine(session_date - dt.timedelta(days=1),
                                   dt.time(17), tzinfo=NY)
    start, end = start_ny.astimezone(JST), (start_ny + dt.timedelta(days=1)).astimezone(JST)
    out = [e for e in parse(page)
           if e["when"] and start <= e["when"] < end and gold_relevant(e)]
    return sorted(out, key=lambda e: e["when"])


def session_events_window(page: str, start, end) -> list[dict]:
    """Gold-relevant events inside an explicit [start, end) JST window."""
    out = [e for e in parse(page)
           if e["when"] and start <= e["when"] < end and gold_relevant(e)]
    return sorted(out, key=lambda e: e["when"])


if __name__ == "__main__":
    page = fetch()
    today = dt.datetime.now(JST).date()
    for d in (today, today + dt.timedelta(days=1)):
        evs = session_events(page, d)
        print(f"\n=== session {d} ({len(evs)} gold-relevant events) ===")
        for e in evs:
            print(f"  {e['when'].strftime('%m/%d %H:%M')} JST  {'★'*e['importance']:<3} "
                  f"{e['country']:<6} {e['name'][:44]:<44} 予想 {e['forecast'] or '-':<9} 結果 {e['actual'] or '-'}")
