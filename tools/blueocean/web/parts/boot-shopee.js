/* Shopee用ツールの立ち上げ。 */

const TOOL_ID = "blueocean.shopee";
const DEFAULT_MARKET = "shopee_tw";

const SHOPEE_SITE = {
  shopee_tw:"https://shopee.tw", shopee_sg:"https://shopee.sg",
  shopee_my:"https://shopee.com.my", shopee_ph:"https://shopee.ph",
  shopee_sea:"https://shopee.sg",
};

function searchUrlFor(q, market){
  const base = SHOPEE_SITE[market] || SHOPEE_SITE.shopee_tw;
  /* Shopee には「売却済みだけ」の検索がない。代わりに販売数の多い順で開いて、
     実際に売れている価格帯を見る。ここは eBay と手順が違う。 */
  return base + "/search?keyword=" + encodeURIComponent(q || "") + "&sortBy=sales";
}

const SEARCH_LINK_LABEL = "販売数順で見る";

const MARKET_SEARCH_HINT =
  'Shopee の検索（<b>販売数の多い順</b>で開きます。Shopeeには売却済みだけを見る検索がないので、'
+ '販売実績のある出品の価格帯を相場として読みます）';

const TRACK_SOURCE_LABEL = "Seller Centre の商品一覧から";

const TRACK_GUIDE_HTML =
    '<ol>'
  + '<li>Seller Centre → 商品管理 → 販売中 を開きます。</li>'
  + '<li>期間を決めて、閲覧数・いいね・販売数をエクスポートします。</li>'
  + '<li>次の形にして貼ってください：<code>sku,title,listed_on,observed_on,views,watchers,sold</code>'
  + '（<code>watchers</code> は Shopee の「いいね」を入れてください）。</li>'
  + '<li><b>毎週やってください。</b>2回目以降は前回との差が出ます。</li>'
  + '</ol>'
  + '<p><b>Shopee ではもう一つ見るものがあります。</b>③出す の「価格差の確認」に、'
  + '現在の売価と<b>いまの仕入値</b>を貼ってください。'
  + '仕入元が切れている行と、仕入値が上がって赤字になっている行を先頭に集めます。'
  + '無在庫では、これを毎週やらないとキャンセル率が上がってペナルティに直結します。</p>';

const SAMPLE_ROWS =
`sku,title_ja,cost_incl_tax_jpy,weight_g,length_cm,width_cm,height_cm,market_price_usd,competitor_count,has_demand_signal,demand_note,source_url
PEN-001,ボールペン 10本セット,900,220,18,10,4,12.80,4,yes,同種が販売数200超,
BATH-01,入浴剤 詰め合わせ 20個,1400,600,22,16,8,18.50,3,yes,日本製の入浴剤は定番,
SNK-001,抹茶キットカット 12袋,1100,480,20,14,8,15.20,12,yes,土産需要が安定,
FIG-002,限定フィギュア,4200,900,20,15,12,38.00,2,no,,
COS-001,日本製 フェイスマスク 30枚,1800,350,18,12,6,9.80,28,yes,競合多数,
KNF-001,関孫六 三徳包丁,4800,420,35,8,4,72.00,3,yes,日本製刃物は台湾で定番,
TEA-001,宇治抹茶 セット 缶入り,3200,600,20,16,10,48.00,5,yes,贈答需要が安定,`;

const SAMPLE_OBS =
`sku,title,listed_on,observed_on,views,watchers,sold
PEN-001,ボールペン 10本セット,2026-06-20,2026-08-17,320,12,3
PEN-001,ボールペン 10本セット,2026-06-20,2026-08-24,410,18,7
BATH-01,入浴剤 詰め合わせ,2026-07-10,2026-08-17,88,1,0
BATH-01,入浴剤 詰め合わせ,2026-07-10,2026-08-24,91,1,0
FIG-002,限定フィギュア,2026-05-01,2026-08-24,14,0,0`;

/* Shopee のプチプラ帯では、SLSの国内集荷料（1件800円前後）が原価の半分を
   占めることがある。ここを黙って「採算割れ」で並べると、実際には成立している
   商売まで捨てることになる。集荷料は規模で消えるので、そのことを言う。 */
function extraPickWarn(rows){
  const c = cfg();
  if (c.carrier === "flat") return "";
  let thinBySmallItem = 0;
  if (GRID){
    GRID.rows.forEach((r, i) => {
      const res = GRID.at(i);
      if (res.verdict !== "thin" || !res.ship) return;
      const price = (+r.market_price_usd || 0) * c.fx;
      if (price > 0 && res.ship / price > 0.25) thinBySmallItem++;
    });
  }
  if (!thinBySmallItem) return "";
  return '<div class="warn"><b>' + thinBySmallItem
    + '件は、国内集荷料が売価の4分の1を超えているために採算割れになっています。</b>'
    + 'SLS でセラーが払うのは集荷場所までの国内送料だけですが、1件ずつ出すと'
    + 'この費用がそのまま乗ります。<b>月100件規模で佐川急便の集荷、800件規模で'
    + 'SPSの国内集荷料が無料になるため、数が出ればこの費用自体が消えます。</b>'
    + 'その規模で計算し直すなら、設定の配送手段を「固定額を使う」にして、'
    + '実際に払っている1件あたりの額（無料なら0）を入れてください。</div>';
}

function onScreen(id){
  /* 隠れている間に描くと高さが 0 なので、表示された時点で描き直す。 */
  if (id === "pick" && GRID) GRID._paint();
  if (id === "list") renderSlots();
}

function applyAll(){
  saveCfg();
  renderSetbar();
  if (GRID){ GRID.cols = pickCols(); GRID.recalcAll(); renderPickWarn(GRID.rows); }
  renderSlots(); renderReprice();
  renderFindPlan();
}

document.addEventListener("DOMContentLoaded", function(){
  bootShell();
  /* Shopee では既定の配送手段を SLS にする。最安を自動にすると、
     実際には自分で選べない郵便の手段が最安として出てしまう。 */
  if (SETTINGS.carrier === "auto"){ SETTINGS.carrier = "sls"; fillSettingsForm(); }
  bootPick();
  bootFind((rows, append) => setRows(rows, append));
  bootListShopee();
  bootTrack();
  $("st-wipe").addEventListener("click", () => {
    if (!confirm("この端末に保存した商品・観測・設定を全部消します。よろしいですか？")) return;
    [CKEY, RKEY, TOOL_ID + ".obs", TOOL_ID + ".history", TOOL_ID + ".screen"]
      .forEach(k => { try{ localStorage.removeItem(k); }catch(e){} });
    location.reload();
  });
  renderSetbar();
});
