// Write ONE tiny daily delta file: fx/data/daily/<date>.json
// The unattended cloud Routine calls this locally to build the file, then
// commits just that file to GitHub via the API (mcp__github__create_or_update_file).
// Merging into the charts happens at build time (see lib.mjs loadAll / build_pages).
//
//   node fx/scripts/append_delta.mjs payload.json
//   echo '<json>' | node fx/scripts/append_delta.mjs -
//
// Payload (any subset of the 6 symbols):
//   { "date":"2026-08-14",
//     "USDJPY":{"open":159.29,"high":159.46,"low":158.61,"close":159.22},
//     "GOLD":{"open":4460,"high":4488,"low":4451,"close":4472} }
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { SYMBOL_KEYS, SYMBOLS, DAILY_DIR } from "./lib.mjs";

const arg = process.argv[2];
if (!arg) { console.error("usage: append_delta.mjs <payload.json|->"); process.exit(2); }
const payload = JSON.parse(arg === "-" ? readFileSync(0, "utf8") : readFileSync(arg, "utf8"));

const date = payload.date;
if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "")) {
  console.error(`bad or missing "date" (need YYYY-MM-DD): ${date}`); process.exit(2);
}

// Rough sanity bands to reject wrong-magnitude values (e.g. gold in JPY).
const BAND = { USDJPY: [80, 260], EURJPY: [90, 280], GBPJPY: [110, 320],
               EURUSD: [0.7, 1.7], GBPUSD: [0.9, 2.1], GOLD: [800, 8000] };

const out = { date };
let n = 0;
for (const key of SYMBOL_KEYS) {
  const bar = payload[key];
  if (!bar) continue;
  const o = Number(bar.open), h = Number(bar.high), l = Number(bar.low), c = Number(bar.close);
  if (![o, h, l, c].every(Number.isFinite)) { console.error(`skip ${key}: non-numeric`); continue; }
  const [lo, hi] = BAND[key];
  if ([o, h, l, c].some((v) => v < lo || v > hi)) { console.error(`skip ${key}: out of band (${lo}-${hi})`); continue; }
  const dec = SYMBOLS.find((s) => s.key === key).decimals;
  const r = (v) => Number(v.toFixed(dec));
  out[key] = { open: r(o), high: r(h), low: r(l), close: r(c) };
  n++;
}
if (!n) { console.error("no valid symbols in payload; nothing written."); process.exit(1); }

mkdirSync(DAILY_DIR, { recursive: true });
const path = join(DAILY_DIR, `${date}.json`);
const json = JSON.stringify(out, null, 2) + "\n";
writeFileSync(path, json);
console.log(`WROTE ${path} (${n} symbol(s))`);
console.log(`RELPATH fx/data/daily/${date}.json`);
console.log("----- CONTENT BEGIN -----");
process.stdout.write(json);
console.log("----- CONTENT END -----");
