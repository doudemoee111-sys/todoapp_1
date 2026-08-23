import fs from 'node:fs';
import path from 'node:path';
import { p, loadConfig, todayJst } from '../lib/paths.mjs';
import { loadEnv, env, requireEnv } from '../lib/env.mjs';
import { fetchRetry } from '../lib/http.mjs';
import { log } from '../lib/log.mjs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Instagram Graph API でリールを公開する。
 * 制限: 25投稿/24時間、APIコール200/時。動画は「公開URL」である必要がある。
 */
export async function publish(date) {
  const { config } = loadConfig();

  // --- 人間承認ゲート（自動化しない）---
  if (config.compliance.requireHumanApproval && !fs.existsSync(p(date, 'APPROVED'))) {
    log.err(`未承認です。out/${date}/REVIEW.md を確認のうえ \`touch out/${date}/APPROVED\` を実行してください。`);
    return { published: false, reason: 'not_approved' };
  }
  const comp = JSON.parse(fs.readFileSync(p(date, 'compliance.json'), 'utf8'));
  if (!comp.pass) {
    log.err('コンプライアンスチェックでブロックがあります。修正するまで投稿しません。');
    return { published: false, reason: 'compliance_block' };
  }

  const igUser = requireEnv('IG_USER_ID');
  const token = requireEnv('IG_ACCESS_TOKEN');
  const ver = env('IG_API_VERSION', 'v21.0');
  const base = env('PUBLIC_ASSET_BASE_URL');
  if (!base) throw new Error('PUBLIC_ASSET_BASE_URL が未設定です。Graph API は公開URLの動画しか受け付けません。');

  const caption = fs.readFileSync(p(date, 'caption.txt'), 'utf8');
  const videoUrl = `${base.replace(/\/$/, '')}/${date}/reel.mp4`;

  // 1) コンテナ作成
  const createUrl = `https://graph.facebook.com/${ver}/${igUser}/media`;
  const params = new URLSearchParams({
    media_type: 'REELS',
    video_url: videoUrl,
    caption,
    share_to_feed: 'true',
    access_token: token,
  });
  log.info(`コンテナ作成: ${videoUrl}`);
  const created = await (await fetchRetry(createUrl, { method: 'POST', body: params }, { label: 'ig-create' })).json();
  const containerId = created.id;
  if (!containerId) throw new Error(`コンテナ作成に失敗: ${JSON.stringify(created)}`);

  // 2) エンコード完了待ち（動画は非同期処理される）
  for (let i = 0; i < 30; i++) {
    await sleep(5000);
    const st = await (
      await fetchRetry(
        `https://graph.facebook.com/${ver}/${containerId}?fields=status_code,status&access_token=${token}`,
        {}, { label: 'ig-status' }
      )
    ).json();
    log.dim(`status: ${st.status_code}`);
    if (st.status_code === 'FINISHED') break;
    if (st.status_code === 'ERROR') throw new Error(`メディア処理エラー: ${JSON.stringify(st)}`);
    if (i === 29) throw new Error('メディア処理がタイムアウトしました');
  }

  // 3) 公開
  const pubParams = new URLSearchParams({ creation_id: containerId, access_token: token });
  const published = await (
    await fetchRetry(`https://graph.facebook.com/${ver}/${igUser}/media_publish`, { method: 'POST', body: pubParams }, { label: 'ig-publish' })
  ).json();
  if (!published.id) throw new Error(`公開に失敗: ${JSON.stringify(published)}`);

  fs.writeFileSync(p(date, 'published.json'), JSON.stringify({ ...published, containerId, videoUrl, at: new Date().toISOString() }, null, 2));
  log.ok(`公開しました media_id=${published.id}`);
  log.warn('AI生成素材を含む場合、Instagramアプリ側でAIラベルの申告状況を確認してください。');
  return { published: true, id: published.id };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  loadEnv();
  const date = process.argv.find((a) => /^\d{4}-\d{2}-\d{2}$/.test(a)) || todayJst();
  publish(date).catch((e) => { log.err(e.message); process.exit(1); });
}
