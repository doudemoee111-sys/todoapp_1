import fs from 'node:fs';
import { p, loadConfig } from '../lib/paths.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry, stubCaption } from '../lib/dry.mjs';
import { hashtagSpec, ctaFor } from '../lib/format.mjs';
import { log } from '../lib/log.mjs';

export async function caption(date) {
  const { config } = loadConfig();
  const plan = JSON.parse(fs.readFileSync(p(date, 'plan.json'), 'utf8'));
  const sc = JSON.parse(fs.readFileSync(p(date, 'script.json'), 'utf8'));
  const tags = hashtagSpec(config);
  const cta = ctaFor(date, config);
  const pick = Math.max(0, tags.count - tags.fixed.length);

  const out = isDry()
    ? stubCaption(plan, config, { cta, pool: tags.pool, pick })
    : await askJson({
        system: `あなたは日本語のInstagram運用者です。必ずJSONのみを返します。
出力形式: {"caption":"本文","hashtags":["#...", ...]}`,
        user: `題材: ${plan.topic}
投稿フォーマット: ${sc.format || '指定なし'}
台本の要点: ${sc.scenes.map((s) => s.onScreenText).join(' / ')}
ターゲット: ${config.account.persona}
トーン: ${config.account.tone}

制約:
- 本文は300〜500文字。冒頭1行で「誰向けか」を明示。
- 「保存して後で試す」動機づけの一文を入れる。
- 末尾に「${cta}」を自然に入れる。
- 禁止表現: ${config.account.ngExpressions.join(' / ')}
- 次の話題には踏み込まない: ${(config.account.forbiddenTopics || []).join(' / ') || 'なし'}
- 効能の断定、根拠のない数値、他社比較の優劣断定を書かない。
- 本文中にPR表記は入れない（システム側で冒頭に付与するため）。
- hashtags には、次の候補から関連性の高い順に**ちょうど${pick}個**だけ選んで返してください（新しいタグを作らない）:
  ${tags.pool.join(' ')}`,
      });

  // --- PR表記を冒頭に強制付与（ステマ規制対応）---
  let body = String(out.caption || '').trim();
  const label = config.post.prLabel;
  if (config.compliance.requirePrLabel && !body.startsWith(label)) {
    body = `${label}\n\n${body}`;
  }
  // 固定タグ + AIが候補プールから選んだタグ を結合して重複排除
  const chosen = (out.hashtags || []).filter((t) => !tags.pool.length || tags.pool.includes(t));
  const hashtags = [...new Set([...tags.fixed, ...chosen])].slice(0, tags.count);
  const full = `${body}\n\n${hashtags.join(' ')}`;

  const result = { caption: body, hashtags, fullText: full };
  fs.writeFileSync(p(date, 'caption.json'), JSON.stringify(result, null, 2));
  fs.writeFileSync(p(date, 'caption.txt'), full);
  log.ok(`キャプション生成（${full.length}文字 / タグ${hashtags.length}個 / 冒頭「${label}」）`);
  if (hashtags.length < tags.count) log.warn(`ハッシュタグが${hashtags.length}個です（目標${tags.count}個）。pool を増やすか count を下げてください。`);
  return result;
}
