import { env, requireEnv } from './env.mjs';
import { fetchRetry } from './http.mjs';

/**
 * OpenAI Chat Completions を叩き、JSON を返す。
 * schemaHint は system プロンプトに埋め込む出力形式の説明。
 */
export async function askJson({ system, user, temperature = 0.8, maxTokens = 4000 }) {
  const key = requireEnv('OPENAI_API_KEY');
  const model = env('OPENAI_MODEL', 'gpt-4o');

  const res = await fetchRetry('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model,
      temperature,
      max_tokens: maxTokens,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
    }),
  }, { label: 'openai' });

  const json = await res.json();
  const text = json.choices?.[0]?.message?.content;
  if (!text) throw new Error('openai: 空のレスポンス');
  try {
    return JSON.parse(text);
  } catch {
    // ```json フェンスで返るケースの保険
    const m = text.match(/\{[\s\S]*\}/);
    if (!m) throw new Error(`openai: JSONとして解釈できません: ${text.slice(0, 300)}`);
    return JSON.parse(m[0]);
  }
}
