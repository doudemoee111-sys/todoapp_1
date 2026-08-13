// Generate deterministic *sample* OHLC history so the pages render and the
// pipeline is verifiable before real data is dropped in. Replace the CSVs in
// fx/data/ with your real export to get the true 10-year charts.
//
//   node fx/scripts/make_sample_data.mjs [endDate=2026-08-12] [days=760]
//
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { SYMBOLS, DATA_DIR, toCsv } from "./lib.mjs";

const endArg = process.argv[2] || "2026-08-12";
const days = Number(process.argv[3] || 760);

// Deterministic PRNG (mulberry32) seeded per symbol — reproducible builds.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function randn(r) {
  // Box–Muller
  const u = Math.max(r(), 1e-9);
  const v = r();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const BASE = {
  USDJPY: { px: 150.0, vol: 0.0055, drift: 0.00010 },
  EURJPY: { px: 163.0, vol: 0.0055, drift: 0.00008 },
  GBPJPY: { px: 190.0, vol: 0.0060, drift: 0.00008 },
  EURUSD: { px: 1.085, vol: 0.0045, drift: -0.00004 },
  GBPUSD: { px: 1.270, vol: 0.0048, drift: -0.00003 },
  GOLD:   { px: 2000.0, vol: 0.0090, drift: 0.00025 },
};

function businessDaysBack(endDate, n) {
  const dates = [];
  const d = new Date(endDate + "T00:00:00Z");
  while (dates.length < n) {
    const dow = d.getUTCDay();
    if (dow !== 0 && dow !== 6) dates.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return dates.reverse();
}

for (let si = 0; si < SYMBOLS.length; si++) {
  const sym = SYMBOLS[si];
  const cfg = BASE[sym.key];
  const r = rng(1000 + si * 97);
  const dates = businessDaysBack(endArg, days);
  let prevClose = cfg.px;
  const rows = [];
  for (const date of dates) {
    const gap = prevClose * (randn(r) * cfg.vol * 0.25);
    const open = prevClose + gap;
    const ret = cfg.drift + randn(r) * cfg.vol;
    const close = open * (1 + ret);
    const wick = Math.abs(randn(r)) * cfg.vol * 0.6 + cfg.vol * 0.2;
    const hi = Math.max(open, close) * (1 + Math.abs(randn(r)) * cfg.vol * 0.4 + wick * 0.3);
    const lo = Math.min(open, close) * (1 - Math.abs(randn(r)) * cfg.vol * 0.4 - wick * 0.3);
    const round = (v) => Number(v.toFixed(sym.decimals));
    rows.push({ date, o: round(open), h: round(hi), l: round(lo), c: round(close) });
    prevClose = close;
  }
  writeFileSync(join(DATA_DIR, `${sym.key}.csv`), toCsv(rows));
  console.log(`${sym.key}: ${rows.length} rows  ${rows[0].date}..${rows.at(-1).date}`);
}
console.log("Sample data written to fx/data/");
