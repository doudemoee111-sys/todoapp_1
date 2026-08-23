import fs from 'node:fs';
import path from 'node:path';
import { p, loadConfig } from '../lib/paths.mjs';
import { generateImage } from '../lib/stability.mjs';
import { isDry, writeSolidPng } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

export async function images(date) {
  const { config } = loadConfig();
  const sc = JSON.parse(fs.readFileSync(p(date, 'script.json'), 'utf8'));
  const dir = p(date, 'images');
  fs.mkdirSync(dir, { recursive: true });

  const files = [];
  for (const s of sc.scenes) {
    const out = path.join(dir, `scene-${String(s.n).padStart(2, '0')}.png`);
    if (fs.existsSync(out)) { log.skip(`scene-${s.n} 既存`); files.push(out); continue; }
    if (isDry()) {
      writeSolidPng(out, 540, 960, [20 + s.n * 12, 32, 58]);
    } else {
      await generateImage({
        prompt: `${s.imagePrompt}. ${config.post.imageStylePrompt}`,
        negativePrompt: 'text, letters, words, watermark, logo, human face, distorted hands',
        outPath: out,
        aspectRatio: config.post.aspectRatio,
      });
    }
    log.ok(`scene-${s.n} 画像生成`);
    files.push(out);
  }
  fs.writeFileSync(p(date, 'images.json'), JSON.stringify({ files }, null, 2));
  return files;
}
