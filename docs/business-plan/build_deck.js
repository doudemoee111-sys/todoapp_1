const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "Claude Code";
pres.title = "副業ビジネス提案：AI検索可視化サービス";

const W = 13.3, H = 7.5, M = 0.62;

// ---- palette : ink + signal amber (the "cited / highlighted" marker) ----
const INK = "141A2E";
const INK2 = "212C48";
const INK3 = "2E3A5A";
const PAPER = "FFFFFF";
const MIST = "F1F4F9";
const MIST2 = "E4EAF4";
const AMBER = "E0A03A";
const AMBER_DK = "9C6C1B";
const AMBER_TINT = "FBF1DE";
const ICE = "A9BEE3";
const BODY = "242B3D";
const SLATE = "667088";
const RISK = "C8503C";
const RISK_TINT = "F8E9E5";

const F = "Yu Gothic";

const sh = (o = {}) => Object.assign({ type: "outer", angle: 90, blur: 12, offset: 2, color: "9AA6BE", opacity: 0.28 }, o);

function darkSlide() {
  const s = pres.addSlide();
  s.background = { color: INK };
  return s;
}
function lightSlide() {
  const s = pres.addSlide();
  s.background = { color: PAPER };
  return s;
}

// section header used on every content slide: amber dot motif + label + title
function head(s, num, label, title, dark) {
  s.addShape(pres.ShapeType.ellipse, { x: M, y: 0.52, w: 0.34, h: 0.34, fill: { color: AMBER } });
  s.addText(num, {
    x: M, y: 0.52, w: 0.34, h: 0.34, align: "center", valign: "middle", margin: 0,
    fontFace: F, fontSize: num.length > 1 ? 10.5 : 13, bold: true, color: INK,
  });
  s.addText(label, {
    x: M + 0.5, y: 0.52, w: 6, h: 0.34, valign: "middle", margin: 0,
    fontFace: F, fontSize: 12, bold: true, charSpacing: 2, color: dark ? ICE : SLATE,
  });
  s.addText(title, {
    x: M, y: 1.0, w: W - M * 2, h: 0.78, valign: "middle", margin: 0,
    fontFace: F, fontSize: 32, bold: true, color: dark ? PAPER : INK,
  });
}

function srcNote(s, txt, dark) {
  s.addText(txt, {
    x: M, y: H - 0.62, w: W - M * 2, h: 0.32, margin: 0, valign: "middle",
    fontFace: F, fontSize: 10, color: dark ? "7E8BA8" : "97A0B4",
  });
}

/* ============================================================ 1. TITLE */
{
  const s = darkSlide();
  s.addShape(pres.ShapeType.ellipse, { x: M, y: 0.95, w: 0.22, h: 0.22, fill: { color: AMBER } });
  s.addText("副業ビジネス提案書　│　2026.08.23　│　調査・分析 Claude Code", {
    x: M + 0.38, y: 0.93, w: 10, h: 0.26, margin: 0, valign: "middle",
    fontFace: F, fontSize: 12, bold: true, charSpacing: 2, color: ICE,
  });

  s.addText([
    { text: "検索順位は1位のまま、", options: { color: PAPER, breakLine: true } },
    { text: "問い合わせだけが半分になった。", options: { color: AMBER } },
  ], {
    x: M, y: 1.9, w: 11.4, h: 2.0, margin: 0, valign: "top",
    fontFace: F, fontSize: 46, bold: true, lineSpacing: 60,
  });

  s.addText("その原因を説明でき、直せる人間が足りていない。\nここに、初期投資23万円・従業員ゼロで参入できる余地がある。", {
    x: M, y: 4.05, w: 9.6, h: 1.0, margin: 0,
    fontFace: F, fontSize: 16, color: ICE, lineSpacing: 26,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 5.35, w: 10.5, h: 0.86, rectRadius: 0.08,
    fill: { color: INK2 },
  });
  s.addText("AI検索可視化（GEO / LLMO）プロダクタイズド・サービス → SaaS化", {
    x: M + 0.34, y: 5.35, w: 9.85, h: 0.86, margin: 0, valign: "middle",
    fontFace: F, fontSize: 16, bold: true, color: PAPER,
  });

  s.addNotes("ChatGPT・Gemini・AI Overviewsに自社が引用されているかを診断し、引用されるよう直す月額サービス。納品工程をAIで全自動化し1人で運営する事業案。");
}

/* ============================================================ 2. 結論 */
{
  const s = darkSlide();
  head(s, "0", "CONCLUSION", "結論：2段ロケットで組み立てる", true);

  s.addText([
    { text: "「AI検索に自社が引用されているか」を診断し、引用されるように直す月額サービスを、", options: { color: PAPER, breakLine: true } },
    { text: "納品工程をAIで完全自動化して1人で運営する。", options: { color: AMBER } },
  ], {
    x: M, y: 2.0, w: 11.9, h: 0.9, margin: 0,
    fontFace: F, fontSize: 19, bold: true, lineSpacing: 30,
  });

  const cardW = 5.3, cardY = 3.15, cardH = 2.65;
  const cards = [
    { t: "PHASE 1 ─ 0〜3か月", h: "高単価サービスで現金を作る", b: "月5〜30万円のプロダクタイズド・サービス。\n手作業で全力納品し、品質基準と\n「本当の顧客課題」を先に手に入れる。", x: M },
    { t: "PHASE 2 ─ 4か月〜", h: "同じエンジンをSaaSに載せる", b: "自動化した診断パイプラインを\nセルフサーブSaaS（月9,800円〜）に転用。\n従業員不在のまま売上だけを伸ばす。", x: M + cardW + 0.7 },
  ];
  cards.forEach((c, i) => {
    s.addShape(pres.ShapeType.roundRect, { x: c.x, y: cardY, w: cardW, h: cardH, rectRadius: 0.06, fill: { color: INK2 } });
    s.addText(c.t, { x: c.x + 0.38, y: cardY + 0.28, w: cardW - 0.76, h: 0.28, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, charSpacing: 1.5, color: AMBER });
    s.addText(c.h, { x: c.x + 0.38, y: cardY + 0.66, w: cardW - 0.76, h: 0.44, margin: 0, valign: "middle", fontFace: F, fontSize: 19, bold: true, color: PAPER });
    s.addText(c.b, { x: c.x + 0.38, y: cardY + 1.2, w: cardW - 0.76, h: 1.2, margin: 0, fontFace: F, fontSize: 13, color: ICE, lineSpacing: 22 });
  });
  s.addShape(pres.ShapeType.chevron, { x: M + cardW + 0.1, y: cardY + 1.05, w: 0.5, h: 0.55, fill: { color: AMBER } });

  s.addText("サービスが顧客課題を教え、SaaSが従業員不在のまま売上を伸ばす — この役割分担が本案の骨格。", {
    x: M, y: 6.15, w: 11.9, h: 0.4, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13.5, color: ICE,
  });
  s.addNotes("いきなりSaaSを作ると初売上まで6〜12か月かかり、3か月要件を満たせない。サービス先行なら4〜6週間で初売上が立つ。");
}

/* ============================================================ 3. 条件適合 */
{
  const s = lightSlide();
  head(s, "1", "REQUIREMENTS", "ご提示の5条件との適合性", false);

  const rows = [
    ["AI活用・自動化・従業員不在", "診断→分析→生成→納品→営業の全工程をLLMパイプライン化。人間は商談と例外対応のみ"],
    ["年商1億以上のマーケット", "国内AI市場は2025年 2.37兆円 → 2029年 6.89兆円（CAGR 36.0%／IDC）"],
    ["3か月以内に軌道に乗る", "無料診断レポートを自動生成してアウトバウンド。商材が営業ツールを兼ねる"],
    ["初期投資が低い", "在庫・設備・人件費ゼロ。3か月累計 23万4,000円"],
    ["伸びており今後も期待", "AI検索セッション +5,535%（2年）。ゼロクリック60%で既存SEO資産が壊れている"],
  ];
  let y = 1.95;
  rows.forEach((r, i) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.76, rectRadius: 0.05, fill: { color: i % 2 ? PAPER : MIST } });
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.3, y: y + 0.19, w: 0.38, h: 0.38, fill: { color: AMBER } });
    s.addText("◎", { x: M + 0.3, y: y + 0.19, w: 0.38, h: 0.38, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 13, bold: true, color: INK });
    s.addText(r[0], { x: M + 0.86, y, w: 3.5, h: 0.76, margin: 0, valign: "middle", fontFace: F, fontSize: 14, bold: true, color: INK });
    s.addText(r[1], { x: M + 4.5, y, w: W - M * 2 - 4.8, h: 0.76, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: BODY });
    y += 0.84;
  });
  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.28, w: W - M * 2, h: 0.72, rectRadius: 0.06, fill: { color: INK } });
  s.addText("5条件すべてに◎で適合する案として、次ページ以降で市場・競合・収益構造を検証する。", {
    x: M + 0.34, y: 6.28, w: W - M * 2 - 0.68, h: 0.72, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13.5, bold: true, color: PAPER,
  });
  s.addNotes("5条件すべてに◎で適合する案として本提案を選んでいる。");
}

/* ============================================================ 4. 市場：検索が壊れた */
{
  const s = darkSlide();
  head(s, "2", "MARKET SHIFT", "この2年で「検索」が壊れた", true);

  const stats = [
    { v: "+5,535%", k: "AI検索の国内セッション数", n: "2024年4月比（2026年4月）\n2年で55倍" },
    { v: "約59%", k: "ChatGPTの国内シェア", n: "Geminiが4か月連続上昇。\n最適化先が複数化している" },
    { v: "60%", k: "ゼロクリック率", n: "Google検索全体。モバイルは77%。\nサイトに人が来ない" },
    { v: "−40%", k: "順位維持時のCTR", n: "「SEOは成功しているのに\n売上が落ちる」現象" },
  ];
  const cw = 2.86, gap = 0.24;
  stats.forEach((st, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.0, w: cw, h: 2.75, rectRadius: 0.06, fill: { color: INK2 } });
    s.addText(st.v, { x: x + 0.24, y: 2.24, w: cw - 0.48, h: 0.86, margin: 0, valign: "middle", fontFace: F, fontSize: 30, bold: true, color: AMBER });
    s.addText(st.k, { x: x + 0.24, y: 3.14, w: cw - 0.48, h: 0.6, margin: 0, fontFace: F, fontSize: 12.5, bold: true, color: PAPER, lineSpacing: 18 });
    s.addText(st.n, { x: x + 0.24, y: 3.8, w: cw - 0.48, h: 0.8, margin: 0, fontFace: F, fontSize: 11, color: ICE, lineSpacing: 17 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.1, w: W - M * 2, h: 1.05, rectRadius: 0.06, fill: { color: INK3 } });
  s.addText([
    { text: "事業者にはこう体感される — ", options: { color: ICE } },
    { text: "「順位は1位なのに問い合わせが半減した」。", options: { color: AMBER, bold: true } },
    { text: "原因を説明でき、打ち手を出せる人間が足りていない。これが収益源。", options: { color: PAPER } },
  ], {
    x: M + 0.34, y: 5.1, w: W - M * 2 - 0.68, h: 1.05, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14.5, lineSpacing: 24,
  });
  srcNote(s, "出典：博報堂DYグループ oneder「AI検索エンジンのトラフィック推移」「2026年版AI検索白書」／Uravation", true);
}

/* ============================================================ 5. 相場は成立している */
{
  const s = lightSlide();
  head(s, "3", "PRICING", "新ジャンルなのに、相場は既に立っている", false);

  s.addText("市場教育コストを自分で払わずに済む。これが3か月での立ち上がりに直結する。", {
    x: M, y: 1.88, w: 11.9, h: 0.34, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, color: BODY,
  });

  // hand-drawn horizontal bars (full control over color per row)
  const bars = [
    { l: "大手LLMO対策会社", r: "月額 20〜80万円", w: 6.9, c: INK3, note: "" },
    { l: "本案 Pro", r: "月額 29.8万円", w: 2.6, c: AMBER, note: "" },
    { l: "本案 Standard", r: "月額 14.98万円", w: 1.35, c: AMBER, note: "主力" },
    { l: "本案 Light", r: "月額 4.98万円", w: 0.5, c: AMBER, note: "" },
    { l: "MEO対策 一般", r: "月額 3〜10万円", w: 0.9, c: ICE, note: "" },
  ];
  let by = 2.44;
  const bx = M + 3.05;
  bars.forEach((b) => {
    s.addText(b.l, { x: M, y: by, w: 2.9, h: 0.46, margin: 0, valign: "middle", align: "right", fontFace: F, fontSize: 12.5, bold: true, color: INK });
    s.addShape(pres.ShapeType.roundRect, { x: bx, y: by + 0.06, w: Math.max(b.w, 0.35), h: 0.34, rectRadius: 0.04, fill: { color: b.c } });
    s.addText(b.r, { x: bx + Math.max(b.w, 0.35) + 0.16, y: by, w: 2.6, h: 0.46, margin: 0, valign: "middle", fontFace: F, fontSize: 12, bold: true, color: b.c === ICE ? SLATE : INK });
    if (b.note) {
      s.addText(b.note, { x: bx + Math.max(b.w, 0.35) + 1.62, y: by, w: 0.8, h: 0.46, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, color: AMBER_DK });
    }
    by += 0.58;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.42, w: W - M * 2, h: 1.12, rectRadius: 0.06, fill: { color: AMBER_TINT } });
  s.addShape(pres.ShapeType.ellipse, { x: M + 0.32, y: 5.76, w: 0.42, h: 0.42, fill: { color: AMBER } });
  s.addText("!", { x: M + 0.32, y: 5.76, w: 0.42, h: 0.42, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 16, bold: true, color: INK });
  s.addText("大手の価格帯（月20〜80万円）と正面衝突しない。月5〜15万円に置き、士業特化で差別化する。LLMO対策会社は既に40社超が参入済み。", {
    x: M + 0.94, y: 5.42, w: W - M * 2 - 1.3, h: 1.12, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13.5, bold: true, color: INK, lineSpacing: 22,
  });
  srcNote(s, "出典：SEデザイン／メディアリーチ「LLMO対策の費用相場」、MEO対策の料金相場2026", false);
}

/* ============================================================ 6. 補助金 */
{
  const s = lightSlide();
  head(s, "4", "TAILWIND", "追い風：デジタル化・AI導入補助金2026", false);

  s.addText("旧IT導入補助金が改称され、生成AIツールの導入費用が明確に対象化された。", {
    x: M, y: 1.88, w: 11.9, h: 0.34, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, color: BODY,
  });

  const cs = [
    { v: "最大450万円", k: "補助額（1者あたり）" },
    { v: "1/2 〜 4/5", k: "補助率（小規模事業者は賃上げ要件等で最大4/5）" },
    { v: "登録が必須", k: "申請には「IT導入支援事業者」との\nパートナーシップが必要" },
  ];
  const cw = 3.86, gap = 0.26;
  cs.forEach((c, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.45, w: cw, h: 1.9, rectRadius: 0.06, fill: { color: MIST }, shadow: sh() });
    s.addText(c.v, { x: x + 0.3, y: 2.68, w: cw - 0.6, h: 0.86, margin: 0, valign: "middle", fontFace: F, fontSize: 24, bold: true, color: AMBER_DK, lineSpacing: 30 });
    s.addText(c.k, { x: x + 0.3, y: 3.56, w: cw - 0.6, h: 0.66, margin: 0, fontFace: F, fontSize: 11.5, color: SLATE, lineSpacing: 18 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 4.66, w: W - M * 2, h: 0.94, rectRadius: 0.06, fill: { color: INK } });
  s.addText("顧客の実質負担を 1/2〜1/5 にできる。成約率を構造的に引き上げる営業カードであり、同時に「支援事業者登録」という参入障壁を自分側に作れる。", {
    x: M + 0.34, y: 4.66, w: W - M * 2 - 0.68, h: 0.94, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14, bold: true, color: PAPER,
  });
  s.addText("ただし制度は変わりうる。補助金は「あれば強い」カードとして扱い、事業の前提には置かない。支援事業者登録は売上が立った後に申請する。", {
    x: M, y: 5.78, w: 11.9, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: SLATE,
  });
  srcNote(s, "出典：中小企業庁「デジタル化・AI導入補助金2026」公募要領、制度概要", false);
}

/* ============================================================ 7. 5案比較 */
{
  const s = lightSlide();
  head(s, "5", "OPTIONS", "AI副業ジャンル 5案の比較検討", false);

  const cols = ["無人化", "市場", "3か月", "低投資", "成長性", "合計"];
  const colX = 6.35, colW = 1.02;
  cols.forEach((c, i) => {
    s.addText(c, { x: colX + i * colW, y: 1.9, w: colW, h: 0.34, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 10.5, bold: true, charSpacing: 0.5, color: SLATE });
  });

  const opts = [
    { n: "A. AI可視性（GEO/LLMO）→ SaaS", v: [5, 4, 5, 5, 5], t: 24, win: true },
    { n: "B. バーティカル・マイクロSaaS", v: [5, 4, 2, 5, 4], t: 20 },
    { n: "C. AI電話／チャット導入代行", v: [3, 4, 4, 5, 3], t: 19 },
    { n: "E. AIショート動画・SNS運用代行", v: [2, 3, 4, 5, 3], t: 17 },
    { n: "D. AIコンテンツメディア", v: [4, 3, 1, 5, 2], t: 15 },
  ];
  let y = 2.3;
  opts.forEach((o) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.78, rectRadius: 0.05, fill: { color: o.win ? AMBER_TINT : MIST } });
    s.addText(o.n, { x: M + 0.34, y, w: 5.4, h: 0.78, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, bold: o.win, color: o.win ? INK : BODY });
    o.v.forEach((v, i) => {
      s.addText(String(v), { x: colX + i * colW, y, w: colW, h: 0.78, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 14, bold: true, color: v >= 4 ? INK : "9AA3B6" });
    });
    s.addText(String(o.t), { x: colX + 5 * colW, y, w: colW, h: 0.78, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 18, bold: true, color: o.win ? AMBER_DK : SLATE });
    y += 0.86;
  });

  s.addText("D（AIメディア）はゼロクリック60%で殴られている側、E（動画代行）は編集が人手に残り無人化できないため除外。B・Cは本案に吸収する。", {
    x: M, y: 6.68, w: 11.9, h: 0.42, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: SLATE,
  });
  s.addNotes("各項目5点満点。Bのマイクロ SaaS は条件適合こそ高いが3か月では売上が立たないため、フェーズ2として吸収する。Cは月額3,980円まで価格が崩れており自前SaaSでは戦えないので、アップセル商材として仕入れる。");
}

/* ============================================================ 8. Aを選ぶ決め手 */
{
  const s = darkSlide();
  head(s, "6", "WHY A", "Aを選ぶ決め手は3つ", true);

  const rs = [
    { n: "01", h: "商材そのものが営業ツールを兼ねる", b: "無料診断レポートを自動生成して送るだけで商談が立つ。広告費ゼロ、制作待ちゼロ。5案の中でこれができるのはAだけ。" },
    { n: "02", h: "納品物がデータとテキストしかない", b: "だから納品工程の100%をLLMで自動化できる。動画も在庫も撮影も発生しない。従業員不在の前提条件を唯一満たす。" },
    { n: "03", h: "顧客の痛みが「今」発生している", b: "ゼロクリック60%は既に起きた事実。将来の課題を啓蒙する必要がなく、既に困っている相手に売れる。" },
  ];
  let y = 2.0;
  rs.forEach((r) => {
    s.addShape(pres.ShapeType.ellipse, { x: M, y: y + 0.1, w: 0.56, h: 0.56, fill: { color: AMBER } });
    s.addText(r.n, { x: M, y: y + 0.1, w: 0.56, h: 0.56, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 15, bold: true, color: INK });
    s.addText(r.h, { x: M + 0.86, y: y + 0.02, w: 11.0, h: 0.46, margin: 0, valign: "middle", fontFace: F, fontSize: 20, bold: true, color: PAPER });
    s.addText(r.b, { x: M + 0.86, y: y + 0.54, w: 11.0, h: 0.72, margin: 0, fontFace: F, fontSize: 13.5, color: ICE, lineSpacing: 23 });
    y += 1.52;
  });
  s.addNotes("この3点が同時に成立するのはA案だけ。特に1つ目が3か月要件と低投資要件を同時に解決している。");
}

/* ============================================================ 9. ターゲット */
{
  const s = lightSlide();
  head(s, "7", "TARGET", "誰に売るか — まず士業1業種に絞る", false);

  const prim = [
    { t: "士業", s2: "税理士・社労士・行政書士", b: "「顧問料 相場」等の検索がAIに奪われている。顧問契約LTVが年60〜120万円あり、投資判断が速い。" },
    { t: "クリニック・歯科", s2: "自由診療", b: "広告規制でリスティングが打ちづらく、検索・口コミ依存が構造的。自由診療の単価が高くROI説明が容易。" },
  ];
  const cw = 5.9, gap = 0.26;
  prim.forEach((p, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 2.35, rectRadius: 0.06, fill: { color: MIST }, shadow: sh() });
    s.addShape(pres.ShapeType.roundRect, { x: x + 0.32, y: 2.2, w: 0.86, h: 0.3, rectRadius: 0.04, fill: { color: AMBER } });
    s.addText("1st", { x: x + 0.32, y: 2.2, w: 0.86, h: 0.3, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 10.5, bold: true, color: INK });
    s.addText(p.t, { x: x + 0.32, y: 2.6, w: cw - 0.64, h: 0.46, margin: 0, valign: "middle", fontFace: F, fontSize: 22, bold: true, color: INK });
    s.addText(p.s2, { x: x + 0.32, y: 3.06, w: cw - 0.64, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 12, bold: true, color: AMBER_DK });
    s.addText(p.b, { x: x + 0.32, y: 3.4, w: cw - 0.64, h: 0.8, margin: 0, fontFace: F, fontSize: 12, color: BODY, lineSpacing: 19 });
  });

  const sec = [
    "2nd　BtoB専門商材の中小メーカー・商社 — 「〇〇 メーカー おすすめ」でLLMに列挙されるかが商談数に直結",
    "2nd　リフォーム・工務店・不動産 — 案件単価が数百万円。1件受注で年間費用を回収でき、ROI訴求が最強",
  ];
  let y = 4.46;
  sec.forEach((t) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.52, rectRadius: 0.04, fill: { color: PAPER }, line: { color: MIST2, width: 1 } });
    s.addText(t, { x: M + 0.34, y, w: W - M * 2 - 0.68, h: 0.52, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: BODY });
    y += 0.6;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.74, w: W - M * 2, h: 0.92, rectRadius: 0.06, fill: { color: INK } });
  s.addText("1業種に絞る理由：①プロンプトと改善テンプレを全顧客で使い回せ自動化効率が最大化　②業界内の紹介が回る　③「専門」が40社超の競合との正面衝突を避ける", {
    x: M + 0.34, y: 5.74, w: W - M * 2 - 0.68, h: 0.92, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13, bold: true, color: PAPER,
  });
}

/* ============================================================ 10. 商品ラダー */
{
  const s = lightSlide();
  head(s, "8", "PRODUCT", "商品ラダーと価格設計", false);

  const rungs = [
    { tier: "フック", name: "AI可視性 無料診断レポート（完全自動生成・営業リストにバッチ実行）", price: "原価 150円/件", core: false },
    { tier: "入口", name: "AI可視性 精密診断＋改善ロードマップ（単発）", price: "98,000円", core: false },
    { tier: "本命 Light", name: "月次モニタリング＋改善指示書", price: "月 49,800円", core: true },
    { tier: "本命 Standard", name: "＋コンテンツ／FAQ／構造化データの実装まで", price: "月 149,800円", core: true },
    { tier: "本命 Pro", name: "＋競合追跡・多拠点・月次オンライン報告", price: "月 298,000円", core: true },
    { tier: "アップセル", name: "AI電話受付・AIチャット導入（他社SaaSの取次）", price: "初期15万＋月1万", core: false },
    { tier: "フェーズ2", name: "セルフサーブSaaS「AI可視性モニター」", price: "月 9,800円〜", core: false },
  ];
  let y = 1.95;
  rungs.forEach((r) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.62, rectRadius: 0.05, fill: { color: r.core ? AMBER_TINT : MIST } });
    s.addText(r.tier, { x: M + 0.32, y, w: 1.75, h: 0.62, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, color: r.core ? AMBER_DK : SLATE });
    s.addText(r.name, { x: M + 2.2, y, w: 6.9, h: 0.62, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: INK });
    s.addText(r.price, { x: W - M - 2.6, y, w: 2.3, h: 0.62, margin: 0, align: "right", valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: r.core ? AMBER_DK : BODY });
    y += 0.7;
  });
  s.addText("無料診断がそのままアウトバウンド営業になり、単発98,000円が月額契約への入口になる。", {
    x: M, y: 6.85, w: 11.9, h: 0.36, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: SLATE,
  });
}

/* ============================================================ 11. ユニットエコノミクス */
{
  const s = darkSlide();
  head(s, "9", "UNIT ECONOMICS", "粗利率96.6%、損益分岐は3社", true);

  const big = [
    { v: "5,000円", k: "1社あたり月次原価", n: "LLM API 3,000円 ＋ 追跡基盤 1,500円\n＋ ホスティング 500円" },
    { v: "144,800円", k: "Standard 1社の月次粗利", n: "売上149,800円 − 原価5,000円\n粗利率 96.6%" },
    { v: "3社", k: "損益分岐点", n: "固定費は月3.5万円のみ。\n10社で月粗利 約145万円" },
  ];
  const cw = 3.86, gap = 0.26;
  big.forEach((b, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.1, w: cw, h: 2.5, rectRadius: 0.06, fill: { color: INK2 } });
    s.addText(b.v, { x: x + 0.3, y: 2.36, w: cw - 0.6, h: 0.84, margin: 0, valign: "middle", fontFace: F, fontSize: 30, bold: true, color: AMBER });
    s.addText(b.k, { x: x + 0.3, y: 3.22, w: cw - 0.6, h: 0.36, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, color: PAPER });
    s.addText(b.n, { x: x + 0.3, y: 3.62, w: cw - 0.6, h: 0.78, margin: 0, fontFace: F, fontSize: 11.5, color: ICE, lineSpacing: 18 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 4.94, w: W - M * 2, h: 1.16, rectRadius: 0.06, fill: { color: INK3 } });
  s.addText("原価がほぼAPI従量課金だけなので、契約数が増えても人件費が増えない。この構造が「従業員不在で年商1億」を可能にする。", {
    x: M + 0.34, y: 4.94, w: W - M * 2 - 0.68, h: 1.16, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14.5, bold: true, color: PAPER, lineSpacing: 24,
  });
}

/* ============================================================ 12. 自動化5レイヤー */
{
  const s = lightSlide();
  head(s, "10", "AUTOMATION", "「従業員不在」を成立させる5レイヤー", false);

  const layers = [
    { id: "L1", h: "収集", b: "業種別プロンプト200〜300問を各AI検索に定期投入し、引用有無・言及順位・引用元URLを記録" },
    { id: "L2", h: "分析", b: "LLMに「なぜ引用されないか」を構造化診断させ、不足トピック・構造化データ不備をJSON出力" },
    { id: "L3", h: "生成", b: "FAQ・用語定義・比較表の草案、JSON-LD、Googleビジネスプロフィール投稿文を自動生成" },
    { id: "L4", h: "納品", b: "レポートHTML／PDFを自動生成し月次で自動送付。顧客ダッシュボードで常時閲覧可能に" },
    { id: "L5", h: "営業", b: "ターゲットにL1〜L4をバッチ実行し「御社は競合5社中4位でした」という無料診断書を生成" },
  ];
  let y = 1.95;
  layers.forEach((l) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.74, rectRadius: 0.05, fill: { color: MIST } });
    s.addShape(pres.ShapeType.roundRect, { x: M + 0.28, y: y + 0.17, w: 0.62, h: 0.4, rectRadius: 0.05, fill: { color: AMBER } });
    s.addText(l.id, { x: M + 0.28, y: y + 0.17, w: 0.62, h: 0.4, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: INK });
    s.addText(l.h, { x: M + 1.06, y, w: 1.0, h: 0.74, margin: 0, valign: "middle", fontFace: F, fontSize: 16, bold: true, color: INK });
    s.addText(l.b, { x: M + 2.1, y, w: W - M * 2 - 2.4, h: 0.74, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: BODY });
    y += 0.82;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.06, w: W - M * 2, h: 0.82, rectRadius: 0.06, fill: { color: INK } });
  s.addText("人間が残る作業は初回商談（週2〜3件・各30分）と月次の例外対応のみ。30社運用で週の実働は約8時間。", {
    x: M + 0.34, y: 6.06, w: W - M * 2 - 0.68, h: 0.82, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13.5, bold: true, color: PAPER,
  });
  s.addNotes("技術スタックはNext.js + Supabase + Vercel、n8n、Claude API + OpenAI API、Stripe、Resend。すべて既存の低コストサービス。");
}

/* ============================================================ 13. 90日ロードマップ */
{
  const s = lightSlide();
  head(s, "11", "ROADMAP", "90日ロードマップ", false);

  const ph = [
    { w: "W1–3", t: "準備・検証・商品化", b: "開業届／士業100社リスト作成\nL1収集を最小構成で実装\n10社ぶんを手作業で診断\nレポート雛形・LP・契約書を整備", goal: "売れる状態", hi: false },
    { w: "W4–6", t: "初商談・初受注", b: "無料診断書を10社に送付\n商談3件を実施\n単発98,000円で1〜2社受注\n手作業で全力納品し品質基準を作る", goal: "初売上 10〜20万円", hi: true },
    { w: "W7–10", t: "自動化と拡販", b: "L2分析・L3生成をパイプライン化\n納品を1社8時間→1時間に短縮\n無料診断を50社にバッチ送付\n既存顧客を月額プランへ転換", goal: "月額3社＝黒字化", hi: false },
    { w: "W11–12", t: "無人化の完成", b: "L4納品・L5営業を自動化\n顧客ダッシュボード公開\n士業向けウェビナー1本", goal: "MRR 50〜100万円", hi: true },
  ];
  const cw = 2.98, gap = 0.24;
  ph.forEach((p, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 3.55, rectRadius: 0.06, fill: { color: p.hi ? AMBER_TINT : MIST } });
    s.addText(p.w, { x: x + 0.26, y: 2.16, w: cw - 0.52, h: 0.34, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, charSpacing: 1, color: AMBER_DK });
    s.addText(p.t, { x: x + 0.26, y: 2.5, w: cw - 0.52, h: 0.72, margin: 0, valign: "top", fontFace: F, fontSize: 17, bold: true, color: INK, lineSpacing: 24 });
    s.addText(p.b, { x: x + 0.26, y: 3.28, w: cw - 0.52, h: 1.45, margin: 0, fontFace: F, fontSize: 11, color: BODY, lineSpacing: 18 });
    s.addShape(pres.ShapeType.roundRect, { x: x + 0.26, y: 4.82, w: cw - 0.52, h: 0.46, rectRadius: 0.05, fill: { color: p.hi ? AMBER : INK } });
    s.addText(p.goal, { x: x + 0.26, y: 4.82, w: cw - 0.52, h: 0.46, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 11.5, bold: true, color: p.hi ? INK : PAPER });
  });

  s.addText("3か月時点の目標値：MRR 50〜100万円、累計売上 120〜200万円。W5–6の「手作業で全力納品」が、後の自動化の仕様書になる。", {
    x: M, y: 5.72, w: 11.9, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 13, color: BODY,
  });
}

/* ============================================================ 14. 収益シミュレーション（native chart） */
{
  const s = lightSlide();
  head(s, "12", "PROJECTION", "収益シミュレーション — 18か月で年商1億円", false);

  const cats = ["3か月", "6か月", "12か月", "18か月", "24か月"];
  s.addChart(
    pres.ChartType.bar,
    [
      { name: "サービスMRR", labels: cats, values: [72, 180, 390, 540, 700] },
      { name: "SaaS MRR", labels: cats, values: [0, 29, 196, 588, 1176] },
    ],
    {
      x: M, y: 1.9, w: 7.9, h: 4.3,
      barGrouping: "stacked",
      chartColors: [INK3, AMBER],
      showValue: false,
      showTitle: true, title: "月商の推移（万円）　※18か月時点 月商1,128万円 ＝ 年商1億3,536万円", titleFontFace: F, titleFontSize: 11.5, titleColor: SLATE,
      showLegend: true, legendPos: "b", legendFontFace: F, legendFontSize: 10, legendColor: BODY,
      catAxisLabelFontFace: F, catAxisLabelFontSize: 10, catAxisLabelColor: BODY,
      valAxisLabelFontFace: F, valAxisLabelFontSize: 9, valAxisLabelColor: SLATE,
      valGridLine: { color: MIST2, size: 1 },
      catGridLine: { style: "none" },
      valAxisMaxVal: 2000,
    }
  );

  const notes = [
    { v: "18か月", k: "年商1億円の到達点", n: "サービス40社＋SaaS 600社。\n1億円の約半分をSaaSが担う。" },
    { v: "週8〜10h", k: "1人の稼働上限", n: "サービス契約は40社を上限とし、\nそれ以上はSaaSへ誘導する。" },
    { v: "1.4億円", k: "保守シナリオの24か月時点", n: "SaaS転換が想定の半分でも到達。\nサービス単独でも年商8,100万円。" },
  ];
  let y = 1.95;
  notes.forEach((n) => {
    s.addShape(pres.ShapeType.roundRect, { x: 8.75, y, w: 3.93, h: 1.4, rectRadius: 0.06, fill: { color: MIST } });
    s.addText(n.v, { x: 9.03, y: y + 0.14, w: 3.4, h: 0.44, margin: 0, valign: "middle", fontFace: F, fontSize: 21, bold: true, color: AMBER_DK });
    s.addText(n.k, { x: 9.03, y: y + 0.58, w: 3.4, h: 0.28, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, color: INK });
    s.addText(n.n, { x: 9.03, y: y + 0.86, w: 3.4, h: 0.44, margin: 0, fontFace: F, fontSize: 10.5, color: SLATE, lineSpacing: 16 });
    y += 1.48;
  });
  srcNote(s, "前提条件付きの試算であり、収益を保証するものではありません。", false);
}

/* ============================================================ 15. 初期投資 */
{
  const s = lightSlide();
  head(s, "13", "INVESTMENT", "初期投資は3か月累計23万4,000円", false);

  const items = [
    ["Claude API / OpenAI API", "60,000"],
    ["名刺・郵送DM（100通）", "55,000"],
    ["SERP・順位取得API", "30,000"],
    ["契約書・利用規約ひな形", "30,000"],
    ["予備費", "30,000"],
    ["n8n（クラウド）", "9,000"],
    ["会計freee・請求書", "9,000"],
    ["Vercel / Supabase", "6,000"],
    ["ドメイン・LP制作（自作）", "3,000"],
    ["Stripe / Resend", "2,000"],
  ];
  let y = 1.95, col = 0;
  items.forEach((it, i) => {
    if (i === 5) { y = 1.95; col = 1; }
    const x = M + col * 6.16;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 5.9, h: 0.5, rectRadius: 0.04, fill: { color: i % 5 < 2 ? MIST : PAPER }, line: { color: MIST2, width: 1 } });
    s.addText(it[0], { x: x + 0.28, y, w: 4.0, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: BODY });
    s.addText(it[1] + "円", { x: x + 4.2, y, w: 1.45, h: 0.5, margin: 0, align: "right", valign: "middle", fontFace: F, fontSize: 12, bold: true, color: INK });
    y += 0.58;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 4.9, w: W - M * 2, h: 1.0, rectRadius: 0.06, fill: { color: INK } });
  s.addText("3か月累計", { x: M + 0.36, y: 4.9, w: 3.0, h: 1.0, margin: 0, valign: "middle", fontFace: F, fontSize: 15, bold: true, color: ICE });
  s.addText("234,000円", { x: M + 3.2, y: 4.9, w: 3.4, h: 1.0, margin: 0, valign: "middle", fontFace: F, fontSize: 30, bold: true, color: AMBER });
  s.addText("法人設立・オフィス・人材採用はすべて不要。\n在庫・設備・人件費はゼロ。", {
    x: M + 7.0, y: 4.9, w: 4.9, h: 1.0, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: PAPER, lineSpacing: 20,
  });

  s.addText("損益分岐は月額契約3社。初月の支出は94,000円で、W5–6の初受注（10〜20万円）が出た時点で回収が始まる。", {
    x: M, y: 6.1, w: 11.9, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 13, color: BODY,
  });
}

/* ============================================================ 16. リスク */
{
  const s = lightSlide();
  head(s, "14", "RISK", "リスクと対策 — 先に潰しておく2つ", false);

  // two critical (legal) risks, called out
  const crit = [
    { h: "AI事業者の利用規約", b: "ChatGPT等のUIをスクレイピングで自動操作するのは規約違反リスクが高い。必ず公式API、または正規のSERP／AI Overviews取得サービスを使い、UI自動操作は行わない。コスト増（1社月3,000円）は原価に織り込み済み。" },
    { h: "特定電子メール法", b: "無差別のメール営業は違法。広告メールはオプトイン取得後のみとし、初回接触は問い合わせフォーム／郵送DM／SNS DM／紹介で行う。郵送DM費用は初期投資に計上済み。" },
  ];
  const cw = 5.9, gap = 0.26;
  crit.forEach((c, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 2.05, rectRadius: 0.06, fill: { color: RISK_TINT } });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.3, y: 2.2, w: 0.4, h: 0.4, fill: { color: RISK } });
    s.addText("!", { x: x + 0.3, y: 2.2, w: 0.4, h: 0.4, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 15, bold: true, color: PAPER });
    s.addText(c.h, { x: x + 0.84, y: 2.18, w: cw - 1.2, h: 0.44, margin: 0, valign: "middle", fontFace: F, fontSize: 17, bold: true, color: RISK });
    s.addText(c.b, { x: x + 0.32, y: 2.72, w: cw - 0.64, h: 1.14, margin: 0, fontFace: F, fontSize: 11.5, color: BODY, lineSpacing: 19 });
  });

  const other = [
    ["競合の増加（40社超）", "士業特化＋月5〜15万円の価格帯で大手と直接競合しない"],
    ["アルゴリズム変動", "複合指標で契約し、成果保証・順位保証は書かない"],
    ["成果不実感による解約", "指名検索数・問い合わせ数まで追い、初月に必ず可視の改善を出す"],
    ["本業の就業規則・税務", "副業可否と競業避止を先に確認。住民税は普通徴収を選択"],
    ["1人稼働の上限", "サービスは40社を上限とし、以降はSaaSへ誘導"],
  ];
  let y = 4.2;
  other.forEach((o) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.5, rectRadius: 0.04, fill: { color: MIST } });
    s.addText(o[0], { x: M + 0.32, y, w: 3.3, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 12, bold: true, color: INK });
    s.addText(o[1], { x: M + 3.8, y, w: W - M * 2 - 4.1, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: BODY });
    y += 0.58;
  });
}

/* ============================================================ 17. 今週やること */
{
  const s = darkSlide();
  head(s, "15", "NEXT ACTIONS", "今週やる5つのこと", true);

  const acts = [
    "本業の就業規則で副業可否を確認する（これが最初のゲート）",
    "税務署に開業届を提出する（e-Taxで15分、無料）",
    "身近な士業3人に「あなたの事務所名をChatGPTに聞いた結果」を手作業で作って見せる",
    "OpenAI / Anthropic のAPIキーを取得し、士業向け診断プロンプトを30問書く",
    "ターゲット士業100社をリスト化する（Googleビジネスプロフィール・士業会名簿から）",
  ];
  let y = 2.0;
  acts.forEach((a, i) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.66, rectRadius: 0.05, fill: { color: INK2 } });
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.26, y: y + 0.13, w: 0.4, h: 0.4, fill: { color: AMBER } });
    s.addText(String(i + 1), { x: M + 0.26, y: y + 0.13, w: 0.4, h: 0.4, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 13, bold: true, color: INK });
    s.addText(a, { x: M + 0.86, y, w: W - M * 2 - 1.2, h: 0.66, margin: 0, valign: "middle", fontFace: F, fontSize: 14, color: PAPER });
    y += 0.74;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.82, w: W - M * 2, h: 0.94, rectRadius: 0.06, fill: { color: INK3 } });
  s.addText([
    { text: "3の反応が鈍ければ、ターゲットをクリニックに切り替えて再検証する。", options: { color: AMBER, bold: true } },
    { text: "　初期投資が小さいので、試行錯誤を3回回してもコストは10万円以下に収まる。", options: { color: PAPER } },
  ], {
    x: M + 0.34, y: 5.82, w: W - M * 2 - 0.68, h: 0.94, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13.5,
  });
  s.addNotes("最初の一手は3番。1日で需要を検証できる。ここで反応が出れば、そのまま無料診断レポートの雛形になる。");
}

pres.writeFile({ fileName: "AI検索可視化_副業ビジネス提案.pptx" }).then((f) => console.log("wrote:", f));
