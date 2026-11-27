#!/usr/bin/env python3
"""Intraday refresh of the MT4 level feed. One command, nothing else.

The morning forecast is the widest one the model ever produces, because at
07:00 JST none of the session has happened yet. The conditional band narrows
as the session fills in, at the same 80% coverage:

    07:00  $251   (the morning box)
    11:00  $193
    15:00  $165
    19:00  $135
    22:00  $124
    23:00   $86

Publishing only in the morning meant the terminal always showed the widest
version. This refreshes the feed during the session so the conditional lines
tighten through the day. It writes no report and touches no dashboard, and it
does not change the EA, so nothing needs recompiling.

    python3 refresh_intraday.py
"""
from __future__ import annotations
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
REPO = HERE.parent.parent
FEED = HERE / "mt4" / "latest.txt"
JST = ZoneInfo("Asia/Tokyo")


def sh(*cmd: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def stamp_of(text: str) -> str:
    m = re.search(r"^META\|generated_at\|(.+)$", text, re.M)
    return m.group(1) if m else ""


def main() -> int:
    before = FEED.read_text() if FEED.exists() else ""
    sys.path.insert(0, str(HERE))
    from update import update_history, update_recent
    import export_mt4_levels

    print("[1/4] data")
    update_history()        # cheap: the archive already covers closed months
    update_recent()         # only the hours since the last run

    print("[2/4] feed")
    if export_mt4_levels.main() != 0:
        print("FAIL: the feed could not be written"); return 1
    refreshed = list(export_mt4_levels.REFRESHED)

    print("[3/4] checks")
    from daily_report import target_session
    after = FEED.read_text()
    counts = {c: after.count(f"|{c}|") for c in ("nyclose", "utc")}
    sessions = dict(re.findall(r"^INFO\|(\w+)\|session\|(.+)$", after, re.M))
    # The session that is live right now, per convention. NOT the JST calendar
    # date: the nyclose session labelled D runs 07:00 JST on D to 07:00 on D+1,
    # so between midnight and 07:00 the live session is yesterday's label and
    # comparing against today's date rejects a perfectly good feed. That is
    # what failed 27 of the last 30 scheduled runs.
    live = {c: str(target_session(c)[0]) for c in ("nyclose", "utc")}
    print(f"      records {counts}   sessions {sessions}   live {live}")
    print(f"      refreshed this run: {refreshed or 'none'}")

    for c in ("nyclose", "utc"):
        if counts[c] == 0:
            print(f"FAIL: no {c} records -- that broker's terminal would draw "
                  f"nothing. Not publishing."); return 1
    if not refreshed:
        # In the last hours before a boundary both conventions roll to a
        # session that has not opened, so neither can be rebuilt and the feed
        # on disk is already the right one. Nothing to do is not a failure.
        print("      no convention could be rebuilt in this window "
              "(each one's next session has not opened yet); feed left as is")
        # Still save the hours just fetched, or the next run pays for them again.
        sh("git", "add", "tools/xauusd-range/data_archive/hourly_recent.csv")
        c = sh("git", "commit", "-q", "-m",
               f"Cache XAU/USD bars fetched at {dt.datetime.now(JST):%Y-%m-%d %H:%M} JST\n\n"
               "No feed change: in this window neither convention's next\n"
               "session has opened, so there was nothing to rebuild.\n\n"
               "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>")
        if c.returncode == 0:
            sh("git", "fetch", "-q", "origin", "claude/funny-mayer-vcwsjx")
            sh("git", "rebase", "-q", "--autostash", "origin/claude/funny-mayer-vcwsjx")
            sh("git", "push", "-q", "origin", "claude/funny-mayer-vcwsjx")
        return 0
    if stamp_of(after) == stamp_of(before):
        print("FAIL: the feed did not change. Not publishing."); return 1

    print("[4/4] publish")
    sh("git", "add", "tools/xauusd-range/mt4/latest.txt",
       "tools/xauusd-range/data_archive/hourly_recent.csv")
    msg = (f"Refresh XAU/USD level feed intraday ({dt.datetime.now(JST):%Y-%m-%d %H:%M} JST)\n\n"
           "Narrows the conditional lines as the session fills in; the morning\n"
           "box is the widest the model produces.\n\n"
           "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n"
           "Claude-Session: https://claude.ai/code/session_0117ccvyYyL65CQ6cy4X4S5N")
    c = sh("git", "commit", "-q", "-m", msg)
    if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
        print(f"FAIL: commit\n{c.stdout}{c.stderr}"); return 1

    sh("git", "fetch", "-q", "origin", "claude/funny-mayer-vcwsjx")
    # --autostash: a rebase refuses outright on a dirty tree, and anything the
    # run regenerated but does not commit would otherwise block the push.
    sh("git", "rebase", "-q", "--autostash", "origin/claude/funny-mayer-vcwsjx")
    p = sh("git", "push", "-q", "origin", "claude/funny-mayer-vcwsjx")
    if p.returncode != 0:
        print(f"FAIL: push refused -- the EA keeps showing the previous "
              f"numbers.\n{p.stdout}{p.stderr}"); return 1

    print(f"      pushed. generated_at {stamp_of(after)}")
    for conv in ("nyclose", "utc"):
        sess = sessions.get(conv, "?")
        # A convention whose boundary has not been crossed yet carries its
        # previous records forward. Saying so here keeps a two-day-old band
        # from reading as this session's.
        tag = "" if sess == live.get(conv) else f"  [CARRIED from {sess} - live session is {live.get(conv)}]"
        band = re.findall(rf"^LEVEL\|{conv}\|cond_(high|low)\|80\|[^|]+\|(.+)$", after, re.M)
        if len(band) == 2:
            v = sorted(float(x[1]) for x in band)
            print(f"      {conv:8} session {sess}  conditional 80%: "
                  f"{v[0]:.2f} - {v[1]:.2f}  (${v[1]-v[0]:.0f} wide){tag}")
        else:
            print(f"      {conv:8} session {sess}  conditional 80%: not yet "
                  f"(under 2h elapsed){tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
