// Shared configuration and helpers for the FX/Gold cloud automation.
// Pure Node (no external deps) so it runs in the locked-down cloud environment.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
export const ROOT = join(__dirname, "..");
export const DATA_DIR = join(ROOT, "data");
export const DAILY_DIR = join(DATA_DIR, "daily");
export const WEB_DIR = join(ROOT, "web");

// The 6 instruments carried over from the local system.
// `decimals` controls display precision; `yahoo` is the source symbol used by
// the daily updater when it asks WebSearch/Yahoo for the day's bar.
export const SYMBOLS = [
  { key: "USDJPY", label: "ドル円",     yahoo: "USDJPY=X", decimals: 3 },
  { key: "EURJPY", label: "ユーロ円",   yahoo: "EURJPY=X", decimals: 3 },
  { key: "GBPJPY", label: "ポンド円",   yahoo: "GBPJPY=X", decimals: 3 },
  { key: "EURUSD", label: "ユーロドル", yahoo: "EURUSD=X", decimals: 5 },
  { key: "GBPUSD", label: "ポンドドル", yahoo: "GBPUSD=X", decimals: 5 },
  { key: "GOLD",   label: "ゴールド",   yahoo: "XAUUSD",   decimals: 2 },
];

export const SYMBOL_KEYS = SYMBOLS.map((s) => s.key);

// Parse a data CSV. Accepts the canonical `date,open,high,low,close` header as
// well as common Japanese variants (日付/始値/高値/安値/終値) so a workbook
// export can be dropped in with minimal fixing.
const HEADER_ALIASES = {
  date: ["date", "日付", "日付き", "day"],
  open: ["open", "始値", "寄付"],
  high: ["high", "高値"],
  low: ["low", "安値"],
  close: ["close", "終値", "引け"],
};

function resolveColumns(header) {
  const cols = header.map((h) => h.trim());
  const idx = {};
  for (const [field, aliases] of Object.entries(HEADER_ALIASES)) {
    idx[field] = cols.findIndex((c) => aliases.includes(c.toLowerCase?.() ? c.toLowerCase() : c) || aliases.includes(c));
  }
  return idx;
}

function normalizeDate(raw) {
  const s = String(raw).trim();
  // Already ISO.
  let m = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if (m) {
    const [, y, mo, d] = m;
    return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }
  return null;
}

export function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
  if (!lines.length) return [];
  const header = lines[0].split(",");
  const idx = resolveColumns(header);
  const hasHeader = idx.date >= 0 && idx.close >= 0;
  const rows = [];
  const start = hasHeader ? 1 : 0;
  const col = hasHeader ? idx : { date: 0, open: 1, high: 2, low: 3, close: 4 };
  for (let i = start; i < lines.length; i++) {
    const parts = lines[i].split(",");
    const date = normalizeDate(parts[col.date]);
    if (!date) continue;
    const o = Number(parts[col.open]);
    const h = Number(parts[col.high]);
    const l = Number(parts[col.low]);
    const c = Number(parts[col.close]);
    if (![o, h, l, c].every(Number.isFinite)) continue;
    rows.push({ date, o, h, l, c });
  }
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return rows;
}

export function loadSymbol(key) {
  const path = join(DATA_DIR, `${key}.csv`);
  if (!existsSync(path)) return [];
  return parseCsv(readFileSync(path, "utf8"));
}

// Daily delta files: fx/data/daily/YYYY-MM-DD.json, each carrying that day's
// OHLC for any subset of symbols. The unattended cloud Routine appends one such
// tiny file per day via the GitHub API (small, reliable), instead of rewriting
// the large base CSVs. build merges base CSV history + all daily deltas.
export function loadDeltas() {
  if (!existsSync(DAILY_DIR)) return [];
  const files = readdirSync(DAILY_DIR).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).sort();
  const out = [];
  for (const f of files) {
    try {
      const obj = JSON.parse(readFileSync(join(DAILY_DIR, f), "utf8"));
      obj.date = obj.date || f.slice(0, 10);
      if (/^\d{4}-\d{2}-\d{2}$/.test(obj.date)) out.push(obj);
    } catch { /* skip malformed delta */ }
  }
  return out;
}

// Merge base CSV history with daily deltas (deltas win on same date).
export function loadAll() {
  const deltas = loadDeltas();
  const out = {};
  for (const s of SYMBOLS) {
    const map = new Map();
    for (const r of loadSymbol(s.key)) map.set(r.date, r);
    for (const d of deltas) {
      const bar = d[s.key];
      if (!bar) continue;
      const o = Number(bar.open ?? bar.o), h = Number(bar.high ?? bar.h);
      const l = Number(bar.low ?? bar.l), c = Number(bar.close ?? bar.c);
      if (![o, h, l, c].every(Number.isFinite)) continue;
      map.set(d.date, { date: d.date, o, h, l, c });
    }
    out[s.key] = [...map.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  }
  return out;
}

export function toCsv(rows) {
  const lines = ["date,open,high,low,close"];
  for (const r of rows) lines.push([r.date, r.o, r.h, r.l, r.c].join(","));
  return lines.join("\n") + "\n";
}
