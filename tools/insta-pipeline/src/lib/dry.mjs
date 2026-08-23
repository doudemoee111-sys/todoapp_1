import fs from 'node:fs';
import zlib from 'node:zlib';

export const isDry = () => process.env.PIPELINE_DRY_RUN === '1';

/** 依存ゼロの単色PNG生成（dry-run用のダミー画像） */
export function writeSolidPng(outPath, w = 540, h = 960, rgb = [24, 34, 58]) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) {
    const o = y * (w * 3 + 1);
    raw[o] = 0;
    for (let x = 0; x < w; x++) {
      raw[o + 1 + x * 3] = rgb[0];
      raw[o + 2 + x * 3] = rgb[1];
      raw[o + 3 + x * 3] = rgb[2];
    }
  }
  const crcTable = [...Array(256)].map((_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
    const cr = Buffer.alloc(4);
    cr.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, cr]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  fs.writeFileSync(outPath, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]));
  return outPath;
}

export function stubScript(plan, cfg) {
  const n = cfg.post.sceneCount;
  return {
    title: `[DRY] ${plan.topic}`,
    hook: '請求書30枚、5分で終わらせた話',
    scenes: Array.from({ length: n }, (_, i) => ({
      n: i + 1,
      narration: `これはドライラン用のダミー音声原稿です。シーン${i + 1}の説明が入ります。`,
      onScreenText: `シーン${i + 1}のテロップ`,
      imagePrompt: 'flat vector infographic, muted navy palette, no text',
    })),
    cta: cfg.post.ctaText,
  };
}

export function stubCaption(plan, cfg) {
  return {
    caption: `${cfg.post.prLabel}\n\n[DRY] ${plan.topic}\n\nダミーのキャプション本文です。\n\n${cfg.post.ctaText}`,
    hashtags: ['#経理', '#業務効率化', '#AI活用', '#バックオフィス'].slice(0, cfg.post.hashtagCount),
  };
}
