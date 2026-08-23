import fs from 'node:fs';
import path from 'node:path';
import { ROOT, p, loadConfig } from '../lib/paths.mjs';
import { hasFfmpeg, run, durationSec, escapeDrawtext } from '../lib/ffmpeg.mjs';
import { findJpFont } from '../lib/font.mjs';
import { isDry } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

const RECORDING_EXT = ['.mp4', '.mov', '.m4v', '.webm'];

/** その日の画面録画（一次情報）があれば返す */
export function findRecording(date) {
  const dir = path.join(ROOT, 'assets', 'recordings');
  if (!fs.existsSync(dir)) return null;
  for (const ext of RECORDING_EXT) {
    const f = path.join(dir, `${date}${ext}`);
    if (fs.existsSync(f)) return f;
  }
  return null;
}

function drawtextFilter({ text, font, y, size, box = true }) {
  if (!font) return null;
  const t = escapeDrawtext(text);
  return [
    `drawtext=fontfile='${font}'`,
    `text='${t}'`,
    `fontcolor=white`,
    `fontsize=${size}`,
    `x=(w-text_w)/2`,
    `y=${y}`,
    box ? `box=1:boxcolor=black@0.55:boxborderw=28` : '',
    `line_spacing=12`,
  ].filter(Boolean).join(':');
}

export async function video(date) {
  const { config } = loadConfig();
  const { width: W, height: H, fps } = config.post;
  const sc = JSON.parse(fs.readFileSync(p(date, 'script.json'), 'utf8'));
  const outFile = p(date, 'reel.mp4');

  if (isDry() || !hasFfmpeg()) {
    const why = isDry() ? 'dry-run' : 'ffmpeg が見つかりません';
    log.warn(`動画合成をスキップしました（${why}）。素材（画像・音声・台本）は出力済みです。`);
    fs.writeFileSync(p(date, 'video-skipped.txt'), `skipped: ${why}\n`);
    return null;
  }

  const font = findJpFont();
  if (!font) log.warn('日本語フォントが見つかりません。テロップ焼き込みをスキップします（音声は入ります）。');

  const tmp = p(date, 'tmp');
  fs.mkdirSync(tmp, { recursive: true });

  // --- ナレーションを1本に結合 ---
  const audios = sc.scenes.map((s) => p(date, 'audio', `scene-${String(s.n).padStart(2, '0')}.mp3`));
  const sceneDur = audios.map((a) => Math.max(1.2, durationSec(a) + 0.35)); // 各シーンに少し余白
  const narration = path.join(tmp, 'narration.mp3');
  const concatList = path.join(tmp, 'audio.txt');
  fs.writeFileSync(concatList, audios.map((a) => `file '${a.replace(/'/g, "'\\''")}'`).join('\n'));
  run(['-f', 'concat', '-safe', '0', '-i', concatList, '-c', 'copy', narration]);

  const recording = findRecording(date);

  if (recording) {
    // === 一次情報（画面録画）を本編に使う ===
    log.info(`画面録画を使用: ${path.basename(recording)}`);
    const filters = [`scale=${W}:${H}:force_original_aspect_ratio=increase`, `crop=${W}:${H}`, `fps=${fps}`];
    if (font) {
      const hook = drawtextFilter({ text: sc.hook, font, y: 'h*0.10', size: 76 });
      filters.push(`${hook}:enable='between(t,0,3)'`);
      let t = 3;
      for (let i = 0; i < sc.scenes.length; i++) {
        const d = sceneDur[i];
        const f = drawtextFilter({ text: sc.scenes[i].onScreenText, font, y: 'h*0.78', size: 54 });
        filters.push(`${f}:enable='between(t,${t.toFixed(2)},${(t + d).toFixed(2)})'`);
        t += d;
      }
    }
    run([
      '-i', recording, '-i', narration,
      '-filter_complex',
      `[0:v]${filters.join(',')}[v];[1:a]adelay=3000|3000,volume=1.0[a]`,
      '-map', '[v]', '-map', '[a]',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-pix_fmt', 'yuv420p',
      '-c:a', 'aac', '-b:a', '128k', '-shortest', outFile,
    ]);
  } else {
    // === 録画が無い場合: 生成画像のスライドショー ===
    log.warn('画面録画が見つかりません。生成画像のスライドショーで組み立てます。');
    log.warn('※ これは「一次情報なし」の状態です。オリジナル評価で不利になるため、本番運用では録画を置いてください。');
    const parts = [];
    for (let i = 0; i < sc.scenes.length; i++) {
      const s = sc.scenes[i];
      const img = p(date, 'images', `scene-${String(s.n).padStart(2, '0')}.png`);
      const clip = path.join(tmp, `clip-${i}.mp4`);
      const d = sceneDur[i];
      const zoom = `zoompan=z='min(zoom+0.0012,1.12)':d=${Math.round(d * fps)}:s=${W}x${H}:fps=${fps}`;
      const vf = [`scale=${W * 1.2}:${H * 1.2}:force_original_aspect_ratio=increase`, `crop=${W * 1.2}:${H * 1.2}`, zoom];
      if (font) {
        if (i === 0) vf.push(`${drawtextFilter({ text: sc.hook, font, y: 'h*0.10', size: 76 })}`);
        vf.push(drawtextFilter({ text: s.onScreenText, font, y: 'h*0.78', size: 54 }));
      }
      run([
        '-loop', '1', '-t', String(d), '-i', img, '-i', audios[i],
        '-vf', vf.join(','),
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-pix_fmt', 'yuv420p', '-r', String(fps),
        '-c:a', 'aac', '-b:a', '128k', '-shortest', clip,
      ]);
      parts.push(clip);
    }
    const list = path.join(tmp, 'clips.txt');
    fs.writeFileSync(list, parts.map((f) => `file '${f.replace(/'/g, "'\\''")}'`).join('\n'));
    run(['-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', outFile]);
  }

  log.ok(`動画を書き出しました: ${outFile} (${durationSec(outFile).toFixed(1)}秒)`);
  fs.writeFileSync(p(date, 'video.json'), JSON.stringify({
    file: outFile,
    usedRecording: Boolean(recording),
    recording: recording || null,
    durationSec: durationSec(outFile),
  }, null, 2));
  return outFile;
}
