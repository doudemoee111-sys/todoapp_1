/* ②選ぶ の中身。列の定義と一覧の組み立て。
   「すべての列を出す」指定なので全部出すが、横に並べたときに読めるよう
   幅と揃えは列ごとに決めている。数字は等幅・右揃え。 */

let GRID = null;

/* 判定の呼び名は業務の言葉にする。「PROBE」は画面に出さない。 */
const VERDICT = {
  blue:  {cls:"blue",  label:"出せる",     desc:"目標利益率・競合・需要のすべてが揃っている"},
  probe: {cls:"probe", label:"小さく試す", desc:"どれかが未確定。1〜2点で反応を見る"},
  thin:  {cls:"thin",  label:"採算割れ",   desc:"仕入値が上限を超えている"},
  red:   {cls:"red",   label:"見送り",     desc:"競合が多く値下げ競争になる"},
  excl:  {cls:"excl",  label:"除外",       desc:"規制品・重量超過・相場未入力など"},
};

function pickCols(){
  const c = cfg();
  const cols = [
    {k:"image_url", label:"写真", w:44, title:"仕入元の画像。型番違いを掴まないための現物照合用",
     cell:r => r.image_url
       ? '<img src="' + esc(r.image_url) + '" alt="" loading="lazy" referrerpolicy="no-referrer">'
       : '<span class="est">—</span>'},

    {k:"title_ja", label:"商品名", w:250,
     cell:r => '<span title="' + esc(r.title_ja) + '">' + esc(r.title_ja || r.sku || "(名称なし)") + '</span>'},

    {k:"cost_incl_tax_jpy", label:"仕入値(円)", w:92, num:true, edit:true,
     title:"税込。ここを動かすと判定が変わります",
     cell:r => gEdit("cost_incl_tax_jpy", r.cost_incl_tax_jpy)},

    {k:"weight_g", label:"重量(g)", w:80, num:true, edit:true, title:"梱包後の実重量",
     cell:r => gEdit("weight_g", r.weight_g)},

    {k:"length_cm", label:"縦", w:52, num:true, edit:true, cell:r => gEdit("length_cm", r.length_cm)},
    {k:"width_cm",  label:"横", w:52, num:true, edit:true, cell:r => gEdit("width_cm", r.width_cm)},
    {k:"height_cm", label:"高", w:52, num:true, edit:true, cell:r => gEdit("height_cm", r.height_cm)},

    {k:"chg", label:"課金重量", w:86, num:true,
     title:"実重量と容積重量の大きいほう。送料はこれで決まります",
     sort:(r,res) => res.chg || null,
     cell:(r,res) => {
       if (!res.chg) return '<span class="est">—</span>';
       const vol = res.quote && res.quote.byVolume;
       return (vol ? '<span class="est" title="容積で課金されています">▲</span> ' : "")
            + res.chg.toLocaleString() + "g";
     }},

    {k:"ship", label:"送料(円)", w:86, num:true,
     title:"課金重量から出した実額。使える手段が無ければ空欄になります",
     sort:(r,res) => res.ship === null || res.ship === undefined ? null : res.ship,
     cell:(r,res) => res.ship == null ? '<span class="est">—</span>'
       : '<span title="' + esc(res.quote ? CLABEL[res.quote.carrier] : "") + '">'
         + yen(res.ship) + '</span>'},

    {k:"market_price_usd", label:"相場($)", w:82, num:true, edit:true,
     title:"売却済みの中央値。出品中の価格ではありません",
     cell:r => gEdit("market_price_usd", r.market_price_usd)},

    {k:"competitor_count", label:"競合数", w:70, num:true, edit:true,
     title:"出品中の件数", cell:r => gEdit("competitor_count", r.competitor_count)},

    {k:"has_demand_signal", label:"需要", w:58,
     title:"売却実績を実際に見たときだけ yes。ここが空だと「出せる」に上がりません",
     sort:r => truthy(r.has_demand_signal) ? 0 : 1,
     cell:(r,res,i) => '<input type="checkbox" data-ck="' + i + '"'
        + (truthy(r.has_demand_signal) ? " checked" : "")
        + ' style="width:auto;margin:0 auto">'},

    {k:"cap", label:"仕入上限(円)", w:100, num:true,
     title:"目標利益率を満たす税込の仕入上限",
     sort:(r,res) => res.cap || null,
     cell:(r,res) => res.cap ? yen(res.cap) : '<span class="est">—</span>'},

    {k:"profit", label:"利益(円)", w:92, num:true,
     sort:(r,res) => res.profit ? res.profit.profit : null,
     cell:(r,res) => {
       if (!res.profit) return '<span class="est">—</span>';
       const p = res.profit.profit;
       return '<span style="color:var(--' + (p >= 0 ? "blue" : "red") + ')">' + yen(p) + '</span>';
     }},

    {k:"margin", label:"利益率", w:74, num:true,
     sort:(r,res) => res.profit ? res.profit.margin : null,
     cell:(r,res) => res.profit ? (res.profit.margin*100).toFixed(1) + "%" : '<span class="est">—</span>'},

    {k:"verdict", label:"判定", w:96,
     cell:(r,res) => {
       const v = VERDICT[res.verdict];
       return '<span class="v v-' + v.cls + '">' + esc(v.label) + '</span>';
     }},

    {k:"flip", label:"あと何を動かせば変わるか", w:290,
     sort:(r,res) => res.flip || null,
     cell:(r,res) => res.flip
       ? '<span title="' + esc(res.flip) + '">' + esc(res.flip) + '</span>'
       : '<span class="est">—</span>'},

    {k:"estimate_note", label:"推定の根拠", w:190,
     title:"重量や原価を推測で埋めた場合、その根拠",
     cell:r => r.estimate_note
       ? '<span class="est" title="' + esc(r.estimate_note) + '">' + esc(r.estimate_note) + '</span>'
       : '<span class="est">—</span>'},

    {k:"source_url", label:"仕入元", w:58,
     cell:r => r.source_url
       ? '<a href="' + esc(r.source_url) + '" target="_blank" rel="noopener">開く</a>'
       : '<span class="est">—</span>'},

    {k:"search", label:"販売先で見る", w:100,
     sort:() => 0,
     /* リンクの文言はツールごとに違う。Shopee には「売却済みだけ」の検索が無い
        ので、そこで「売却済みを検索」と書くと嘘になる。 */
     cell:r => '<a href="' + esc(searchUrlFor(r.title_ja || r.sku, cfg().market))
       + '" target="_blank" rel="noopener">' + SEARCH_LINK_LABEL + '</a>'},
  ];
  return cols;
}

function bootPick(){
  GRID = new Grid({
    root: $("pick-grid"),
    cols: pickCols(),
    calc: r => scoreOne(r, cfg()),
    onChange: g => { saveRows(g.rows); scheduleRecount(g); },
  });

  /* チェックボックスは Grid の共通処理に乗らないのでここで拾う。 */
  $("pick-grid").addEventListener("change", e => {
    const ck = e.target.closest("input[data-ck]"); if (!ck) return;
    const i = +ck.dataset.ck;
    GRID.rows[i].has_demand_signal = ck.checked ? "yes" : "";
    GRID.calcCache.delete(i);
    GRID._repaintRow(i);
    saveRows(GRID.rows);
  });

  $("pk-recalc").addEventListener("click", () => { GRID.recalcAll(); toast("計算し直しました"); });
  $("pk-add").addEventListener("click", () => {
    GRID.rows.push(blankRow()); GRID.calcCache.clear(); GRID.apply(); saveRows(GRID.rows);
  });
  $("pk-csv").addEventListener("click", () => {
    if (!GRID.rows.length){ toast("書き出す行がありません"); return; }
    download(TOOL_ID + "-candidates.csv", rowsToCsv(GRID.rows));
  });
  $("pk-clear").addEventListener("click", () => {
    if (!GRID.rows.length) return;
    if (!confirm(GRID.rows.length + "件を全部消します。よろしいですか？")) return;
    setRows([]); toast("消しました");
  });

  $("pk-market-link").innerHTML = MARKET_SEARCH_HINT;
  setRows(loadRows());
}

/* 判定の内訳が変わったら集計だけ引き直す。入力のたびに全行を回すと重い。 */
let _recountT = null;
function scheduleRecount(g){
  clearTimeout(_recountT);
  _recountT = setTimeout(() => g._renderTally(), 250);
}

function setRows(rows, append){
  const all = append ? GRID.rows.concat(rows) : rows;
  GRID.setRows(all);
  saveRows(all);
  renderPickWarn(all);
}

function renderPickWarn(rows){
  const out = [];
  const noMarket = rows.filter(r => !(+r.market_price_usd > 0)).length;
  const est = rows.filter(r => truthy(r.weight_is_estimate)).length;
  if (noMarket)
    out.push('<div class="warn"><b>' + noMarket.toLocaleString()
      + '件は相場が空です。</b>相場が無いと採算は出せないので、これらは「除外」に並びます。'
      + '一覧の右端「' + SEARCH_LINK_LABEL + '」から埋めてください。</div>');
  if (est)
    out.push('<div class="warn"><b>' + est.toLocaleString()
      + '件は重量が推定値です。</b>国内ショップのAPIは重量も寸法も返さないので、'
      + '商品名やカテゴリから当てています。実測に置き換えるまで、最良でも「小さく試す」までしか上がりません。</div>');
  if (typeof extraPickWarn === "function") out.push(extraPickWarn(rows) || "");
  $("pick-warn").innerHTML = out.join("");
}
