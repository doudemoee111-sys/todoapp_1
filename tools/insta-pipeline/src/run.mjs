#!/usr/bin/env node
import fs from 'node:fs';
import { loadEnv, env } from './lib/env.mjs';
import { todayJst, p, readState, markDone, isDone, loadConfig, ROOT } from './lib/paths.mjs';
import { hasFfmpeg } from './lib/ffmpeg.mjs';
import { findJpFont } from './lib/font.mjs';
import { log } from './lib/log.mjs';

import { plan } from './steps/01-plan.mjs';
import { script } from './steps/02-script.mjs';
import { images } from './steps/03-images.mjs';
import { voice } from './steps/04-voice.mjs';
import { video, findRecording } from './steps/05-video.mjs';
import { caption } from './steps/06-caption.mjs';
import { compliance } from './steps/07-compliance.mjs';
import { publish } from './steps/08-publish.mjs';

const STEPS = [
  ['plan', '企画（ネタ選定）', plan],
  ['script', '台本生成', script],
  ['images', '画像生成', images],
  ['voice', 'ナレーション生成', voice],
  ['video', '動画合成', video],
  ['caption', 'キャプション生成', caption],
  ['compliance', '法務セルフチェック', compliance],
];

function parseArgs(argv) {
  const a = { date: null, dryRun: false, force: false, only: null, publish: false, doctor: false };
  for (const x of argv.slice(2)) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(x)) a.date = x;
    else if (x === '--dry-run') a.dryRun = true;
    else if (x === '--force') a.force = true;
    else if (x === '--publish') a.publish = true;
    else if (x === '--doctor') a.doctor = true;
    else if (x.startsWith('--date=')) a.date = x.slice(7);
    else if (x.startsWith('--only=')) a.only = x.slice(7).split(',');
  }
  return a;
}

function doctor() {
  const { configPath } = loadConfig();
  const checks = [
    ['OPENAI_API_KEY', Boolean(env('OPENAI_API_KEY')), '企画・台本・キャプション・法務レビュー'],
    ['STABILITY_API_KEY', Boolean(env('STABILITY_API_KEY')), '画像生成'],
    ['GOOGLE_TTS_API_KEY', Boolean(env('GOOGLE_TTS_API_KEY')), 'ナレーション生成'],
    ['IG_USER_ID', Boolean(env('IG_USER_ID')), '自動投稿・インサイト（任意）'],
    ['IG_ACCESS_TOKEN', Boolean(env('IG_ACCESS_TOKEN')), '自動投稿・インサイト（任意）'],
    ['PUBLIC_ASSET_BASE_URL', Boolean(env('PUBLIC_ASSET_BASE_URL')), '自動投稿（動画の公開URL）'],
  ];
  log.step('doctor', '環境チェック');
  log.info(`config: ${configPath.replace(ROOT + '/', '')}`);
  for (const [k, ok, use] of checks) (ok ? log.ok : log.warn)(`${k.padEnd(24)} ${ok ? 'OK  ' : '未設定'} — ${use}`);
  (hasFfmpeg() ? log.ok : log.warn)(`${'ffmpeg'.padEnd(24)} ${hasFfmpeg() ? 'OK' : '未インストール — 動画合成のみ不可'}`);
  const f = findJpFont();
  (f ? log.ok : log.warn)(`${'日本語フォント'.padEnd(20)} ${f || '未検出 — テロップ焼き込み不可（FONT_FILE で指定可）'}`);
  const rec = findRecording(todayJst());
  (rec ? log.ok : log.warn)(`${'本日の画面録画'.padEnd(20)} ${rec || `assets/recordings/${todayJst()}.mp4 が未配置`}`);
}

async function main() {
  loadEnv();
  const args = parseArgs(process.argv);
  if (args.dryRun) process.env.PIPELINE_DRY_RUN = '1';
  if (args.doctor) return doctor();

  const date = args.date || todayJst();
  log.step('start', `Instagram 日次パイプライン — ${date}${args.dryRun ? ' (DRY RUN)' : ''}`);

  for (const [key, label, fn] of STEPS) {
    if (args.only && !args.only.includes(key)) { log.skip(`${key}（--only 指定外）`); continue; }
    if (!args.force && isDone(date, key)) { log.skip(`${key}（実行済み。--force で再実行）`); continue; }
    log.step(key, label);
    try {
      const r = await fn(date);
      markDone(date, key, { summary: typeof r === 'object' && r ? undefined : String(r ?? '') });
    } catch (e) {
      log.err(`${key} で失敗: ${e.message}`);
      markDone(date, key, { done: false, error: e.message });
      process.exitCode = 1;
      return;
    }
  }

  log.step('done', '素材の生成が完了しました');
  log.info(`出力先: out/${date}/`);
  log.info(`次にやること: out/${date}/REVIEW.md を確認 → 問題なければ  touch out/${date}/APPROVED`);
  if (!fs.existsSync(p(date, 'reel.mp4'))) {
    log.warn('reel.mp4 は未生成です（ffmpeg未導入 or dry-run）。画像・音声・台本から手動で組み立ててください。');
  }

  if (args.publish) {
    log.step('publish', 'Instagram へ公開');
    await publish(date);
  } else {
    log.dim('（--publish を付けると承認済みの場合に自動公開します）');
  }
}

main().catch((e) => { log.err(e.stack || e.message); process.exit(1); });
