import fs from 'node:fs';
import path from 'node:path';
import { ROOT } from './paths.mjs';

/** 依存ゼロの .env ローダ（既存の環境変数は上書きしない） */
export function loadEnv() {
  const f = path.join(ROOT, '.env');
  if (!fs.existsSync(f)) return;
  for (const line of fs.readFileSync(f, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    const v = m[2].replace(/^["']|["']$/g, '');
    if (v && process.env[m[1]] === undefined) process.env[m[1]] = v;
  }
}

export function env(key, fallback = undefined) {
  const v = process.env[key];
  return v === undefined || v === '' ? fallback : v;
}

export function requireEnv(key) {
  const v = env(key);
  if (!v) throw new Error(`環境変数 ${key} が未設定です。.env を確認してください（.env.example をコピー）。`);
  return v;
}
