/** 指数バックオフ付き fetch。429/5xx はリトライする。 */
export async function fetchRetry(url, options = {}, { retries = 4, base = 1500, label = 'request' } = {}) {
  let lastErr;
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url, options);
      if (res.ok) return res;
      const body = await res.text().catch(() => '');
      if (res.status === 429 || res.status >= 500) {
        lastErr = new Error(`${label}: HTTP ${res.status} ${body.slice(0, 300)}`);
      } else {
        throw new Error(`${label}: HTTP ${res.status} ${body.slice(0, 500)}`);
      }
    } catch (e) {
      lastErr = e;
      if (!/HTTP (429|5\d\d)/.test(e.message) && !/fetch failed|ETIMEDOUT|ECONNRESET/i.test(e.message)) throw e;
    }
    if (i < retries) await new Promise((r) => setTimeout(r, base * 2 ** i));
  }
  throw lastErr;
}
