# シンプル ToDo

Next.js + Tailwind CSS で作った、シンプルでおしゃれなタスク管理アプリです。タスクはブラウザの `localStorage` に保存されます。

## 特徴

- タスクの追加・完了・削除
- 残り件数 / 全件数の表示
- `localStorage` による永続化（サーバー不要）
- Noto Sans JP による日本語フォント最適化

## 技術スタック

| 項目 | 使用技術 |
| --- | --- |
| フレームワーク | [Next.js](https://nextjs.org/) 16 (App Router) |
| UI | [React](https://react.dev/) 19 |
| スタイリング | [Tailwind CSS](https://tailwindcss.com/) 3 |
| 言語 | TypeScript |

## セットアップ

```bash
# 依存関係のインストール
npm install

# 開発サーバーの起動
npm run dev
```

起動後、ブラウザで [http://localhost:3000](http://localhost:3000) を開きます。

## スクリプト

| コマンド | 説明 |
| --- | --- |
| `npm run dev` | 開発サーバーを起動 |
| `npm run build` | 本番用にビルド |
| `npm run start` | ビルド済みアプリを起動 |
| `npm run lint` | ESLint を実行 |

## ディレクトリ構成

```
.
├── app/                # App Router のエントリ（layout / page / globals.css）
├── components/
│   └── TodoApp.tsx     # ToDo アプリ本体
├── next.config.js
├── tailwind.config.ts
└── tsconfig.json
```
