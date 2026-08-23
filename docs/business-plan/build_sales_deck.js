const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "AI検索可視化サービス";
pres.title = "AI検索可視化サービス ご提案（As-Is / To-Be）";

const W = 13.3, H = 7.5, M = 0.62;

// ---- palette : shared identity with the internal deck (ink + signal amber) ----
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
// As-Is is deliberately cool and drained; To-Be carries the amber
const ASIS_BG = "EDEFF4";
const ASIS_TXT = "5C6478";

const F = "Yu Gothic";
const sh = (o = {}) => Object.assign({ type: "outer", angle: 90, blur: 12, offset: 2, color: "9AA6BE", opacity: 0.28 }, o);

function darkSlide() { const s = pres.addSlide(); s.background = { color: INK }; return s; }
function lightSlide() { const s = pres.addSlide(); s.background = { color: PAPER }; return s; }

function head(s, num, label, title, dark) {
  s.addShape(pres.ShapeType.ellipse, { x: M, y: 0.52, w: 0.34, h: 0.34, fill: { color: AMBER } });
  s.addText(num, { x: M, y: 0.52, w: 0.34, h: 0.34, align: "center", valign: "middle", margin: 0, fontFace: F, fontSize: num.length > 1 ? 10.5 : 13, bold: true, color: INK });
  s.addText(label, { x: M + 0.5, y: 0.52, w: 7, h: 0.34, valign: "middle", margin: 0, fontFace: F, fontSize: 12, bold: true, charSpacing: 2, color: dark ? ICE : SLATE });
  s.addText(title, { x: M, y: 1.0, w: W - M * 2, h: 0.78, valign: "middle", margin: 0, fontFace: F, fontSize: 32, bold: true, color: dark ? PAPER : INK });
}
function srcNote(s, txt, dark) {
  s.addText(txt, { x: M, y: H - 0.6, w: W - M * 2, h: 0.32, margin: 0, valign: "middle", fontFace: F, fontSize: 9.5, color: dark ? "7E8BA8" : "97A0B4" });
}

/* ========================================================== 1. 表紙 */
{
  const s = darkSlide();
  s.addShape(pres.ShapeType.ellipse, { x: M, y: 0.95, w: 0.22, h: 0.22, fill: { color: AMBER } });
  s.addText("士業事務所さま向け　ご提案書", {
    x: M + 0.38, y: 0.93, w: 10, h: 0.26, margin: 0, valign: "middle",
    fontFace: F, fontSize: 12, bold: true, charSpacing: 2, color: ICE,
  });

  s.addText([
    { text: "その問い合わせ、", options: { color: PAPER, breakLine: true } },
    { text: "AIに奪われていませんか？", options: { color: AMBER } },
  ], { x: M, y: 1.95, w: 11.6, h: 2.0, margin: 0, valign: "top", fontFace: F, fontSize: 46, bold: true, lineSpacing: 62 });

  s.addText("いま、見込み客の6割はGoogleで検索してもサイトを見ずに離脱しています。\n答えているのはAIです。そのAIが「御社を挙げるかどうか」を、私たちが可視化して改善します。", {
    x: M, y: 4.15, w: 11.0, h: 1.0, margin: 0, fontFace: F, fontSize: 16, color: ICE, lineSpacing: 27,
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.45, w: 11.0, h: 0.9, rectRadius: 0.08, fill: { color: INK2 } });
  s.addText("AI検索可視化サービス　│　まずは無料のAI可視性診断から", {
    x: M + 0.36, y: 5.45, w: 10.3, h: 0.9, margin: 0, valign: "middle",
    fontFace: F, fontSize: 17, bold: true, color: PAPER,
  });
  s.addNotes("冒頭は「困っていることの言語化」から入る。売り込みではなく、相手がまだ気づいていない現象を先に説明する。");
}

/* ========================================================== 2. いま何が起きているか */
{
  const s = darkSlide();
  head(s, "1", "WHAT'S HAPPENING", "いま、検索で何が起きているか", true);

  const stats = [
    { v: "60%", k: "ゼロクリック率", n: "Google検索の約6割が\nサイトを見ずに終わる" },
    { v: "−40%", k: "順位が同じでもCTRは", n: "1位のままなのに\nクリックが減っている" },
    { v: "55倍", k: "AI検索の利用量", n: "2024年4月比で\nセッションが+5,535%" },
    { v: "25倍", k: "AI経由のCVR", n: "従来SEO経由と比べた\n成約率の差（支援会社公表値）" },
  ];
  const cw = 2.86, gap = 0.24;
  stats.forEach((st, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.0, w: cw, h: 2.7, rectRadius: 0.06, fill: { color: INK2 } });
    s.addText(st.v, { x: x + 0.24, y: 2.22, w: cw - 0.48, h: 0.84, margin: 0, valign: "middle", fontFace: F, fontSize: 32, bold: true, color: AMBER });
    s.addText(st.k, { x: x + 0.24, y: 3.1, w: cw - 0.48, h: 0.36, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: PAPER });
    s.addText(st.n, { x: x + 0.24, y: 3.5, w: cw - 0.48, h: 0.9, margin: 0, fontFace: F, fontSize: 11, color: ICE, lineSpacing: 17 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.05, w: W - M * 2, h: 1.05, rectRadius: 0.06, fill: { color: INK3 } });
  s.addText([
    { text: "つまり、", options: { color: ICE } },
    { text: "「SEOは順調なのに問い合わせだけが減る」", options: { color: AMBER, bold: true } },
    { text: "という状態が、いま全国の事務所で同時に起きています。", options: { color: PAPER } },
  ], { x: M + 0.34, y: 5.05, w: W - M * 2 - 0.68, h: 1.05, margin: 0, valign: "middle", fontFace: F, fontSize: 15, lineSpacing: 25 });

  srcNote(s, "出典：博報堂DYグループ oneder「2026年版AI検索白書」／Uravation／各支援会社公表データ", true);
}

/* ========================================================== 3. As-Is 症状 */
{
  const s = lightSlide();
  head(s, "2", "AS-IS", "こんな症状が出ていませんか", false);

  const sym = [
    "検索順位は落ちていないのに、問い合わせ件数だけが減っている",
    "ホームページのアクセス数が、去年の同じ月より明らかに少ない",
    "「先生の事務所、ChatGPTで聞いたら出てこなかった」と言われたことがある",
    "広告費を足して件数を維持しているが、獲得単価が上がり続けている",
    "何が原因か分からないまま、SEO会社への支払いだけが続いている",
  ];
  let y = 2.0;
  sym.forEach((t) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.72, rectRadius: 0.05, fill: { color: ASIS_BG } });
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.3, y: y + 0.18, w: 0.36, h: 0.36, fill: { color: ASIS_TXT } });
    s.addText("✓", { x: M + 0.3, y: y + 0.18, w: 0.36, h: 0.36, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 13, bold: true, color: PAPER });
    s.addText(t, { x: M + 0.86, y, w: W - M * 2 - 1.2, h: 0.72, margin: 0, valign: "middle", fontFace: F, fontSize: 14.5, color: BODY });
    y += 0.8;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.12, w: W - M * 2, h: 0.82, rectRadius: 0.06, fill: { color: AMBER_TINT } });
  s.addText("1つでも当てはまるなら、原因はSEOではなくAI検索側にあります。次のページで、現状と改善後を並べます。", {
    x: M + 0.36, y: 6.12, w: W - M * 2 - 0.72, h: 0.82, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14, bold: true, color: INK,
  });
  s.addNotes("ここは相手に自己診断させるパート。うなずきが出た項目を覚えておき、後半の事例と結びつける。");
}

/* ========================================================== 4. As-Is → To-Be 全体像（中心スライド） */
{
  const s = lightSlide();
  head(s, "3", "AS-IS → TO-BE", "現状と、導入後に起きる変化", false);

  const colW = 5.55, gapC = 0.9;
  const xA = M, xB = M + colW + gapC;
  const top = 1.95, colH = 4.35;

  // As-Is column
  s.addShape(pres.ShapeType.roundRect, { x: xA, y: top, w: colW, h: colH, rectRadius: 0.06, fill: { color: ASIS_BG } });
  s.addText("AS-IS ／ 現状", { x: xA + 0.34, y: top + 0.24, w: colW - 0.68, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, charSpacing: 1.5, color: ASIS_TXT });
  s.addText("AIの答えに、御社がいない", { x: xA + 0.34, y: top + 0.6, w: colW - 0.68, h: 0.46, margin: 0, valign: "middle", fontFace: F, fontSize: 21, bold: true, color: INK });

  const asis = [
    "「相続に強い税理士は？」への答えに載らない",
    "何位なのか、誰が挙がっているのか分からない",
    "サイトを直しても効果があったか測れない",
    "対策できるのは検索順位だけ（＝もう効かない）",
    "問い合わせが減った理由を説明できない",
  ];
  let ya = top + 1.2;
  asis.forEach((t) => {
    s.addText("✕", { x: xA + 0.36, y: ya, w: 0.3, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, color: ASIS_TXT });
    s.addText(t, { x: xA + 0.72, y: ya, w: colW - 1.1, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: ASIS_TXT });
    ya += 0.58;
  });

  // arrow
  s.addShape(pres.ShapeType.chevron, { x: xA + colW + 0.16, y: top + 1.75, w: 0.58, h: 0.66, fill: { color: AMBER } });

  // To-Be column
  s.addShape(pres.ShapeType.roundRect, { x: xB, y: top, w: colW, h: colH, rectRadius: 0.06, fill: { color: AMBER_TINT } });
  s.addText("TO-BE ／ 導入後", { x: xB + 0.34, y: top + 0.24, w: colW - 0.68, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, charSpacing: 1.5, color: AMBER_DK });
  s.addText("AIが、御社を名指しで挙げる", { x: xB + 0.34, y: top + 0.6, w: colW - 0.68, h: 0.46, margin: 0, valign: "middle", fontFace: F, fontSize: 21, bold: true, color: INK });

  const tobe = [
    "主要な質問200問で引用されるかを毎月測定",
    "競合と比べた「AI上での順位」が数字で出る",
    "直した箇所と引用率の変化がひも付いて見える",
    "AI・検索・地図の3経路をまとめて対策",
    "減った理由も増えた理由も説明できる",
  ];
  let yb = top + 1.2;
  tobe.forEach((t) => {
    s.addText("●", { x: xB + 0.36, y: yb, w: 0.3, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, color: AMBER_DK });
    s.addText(t, { x: xB + 0.72, y: yb, w: colW - 1.1, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: INK });
    yb += 0.58;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.5, w: W - M * 2, h: 0.7, rectRadius: 0.06, fill: { color: INK } });
  s.addText("変わるのは「順位を上げる」ではなく、AIが答えを作るときの引用元に御社が入ること。", {
    x: M + 0.36, y: 6.5, w: W - M * 2 - 0.72, h: 0.7, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14, bold: true, color: PAPER,
  });
  s.addNotes("このスライドが提案の中心。ここで「順位ではなく引用」という視点の転換を必ず言語化する。");
}

/* ========================================================== 5. 対比① 集客チャネル */
{
  const s = lightSlide();
  head(s, "4", "CHANGE 1", "変化①　集客の入口が増える", false);

  const rows = [
    { k: "見込み客が使う入口", a: "Google検索のみを想定", b: "Google＋ChatGPT・Gemini＋地図" },
    { k: "指名される瞬間", a: "検索結果の一覧に並ぶ（選ばれるかは運）", b: "AIが「この事務所です」と1〜3件に絞って挙げる" },
    { k: "競合との比較", a: "10件横並びの中の1つ", b: "AIが挙げる少数の中に入れば実質ほぼ独占" },
    { k: "問い合わせの質", a: "相見積もり前提の一括依頼が多い", b: "推薦された状態で来るため比較検討が済んでいる" },
  ];
  compareTable(s, rows, 2.24);

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.05, w: W - M * 2, h: 0.86, rectRadius: 0.06, fill: { color: AMBER_TINT } });
  s.addText("AI経由の問い合わせは成約率が高い傾向が報告されています（従来SEO比で最大25倍という支援会社の公表値あり）。件数だけでなく「決まりやすさ」が変わります。", {
    x: M + 0.36, y: 6.05, w: W - M * 2 - 0.72, h: 0.86, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13, bold: true, color: INK, lineSpacing: 21,
  });
}

/* ========================================================== 6. 対比② 手間とコスト */
{
  const s = lightSlide();
  head(s, "5", "CHANGE 2", "変化②　手間とコストが下がる", false);

  const rows = [
    { k: "先生の作業時間", a: "ブログ記事のネタ出しと執筆に月10時間以上", b: "AIが草案を作り、先生は監修だけ（月1〜2時間）" },
    { k: "外注費", a: "SEO会社＋記事外注＋広告で月20〜40万円", b: "月4.98万円〜。広告依存を減らして総額を圧縮" },
    { k: "報告資料", a: "順位表だけ。何をすればいいか分からない", b: "引用状況＋やるべきことが指示書として毎月届く" },
    { k: "人の増員", a: "Web担当を採用しないと回らない", b: "採用不要。仕組み側が自動で回る" },
  ];
  compareTable(s, rows, 2.24);

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.05, w: W - M * 2, h: 0.86, rectRadius: 0.06, fill: { color: INK } });
  s.addText("「デジタル化・AI導入補助金2026」の対象になれば、補助率1/2〜4/5・最大450万円。実質負担はさらに下がります。",
    { x: M + 0.36, y: 6.05, w: W - M * 2 - 0.72, h: 0.86, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: PAPER });
}

/* ========================================================== 7. 対比③ 経営数字 */
{
  const s = darkSlide();
  head(s, "6", "CHANGE 3", "変化③　経営の数字がこう動く", true);

  const kpis = [
    { k: "AI検索での引用率", a: "測っていない（0%扱い）", b: "主要200問中の引用率を毎月可視化" },
    { k: "新規問い合わせ", a: "前年割れが続いている", b: "AI経由という新チャネルが上乗せされる" },
    { k: "顧客獲得単価", a: "広告依存で上昇中", b: "自然流入が戻り、単価が下がる" },
    { k: "説明責任", a: "「なぜ減ったか」に答えられない", b: "月次レポートで打ち手と結果が対応づく" },
  ];
  let y = 2.26;
  s.addText("項目", { x: M + 0.3, y: 1.92, w: 3.0, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1, color: SLATE });
  s.addText("AS-IS ／ 現状", { x: M + 3.6, y: 1.92, w: 4.0, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1, color: SLATE });
  s.addText("TO-BE ／ 導入後", { x: M + 7.9, y: 1.92, w: 4.0, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1, color: AMBER });
  kpis.forEach((r) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.86, rectRadius: 0.05, fill: { color: INK2 } });
    s.addText(r.k, { x: M + 0.3, y, w: 3.2, h: 0.86, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: PAPER });
    s.addText(r.a, { x: M + 3.6, y, w: 4.1, h: 0.86, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: "8892AA" });
    s.addShape(pres.ShapeType.chevron, { x: M + 7.5, y: y + 0.31, w: 0.28, h: 0.26, fill: { color: AMBER } });
    s.addText(r.b, { x: M + 7.9, y, w: 4.1, h: 0.86, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: AMBER });
    y += 0.94;
  });
  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.14, w: W - M * 2, h: 0.74, rectRadius: 0.06, fill: { color: INK3 } });
  s.addText("いちばん大きな変化は「説明できるようになる」ことです。打ち手と結果が毎月ひも付き、判断ができるようになります。", {
    x: M + 0.34, y: 6.14, w: W - M * 2 - 0.68, h: 0.74, margin: 0, valign: "middle",
    fontFace: F, fontSize: 13.5, bold: true, color: PAPER,
  });
  s.addNotes("数値の約束はここではしない。無料診断で現在地を測ってから合意する、という順番を明言する。");
}

/* ========================================================== 8. 何をするのか */
{
  const s = lightSlide();
  head(s, "7", "WHAT WE DO", "私たちが毎月やること", false);

  const steps = [
    { n: "01", h: "測る", b: "御社の見込み客が実際に聞く質問を200問用意し、ChatGPT・Gemini・AI Overviewsに毎月投げます。御社と競合が何回引用されたかを記録します。", note: "現在地が数字になる" },
    { n: "02", h: "直す", b: "引用されない原因（不足している説明・FAQ・構造化データ・第三者からの言及）を特定し、追加する文章とタグをこちらで作成します。", note: "作業は先生の監修だけ" },
    { n: "03", h: "見せる", b: "先月からどう変わったかを1枚のレポートにしてお送りします。引用率・指名検索数・問い合わせ数まで追いかけます。", note: "効果が説明できる" },
  ];
  const cw = 3.86, gap = 0.26;
  steps.forEach((st, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 3.5, rectRadius: 0.06, fill: { color: MIST }, shadow: sh() });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.3, y: 2.2, w: 0.52, h: 0.52, fill: { color: AMBER } });
    s.addText(st.n, { x: x + 0.3, y: 2.2, w: 0.52, h: 0.52, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 14, bold: true, color: INK });
    s.addText(st.h, { x: x + 0.96, y: 2.2, w: cw - 1.3, h: 0.52, margin: 0, valign: "middle", fontFace: F, fontSize: 24, bold: true, color: INK });
    s.addText(st.b, { x: x + 0.3, y: 2.92, w: cw - 0.6, h: 1.75, margin: 0, fontFace: F, fontSize: 12, color: BODY, lineSpacing: 20 });
    s.addShape(pres.ShapeType.roundRect, { x: x + 0.3, y: 4.78, w: cw - 0.6, h: 0.44, rectRadius: 0.05, fill: { color: AMBER } });
    s.addText(st.note, { x: x + 0.3, y: 4.78, w: cw - 0.6, h: 0.44, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 12, bold: true, color: INK });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.72, w: W - M * 2, h: 0.86, rectRadius: 0.06, fill: { color: INK } });
  s.addText("先生にお願いするのは、月1回30分の確認と、専門家としての監修だけです。記事の執筆も、タグの設定も、こちらで行います。", {
    x: M + 0.36, y: 5.72, w: W - M * 2 - 0.72, h: 0.86, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14, bold: true, color: PAPER,
  });
}

/* ========================================================== 9-11. 成功事例 */
{
  const s = lightSlide();
  head(s, "8", "CASE STUDIES", "実際に出ている成果（公表事例）", false);

  const cases = [
    { tag: "CASE 01", v: "6倍", k: "AI経由の問い合わせ", b: "「AI対策（LLMO）90日プログラム」の支援先で、AI経由の問い合わせが半年で約6倍、売上は8倍ペースに。", src: "株式会社ルーシー（バズ部）公表" },
    { tag: "CASE 02", v: "10倍", k: "問い合わせ件数", b: "2025年10月〜2026年2月の期間で、AI経由の流入が約6倍、問い合わせが約10倍。引用の初動は早ければ約1か月から。", src: "支援会社公表事例" },
    { tag: "CASE 03", v: "2倍", k: "商談数（6か月）", b: "GEO対策の導入6か月で商談数が2倍に。別の企業では売上130%増を達成した事例も報告されている。", src: "複数の支援会社公表事例" },
  ];
  const cw = 3.86, gap = 0.26;
  cases.forEach((c, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 3.6, rectRadius: 0.06, fill: { color: MIST } });
    s.addText(c.tag, { x: x + 0.3, y: 2.16, w: cw - 0.6, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1.5, color: AMBER_DK });
    s.addText(c.v, { x: x + 0.3, y: 2.5, w: cw - 0.6, h: 0.9, margin: 0, valign: "middle", fontFace: F, fontSize: 44, bold: true, color: AMBER_DK });
    s.addText(c.k, { x: x + 0.3, y: 3.42, w: cw - 0.6, h: 0.34, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: INK });
    s.addText(c.b, { x: x + 0.3, y: 3.84, w: cw - 0.6, h: 1.1, margin: 0, fontFace: F, fontSize: 11.5, color: BODY, lineSpacing: 19 });
    s.addText(c.src, { x: x + 0.3, y: 5.02, w: cw - 0.6, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 9.5, color: SLATE });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.78, w: W - M * 2, h: 0.86, rectRadius: 0.06, fill: { color: RISK_TINT } });
  s.addText("いずれも支援会社が自社サイトで公表している事例で、第三者による検証を経たものではありません。御社での成果をお約束するものではなく、まず無料診断で現在地を測ることをおすすめします。", {
    x: M + 0.36, y: 5.78, w: W - M * 2 - 0.72, h: 0.86, margin: 0, valign: "middle",
    fontFace: F, fontSize: 12, color: BODY, lineSpacing: 19,
  });
  srcNote(s, "出典：ai-search.techsuite.co.jp／jinrai.co.jp／start-link.jp ほか（詳細は巻末の参考資料一覧）", false);
}

{
  const s = lightSlide();
  head(s, "9", "CASE STUDIES", "士業・店舗ビジネスでの事例", false);

  const cs = [
    { h: "士業：ChatGPT経由で受任まで到達", b: "「ChatGPT経由で問い合わせがあり、そのまま受任につながった」という士業事務所の実例が報告されています。AI検索は既に実際の集客チャネルとして機能し始めています。2025年以降、AI Overviewsが士業分野でも拡大し、「AIに引用される事務所かどうか」が新規問い合わせ数に直結する局面に入りました。", src: "集客大陸（seo-best.jp）公表事例" },
    { h: "多店舗：情報の一元管理で引用率が向上", b: "複数店舗の美容室・飲食店で、Googleマップ・SNS・ホームページの情報を一元管理して整合性を担保したところ、AI検索からの引用率が向上し、マップ経由のルート検索と新規予約・来店が増加しました。", src: "支援会社公表事例" },
  ];
  const cw = 5.9, gap = 0.26;
  cs.forEach((c, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 2.9, rectRadius: 0.06, fill: { color: MIST } });
    s.addText(c.h, { x: x + 0.34, y: 2.2, w: cw - 0.68, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 17, bold: true, color: INK });
    s.addText(c.b, { x: x + 0.34, y: 2.78, w: cw - 0.68, h: 1.6, margin: 0, fontFace: F, fontSize: 12, color: BODY, lineSpacing: 20 });
    s.addText(c.src, { x: x + 0.34, y: 4.42, w: cw - 0.68, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 9.5, color: SLATE });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.1, w: W - M * 2, h: 1.5, rectRadius: 0.06, fill: { color: AMBER_TINT } });
  s.addText("経営者はいま、AIにこう聞いています", { x: M + 0.36, y: 5.24, w: 11.9, h: 0.32, margin: 0, valign: "middle", fontFace: F, fontSize: 12, bold: true, charSpacing: 1, color: AMBER_DK });
  s.addText("「うちの会社規模で月1万円台の税理士、誰がいい？」「相続に強い税理士事務所は？」\nこうした自然文の質問に、AIが具体的な事務所名を挙げて答えます。その答えに入っているかどうかが、顧問先獲得の土台になります。", {
    x: M + 0.36, y: 5.6, w: 11.9, h: 0.9, margin: 0, fontFace: F, fontSize: 13.5, bold: true, color: INK, lineSpacing: 22,
  });
}

/* ========================================================== 12. 勝ちパターン */
{
  const s = darkSlide();
  head(s, "10", "PATTERN", "成果を出した事例に共通する3つのこと", true);

  const ps = [
    { n: "01", h: "新しく作るのではなく、既存ページを作り直した", b: "成果を出した企業の共通点は、記事の新規量産ではなく、いま持っているページへのFAQスキーマ追加・冒頭への直接回答文の配置・著者情報の充実。既存資産の作り直しから着手しています。" },
    { n: "02", h: "自分たちしか出せないデータを公開した", b: "一次データ（自社調査・実績数値・料金の内訳）はAIが引用したがる素材です。どこにでもある一般論のページは引用されません。" },
    { n: "03", h: "第三者からの言及を増やした", b: "自社サイトの中だけでは足りません。業界メディア・士業ポータル・Googleビジネスプロフィールなど、外からの言及がAIの判断材料になります。" },
  ];
  let y = 2.0;
  ps.forEach((p) => {
    s.addShape(pres.ShapeType.ellipse, { x: M, y: y + 0.08, w: 0.54, h: 0.54, fill: { color: AMBER } });
    s.addText(p.n, { x: M, y: y + 0.08, w: 0.54, h: 0.54, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 14, bold: true, color: INK });
    s.addText(p.h, { x: M + 0.84, y, w: 11.1, h: 0.44, margin: 0, valign: "middle", fontFace: F, fontSize: 19, bold: true, color: PAPER });
    s.addText(p.b, { x: M + 0.84, y: 0.5 + y, w: 11.1, h: 0.86, margin: 0, fontFace: F, fontSize: 13, color: ICE, lineSpacing: 21 });
    y += 1.5;
  });
  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.46, w: W - M * 2, h: 0.64, rectRadius: 0.06, fill: { color: INK2 } });
  s.addText("特別な技術も大きな予算も不要。この3つを地道に積み上げた企業が成果を出しています。", {
    x: M + 0.34, y: 6.46, w: W - M * 2 - 0.68, h: 0.64, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, bold: true, color: AMBER,
  });
  s.addNotes("出典：jinrai.co.jp「GEO対策の成功事例5選」／connected-one.world「GEO対策の成功事例8選」ほか。詳細は巻末の参考資料一覧。");
}

/* ========================================================== 13. 導入の流れ */
{
  const s = lightSlide();
  head(s, "11", "HOW IT STARTS", "導入の流れ", false);

  const ph = [
    { w: "STEP 0 ／ 今週", t: "無料の可視性診断", b: "御社名と主要サービスを伺い、AIに聞いた結果をレポートでお返しします。費用は無料です。", hi: true },
    { w: "STEP 1 ／ 1か月目", t: "現在地の確定", b: "引用されない原因を特定し、優先度の高い箇所から着手。早ければ1か月で初動が出ます。", hi: false },
    { w: "STEP 2 ／ 2〜3か月目", t: "改善の反映と定着", b: "FAQ・構造化データ・第三者言及を順に整備。毎月レポートで変化を確認します。", hi: false },
    { w: "STEP 3 ／ 4か月目〜", t: "運用と横展開", b: "取れた質問を広げ、地図・指名検索まで最適化。問い合わせの数と質を積み上げます。", hi: false },
  ];
  const cw = 2.98, gap = 0.24;
  ph.forEach((p, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 3.2, rectRadius: 0.06, fill: { color: p.hi ? AMBER_TINT : MIST } });
    s.addText(p.w, { x: x + 0.26, y: 2.16, w: cw - 0.52, h: 0.32, margin: 0, valign: "middle", fontFace: F, fontSize: 11.5, bold: true, charSpacing: 1, color: p.hi ? AMBER_DK : SLATE });
    s.addText(p.t, { x: x + 0.26, y: 2.5, w: cw - 0.52, h: 0.7, margin: 0, valign: "top", fontFace: F, fontSize: 16.5, bold: true, color: INK, lineSpacing: 23 });
    s.addText(p.b, { x: x + 0.26, y: 3.26, w: cw - 0.52, h: 1.6, margin: 0, fontFace: F, fontSize: 11.5, color: BODY, lineSpacing: 19 });
  });
  s.addShape(pres.ShapeType.chevron, { x: M + cw + 0.02, y: 3.3, w: 0.3, h: 0.42, fill: { color: AMBER } });
  s.addShape(pres.ShapeType.chevron, { x: M + (cw + gap) + cw + 0.02, y: 3.3, w: 0.3, h: 0.42, fill: { color: AMBER } });
  s.addShape(pres.ShapeType.chevron, { x: M + 2 * (cw + gap) + cw + 0.02, y: 3.3, w: 0.3, h: 0.42, fill: { color: AMBER } });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.42, w: W - M * 2, h: 0.9, rectRadius: 0.06, fill: { color: INK } });
  s.addText("STEP 0 の診断は無料です。結果を見てから、続けるかどうかをお決めください。契約の縛りはありません。", {
    x: M + 0.36, y: 5.42, w: W - M * 2 - 0.72, h: 0.9, margin: 0, valign: "middle",
    fontFace: F, fontSize: 14.5, bold: true, color: PAPER,
  });
}

/* ========================================================== 14. 料金 */
{
  const s = lightSlide();
  head(s, "12", "PRICING", "料金プラン", false);

  const plans = [
    { n: "Light", p: "月 49,800円", b: ["毎月のAI引用状況の測定", "競合との比較レポート", "改善指示書の提供"], core: false },
    { n: "Standard", p: "月 149,800円", b: ["Lightの内容すべて", "コンテンツ・FAQの制作代行", "構造化データの実装まで"], core: true },
    { n: "Pro", p: "月 298,000円", b: ["Standardの内容すべて", "競合の継続追跡・多拠点対応", "月次オンライン報告会"], core: false },
  ];
  const cw = 3.86, gap = 0.26;
  plans.forEach((pl, i) => {
    const x = M + i * (cw + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: cw, h: 3.1, rectRadius: 0.06, fill: { color: pl.core ? AMBER_TINT : MIST } });
    if (pl.core) {
      s.addShape(pres.ShapeType.roundRect, { x: x + cw - 1.5, y: 2.16, w: 1.2, h: 0.3, rectRadius: 0.04, fill: { color: AMBER } });
      s.addText("おすすめ", { x: x + cw - 1.5, y: 2.16, w: 1.2, h: 0.3, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 10, bold: true, color: INK });
    }
    s.addText(pl.n, { x: x + 0.3, y: 2.16, w: cw - 1.7, h: 0.4, margin: 0, valign: "middle", fontFace: F, fontSize: 20, bold: true, color: INK });
    s.addText(pl.p, { x: x + 0.3, y: 2.66, w: cw - 0.6, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 22, bold: true, color: pl.core ? AMBER_DK : BODY });
    let by = 3.3;
    pl.b.forEach((t) => {
      s.addText("●", { x: x + 0.32, y: by, w: 0.26, h: 0.42, margin: 0, valign: "middle", fontFace: F, fontSize: 9, color: AMBER_DK });
      s.addText(t, { x: x + 0.62, y: by, w: cw - 0.94, h: 0.42, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: BODY });
      by += 0.5;
    });
  });

  const notes = [
    "初期費用0円。最低契約期間の縛りはありません（1か月単位）。",
    "「デジタル化・AI導入補助金2026」の対象になれば補助率1/2〜4/5・最大450万円。申請のご支援も可能です。",
    "順位保証・成果保証はいたしません（AI検索の仕様上、保証できるものではないためです）。",
  ];
  let y = 5.25;
  notes.forEach((t) => {
    s.addText("・" + t, { x: M, y, w: 11.9, h: 0.42, margin: 0, valign: "middle", fontFace: F, fontSize: 12.5, color: BODY });
    y += 0.46;
  });
}

/* ========================================================== 15. CTA */
{
  const s = darkSlide();
  head(s, "13", "NEXT STEP", "まずは、御社の現在地を見てみませんか", true);

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 2.05, w: W - M * 2, h: 2.3, rectRadius: 0.08, fill: { color: INK2 } });
  s.addText("無料 AI可視性診断", { x: M + 0.5, y: 2.3, w: 6.0, h: 0.6, margin: 0, valign: "middle", fontFace: F, fontSize: 30, bold: true, color: AMBER });
  s.addText("御社名と主要サービスをお伺いするだけで結構です。\n見込み客が実際に聞くであろう質問をAIに投げ、御社と競合が\n何回引用されたかをレポートにしてお返しします。", {
    x: M + 0.5, y: 2.98, w: 7.2, h: 1.1, margin: 0, fontFace: F, fontSize: 14, color: ICE, lineSpacing: 24,
  });
  const facts = [["ヒアリング", "15分"], ["費用", "無料"], ["納品", "5営業日以内"]];
  let fx = 8.4;
  facts.forEach((f) => {
    s.addShape(pres.ShapeType.roundRect, { x: fx, y: 2.5, w: 1.35, h: 1.4, rectRadius: 0.06, fill: { color: INK3 } });
    s.addText(f[0], { x: fx, y: 2.66, w: 1.35, h: 0.3, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 10.5, bold: true, color: ICE });
    s.addText(f[1], { x: fx + 0.1, y: 3.0, w: 1.15, h: 0.7, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 12.5, bold: true, color: PAPER, lineSpacing: 18 });
    fx += 1.5;
  });

  s.addText("診断レポートでお見せする3つのこと", { x: M, y: 4.62, w: 11.9, h: 0.36, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, charSpacing: 1, color: AMBER });
  const three = ["主要な質問で、御社が何回引用されたか", "同じ質問で、どの競合が何回挙がっているか", "引用されない原因として何が不足しているか"];
  let y3 = 5.04;
  three.forEach((t, i) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y: y3, w: W - M * 2, h: 0.54, rectRadius: 0.05, fill: { color: INK2 } });
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.26, y: y3 + 0.11, w: 0.32, h: 0.32, fill: { color: AMBER } });
    s.addText(String(i + 1), { x: M + 0.26, y: y3 + 0.11, w: 0.32, h: 0.32, margin: 0, align: "center", valign: "middle", fontFace: F, fontSize: 11, bold: true, color: INK });
    s.addText(t, { x: M + 0.76, y: y3, w: 11.0, h: 0.54, margin: 0, valign: "middle", fontFace: F, fontSize: 13.5, color: PAPER });
    y3 += 0.62;
  });
}

/* ========================================================== 16. 出典 */
{
  const s = lightSlide();
  head(s, "14", "REFERENCES", "参考資料・出典一覧", false);

  const refs = [
    ["市場データ", "博報堂DYグループ oneder「2026年版AI検索白書が示すゼロクリックの実態」", "oneder.hakuhodody-one.co.jp"],
    ["市場データ", "博報堂DYグループ oneder「AI検索エンジンのトラフィック推移と動向（2026年4月）」", "oneder.hakuhodody-one.co.jp"],
    ["市場データ", "Uravation「AI検索で流入60%消失｜ゼロクリック時代の5つの対策」", "uravation.com"],
    ["市場規模", "IDC Japan「国内AI市場は今後4年で約3倍に成長」", "idc.com"],
    ["成功事例", "AI検索パートナーズ「税理士事務所のAI検索集客とは？」（ルーシー／バズ部の事例を含む）", "ai-search.techsuite.co.jp"],
    ["成功事例", "株式会社仁頼「GEO対策（AIO/LLMO）の成功事例5選」", "jinrai.co.jp"],
    ["成功事例", "connected-one「GEO対策の成功事例8選｜海外企業がAIに引用された施策と数字」", "connected-one.world"],
    ["成功事例", "集客大陸「【士業の成功事例】ChatGPT経由で受任に至った！」", "seo-best.jp"],
    ["成功事例", "start-link「GEO対策（生成AI検索最適化）完全ガイド」", "start-link.jp"],
    ["料金相場", "SEデザイン「LLMO対策の費用相場はいくら？」／メディアリーチ「LLMO対策の費用比較」", "sedesign.co.jp ほか"],
    ["補助金", "中小企業庁「デジタル化・AI導入補助金2026」公募要領・制度概要", "chusho.meti.go.jp / it-shien.smrj.go.jp"],
  ];
  let y = 1.88;
  refs.forEach((r, i) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: W - M * 2, h: 0.4, rectRadius: 0.03, fill: { color: i % 2 ? PAPER : MIST } });
    s.addText(r[0], { x: M + 0.24, y, w: 1.1, h: 0.4, margin: 0, valign: "middle", fontFace: F, fontSize: 10, bold: true, color: AMBER_DK });
    s.addText(r[1], { x: M + 1.44, y, w: 7.6, h: 0.4, margin: 0, valign: "middle", fontFace: F, fontSize: 11, color: BODY });
    s.addText(r[2], { x: M + 9.2, y, w: 2.8, h: 0.4, margin: 0, valign: "middle", fontFace: F, fontSize: 10, color: SLATE });
    y += 0.44;
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 6.72, w: W - M * 2, h: 0.5, rectRadius: 0.05, fill: { color: RISK_TINT } });
  s.addText("成功事例として掲載した数値は、いずれも各支援会社が自社サイトで公表しているもので、第三者による検証を経ていません。", {
    x: M + 0.3, y: 6.72, w: W - M * 2 - 0.6, h: 0.5, margin: 0, valign: "middle", fontFace: F, fontSize: 11, color: BODY,
  });
}

/* ---------- shared: As-Is / To-Be comparison table ---------- */
function compareTable(s, rows, top) {
  const kx = M + 0.3, ax = M + 3.6, bx = M + 7.9;
  s.addText("項目", { x: kx, y: top - 0.34, w: 3.0, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1, color: SLATE });
  s.addText("AS-IS ／ 現状", { x: ax, y: top - 0.34, w: 4.0, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1, color: ASIS_TXT });
  s.addText("TO-BE ／ 導入後", { x: bx, y: top - 0.34, w: 4.0, h: 0.3, margin: 0, valign: "middle", fontFace: F, fontSize: 11, bold: true, charSpacing: 1, color: AMBER_DK });
  let y = top;
  rows.forEach((r) => {
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: 3.3 + 0.3, h: 0.88, rectRadius: 0.05, fill: { color: PAPER } });
    s.addShape(pres.ShapeType.roundRect, { x: ax - 0.24, y, w: 4.3, h: 0.88, rectRadius: 0.05, fill: { color: ASIS_BG } });
    s.addShape(pres.ShapeType.roundRect, { x: bx - 0.24, y, w: 4.36, h: 0.88, rectRadius: 0.05, fill: { color: AMBER_TINT } });
    s.addText(r.k, { x: kx, y, w: 3.2, h: 0.88, margin: 0, valign: "middle", fontFace: F, fontSize: 13, bold: true, color: INK });
    s.addText(r.a, { x: ax, y, w: 3.9, h: 0.88, margin: 0, valign: "middle", fontFace: F, fontSize: 12, color: ASIS_TXT });
    s.addShape(pres.ShapeType.chevron, { x: bx - 0.64, y: y + 0.3, w: 0.3, h: 0.28, fill: { color: AMBER } });
    s.addText(r.b, { x: bx, y, w: 3.96, h: 0.88, margin: 0, valign: "middle", fontFace: F, fontSize: 12, bold: true, color: INK });
    y += 0.96;
  });
}

pres.writeFile({ fileName: "AI検索可視化_顧客向け提案_AsIs-ToBe.pptx" }).then((f) => console.log("wrote:", f));
