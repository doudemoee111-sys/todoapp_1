// Build the two self-contained HTML pages from fx/data/*.csv.
//   node fx/scripts/build_pages.mjs
// Output: fx/web/fx_candlestick.html, fx/web/fx_dashboard.html
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SYMBOLS, WEB_DIR, loadAll } from "./lib.mjs";

const TPL = join(import.meta.dirname, "templates");
const core = readFileSync(join(TPL, "core.js"), "utf8");

const all = loadAll();
// Compact rows: [date, o, h, l, c]
const data = {};
let total = 0;
for (const s of SYMBOLS) {
  data[s.key] = all[s.key].map((r) => [r.date, r.o, r.h, r.l, r.c]);
  total += data[s.key].length;
}
const syms = SYMBOLS.map((s) => ({ key: s.key, label: s.label, decimals: s.decimals }));
// UTC build stamp (no Date.now dependency on wall clock beyond this)
const built = new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC";

function render(name) {
  let html = readFileSync(join(TPL, name), "utf8");
  html = html.replace("/*__DATA__*/ {}", JSON.stringify(data));
  html = html.replace("/*__SYMS__*/ []", JSON.stringify(syms));
  html = html.replace("/*__BUILT__*/", built);
  html = html.replace("/*__CORE__*/", core);
  return html;
}

writeFileSync(join(WEB_DIR, "fx_candlestick.html"), render("candlestick.html"));
writeFileSync(join(WEB_DIR, "fx_dashboard.html"), render("dashboard.html"));
console.log(`Built 2 pages from ${total} rows across ${SYMBOLS.length} symbols. Stamp: ${built}`);
for (const s of SYMBOLS) console.log(`  ${s.key}: ${data[s.key].length} rows`);
