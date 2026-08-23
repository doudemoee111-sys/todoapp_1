import fs from 'node:fs';
import { env, requireEnv } from './env.mjs';
import { fetchRetry } from './http.mjs';

/** Google Cloud Text-to-Speech でMP3を生成する。 */
export async function synthesize({ text, outPath }) {
  const key = requireEnv('GOOGLE_TTS_API_KEY');
  const voice = env('GOOGLE_TTS_VOICE', 'ja-JP-Neural2-B');
  const rate = Number(env('GOOGLE_TTS_RATE', '1.05'));

  const res = await fetchRetry(
    `https://texttospeech.googleapis.com/v1/text:synthesize?key=${encodeURIComponent(key)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input: { text },
        voice: { languageCode: 'ja-JP', name: voice },
        audioConfig: { audioEncoding: 'MP3', speakingRate: rate, pitch: 0 },
      }),
    },
    { label: 'google-tts' }
  );

  const json = await res.json();
  if (!json.audioContent) throw new Error('google-tts: audioContent が空です');
  fs.writeFileSync(outPath, Buffer.from(json.audioContent, 'base64'));
  return outPath;
}
