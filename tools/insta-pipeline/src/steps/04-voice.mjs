import fs from 'node:fs';
import path from 'node:path';
import { p } from '../lib/paths.mjs';
import { synthesize } from '../lib/tts.mjs';
import { isDry } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

export async function voice(date) {
  const sc = JSON.parse(fs.readFileSync(p(date, 'script.json'), 'utf8'));
  const dir = p(date, 'audio');
  fs.mkdirSync(dir, { recursive: true });

  const files = [];
  for (const s of sc.scenes) {
    const out = path.join(dir, `scene-${String(s.n).padStart(2, '0')}.mp3`);
    if (fs.existsSync(out)) { log.skip(`scene-${s.n} 既存`); files.push(out); continue; }
    if (isDry()) {
      fs.writeFileSync(out, Buffer.alloc(64)); // ダミー
    } else {
      await synthesize({ text: s.narration, outPath: out });
    }
    log.ok(`scene-${s.n} 音声生成`);
    files.push(out);
  }
  fs.writeFileSync(p(date, 'audio.json'), JSON.stringify({ files }, null, 2));
  return files;
}
