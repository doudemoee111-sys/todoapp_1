import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

/** JSTの YYYY-MM-DD を返す（サーバのTZに依存しない） */
export function todayJst(offsetDays = 0) {
  const now = new Date(Date.now() + offsetDays * 86400000);
  const jst = new Date(now.getTime() + 9 * 3600 * 1000);
  return jst.toISOString().slice(0, 10);
}

export function dayDir(date) {
  const d = path.join(ROOT, 'out', date);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

export const p = (date, ...rest) => path.join(dayDir(date), ...rest);

export function readState(date) {
  const f = p(date, 'state.json');
  if (!fs.existsSync(f)) return { date, steps: {} };
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

export function writeState(date, state) {
  fs.writeFileSync(p(date, 'state.json'), JSON.stringify(state, null, 2));
  return state;
}

export function markDone(date, step, data = {}) {
  const s = readState(date);
  s.steps[step] = { done: true, at: new Date().toISOString(), ...data };
  return writeState(date, s);
}

export function isDone(date, step) {
  return Boolean(readState(date).steps?.[step]?.done);
}

export function loadConfig() {
  const custom = path.join(ROOT, 'config.json');
  const example = path.join(ROOT, 'config.example.json');
  const f = fs.existsSync(custom) ? custom : example;
  return { config: JSON.parse(fs.readFileSync(f, 'utf8')), configPath: f };
}
