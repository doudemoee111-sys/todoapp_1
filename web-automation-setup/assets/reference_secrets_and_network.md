# 参照：秘密情報7つ ＋ ネットワーク許可ドメイン

クラウド環境（Claude Code Routines の Cloud Environment）設定画面で、この2つを登録します。

---

## 1. 秘密情報（Secrets / 環境変数）― 7つ

| 環境変数名 | 中身のありか（ローカル） | 備考 |
|---|---|---|
| `ANTHROPIC_API_KEY` | `generator/anthropic_api_key.txt` の中身そのまま | 台本生成（Claude） |
| `OPENAI_API_KEY` | `generator/openai_api_key.txt` の中身そのまま | ナレーション音声（TTS） |
| `STABILITY_API_KEY` | `generator/stability_api_key.txt` の中身そのまま | 背景画像生成 |
| `YOUTUBE_RESEARCH_API_KEY` | `research/api_key.txt` の中身そのまま | リサーチ用（再生数取得） |
| `YOUTUBE_CLIENT_ID` | `generator/client_secret.json` → `client_id` の値 | YouTube OAuth |
| `YOUTUBE_CLIENT_SECRET` | `generator/client_secret.json` → `client_secret` の値 | YouTube OAuth |
| `YOUTUBE_REFRESH_TOKEN` | `generator/token.json` → `refresh_token` の値 | これがあれば再ログイン不要 |

### client_secret.json の見方
中身はこんな形です（値は例）。`installed` または `web` の下にあります。
```json
{
  "installed": {
    "client_id": "xxxxxxxx.apps.googleusercontent.com",   ← YOUTUBE_CLIENT_ID
    "client_secret": "GOCSPX-xxxxxxxx",                     ← YOUTUBE_CLIENT_SECRET
    ...
  }
}
```

### token.json の見方
```json
{
  "token": "ya29.xxxx",
  "refresh_token": "1//xxxxxxxx",   ← YOUTUBE_REFRESH_TOKEN（これをコピー）
  "client_id": "...",
  "client_secret": "...",
  ...
}
```
`refresh_token` が無い場合のみ、PCで `python -u youtube_upload.py` を1回実行して再取得します。

> ⚠️ Routine の環境変数は「その環境を使う人に見える」仕様です。個人アカウント運用なら実害は小さいですが、
> 共有しないアカウントで運用してください。

---

## 2. ネットワーク許可ドメイン（Custom / allowlist）

ネットワークアクセスを **Custom** にして、次を許可します。

| ドメイン | 用途 |
|---|---|
| `api.anthropic.com` | 台本生成（Claude API） |
| `api.openai.com` | ナレーション音声合成（OpenAI TTS） |
| `api.stability.ai` | 背景画像生成（Stability AI） |
| `www.googleapis.com` | YouTube アップロード／リサーチ（YouTube Data API） |
| `oauth2.googleapis.com` | YouTube ログインの自動更新（トークンリフレッシュ） |

> 💡 `pip` や `apt` のパッケージ取得先（PyPI・Ubuntu ミラー等）は、通常「Trusted」既定で到達できます。
> もし `setup.sh` の導入段階で通信が弾かれる場合は、パッケージレジストリのドメインも許可に追加してください。

---

## 補足：これで解決する「現状の課題」

- ✅ PCの電源状態に関係なく実行される（クラウド実行）
- ✅ 実行結果を Web・スマホから確認できる（claude.ai/code の実行履歴）
- ✅ APIキーが平文ファイルでなく秘密情報として管理される
- ✅ `www.googleapis.com` へ到達できなかった Cowork の制約が解消（Customで明示許可）
