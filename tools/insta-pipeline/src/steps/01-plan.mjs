import fs from 'node:fs';
import path from 'node:path';
import { ROOT, p, loadConfig } from '../lib/paths.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

const USED = path.join(ROOT, 'out', '_used-topics.json');

function readUsed() {
  return fs.existsSync(USED) ? JSON.parse(fs.readFileSync(USED, 'utf8')) : [];
}
function pushUsed(topic) {
  const u = readUsed();
  u.push({ topic, at: new Date().toISOString() });
  fs.mkdirSync(path.dirname(USED), { recursive: true });
  fs.writeFileSync(USED, JSON.stringify(u, null, 2));
}

/** topics/backlog.md から未使用のネタを1件取り出す。無ければAIで補充。 */
export async function plan(date) {
  const { config } = loadConfig();
  const backlogFile = path.join(ROOT, 'topics', 'backlog.md');
  const used = new Set(readUsed().map((u) => u.topic));

  let topic = null;
  if (fs.existsSync(backlogFile)) {
    const lines = fs.readFileSync(backlogFile, 'utf8')
      .split('\n')
      .filter((l) => /^\s*[-*]\s+\S/.test(l))       // 箇条書き行のみをネタとして扱う
      .map((l) => l.replace(/^\s*[-*]\s+/, '').trim());
    topic = lines.find((l) => !used.has(l)) || null;
  }

  if (!topic) {
    log.warn('バックログに未使用ネタがありません。AIで20件補充します。');
    const gen = isDry()
      ? { topics: Array.from({ length: 20 }, (_, i) => `[DRY] 自動補充ネタ ${Date.now()}-${i}`) }
      : await askJson({
          system:
            'あなたは日本語のInstagramリール企画者です。必ずJSONのみを返します。形式: {"topics": ["...", ...]}',
          user: `ジャンル: ${config.account.genre}
ターゲット: ${config.account.persona}

このターゲットが「保存したくなる」リールのネタを20件、日本語で出してください。
条件:
- 1件は40文字以内の具体的な題材（例:「請求書PDF30枚をAIで仕訳データにした手順」）
- 実際に画面録画または実測で検証できるものに限る
- 抽象的な精神論・モチベーション系は禁止
- 既出と重複しないこと。既出: ${[...used].slice(-40).join(' / ') || 'なし'}`,
        });
    const fresh = (gen.topics || []).filter((t) => !used.has(t));
    if (!fresh.length) throw new Error('ネタを補充できませんでした。topics/backlog.md に手で追記してください。');
    fs.appendFileSync(backlogFile, '\n' + fresh.map((t) => `- ${t}`).join('\n') + '\n');
    topic = fresh[0];
  }

  const planObj = { date, topic, genre: config.account.genre, persona: config.account.persona };
  fs.writeFileSync(p(date, 'plan.json'), JSON.stringify(planObj, null, 2));
  pushUsed(topic);
  log.ok(`題材: ${topic}`);
  return planObj;
}
