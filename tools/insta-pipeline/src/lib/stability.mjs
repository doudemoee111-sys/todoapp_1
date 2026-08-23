import fs from 'node:fs';
import { env, requireEnv } from './env.mjs';
import { fetchRetry } from './http.mjs';

/**
 * Stability AI Stable Image API で画像を生成し、ファイルに保存する。
 * model: 'core' | 'ultra' | 'sd3.5-large'
 */
export async function generateImage({ prompt, negativePrompt, outPath, aspectRatio = '9:16' }) {
  const key = requireEnv('STABILITY_API_KEY');
  const model = env('STABILITY_MODEL', 'core');
  const endpoint =
    model === 'ultra'
      ? 'https://api.stability.ai/v2beta/stable-image/generate/ultra'
      : model.startsWith('sd3')
      ? 'https://api.stability.ai/v2beta/stable-image/generate/sd3'
      : 'https://api.stability.ai/v2beta/stable-image/generate/core';

  const form = new FormData();
  form.append('prompt', prompt);
  form.append('aspect_ratio', aspectRatio);
  form.append('output_format', 'png');
  if (negativePrompt) form.append('negative_prompt', negativePrompt);
  if (model.startsWith('sd3')) form.append('model', model);

  const res = await fetchRetry(endpoint, {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, Accept: 'image/*' },
    body: form,
  }, { label: 'stability' });

  const buf = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(outPath, buf);
  return outPath;
}
