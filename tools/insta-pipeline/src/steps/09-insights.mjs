import fs from 'node:fs';
import path from 'node:path';
import { ROOT, todayJst } from '../lib/paths.mjs';
import { loadEnv, env, requireEnv } from '../lib/env.mjs';
import { fetchRetry } from '../lib/http.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

/** 直近N件の投稿インサイトを取得し、週次レポートを生成する。 */
export async function insights({ limit = 20 } = {}) {
  const igUser = requireEnv('IG_USER_ID');
  const token = requireEnv('IG_ACCESS_TOKEN');
  const ver = env('IG_API_VERSION', 'v21.0');

  const mediaUrl = `https://graph.facebook.com/${ver}/${igUser}/media?fields=id,caption,media_type,permalink,timestamp,like_count,comments_count&limit=${limit}&access_token=${token}`;
  const media = await (await fetchRetry(mediaUrl, {}, { label: 'ig-media' })).json();

  const rows = [];
  for (const m of media.data || []) {
    const metrics = m.media_type === 'VIDEO' ? 'reach,saved,shares,total_interactions' : 'reach,saved,total_interactions';
    let ins = {};
    try {
      const r = await (
        await fetchRetry(`https://graph.facebook.com/${ver}/${m.id}/insights?metric=${metrics}&access_token=${token}`, {}, { label: 'ig-insights' })
      ).json();
      for (const d of r.data || []) ins[d.name] = d.values?.[0]?.value ?? 0;
    } catch (e) {
      log.warn(`insights取得失敗 ${m.id}: ${e.message}`);
    }
    const reach = ins.reach || 0;
    rows.push({
      id: m.id,
      date: (m.timestamp || '').slice(0, 10),
      type: m.media_type,
      permalink: m.permalink,
      hook: (m.caption || '').split('\n').filter(Boolean)[1]?.slice(0, 30) || '',
      reach,
      saved: ins.saved || 0,
      shares: ins.shares || 0,
      likes: m.like_count || 0,
      comments: m.comments_count || 0,
      saveRate: reach ? +((ins.saved || 0) / reach * 100).toFixed(2) : 0,
    });
  }

  const dir = path.join(ROOT, 'out', '_reports');
  fs.mkdirSync(dir, { recursive: true });
  const stamp = todayJst();

  const header = 'date,type,hook,reach,saved,saveRate%,shares,likes,comments,permalink';
  const csv = [header, ...rows.map((r) =>
    [r.date, r.type, `"${r.hook.replace(/"/g, '""')}"`, r.reach, r.saved, r.saveRate, r.shares, r.likes, r.comments, r.permalink].join(',')
  )].join('\n');
  fs.writeFileSync(path.join(dir, `insights-${stamp}.csv`), csv);

  let summary = '(dry-run: AI要約をスキップ)';
  if (!isDry() && rows.length) {
    const s = await askJson({
      system: 'あなたはSNS運用アナリストです。必ずJSONのみを返します。形式: {"winners":["..."],"losers":["..."],"nextActions":["..."],"comment":"..."}',
      user: `直近${rows.length}件のInstagram投稿データです。保存率(saveRate)を最重要指標として分析してください。

${csv}

- winners: 数値が良かった投稿の共通点（3件以内）
- losers: 数値が悪かった投稿の共通点（3件以内）
- nextActions: 来週やるべきこと（3件以内、具体的に）
- comment: 200文字以内の総括
数値の裏付けがない推測は書かないでください。`,
      temperature: 0.3,
    });
    summary = `### 伸びた要因\n${(s.winners || []).map((x) => `- ${x}`).join('\n')}\n\n### 伸びなかった要因\n${(s.losers || []).map((x) => `- ${x}`).join('\n')}\n\n### 来週のアクション\n${(s.nextActions || []).map((x) => `- ${x}`).join('\n')}\n\n### 総括\n${s.comment || ''}`;
  }

  const avgSave = rows.length ? (rows.reduce((a, r) => a + r.saveRate, 0) / rows.length).toFixed(2) : '0';
  const md = `# 週次インサイトレポート ${stamp}

対象: 直近 ${rows.length} 投稿

| 指標 | 値 |
|---|---|
| 平均保存率 | ${avgSave}% |
| 合計リーチ | ${rows.reduce((a, r) => a + r.reach, 0).toLocaleString()} |
| 合計保存 | ${rows.reduce((a, r) => a + r.saved, 0).toLocaleString()} |

> 判定ライン: **保存率1%超**の投稿が3本以上あればフェーズを進める。

## 投稿別

| 日付 | フック | リーチ | 保存 | 保存率 | シェア |
|---|---|---|---|---|---|
${rows.map((r) => `| ${r.date} | ${r.hook} | ${r.reach} | ${r.saved} | ${r.saveRate}% | ${r.shares} |`).join('\n')}

## AI分析

${summary}

---
⚠️ **この分析は判断材料であって、判断そのものではありません。** ジャンル変更・撤退の意思決定は人間が行ってください。
`;
  fs.writeFileSync(path.join(dir, `report-${stamp}.md`), md);
  log.ok(`レポート生成: out/_reports/report-${stamp}.md（平均保存率 ${avgSave}%）`);
  return { rows, file: path.join(dir, `report-${stamp}.md`) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  loadEnv();
  insights({}).catch((e) => { log.err(e.message); process.exit(1); });
}
