// Build a compact machine-readable feed for the MT4 overlay.
//   node fx/scripts/build_mt4_feed.mjs
// Outputs (served via the same GitHub repo, picked up by `git add fx/web`):
//   fx/web/mt4_feed.csv  — ASCII, one row per symbol (easy to parse in MQL4)
//   fx/web/mt4_feed.json — same content as JSON, for any other consumer
//
// IMPORTANT: the values here are DERIVED STATISTICS, not a price feed.
// The daily close is the approximate (概算) value recorded each morning and
// must NOT be used as an execution price. MT4 already has the broker's live
// ticks; this feed only drives the statistical overlay (expected range, the
// validated reversal signal's parameters, and the latest recorded close marker).
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { SYMBOLS, WEB_DIR, loadAll } from "./lib.mjs";

// --- small stats helpers (sample std, matches the dashboard's std) ----------
function mean(a) { return a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN; }
function std(a) {
  if (a.length < 2) return NaN;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1));
}
function round(v, d) { return Number.isFinite(v) ? Number(v.toFixed(d)) : null; }

// Weekday (exclude Sat/Sun) rows, matching the dashboard's `weekdayRows()`.
function weekdayRows(rows) {
  return rows.filter((r) => {
    const dow = new Date(r.date + "T00:00:00Z").getUTCDay();
    return dow !== 0 && dow !== 6;
  });
}

// --- expected-range coefficients (parity with the dashboard forecast) -------
// 予想高値(k) = open + mu + k*su ;  予想安値(k) = open - (md + k*sd)
//   up   = high - open   (upside room from the open)
//   down = open - low    (downside room from the open)
function rangeCoeffs(rows) {
  const up = rows.map((r) => r.h - r.o);
  const down = rows.map((r) => r.o - r.l);
  return { mu: mean(up), su: std(up), md: mean(down), sd: std(down), n: rows.length };
}

// --- validated close-to-close reversal signal -------------------------------
// Mirrors fx/scripts/edge_scan2.py: look at consecutive daily close-to-close
// moves. For each N in 2..4 test both:
//   down-reversal: last N moves all DOWN  -> next day UP   (buy)
//   up-reversal:   last N moves all UP    -> next day DOWN (sell)
// Pick the best variant with samples >= MIN_N and winrate >= MIN_WR.
// The MT4 side re-evaluates the trigger live on the broker's own D1 closes;
// this only ships the rule and its measured edge.
const MIN_N = 60;
const MIN_WR = 0.60; // the user's stated guideline: surface a signal only at >=60%

function bestSignal(rows) {
  const c = rows.map((r) => r.c);
  const n = c.length;
  // up[i] = close[i] > close[i-1]
  const upMove = [null];
  for (let i = 1; i < n; i++) upMove.push(c[i] > c[i - 1]);

  let best = null;
  for (let k = 2; k <= 4; k++) {
    let kb = 0, nb = 0, ks = 0, ns = 0; // buy (down-reversal) / sell (up-reversal)
    for (let i = k + 1; i < n; i++) {
      const seg = upMove.slice(i - k, i);
      if (seg.every((x) => x === false)) { nb++; if (upMove[i]) kb++; }
      if (seg.every((x) => x === true)) { ns++; if (upMove[i] === false) ks++; }
    }
    const consider = [
      { dir: 1, consec: k, wins: kb, samples: nb },   // buy after k down
      { dir: -1, consec: k, wins: ks, samples: ns },  // sell after k up
    ];
    for (const cand of consider) {
      if (cand.samples < MIN_N) continue;
      const wr = cand.wins / cand.samples;
      if (wr < MIN_WR) continue;
      if (!best || wr > best.winrate) best = { dir: cand.dir, consec: cand.consec, winrate: wr, samples: cand.samples };
    }
  }
  return best || { dir: 0, consec: 0, winrate: 0, samples: 0 };
}

export function buildFeed() {
  const all = loadAll();
  const asof = new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC";
  const items = [];
  for (const s of SYMBOLS) {
    const rows = all[s.key];
    if (!rows || !rows.length) continue;
    const wd = weekdayRows(rows);
    const last = rows[rows.length - 1];
    const rc = rangeCoeffs(wd);
    const sig = bestSignal(wd);
    items.push({
      symbol: s.key,
      label: s.label,
      decimals: s.decimals,
      date: last.date,
      close: round(last.c, s.decimals),
      // expected-range coefficients
      mu: round(rc.mu, s.decimals + 2),
      su: round(rc.su, s.decimals + 2),
      md: round(rc.md, s.decimals + 2),
      sd: round(rc.sd, s.decimals + 2),
      n: rc.n,
      // signal rule (dir: 1=buy after N down, -1=sell after N up, 0=none)
      sig: sig.dir,
      consec: sig.consec,
      winrate: round(sig.winrate, 3),
      wins_n: sig.samples,
    });
  }
  return { asof, items };
}

function toCsv(feed) {
  const cols = ["symbol", "date", "close", "decimals", "mu", "su", "md", "sd", "n", "sig", "consec", "winrate", "wins_n"];
  const lines = ["# CloudFX MT4 feed — derived stats, NOT an execution price. asof=" + feed.asof, cols.join(",")];
  for (const it of feed.items) {
    lines.push([it.symbol, it.date, it.close, it.decimals, it.mu, it.su, it.md, it.sd, it.n, it.sig, it.consec, it.winrate, it.wins_n].join(","));
  }
  return lines.join("\n") + "\n";
}

export function writeFeed() {
  const feed = buildFeed();
  writeFileSync(join(WEB_DIR, "mt4_feed.json"), JSON.stringify(feed, null, 2) + "\n");
  writeFileSync(join(WEB_DIR, "mt4_feed.csv"), toCsv(feed));
  return feed;
}

// Allow running standalone as well as importing writeFeed() from build_pages.
if (import.meta.url === `file://${process.argv[1]}`) {
  const feed = writeFeed();
  console.log(`MT4 feed written: ${feed.items.length} symbols, asof ${feed.asof}`);
  for (const it of feed.items) {
    const sigTxt = it.sig === 1 ? `買い(${it.consec}連続下落→, ${(it.winrate * 100).toFixed(1)}%/n=${it.wins_n})`
      : it.sig === -1 ? `売り(${it.consec}連続上昇→, ${(it.winrate * 100).toFixed(1)}%/n=${it.wins_n})`
      : "シグナル無し";
    console.log(`  ${it.symbol}: close ${it.close} (${it.date})  μ↑${it.mu}/σ↑${it.su} μ↓${it.md}/σ↓${it.sd}  → ${sigTxt}`);
  }
}
