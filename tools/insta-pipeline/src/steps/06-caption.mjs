import fs from 'node:fs';
import { p, loadConfig } from '../lib/paths.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry, stubCaption } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

export async function caption(date) {
  const { config } = loadConfig();
  const plan = JSON.parse(fs.readFileSync(p(date, 'plan.json'), 'utf8'));
  const sc = JSON.parse(fs.readFileSync(p(date, 'script.json'), 'utf8'));

  const out = isDry()
    ? stubCaption(plan, config)
    : await askJson({
        system: `あなたは日本語のInstagram運用者です。必ずJSONのみを返します。
出力形式: {"caption":"本文","hashtags":["#...", ...]}`,
        user: `題材: ${plan.topic}
台本の要点: ${sc.scenes.map((s) => s.onScreenText).join(' / ')}
ターゲット: ${config.account.persona}
トーン: ${config.account.tone}

制約:
- 本文は300〜500文字。冒頭1行で「誰向けか」を明示。
- 「保存して後で試す」動機づけの一文を入れる。
- 末尾に「${config.post.ctaText}」を自然に入れる。
- ハッシュタグはちょうど${config.post.hashtagCount}個。関連性の高いものだけ。ビッグワードを並べない。
- 禁止表現: ${config.account.ngExpressions.join(' / ')}
- 効能の断定、根拠のない数値、他社比較の優劣断定を書かない。
- 本文中にPR表記は入れない（システム側で冒頭に付与するため）。`,
      });

  // --- PR表記を冒頭に強制付与（ステマ規制対応）---
  let body = String(out.caption || '').trim();
  const label = config.post.prLabel;
  if (config.compliance.requirePrLabel && !body.startsWith(label)) {
    body = `${label}\n\n${body}`;
  }
  const hashtags = (out.hashtags || []).slice(0, config.post.hashtagCount);
  const full = `${body}\n\n${hashtags.join(' ')}`;

  const result = { caption: body, hashtags, fullText: full };
  fs.writeFileSync(p(date, 'caption.json'), JSON.stringify(result, null, 2));
  fs.writeFileSync(p(date, 'caption.txt'), full);
  log.ok(`キャプション生成（${full.length}文字 / タグ${hashtags.length}個 / 冒頭「${label}」）`);
  return result;
}
