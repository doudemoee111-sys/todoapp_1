import fs from 'node:fs';
import { p, loadConfig } from '../lib/paths.mjs';
import { askJson } from '../lib/openai.mjs';
import { isDry } from '../lib/dry.mjs';
import { log } from '../lib/log.mjs';

/**
 * ローカル正規表現チェック + AIによる一次レビュー。
 * 最終承認は人間（APPROVED ファイルの作成）に限る。
 */
export async function compliance(date) {
  const { config } = loadConfig();
  const sc = JSON.parse(fs.readFileSync(p(date, 'script.json'), 'utf8'));
  const cap = JSON.parse(fs.readFileSync(p(date, 'caption.json'), 'utf8'));
  const allText = [sc.hook, ...sc.scenes.map((s) => `${s.onScreenText} ${s.narration}`), sc.cta, cap.fullText].join('\n');

  const issues = [];

  // 1) PR表記
  if (config.compliance.requirePrLabel && !cap.caption.startsWith(config.post.prLabel)) {
    issues.push({ level: 'block', rule: 'PR表記', detail: `キャプション冒頭に「${config.post.prLabel}」がありません（景表法・ステマ規制）` });
  }
  // 2) 禁止ワード（正規表現として解釈。不正な場合は素の文字列一致にフォールバック）
  for (const w of config.compliance.bannedPatterns) {
    let hit = null;
    try {
      const m = allText.match(new RegExp(w));
      hit = m && m[0];
    } catch {
      hit = allText.includes(w) ? w : null;
    }
    if (hit) issues.push({ level: 'block', rule: '禁止表現', detail: `「${hit}」が含まれています（パターン: ${w}）` });
  }
  for (const w of config.account.ngExpressions) {
    if (allText.includes(w)) issues.push({ level: 'warn', rule: 'トーン', detail: `「${w}」は使わない方針です` });
  }
  // 3) ハッシュタグ数
  if (cap.hashtags.length > 5) issues.push({ level: 'warn', rule: 'ハッシュタグ', detail: `${cap.hashtags.length}個。3〜5個推奨（過剰はスパム判定）` });

  // 3b) アフィリエイト案件レジストリ照合（ASP規約違反の事前検出）
  if (config.compliance.checkAffiliateRegistry) {
    for (const prog of config.affiliate?.programs || []) {
      const name = String(prog.name || '').replace(/^（例）/, '').trim();
      if (!name || !allText.includes(name)) continue;
      if (prog.instagramAllowed === false) {
        issues.push({ level: 'block', rule: 'ASP規約', detail: `「${name}」は Instagram 掲載不可の案件です（${prog.asp || 'ASP未記載'}）` });
      } else if (prog.instagramAllowed !== true) {
        issues.push({ level: 'block', rule: 'ASP規約', detail: `「${name}」の Instagram 掲載可否が未確認です。ASP管理画面で確認し config.json の instagramAllowed を true/false にしてください` });
      }
    }
  }

  // 4) AIによる一次レビュー
  let aiReview = { verdict: 'skipped', findings: [] };
  if (!isDry()) {
    aiReview = await askJson({
      system: `あなたは日本の広告法務レビュー担当です。必ずJSONのみを返します。
出力形式: {"verdict":"ok"|"needs_fix","findings":[{"level":"block"|"warn","law":"景表法|薬機法|金商法|著作権|その他","quote":"該当箇所","reason":"理由","suggestion":"修正案"}]}`,
      user: `以下のInstagram投稿案を、日本の法令観点でレビューしてください。
観点: ①景品表示法（優良誤認・有利誤認・ステマ規制のPR表記）②薬機法（効能効果の断定）③金融商品取引法（投資助言・断定的判断の提供）④著作権 ⑤根拠のない数値・比較

--- 投稿案 ---
${allText}
--- ここまで ---

該当がなければ verdict は "ok"、findings は空配列にしてください。過剰検出はしないでください。`,
      temperature: 0.2,
    });
    for (const f of aiReview.findings || []) {
      issues.push({ level: f.level || 'warn', rule: `AI:${f.law}`, detail: `${f.reason}（該当:「${f.quote}」）→ ${f.suggestion}` });
    }
  }

  const blocks = issues.filter((i) => i.level === 'block');
  const result = { pass: blocks.length === 0, issues, aiReview };
  fs.writeFileSync(p(date, 'compliance.json'), JSON.stringify(result, null, 2));

  // 人間レビュー用のチェックシート
  const md = `# 投稿前チェック ${date}

## 判定: ${result.pass ? '✅ 自動チェックは通過' : '⛔ ブロックあり（修正が必要）'}

${issues.length === 0 ? '自動検出された問題はありません。\n' : issues.map((i) => `- ${i.level === 'block' ? '⛔' : '⚠️'} **[${i.rule}]** ${i.detail}`).join('\n')}

---

## 人間が必ず確認すること（自動化不可）

- [ ] **画面録画の中身**に個人情報・取引先名・金額・メールアドレスが写り込んでいないか
- [ ] 台本の**数値・料金・仕様**が現在の一次ソースと一致しているか（AIは平気で古い値を書く）
- [ ] 紹介するサービスのASP案件が**「SNS可 / Instagram掲載可」**か
- [ ] 使用した**音源・画像・フォント**の権利が問題ないか
${config.publish?.aiLabelRequired === false ? '' : '- [ ] AI生成素材を使った場合、投稿時に**AIラベルを申告**したか\n'}- [ ] 紹介するサービスが config.json の affiliate.programs に登録され、instagramAllowed が確認済みか
- [ ] 冒頭のPR表記が**ハッシュタグ内ではなく本文冒頭**にあるか

## 承認するには

\`\`\`bash
touch out/${date}/APPROVED
\`\`\`

このファイルが無い限り、08-publish は投稿しません。

---

## キャプション本文

\`\`\`
${fs.readFileSync(p(date, 'caption.txt'), 'utf8')}
\`\`\`
`;
  fs.writeFileSync(p(date, 'REVIEW.md'), md);

  if (result.pass) log.ok('自動チェック通過。REVIEW.md を確認して APPROVED を作成してください。');
  else log.err(`ブロック ${blocks.length}件。REVIEW.md を確認してください。`);
  for (const i of issues) (i.level === 'block' ? log.err : log.warn)(`[${i.rule}] ${i.detail}`);
  return result;
}
