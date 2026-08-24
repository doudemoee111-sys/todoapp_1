/* 2つのツールで共通の土台。
   ・設定は1か所（SETTINGS）。4画面すべてがここを見る。同じ数字を2回入れさせない。
   ・画面は業務の順番でしか並べない。
   ・保存は端末ローカル（localStorage）。外へは一切出さない。 */

const $ = id => document.getElementById(id);
/* yen は core.js が持っている（判定文でも使うため） */
const CKEY = TOOL_ID + ".cfg";
const RKEY = TOOL_ID + ".rows";

/* ---------------- 設定 ---------------- */

const SETTINGS = {
  market: DEFAULT_MARKET,
  level: "above_standard",
  fx: 150,
  target: 20,          /* % */
  taxable: true,
  carrier: "auto",
  fee: null, duty: null, ship: null, pack: null, per: null,   /* null = 市場の既定値 */
};

function loadCfg(){
  try{
    const o = JSON.parse(localStorage.getItem(CKEY) || "{}");
    Object.keys(SETTINGS).forEach(k => { if (o[k] !== undefined) SETTINGS[k] = o[k]; });
  }catch(e){ /* 壊れていたら既定値で立ち上げる */ }
  if (!PROFILES[SETTINGS.market]) SETTINGS.market = DEFAULT_MARKET;
}
function saveCfg(){
  try{ localStorage.setItem(CKEY, JSON.stringify(SETTINGS)); }catch(e){}
}

/* core.js が期待する形に落とす。ここだけが設定の出口。 */
function cfg(){
  const m = SETTINGS.market, p = PROFILES[m];
  const pick = (v, d) => (v === null || v === "" || v === undefined) ? d : +v;
  return {
    market:m, level:SETTINGS.level,
    fx: +SETTINGS.fx || 150,
    target: (+SETTINGS.target || 0) / 100,
    fee: pick(SETTINGS.fee, p.fee * 100) / 100,
    duty: pick(SETTINGS.duty, p.duty * 100) / 100,
    ship: pick(SETTINGS.ship, p.ship),
    pack: pick(SETTINGS.pack, p.pack),
    per:  pick(SETTINGS.per,  p.per),
    taxable: !!SETTINGS.taxable,
    zone: ZONE_OF[m],
    autoShip: true,
    carrier: SETTINGS.carrier,
  };
}

const LV_LABEL = {top_rated:"Top Rated", above_standard:"Above Standard",
                  below_standard:"Below Standard"};

function renderSetbar(){
  const c = cfg();
  const q = c.carrier === "flat" ? ("固定額 " + yen(c.ship) + "円")
    : IS_SHOPEE(c.market) ? "SLS（国内送料のみ）"
    : (c.carrier === "auto" ? "最安を自動" : CLABEL[c.carrier]);
  $("setbar").innerHTML =
      '市場 <b>' + esc(PROFILES[c.market].label) + '</b>'
    + '<span>為替 <b>' + c.fx + '</b> 円/$</span>'
    + '<span>目標利益率 <b>' + (c.target*100).toFixed(0) + '%</b></span>'
    + '<span>配送 <b>' + esc(q) + '</b></span>'
    + '<span>手数料 <b>' + (c.fee*100).toFixed(1) + '%</b></span>'
    + (c.duty ? '<span>関税 <b>' + (c.duty*100).toFixed(1) + '%</b></span>' : "")
    + '<span>' + (c.taxable ? "課税事業者（消費税還付あり）" : "免税事業者（還付なし）") + '</span>'
    + (IS_SHOPEE(c.market) ? "" : '<span>' + esc(LV_LABEL[c.level]) + '</span>');
}

function buildSettingsForm(){
  const wrap = $("set-form");
  wrap.innerHTML =
    '<div class="row">'
  +  fSel("s-market", "販売先", Object.keys(PROFILES).map(k => [k, PROFILES[k].label]))
  +  fSel("s-level", "eBayのセラーレベル", Object.keys(LV_LABEL).map(k => [k, LV_LABEL[k]]),
          "手数料が上下します。Shopeeでは使いません")
  +  fNum("s-fx", "為替（円/$）", "仕入も送料も円、売上はドル。ここが1円動くと利益が動きます")
  +  fNum("s-target", "目標利益率（%）", "仕入上限の逆算に使う数字")
  + '</div>'
  + '<div class="row" style="margin-top:12px">'
  +  fSel("s-carrier", "配送手段",
          [["auto","最安を自動で選ぶ"]].concat(CARRIERS.map(c => [c, CLABEL[c]]))
            .concat([["flat","固定額を使う（下の送料欄の値）"]]))
  +  fNum("s-ship", "送料の固定額（円）",
          "「固定額を使う」を選んだときだけ使います")
  +  fNum("s-fee", "販売手数料（%）", "空欄なら市場の既定値")
  +  fNum("s-duty", "関税（%）", "セラー負担ぶん。DDPでない市場は0")
  +  fNum("s-pack", "梱包資材（円）", "1件あたり")
  +  fNum("s-per", "注文ごとの固定費（円）", "eBayの $0.40 相当など")
  + '</div>'
  + '<label class="ck" style="margin-top:14px"><input type="checkbox" id="s-taxable">'
  + '課税事業者として計算する（税込仕入の 10/110 が還付される前提）</label>'
  + '<div class="btns"><button class="btn" id="s-apply">この条件で全部を計算し直す</button>'
  + '<button class="btn ghost sm" id="s-reset">既定値に戻す</button></div>';

  function fNum(id, label, why){
    return '<div class="f"><label for="' + id + '">' + esc(label)
         + (why ? ' <span class="why">' + esc(why) + '</span>' : "")
         + '</label><input type="number" step="any" id="' + id + '"></div>';
  }
  function fSel(id, label, opts, why){
    return '<div class="f"><label for="' + id + '">' + esc(label)
         + (why ? ' <span class="why">' + esc(why) + '</span>' : "")
         + '</label><select id="' + id + '">'
         + opts.map(o => '<option value="' + o[0] + '">' + esc(o[1]) + '</option>').join("")
         + '</select></div>';
  }

  fillSettingsForm();

  $("s-market").addEventListener("change", () => {
    SETTINGS.market = $("s-market").value;
    /* 市場を変えたら料金の上書きは捨てる。前の市場の手数料が残ると事故になる。 */
    SETTINGS.fee = SETTINGS.duty = SETTINGS.ship = SETTINGS.pack = SETTINGS.per = null;
    SETTINGS.carrier = IS_SHOPEE(SETTINGS.market) ? "sls" : "auto";
    fillSettingsForm(); applyAll();
  });
  $("s-apply").addEventListener("click", () => { readSettingsForm(); applyAll(); toast("計算し直しました"); });
  $("s-reset").addEventListener("click", () => {
    SETTINGS.fee = SETTINGS.duty = SETTINGS.ship = SETTINGS.pack = SETTINGS.per = null;
    fillSettingsForm(); applyAll(); toast("既定値に戻しました");
  });
}

function fillSettingsForm(){
  const p = PROFILES[SETTINGS.market];
  $("s-market").value = SETTINGS.market;
  $("s-level").value = SETTINGS.level;
  $("s-carrier").value = SETTINGS.carrier;
  $("s-fx").value = SETTINGS.fx;
  $("s-target").value = SETTINGS.target;
  $("s-taxable").checked = !!SETTINGS.taxable;
  $("s-fee").value  = SETTINGS.fee  === null ? (p.fee*100).toFixed(1) : SETTINGS.fee;
  $("s-duty").value = SETTINGS.duty === null ? (p.duty*100).toFixed(1) : SETTINGS.duty;
  $("s-ship").value = SETTINGS.ship === null ? p.ship : SETTINGS.ship;
  $("s-pack").value = SETTINGS.pack === null ? p.pack : SETTINGS.pack;
  $("s-per").value  = SETTINGS.per  === null ? p.per  : SETTINGS.per;
  $("s-level").closest(".f").style.display = IS_SHOPEE(SETTINGS.market) ? "none" : "";
}
function readSettingsForm(){
  SETTINGS.level   = $("s-level").value;
  SETTINGS.carrier = $("s-carrier").value;
  SETTINGS.fx      = +$("s-fx").value || 150;
  SETTINGS.target  = +$("s-target").value || 0;
  SETTINGS.taxable = $("s-taxable").checked;
  SETTINGS.fee  = $("s-fee").value  === "" ? null : +$("s-fee").value;
  SETTINGS.duty = $("s-duty").value === "" ? null : +$("s-duty").value;
  SETTINGS.ship = $("s-ship").value === "" ? null : +$("s-ship").value;
  SETTINGS.pack = $("s-pack").value === "" ? null : +$("s-pack").value;
  SETTINGS.per  = $("s-per").value  === "" ? null : +$("s-per").value;
}

/* ---------------- 画面の切り替え ---------------- */

function showScreen(id){
  document.querySelectorAll(".screen").forEach(s =>
    s.dataset.on = (s.id === "sc-" + id) ? "1" : "0");
  document.querySelectorAll("nav.steps button").forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.sc === id)));
  try{ localStorage.setItem(TOOL_ID + ".screen", id); }catch(e){}
  window.scrollTo(0, 0);
  if (typeof onScreen === "function") onScreen(id);
}

function toast(msg){
  const t = $("toast");
  t.textContent = msg; t.dataset.on = "1";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.dataset.on = "0", 2200);
}

/* ---------------- 商品行 ---------------- */

/* 一覧が持つ列。抽出CSVの列名をそのまま受ける。 */
const ROW_KEYS = ["sku","title_ja","source_url","cost_incl_tax_jpy","weight_g",
                  "length_cm","width_cm","height_cm","category","market_price_usd",
                  "competitor_count","has_demand_signal","demand_note",
                  "is_restricted","restricted_reason","image_url",
                  "weight_is_estimate","cost_is_estimate","estimate_note","note"];

function blankRow(){
  const r = {}; ROW_KEYS.forEach(k => r[k] = ""); return r;
}

function saveRows(rows){
  try{ localStorage.setItem(RKEY, JSON.stringify(rows)); return true; }
  catch(e){ return false; }
}
function loadRows(){
  try{
    const a = JSON.parse(localStorage.getItem(RKEY) || "[]");
    return Array.isArray(a) ? a : [];
  }catch(e){ return []; }
}

/* 抽出CSV（domestic の書き出し）も候補CSVも、同じ一覧に流し込めるようにする。
   列名が違うだけで中身は同じものなので、ここで名寄せする。 */
const IMPORT_ALIAS = {
  title: "title_ja", name: "title_ja", 商品名: "title_ja",
  url: "source_url", item_url: "source_url",
  price_jpy: "cost_incl_tax_jpy", cost: "cost_incl_tax_jpy", 仕入値: "cost_incl_tax_jpy",
  weight_est_g: "weight_g", weight: "weight_g",
  jan: "sku", item_code: "sku",
  genre_name: "category",
  image_urls: "image_url",
};

function importRows(text){
  const raw = parseCsv(text);
  if (!raw.length) return {rows:[], warnings:["読み取れる行がありませんでした。"]};

  const warnings = [];
  const rows = raw.map(o => {
    const r = blankRow();
    Object.keys(o).forEach(k0 => {
      const k = IMPORT_ALIAS[k0] || k0;
      if (ROW_KEYS.indexOf(k) >= 0 && (r[k] === "" || o[k0] !== "")) r[k] = o[k0];
    });
    if (!r.sku) r.sku = r.title_ja.slice(0, 40);
    /* 推定重量の印は文字でも真偽でも来る */
    r.weight_is_estimate = /^(yes|true|1|genre|unknown)$/i.test(String(r.weight_is_estimate)) ? "yes" : "";
    r.cost_is_estimate   = /^(yes|true|1)$/i.test(String(r.cost_is_estimate)) ? "yes" : "";
    return r;
  }).filter(r => r.title_ja || r.sku);

  /* 黙って落とさない。何が足りないかを数えて言う。 */
  const noPrice  = rows.filter(r => !(+r.cost_incl_tax_jpy > 0)).length;
  const noWeight = rows.filter(r => !(+r.weight_g > 0)).length;
  const noMarket = rows.filter(r => !(+r.market_price_usd > 0)).length;
  if (noPrice)  warnings.push(noPrice + "件は仕入値が空です。判定は暫定値のままになります。");
  if (noWeight) warnings.push(noWeight + "件は重量が空です。送料が出せないので採算判定が出ません。");
  if (noMarket) warnings.push(noMarket + "件は販売先の相場が空です。<b>相場を入れるまで採算は出ません。</b>③出す の手順で入れてください。");
  const est = rows.filter(r => r.weight_is_estimate).length;
  if (est) warnings.push(est + "件は重量が推定値（商品名やカテゴリからの当たり）です。実測に置き換えるまで最良でも「小さく試す」止まりになります。");
  return {rows, warnings};
}

function rowsToCsv(rows){
  const e = v => /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g,'""') + '"' : String(v ?? "");
  return [ROW_KEYS.join(",")]
    .concat(rows.map(r => ROW_KEYS.map(k => e(r[k])).join(","))).join("\n");
}

/* ファイルの渡し方は置かれている場所で変わる。
   ・claude.ai の閲覧画面：ページからの直接ダウンロードは塞がれているので、
     downloads 機能を通して保存の確認を出す。
   ・手元でHTMLを開いている場合：ふつうのブラウザ保存で足りる。
   どちらも使えないときは、黙って何も起きないのではなく中身を出して拾わせる。 */
async function download(name, text){
  const hosted = typeof window.claude !== "undefined" && window.claude
                 && typeof window.claude.use === "function";
  if (hosted){
    let dl = null;
    try{ dl = await window.claude.use("downloads"); }catch(e){ dl = null; }
    if (dl){
      try{
        await dl.save({filename:name, data:text});
        toast("保存しました");
        return;
      }catch(e){
        const code = e && e.code;
        if (code === "declined"){ toast("保存を取りやめました"); return; }
        if (code === "extension_not_enabled"){
          /* .csv が許可されていない環境では .txt で渡す。中身は同じCSV。 */
          try{
            await dl.save({filename:name.replace(/\.csv$/i, ".txt"), data:text});
            toast("保存しました（拡張子は .txt ですが中身はCSVです）");
            return;
          }catch(e2){ /* 下の手に落とす */ }
        }
      }
    }
    showCopyFallback(name, text);
    return;
  }
  try{
    const b = new Blob([text], {type:"text/csv;charset=utf-8"});
    const u = URL.createObjectURL(b), a = document.createElement("a");
    a.href = u; a.download = name; document.body.appendChild(a); a.click();
    a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000);
  }catch(e){
    showCopyFallback(name, text);
  }
}

/* 保存できない環境で「押したのに何も起きない」を作らないための逃げ道。 */
function showCopyFallback(name, text){
  let box = $("dl-fallback");
  if (!box){
    box = document.createElement("div");
    box.id = "dl-fallback";
    box.className = "panel";
    box.style.cssText = "position:fixed;inset:auto 18px 18px 18px;max-width:900px;"
      + "margin:0 auto;z-index:80;box-shadow:0 8px 40px rgba(0,0,0,.28);max-height:60vh;overflow:auto";
    document.body.appendChild(box);
  }
  box.innerHTML = '<h3>' + esc(name) + ' <span class="sub">この環境ではファイル保存ができないので、'
    + '中身をそのまま出しています</span></h3>'
    + '<pre class="out" id="dl-text" style="max-height:34vh">' + esc(text) + '</pre>'
    + '<div class="btns"><button class="btn sm" id="dl-copy">全部コピー</button>'
    + '<button class="btn ghost sm" id="dl-close">閉じる</button></div>';
  $("dl-copy").addEventListener("click", () => copyText($("dl-text"), "コピーしました"));
  $("dl-close").addEventListener("click", () => box.remove());
}

/* 埋め込み表示ではクリップボードAPIが塞がれていることがある。
   その場合は選択状態にして Ctrl+C で拾えるようにする。 */
function copyText(el, msg){
  const t = el.textContent;
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(() => toast(msg || "コピーしました"),
                                          () => selectNode(el));
  } else selectNode(el);
}
function selectNode(el){
  const r = document.createRange(); r.selectNodeContents(el);
  const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  toast("選択しました。Ctrl+C（⌘C）でコピーしてください");
}

/* ---------------- 起動 ---------------- */

function bootShell(){
  loadCfg();
  buildSettingsForm();
  document.querySelectorAll("nav.steps button").forEach(b =>
    b.addEventListener("click", () => showScreen(b.dataset.sc)));
  let start = "find";
  try{ start = localStorage.getItem(TOOL_ID + ".screen") || "find"; }catch(e){}
  if (!$("sc-" + start)) start = "find";
  showScreen(start);
  renderSetbar();
}
