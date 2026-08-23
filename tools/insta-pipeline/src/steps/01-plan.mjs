import fs from 'node:fs';
import path from 'node:path';
import { ROOT, p, loadConfig } from '../lib/paths.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry } from '../lib/dry.mjs';
import { formatFor, weekdayKey } from '../lib/format.mjs';
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

  const dayKey = weekdayKey(date);
  const fmt = formatFor(date, config);

  // バックログ行は「- [mon] 題材」形式。タグ無しはどの曜日にも使える。
  function readBacklog() {
    if (!fs.existsSync(backlogFile)) return [];
    return fs.readFileSync(backlogFile, 'utf8')
      .split('\n')
      .filter((l) => /^\s*[-*]\s+\S/.test(l))
      .map((l) => {
        const body = l.replace(/^\s*[-*]\s+/, '').trim();
        const m = body.match(/^\[(mon|tue|wed|thu|fri|sat|sun)\]\s*(.+)$/i);
        return m ? { tag: m[1].toLowerCase(), topic: m[2].trim() } : { tag: null, topic: body };
      });
  }

  // その日の型に合うネタを優先。無ければタグ無し → 最後にどれでも。
  function pickFrom(entries) {
    const avail = entries.filter((e) => !used.has(e.topic));
    return (
      avail.find((e) => e.tag === dayKey) ||
      avail.find((e) => e.tag === null) ||
      null
    );
  }

  let picked = pickFrom(readBacklog());

  if (!picked) {
    log.warn(`「${fmt?.name || dayKey}」に使えるネタが在庫にありません。AIで補充します。`);
    const gen = isDry()
      ? { topics: Array.from({ length: 7 }, (_, i) => `[DRY] ${dayKey} 自動補充ネタ ${Date.now()}-${i}`) }
      : await askJson({
          system:
            'あなたは日本語のInstagramリール企画者です。必ずJSONのみを返します。形式: {"topics": ["...", ...]}',
          user: `ジャンル: ${config.account.genre}
ターゲット: ${config.account.persona}
${fmt ? `投稿フォーマット: 「${fmt.name}」（狙う指標: ${fmt.goal}）\n構成の型: ${fmt.structure}\nこの型で成立する題材だけを出してください。` : ''}

このターゲットが「保存したくなる」リールのネタを14件、日本語で出してください。
条件:
- 1件は40文字以内の具体的な題材（例:「請求書PDF30枚をAIで仕訳データにした手順」）
- 実際に画面録画または実測で検証できるものに限る
- 抽象的な精神論・モチベーション系は禁止
- 次の話題には踏み込まない: ${(config.account.forbiddenTopics || []).join(' / ') || 'なし'}
- 既出と重複しないこと。既出: ${[...used].slice(-40).join(' / ') || 'なし'}`,
        });
    const fresh = (gen.topics || []).map((t) => String(t).trim()).filter((t) => t && !used.has(t));
    if (!fresh.length) throw new Error('ネタを補充できませんでした。topics/backlog.md に手で追記してください。');
    fs.appendFileSync(backlogFile, '\n' + fresh.map((t) => `- [${dayKey}] ${t}`).join('\n') + '\n');
    picked = { tag: dayKey, topic: fresh[0] };
  }

  const topic = picked.topic;
  if (picked.tag !== dayKey) log.warn(`この題材は「${dayKey}」用のタグが付いていません（型と噛み合わない可能性があります）。`);

  const planObj = {
    date,
    topic,
    weekday: dayKey,
    format: fmt?.name || null,
    formatGoal: fmt?.goal || null,
    genre: config.account.genre,
    persona: config.account.persona,
  };
  fs.writeFileSync(p(date, 'plan.json'), JSON.stringify(planObj, null, 2));
  pushUsed(topic);
  log.ok(`題材: ${topic}${fmt ? `  [${dayKey} / ${fmt.name}]` : ''}`);
  return planObj;
}
