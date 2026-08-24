/* eBay用ツールの立ち上げ。ツールごとに違うのはここだけ。 */

const TOOL_ID = "blueocean.ebay";
const DEFAULT_MARKET = "ebay_us";

const EBAY_SITE = {ebay_us:"https://www.ebay.com", ebay_eu:"https://www.ebay.de",
                   ebay_au:"https://www.ebay.com.au"};

function searchUrlFor(q, market){
  const base = EBAY_SITE[market] || EBAY_SITE.ebay_us;
  /* LH_Sold=1 & LH_Complete=1 で「売却済み」に絞る。
     出品中の価格は「まだ売れていない価格」なので相場には使わない。 */
  return base + "/sch/i.html?_nkw=" + encodeURIComponent(q || "")
       + "&LH_Sold=1&LH_Complete=1";
}

const SEARCH_LINK_LABEL = "売却済みを検索";

const MARKET_SEARCH_HINT =
  'eBay（<a href="https://www.ebay.com/sch/i.html?_nkw=&LH_Sold=1&LH_Complete=1" '
+ 'target="_blank" rel="noopener">売却済み検索</a>）';

const TRACK_SOURCE_LABEL = "eBay の Seller Hub レポートをそのまま貼れます";

const TRACK_GUIDE_HTML =
    '<ol>'
  + '<li><a href="https://www.ebay.com/sh/lst/active" target="_blank" rel="noopener">Seller Hub → 出品 → 出品中</a> を開きます。</li>'
  + '<li>右上の <b>Download</b> から「All active listings」をCSVで落とします。</li>'
  + '<li>そのCSVの中身を、この画面のテキスト欄に<b>そのまま貼って</b>「取り込む」を押します。列名は自動で合わせます。</li>'
  + '<li><b>毎週やってください。</b>2回目以降は前回との差が出ます。1回だけでは「動いていない」が分かりません。</li>'
  + '</ol>'
  + '<p>手で作る場合は <code>sku,title,listed_on,observed_on,views,watchers,sold</code> の形にしてください。'
  + '<code>listed_on</code> は出品日、<code>observed_on</code> はその数字を見た日です。</p>'
  + '<p><b>販売個数・売却率までは Seller Hub のレポートには入りません。</b>'
  + 'それが要る場合は Terapeak（eBayの出品者向け機能）を別途見てください。ここで扱うのは自分の出品の反応です。</p>';

const SAMPLE_ROWS =
`sku,title_ja,cost_incl_tax_jpy,weight_g,length_cm,width_cm,height_cm,market_price_usd,competitor_count,has_demand_signal,demand_note,source_url
LENS-001,Nikon Ai-s 50mm F1.2 manual lens,42000,320,18,14,12,620,4,yes,同型の落札を直近90日で12件確認,
LENS-002,Konica Hexanon AR 40mm F1.8,9800,180,16,12,10,185,2,yes,近縁モデルの落札あり,
FIG-001,ねんどろいど 限定版,4200,900,20,15,12,68,7,no,,
CAM-001,Canon AE-1 Program body,18000,620,20,14,12,145,34,yes,落札多数だが競合も多い,
WATCH-01,Seiko 5 Sports 自動巻き,16000,180,12,10,8,210,3,no,,`;

const SAMPLE_OBS =
`sku,title,listed_on,observed_on,views,watchers,sold
LENS-001,Nikon Ai-s 50mm F1.2,2026-06-20,2026-08-17,148,6,0
LENS-001,Nikon Ai-s 50mm F1.2,2026-06-20,2026-08-24,171,9,1
LENS-002,Konica Hexanon AR 40mm,2026-07-10,2026-08-17,62,0,0
LENS-002,Konica Hexanon AR 40mm,2026-07-10,2026-08-24,64,0,0
CAM-001,Canon AE-1 Program,2026-05-01,2026-08-24,18,0,0`;

function onScreen(id){
  /* 隠れている間に描くと高さが 0 なので、表示された時点で描き直す。 */
  if (id === "pick" && GRID) GRID._paint();
  if (id === "list" && GRID && GRID.sel >= 0) fillListFromRow(GRID.rows[GRID.sel]);
}

function applyAll(){
  saveCfg();
  renderSetbar();
  if (GRID){ GRID.cols = pickCols(); GRID.recalcAll(); renderPickWarn(GRID.rows); }
  renderListPrice(); renderBundle();
  renderFindPlan();
}

document.addEventListener("DOMContentLoaded", function(){
  bootShell();
  bootPick();
  bootFind((rows, append) => setRows(rows, append));
  bootListEbay();
  bootTrack();
  GRID.onSelect = r => { $("lp-who").textContent = "選択中：" + (r.title_ja || r.sku || ""); };
  $("st-wipe").addEventListener("click", () => {
    if (!confirm("この端末に保存した商品・観測・設定を全部消します。よろしいですか？")) return;
    [CKEY, RKEY, TOOL_ID + ".obs", TOOL_ID + ".history", TOOL_ID + ".screen"]
      .forEach(k => { try{ localStorage.removeItem(k); }catch(e){} });
    location.reload();
  });
  renderSetbar();
});
