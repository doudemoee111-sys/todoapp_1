import fs from 'node:fs';
import { env } from './env.mjs';

const CANDIDATES = [
  '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
  '/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf',
  '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
  '/usr/share/fonts/truetype/fonts-japanese-gothic.ttf',
  '/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf',
  '/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc',
  '/System/Library/Fonts/Hiragino Sans GB.ttc',
  'C:/Windows/Fonts/YuGothB.ttc',
  'C:/Windows/Fonts/meiryob.ttc',
];

/** 日本語テロップ用フォントを探す。見つからなければ null。 */
export function findJpFont() {
  const override = env('FONT_FILE');
  if (override && fs.existsSync(override)) return override;
  return CANDIDATES.find((f) => fs.existsSync(f)) || null;
}
