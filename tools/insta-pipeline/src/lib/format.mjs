const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

/** 'YYYY-MM-DD' の曜日キーを、実行環境のTZに依存せずに返す */
export function weekdayKey(date) {
  const [y, m, d] = date.split('-').map(Number);
  return DAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

/** その日の投稿フォーマット（曜日ローテ）。未定義ならnull */
export function formatFor(date, config) {
  const rot = config.post?.formatRotation;
  if (!rot) return null;
  return rot[weekdayKey(date)] || null;
}

/** その日のCTA。ctaVariants を日付で回す。旧 ctaText にもフォールバック */
export function ctaFor(date, config) {
  const v = config.post?.ctaVariants;
  if (Array.isArray(v) && v.length) {
    const [y, m, d] = date.split('-').map(Number);
    const dayNo = Math.floor(Date.UTC(y, m - 1, d) / 86400000);
    return v[dayNo % v.length];
  }
  return config.post?.ctaText || '';
}

/** ハッシュタグ設定を正規化（旧 post.hashtagCount にもフォールバック） */
export function hashtagSpec(config) {
  const h = config.hashtags || {};
  return {
    count: h.count ?? config.post?.hashtagCount ?? 4,
    fixed: h.fixed ?? [],
    pool: h.pool ?? [],
  };
}
