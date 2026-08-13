// Append (or replace) one day's OHLC bars into fx/data/*.csv, then the caller
// runs build_pages.mjs. Used by the daily cloud Routine, which collects the
// day's numbers via WebSearch and hands them to this script as JSON.
//
//   node fx/scripts/append_daily.mjs payload.json
//   echo '<json>' | node fx/scripts/append_daily.mjs -
//
// Payload shape:
//   { "date": "2026-08-13",
//     "USDJPY": { "open": 159.29, "high": 159.46, "low": 158.61, "close": 159.22 },
//     "GOLD":   { "open": 2400.1, "high": 2412.0, "low": 2395.5, "close": 2408.3 } }
// Any subset of the 6 symbols may be present; missing ones are left untouched.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SYMBOL_KEYS, SYMBOLS, DATA_DIR, loadSymbol, toCsv } from "./lib.mjs";

const arg = process.argv[2];
if (!arg) { console.error("usage: append_daily.mjs <payload.json|->"); process.exit(2); }
const text = arg === "-" ? readFileSync(0, "utf8") : readFileSync(arg, "utf8");
const payload = JSON.parse(text);

const date = payload.date;
if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "")) {
  console.error(`bad or missing "date" (need YYYY-MM-DD): ${date}`); process.exit(2);
}

let changed = 0;
for (const key of SYMBOL_KEYS) {
  const bar = payload[key];
  if (!bar) continue;
  const o = Number(bar.open), h = Number(bar.high), l = Number(bar.low), c = Number(bar.close);
  if (![o, h, l, c].every(Number.isFinite)) { console.error(`skip ${key}: non-numeric OHLC`); continue; }
  const dec = SYMBOLS.find((s) => s.key === key).decimals;
  const round = (v) => Number(v.toFixed(dec));
  const rows = loadSymbol(key).filter((r) => r.date !== date); // replace same-date
  rows.push({ date, o: round(o), h: round(h), l: round(l), c: round(c) });
  rows.sort((a, b) => (a.date < b.date ? -1 : 1));
  writeFileSync(join(DATA_DIR, `${key}.csv`), toCsv(rows));
  console.log(`${key}: ${date}  O ${round(o)} H ${round(h)} L ${round(l)} C ${round(c)}`);
  changed++;
}
console.log(changed ? `Updated ${changed} symbol(s) for ${date}.` : "No symbols updated.");
