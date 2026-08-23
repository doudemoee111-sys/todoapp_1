import fs from 'node:fs';
import { p, loadConfig } from '../lib/paths.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry, stubScript } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

export async function script(date) {
  const { config } = loadConfig();
  const plan = JSON.parse(fs.readFileSync(p(date, 'plan.json'), 'utf8'));
  const { durationSec, sceneCount } = config.post;

  const out = isDry()
    ? stubScript(plan, config)
    : await askJson({
        system: `あなたは日本語のInstagramリール構成作家です。必ずJSONのみを返します。
出力形式:
{
  "title": "20文字以内の内部管理用タイトル",
  "hook": "冒頭3秒で読ませる12文字以内のテロップ",
  "scenes": [
    {"n":1,"narration":"読み上げ原稿","onScreenText":"画面テロップ(18文字以内)","imagePrompt":"英語の画像生成プロンプト"}
  ],
  "cta": "最後の一言"
}`,
        user: `題材: ${plan.topic}
ジャンル: ${config.account.genre}
ターゲット: ${config.account.persona}
トーン: ${config.account.tone}

制約:
- 全体で約${durationSec}秒。シーンは${sceneCount}個ちょうど。
- narration は1シーンあたり日本語で${Math.round((durationSec / sceneCount) * 6)}文字前後（読み上げ速度を考慮）。
- 冒頭3秒(hook)で「自分ごと」だと分からせる。煽らない。数字か具体物を入れる。
- 最後は「${config.post.ctaText}」に自然につなげる。
- imagePrompt は英語。人物の顔・文字・ロゴを含めない。スタイル: ${config.post.imageStylePrompt}
- 次の表現は使用禁止: ${config.account.ngExpressions.join(' / ')}
- 断定的な効能表現、誇大表現、根拠のない数値を書かない。実演で確認できる範囲のことだけ書く。`,
      });

  if (!Array.isArray(out.scenes) || !out.scenes.length) throw new Error('script: scenes が空です');
  out.scenes = out.scenes.slice(0, sceneCount).map((s, i) => ({ ...s, n: i + 1 }));
  fs.writeFileSync(p(date, 'script.json'), JSON.stringify(out, null, 2));
  log.ok(`台本生成: ${out.scenes.length}シーン / hook「${out.hook}」`);
  return out;
}
