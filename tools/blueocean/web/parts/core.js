/* blueocean 計算コア。
   **このファイルが唯一の計算の出どころ。** eBay用ツールとShopee用ツールは
   どちらもここを取り込んでビルドされるので、2つの画面で数字がずれることがない。
   Python 側（blueocean/*.py）と同じ式で、tests/test_parity.py が突き合わせている。
   DOM には一切触らない。設定は呼び出し側が平のオブジェクトで渡す。 */


/* 数字の表示。core.js 内の判定文でも使うのでここに置く。 */
const yen = n => Math.round(n).toLocaleString("ja-JP");

/* ===== 市場ごとの手数料・関税・送料の既定値 ===== */
const PROFILES = {
  ebay_us:    {fee:.18, per:60, duty:.125, ship:3000, pack:200, label:"eBay 米国"},
  ebay_eu:    {fee:.18, per:60, duty:0,    ship:3000, pack:200, label:"eBay 欧州"},
  ebay_au:    {fee:.18, per:60, duty:0,    ship:3000, pack:200, label:"eBay 豪州"},
  /* Shopee：販売+決済は各国 5.3〜7.0%（VAT込み表示）。為替・送金を足して実効8%。
     出品ごとの固定費は無い。関税は原則購入者負担なので0。
     送料は**セラー負担ぶん（国内の集荷場所まで）だけ**。国際送料とラストマイルは
     SLSが処理するのでセラーの原価には乗らない。 */
  shopee_sea: {fee:.08, per:0,  duty:0,    ship:800,  pack:200, label:"Shopee 東南ア"},
  shopee_tw:  {fee:.08, per:0,  duty:0,    ship:800,  pack:200, label:"Shopee 台湾"},
  shopee_sg:  {fee:.08, per:0,  duty:0,    ship:800,  pack:200, label:"Shopee シンガポール"},
  shopee_my:  {fee:.08, per:0,  duty:0,    ship:800,  pack:200, label:"Shopee マレーシア"},
  shopee_ph:  {fee:.08, per:0,  duty:0,    ship:800,  pack:200, label:"Shopee フィリピン"},
};
const IS_SHOPEE = m => String(m).startsWith("shopee");
const LEVEL_ADJ = {top_rated:-.02, above_standard:0, below_standard:.06};

/* ===== CSV ===== */
function parseCsv(text){
  const lines = text.trim().split(/\r?\n/).filter(l => l.trim() !== "");
  if (!lines.length) return [];
  const head = lines[0].split(",").map(s => s.trim());
  return lines.slice(1).map(line => {
    const cells = line.split(",");
    const o = {};
    head.forEach((h,i) => o[h] = (cells[i] ?? "").trim());
    return o;
  });
}
const truthy = v => ["1","true","yes","y"].includes(String(v||"").toLowerCase());



/* ===== 抽出条件の組み立て =====
   抽出そのものは eBay のAPIが要るのでこのページではできない。
   だが**条件を決めるのは人の仕事**で、そこはここでできる。
   決めた条件を jobs.json とコマンドの形で出し、Python版にそのまま渡す。 */

/* ===== 送料エンジン（shipping.py と同一） ===== */
const ZONE_OF   = {ebay_us:"zone4", ebay_eu:"zone3", ebay_au:"zone3",
                   shopee_sea:"zone2", shopee_tw:"zone1", shopee_sg:"zone2",
                   shopee_my:"zone2", shopee_ph:"zone2"};
const ZONE_NAME = {zone1:"第1地帯（中国・韓国・台湾）", zone2:"第2地帯（アジア）",
                   zone3:"第3地帯（欧州・豪州・北米※米国除く）", zone4:"第4地帯（米国）"};
const VDIV    = {ems:null, parcel:6000, epacket:null, courier:5000, sls:6000};  /* null = 容積重量を採らない */
const WMAX    = {ems:30000, parcel:30000, epacket:2000, courier:30000, sls:30000};
const DMAX    = {ems:[150,300,null], parcel:[150,300,null], epacket:[60,null,90],
                 courier:[274,330,null], sls:[150,300,null]};
/* SLS は郵便の何割、という話ではない（_DOMESTIC_SIZE を使う）。形を揃えるためだけの値。 */
const CFACTOR = {ems:1.00, parcel:0.80, epacket:0.55, courier:1.35, sls:1.00};
/* SLSでセラーが負担するのは「国内送料（集荷場所まで）」だけ。国際送料とラストマイルは
   SLSが処理し、関税・通関は原則購入者負担。eBay（DDPで関税も国際送料もセラー負担）とは
   負担の構造が逆で、ここを取り違えるとプチプラ商品がすべて赤字に見える。
   国内宅配便は重量ではなく三辺計のサイズ区分で決まる。 */
const DOMESTIC_SIZE = [[60,800],[80,1000],[100,1250],[120,1500],[140,1750],[160,2000]];
function domesticLegJpy(p){
  if (p.g > 25000) return null;
  const total = (p.l>0 && p.w>0 && p.h>0) ? (p.l+p.w+p.h) : 60;
  for (const [lim, jpy] of DOMESTIC_SIZE) if (total <= lim) return jpy;
  return null;
}
const CLABEL  = {ems:"EMS", parcel:"国際小包", epacket:"eパケット",
                 courier:"UGX / FedEx / DHL", sls:"SLS（Shopee配送）"};
const CARRIERS = ["ems","parcel","epacket","courier","sls"];
const SLS_NOTICE = "SLSでセラーが負担するのは<b>国内送料（集荷場所まで）だけ</b>です。国際送料とラストマイル配送はSLSが処理し、関税・通関手数料は原則購入者負担。<b>eBay（DDPで関税も国際送料もセラー負担）とは負担の構造が逆</b>になります。国内送料は三辺計のサイズ区分で決まる概算で、月100件規模から佐川急便の集荷、800件規模でSPSの国内集荷料が無料になるため、数が出れば<b>この費用自体が消えます</b>。";
/* SLSはShopeeに出品して初めて使える。一般の比較に混ぜると「選べない手段が最安」になる。 */
const POSTAL_CARRIERS = ["ems","parcel","epacket","courier"];

/* アンカー＝公表値として確認できた金額。その間は刻み幅から内挿する。
   内挿値は必ず「推定」と表示し、事実として一人歩きさせない。 */
function buildSteps(anchors, stepG, uptoG, inc){
  const known = Object.keys(anchors).map(Number).sort((a,b)=>a-b);
  const out = [];
  let lastW = known[0], lastJ = anchors[known[0]];
  for (let w = known[0]; w <= uptoG; w += stepG){
    if (anchors[w] !== undefined){ lastW = w; lastJ = anchors[w]; out.push({w, jpy:anchors[w], anchor:true}); }
    else out.push({w, jpy: Math.round(lastJ + inc*((w-lastW)/stepG)), anchor:false});
  }
  return out;
}
function emsTable(anchors, inc100, inc250){
  const fine = buildSteps(anchors, 100, 1000, inc100);
  const coarse = buildSteps({1000: fine[fine.length-1].jpy}, 250, 5000, inc250).slice(1)
                 .map(b => ({...b, anchor:false}));
  return fine.concat(coarse);
}
const EMS_TABLE = {
  /* 第1地帯（中国・韓国・台湾）。第2地帯の刻みから比例で置いた推定値。 */
  zone1: emsTable({500:1900}, 220, 180),
  zone2: emsTable({500:2150,600:2400,700:2650,800:2900,900:3150}, 250, 200),
  zone3: emsTable({500:3400,600:3650,700:3900,800:4150,900:4400}, 250, 310),
  zone4: emsTable({500:4180,600:4460,700:4740,800:5020},          280, 350),
};

function volWeight(p, carrier){
  const d = VDIV[carrier];
  if (d === null || !(p.l>0 && p.w>0 && p.h>0)) return 0;
  return Math.ceil(p.l*p.w*p.h/d*1000);
}
function chargeable(p, carrier){ return Math.max(p.g, volWeight(p, carrier)); }

function overSize(p, carrier){
  if (!(p.l>0 && p.w>0 && p.h>0)) return null;   /* 未入力は検査できない */
  const [longest, girth, total] = DMAX[carrier];
  const dims = [p.l,p.w,p.h].sort((a,b)=>b-a);
  const g = dims[0] + 2*(dims[1]+dims[2]);
  if (longest !== null && dims[0] > longest) return `最長辺 ${dims[0]}cm が上限 ${longest}cm を超過`;
  if (girth   !== null && g > girth)         return `長さ+胴回り ${Math.round(g)}cm が上限 ${girth}cm を超過`;
  if (total   !== null && p.l+p.w+p.h > total) return `三辺計 ${Math.round(p.l+p.w+p.h)}cm が上限 ${total}cm を超過`;
  return null;
}

const US_NOTICE = "米国宛て：2025年8月のデミニミス（$800免税）撤廃を受け、日本郵便は物品を含む小形包装物・国際小包・EMS(物品)の引受を一時停止しました。2026年4月14日以降、米国税関が認証した事業者のアプリで関税を事前納付すれば指定郵便局で引受再開。その手当てが済むまで、米国宛ては UGX / FedEx / DHL で見積もってください。";

/* 1手段の見積もり。使えない場合は {error} を返す。 */
function quoteOne(p, zone, carrier){
  if (carrier === "sls"){
    const jpy = domesticLegJpy(p);
    if (jpy === null) return {error:"SLS：三辺計または重量が国内宅配便の範囲外"};
    const warnings = [SLS_NOTICE];
    if (!(p.l>0 && p.w>0 && p.h>0))
      warnings.unshift("寸法が未入力のため60サイズとみなしています。国内送料はサイズ区分で決まるので実寸を入れてください");
    return {carrier, zone, jpy, actual:p.g, vol:0, chg:p.g,
            estimated:true, warnings, byVolume:false};
  }
  const table = EMS_TABLE[zone];
  if (!table) return {error:`${zone} の料金表が未登録`};
  const os = overSize(p, carrier);
  if (os) return {error:`${CLABEL[carrier]}：${os}`};
  const chg = chargeable(p, carrier);
  if (chg > WMAX[carrier]) return {error:`${CLABEL[carrier]}：課金重量 ${chg}g が上限 ${WMAX[carrier]}g を超過`};
  const step = table.find(b => chg <= b.w);
  if (!step) return {error:`料金表の上限 ${table[table.length-1].w}g を超過（課金重量 ${chg}g）`};

  const warnings = [];
  if (!(p.l>0 && p.w>0 && p.h>0) && VDIV[carrier] !== null)
    warnings.push("寸法が未入力のため容積重量を評価していません。嵩張る商品では実際の送料が上振れします");
  if (zone === "zone4" && carrier !== "courier") warnings.push(US_NOTICE);
  const estimated = !step.anchor || CFACTOR[carrier] !== 1;
  if (estimated) warnings.push("料金は内挿による推定値です。公式料金表で確認してから仕入判断に使ってください");

  return {carrier, zone, jpy: Math.round(step.jpy*CFACTOR[carrier]),
          actual:p.g, vol:volWeight(p,carrier), chg, estimated, warnings,
          byVolume: volWeight(p,carrier) > p.g};
}
function quoteAll(p, zone, pool){
  return (pool || POSTAL_CARRIERS).map(c => quoteOne(p, zone, c))
    .filter(q => !q.error).sort((a,b)=>a.jpy-b.jpy);
}
/* Shopeeのときだけ SLS を候補に含める */
const carrierPool = market => IS_SHOPEE(market) ? POSTAL_CARRIERS.concat("sls") : POSTAL_CARRIERS;
function cheapestQuote(p, zone, pool){ const q = quoteAll(p, zone, pool); return q.length ? q[0] : null; }
function parcelOf(g,l,w,h){ return {g:+g||0, l:+l||0, w:+w||0, h:+h||0}; }

/* ===== 利益計算（profit.py と同一） ===== */
function effFee(c){ return Math.max(0, c.fee + LEVEL_ADJ[c.level]); }

function compute(priceUsd, costJpy, c){
  const price = priceUsd * c.fx;
  const fees  = price * effFee(c) + c.per;
  const duty  = price * c.duty;
  const refund = c.taxable ? costJpy * 0.10 / 1.10 : 0;
  const profit = price - fees - duty - c.ship - c.pack - costJpy + refund;
  return {price, fees, duty, ship:c.ship, pack:c.pack, cost:costJpy, refund, profit,
          margin: price ? profit/price : 0};
}
function maxCost(priceUsd, c, target){
  const t = target === undefined ? c.target : target;
  const price = priceUsd * c.fx;
  const fees  = price * effFee(c) + c.per;
  const duty  = price * c.duty;
  const k = c.taxable ? 0.10/1.10 : 0;
  return Math.max(0, (price*(1-t) - fees - duty - c.ship - c.pack) / (1-k));
}
function reqMultiple(priceUsd, c, target){
  const cap = maxCost(priceUsd, c, target);
  return cap <= 0 ? Infinity : (priceUsd*c.fx)/cap;
}


/* ===== 荷物から送料を決める ===== */
/* 荷物が入力されていれば、固定値ではなく実際の課金重量から送料を出す。
   ここが「固定送料」との分かれ目。返り値は {ship, quote} 。 */
function shipFor(c, parcel){
  /* 「固定額」を選んだときは料金表を引かない。Python の --flat-shipping と同じ。
     SLSの国内集荷料のように、規模で実額が変わる費用を自分で入れるための口。 */
  if (c.carrier === "flat") return {ship:c.ship, quote:null};
  if (!c.autoShip || !parcel || parcel.g <= 0) return {ship:c.ship, quote:null};
  const qs = quoteAll(parcel, c.zone, carrierPool(c.market));
  if (!qs.length) return {ship:null, quote:null};   /* 使える手段が無い */
  /* Shopeeの越境では自分で国際発送しない。「最安を自動」でも SLS に寄せる。
     ここを最安のままにすると、実際には選べない手段で採算を出してしまう。 */
  const want = c.carrier !== "auto" ? c.carrier : (IS_SHOPEE(c.market) ? "sls" : null);
  const q = want ? (qs.find(x => x.carrier === want) || null) : qs[0];
  return q ? {ship:q.jpy, quote:q} : {ship:null, quote:null};
}

/* ===== 軸1の判定（scoring.py と同一） ===== */
/* ===== 軸1（scoring.py と同一） ===== */
/* eBayの主戦場は $200 前後の中古・コレクター品なので「$30未満は手数料と送料に食われる」
   で正しい。だがShopeeの主戦場はプチプラの新品消耗品なので、$30の下限を当てると
   売れ筋がほぼ全部落ちる。市場で下限を変える。 */
const POLICY = {blueMax:5, redMin:30, maxWeight:2000, minPrice:30};
const minPriceFor = m => IS_SHOPEE(m) ? 8 : 30;
/* 判定の呼び名（画面に出す言葉）は UI 側（pick.js）が持つ。
   ここは計算だけを持つ。 */

function flipHint(verdict, n, demand, costRoom, floorPrice){
  if (verdict === "blue"){
    const p = [];
    if (n !== null && n !== undefined) p.push(`競合があと${POLICY.redMin - n}件増えると見送り`);
    if (floorPrice) p.push(`相場が $${floorPrice.toFixed(0)} まで下がると採算割れ`);
    return p.join("／") || "余裕あり";
  }
  if (verdict === "thin")
    return `仕入をあと ${yen(Math.abs(costRoom))}円 下げれば採算に乗る`
         + (floorPrice ? `／相場が $${floorPrice.toFixed(0)} 以上に戻っても同じ` : "");
  if (verdict === "red")
    return `競合が ${POLICY.redMin - 1}件以下に減れば再評価。ただし競合数は自分では動かせない`;
  if (verdict === "probe"){
    if (!demand) return "需要の裏付けが取れれば BLUE。少量で出して軸2で確かめる";
    if (n !== null && n !== undefined && n > POLICY.blueMax)
      return `競合が ${POLICY.blueMax}件以下に減れば BLUE`;
    return "需要が確定すれば BLUE";
  }
  return "";
}

function scoreOne(r, c){
  const reasons = [];
  const out = v => ({verdict:v, score:0, reasons, row:r, profit:null, cap:0,
                     ship:null, quote:null, chg:0});

  if (truthy(r.is_restricted)) { reasons.push("除外：" + (r.restricted_reason || "輸出規制・禁止品")); return out("excl"); }

  // 重量の判定は「課金重量」で行う。実重量が軽くても嵩張れば送料は容積で決まる。
  const parcel = parcelOf(r.weight_g, r.length_cm, r.width_cm, r.height_cm);
  const w = parcel.g;
  const chg = chargeable(parcel, c.carrier === "auto" ? "parcel" : c.carrier);
  if (chg > POLICY.maxWeight) {
    reasons.push(chg > w
      ? `除外：容積重量 ${chg}g（実重量 ${w}g）が上限 ${POLICY.maxWeight}g を超過。軽いが嵩張るため送料で採算が崩れる`
      : `除外：重量 ${w}g が上限 ${POLICY.maxWeight}g を超過`);
    return out("excl");
  }
  const price = r.market_price_usd === "" ? null : +r.market_price_usd;
  if (price === null || !isFinite(price) || price <= 0) { reasons.push("除外：eBay側の相場が未入力"); return out("excl"); }
  const floorUsd = minPriceFor(c.market);
  if (price < floorUsd) { reasons.push(`除外：想定売価 $${price} が下限 $${floorUsd} 未満`); return out("excl"); }

  // 送料を先に確定する。送料が決まらないと採算は出せない。
  const sf = shipFor(c, parcel);
  if (sf.ship === null) {
    reasons.push("除外：この重量・寸法で使える配送手段が無い（重量／寸法の上限超過）");
    return out("excl");
  }
  const cc = {...c, ship: sf.ship};
  if (sf.quote) {
    reasons.push(`送料 ${yen(sf.quote.jpy)}円（${CLABEL[sf.quote.carrier]} / 課金重量 ${sf.quote.chg}g）`);
    if (sf.quote.byVolume)
      reasons.push(`送料は容積重量 ${sf.quote.chg}g で課金される（実重量 ${sf.quote.actual}g）。梱包を薄くすると直接効く`);
    if (!(parcel.l>0 && parcel.w>0 && parcel.h>0))
      reasons.push("寸法が未入力のため送料は実重量ベースの下振れ値");
  }

  const cost = +r.cost_incl_tax_jpy || 0;
  const cap = maxCost(price, cc);
  const profit = compute(price, cost, cc);

  /* 走査の雛形は仕入値が空。0を「タダで買える」と解釈すると必ずBLUEになる */
  const costUnknown = cost <= 0;
  if (costUnknown) reasons.push("仕入値が未入力。判定は相場と競合だけに基づく暫定値");
  if (cost > cap && !costUnknown){
    reasons.push(`採算割れ：仕入 ${yen(cost)}円 が上限 ${yen(cap)}円 を ${yen(cost-cap)}円 超過`
      + `（実績利益率 ${(profit.margin*100).toFixed(1)}%）`);
    const fp = listPriceForMargin(cost, c.target, cc, cc.ship);
    return {verdict:"thin", score:0, reasons, row:r, profit, cap,
            ship:sf.ship, quote:sf.quote, chg,
            /* THIN の文言は競合・需要を使わない（採算だけで決まる） */
            flip: flipHint("thin", null, false, cap - cost, isFinite(fp) ? fp : null)};
  }

  const nRaw = r.competitor_count;
  const n = nRaw === "" || nRaw === undefined ? null : +nRaw;
  const demand = truthy(r.has_demand_signal);
  let verdict;

  if (n === null){ reasons.push("競合数が未入力のため PROBE に分類"); verdict = "probe"; }
  else if (n >= POLICY.redMin){
    reasons.push(`競合 ${n}件。価格競争に巻き込まれるため見送り`);
    return {verdict:"red", score:0, reasons, row:r, profit, cap,
            ship:sf.ship, quote:sf.quote, chg,
            flip: flipHint("red", n, demand, cap - cost, null)};
  }
  else if (n === 0 && !demand){
    reasons.push("競合0件だが需要の裏付けが無い。少量で反応を試す（軸2へ）");
    verdict = "probe";
  }
  else if (n <= POLICY.blueMax){
    reasons.push(`競合 ${n}件。値下げ圧力を受けにくい`);
    verdict = demand ? "blue" : "probe";
    if (!demand) reasons.push("需要の裏付けが無いため PROBE に据え置き");
  }
  else { reasons.push(`競合 ${n}件。ブルーではないが致命的でもない`); verdict = "probe"; }

  /* 仕入値が未確定なら BLUE と言い切らない */
  if (costUnknown && verdict === "blue") verdict = "probe";

  /* 国内APIは重量を返さないので、商品名やカテゴリから当てて埋まっていることがある。
     推定重量のまま BLUE を出すと、実物が届いて送料が倍になった時点で崩れる。
     scoring.py の同じ規則と揃えてある。 */
  if (truthy(r.weight_is_estimate) || truthy(r.cost_is_estimate)){
    const what = [truthy(r.weight_is_estimate) ? "重量" : "",
                  truthy(r.cost_is_estimate) ? "仕入値" : ""].filter(Boolean).join("・");
    reasons.push(what + "が推定値"
      + (r.estimate_note ? `（${r.estimate_note}）` : "")
      + "。実測に置き換えるまで BLUE には上げない");
    if (verdict === "blue") verdict = "probe";
  }
  if (w <= 0) reasons.push("重量が未入力。送料は最小重量帯の概算");
  if (demand && r.demand_note) reasons.push("需要の裏付け：" + r.demand_note);

  /* 何がこの判定を分けているか（scoring.py の _flip_hint と同一）。
     判定を動かす変数は3つしかない：仕入値・競合数・相場。
     このうち自分で動かせるのは仕入値だけなので、そこを優先して書く。 */
  const floorPrice = listPriceForMargin(cost, c.target, cc, cc.ship);
  const flip = flipHint(verdict, n, demand, cap - cost, isFinite(floorPrice) ? floorPrice : null);

  const score = Math.max(0,
      Math.min(profit.margin / (c.target || .2), 2) * 50
    + 50 / (1 + (n || 0))
    + (demand ? 20 : 0)
    - (chg / POLICY.maxWeight) * 10);

  return {verdict, score:Math.round(score*10)/10, reasons, row:r, profit, cap, flip,
          ship:sf.ship, quote:sf.quote, chg};
}

/* ===== 履歴の差分（history.py と同一） ===== */
const HKEY = (typeof TOOL_ID !== "undefined" ? TOOL_ID : "blueocean") + ".history";
const RANK = {blue:4, probe:3, thin:2, red:1, excl:0};
const DIFF = {compAbs:5, compRatio:.5, priceRatio:.10, staleDays:7};
const CHANGE = {
  downgrade:{cls:"red",  label:"判定悪化", act:"出品中なら価格と在庫を見直す。未出品なら見送りに回す"},
  breach:   {cls:"red",  label:"採算割れ", act:"相場・為替・送料のどれかが動いた。仕入値を下げられないなら見送る"},
  upgrade:  {cls:"good", label:"判定改善", act:"見送っていた候補が買えるようになった。仕入を再検討する"},
  room:     {cls:"good", label:"採算回復", act:"採算が戻った。まだ在庫があるうちに動く"},
  comp:     {cls:"probe",label:"競合変動", act:""},
  price:    {cls:"probe",label:"相場変動", act:"出品中なら価格を追随させる"},
  fresh:    {cls:"dim",  label:"新規追加", act:"初回なので、この判定がそのまま出発点になる"},
  gone:     {cls:"dim",  label:"候補消滅", act:"売れた・取り下げたなら正常。消し忘れなら候補CSVを確認する"},
};
const CH_ORDER = ["downgrade","breach","upgrade","room","comp","price","fresh","gone"];
const ACTIONABLE = new Set(["downgrade","breach","upgrade","room"]);

function todayISO(){ const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset()*60000).toISOString().slice(0,10); }

function snapshotOf(res){
  return {takenOn: todayISO(), rows: res.map(r => ({
    sku: r.row.sku || r.row.title_ja || "", title: r.row.title_ja || r.row.sku || "",
    verdict: r.verdict, comp: r.row.competitor_count === "" ? null : +r.row.competitor_count,
    price: r.row.market_price_usd === "" ? null : +r.row.market_price_usd,
    cost: +r.row.cost_incl_tax_jpy || 0, cap: Math.round(r.cap),
  }))};
}
const pct = (a,b) => a === 0 ? "—" : `${(b-a)/a*100 > 0 ? "+" : ""}${((b-a)/a*100).toFixed(0)}%`;

function diffSnapshots(prev, cur){
  const before = new Map((prev?.rows || []).map(r => [r.sku, r]));
  const out = [], seen = new Set();
  for (const c of cur.rows){
    seen.add(c.sku);
    const p = before.get(c.sku);
    if (!p){ out.push({kind:"fresh", sku:c.sku, title:c.title, detail:`新規候補。判定 ${c.verdict.toUpperCase()}`}); continue; }

    const pr = RANK[p.verdict] ?? 0, cr = RANK[c.verdict] ?? 0;
    if (cr < pr) out.push({kind:"downgrade", sku:c.sku, title:c.title,
      detail:`${p.verdict.toUpperCase()} → ${c.verdict.toUpperCase()}（${prev.takenOn} → ${cur.takenOn}）`});
    else if (cr > pr) out.push({kind:"upgrade", sku:c.sku, title:c.title,
      detail:`${p.verdict.toUpperCase()} → ${c.verdict.toUpperCase()}`});

    /* 判定が変わらなくても採算は動く。仕入上限との関係を別に見る */
    const wasOk = p.cost <= p.cap, nowOk = c.cost <= c.cap;
    if (wasOk && !nowOk) out.push({kind:"breach", sku:c.sku, title:c.title,
      detail:`仕入上限 ${yen(p.cap)}円 → ${yen(c.cap)}円。仕入 ${yen(c.cost)}円 が上限を超えた`});
    else if (!wasOk && nowOk) out.push({kind:"room", sku:c.sku, title:c.title,
      detail:`仕入上限 ${yen(p.cap)}円 → ${yen(c.cap)}円。仕入 ${yen(c.cost)}円 が上限内に戻った`});

    if (p.comp !== null && c.comp !== null && p.comp !== c.comp){
      const moved = Math.abs(c.comp-p.comp) >= DIFF.compAbs || (p.comp > 0 && Math.abs(c.comp-p.comp)/p.comp >= DIFF.compRatio);
      if (moved) out.push({kind:"comp", sku:c.sku, title:c.title,
        detail:`競合 ${p.comp}件 → ${c.comp}件（${pct(p.comp,c.comp)}）`,
        act: c.comp > p.comp ? "増えているなら早く出す。値下げ競争が始まる前が勝負" : "減っている。出し直す価値がある"});
    }
    if (p.price && c.price && Math.abs(c.price-p.price)/p.price >= DIFF.priceRatio)
      out.push({kind:"price", sku:c.sku, title:c.title,
        detail:`相場 $${p.price.toFixed(0)} → $${c.price.toFixed(0)}（${pct(p.price,c.price)}）`});
  }
  for (const [sku,p] of before)
    if (!seen.has(sku)) out.push({kind:"gone", sku, title:p.title,
      detail:`今回の候補リストに無い（前回 ${prev.takenOn} は ${p.verdict.toUpperCase()}）`});

  return out.sort((a,b) => CH_ORDER.indexOf(a.kind)-CH_ORDER.indexOf(b.kind) || a.sku.localeCompare(b.sku));
}

function daysBetween(aISO, bISO){ return Math.round((new Date(bISO) - new Date(aISO))/86400000); }

/* 販売先の検索URLは市場ごとに違うので、ツール側（boot-*.js）が持つ。 */

/* ===== 値決め（pricing.py と同一） ===== */
function fixedCosts(cost, c, ship){
  const k = c.taxable ? 0.10/1.10 : 0;
  return c.per + ship + c.pack + cost * (1 - k);
}
function varRate(c){ return effFee(c) + c.duty; }

/* P(1 − f − d − m) = Fo + S + K + C(1 − k) */
function listPriceForMargin(cost, margin, c, ship){
  const denom = 1 - varRate(c) - margin;
  if (denom <= 0) return Infinity;
  return fixedCosts(cost, c, ship) / denom / c.fx;
}
function breakevenFx(priceUsd, cost, c, ship){
  const denom = 1 - varRate(c);
  if (priceUsd <= 0 || denom <= 0) return Infinity;
  return fixedCosts(cost, c, ship) / denom / priceUsd;
}
function breakevenDuty(priceUsd, cost, c, ship){
  const pj = priceUsd * c.fx;
  if (pj <= 0) return 0;
  return Math.max(0, (pj * (1 - effFee(c)) - fixedCosts(cost, c, ship)) / pj);
}
/* (1−r)·利益 − r·損失 = 0 → r = 利益 /(利益 + 損失) */
function returnImpact(priceUsd, cost, c, ship, opt){
  const b = compute(priceUsd, cost, {...c, ship});
  let loss = b.ship + c.pack + c.per;
  if (opt.sellerPays) loss += b.ship;          /* 返送料は往路と同額とみなす */
  if (!opt.recovered) loss += cost - b.refund;
  const profit = b.profit;
  const rate = profit > 0 ? profit / (profit + loss) : 0;
  return {profit, loss, rate, oneIn: rate > 0 ? 1/rate : Infinity,
          fragile: profit > 0 && loss > profit * 2, recovered: opt.recovered};
}


/* ===== セット販売（bundle.py と同一） ===== */
function bundleShip(parcel, c){
  const qs = quoteAll(parcel, c.zone, carrierPool(c.market));
  if (!qs.length) return {jpy: c.ship, quotable: false, chg: parcel.g, byVol: false};
  const q = c.carrier === "auto" ? qs[0] : (qs.find(x => x.carrier === c.carrier) || qs[0]);
  return {jpy: q.jpy, quotable: true, chg: q.chg, byVol: q.byVolume};
}

function sellSeparately(items, c){
  let rev=0, fees=0, duty=0, ship=0, pack=0, refund=0, profit=0, orders=0, dead=0;
  const unsold = [];
  for (const it of items){
    if (!(it.solo > 0)){ unsold.push(it.name); dead += it.cost; continue; }
    const s = bundleShip(parcelOf(it.g, it.l, it.w, it.h), c);
    const b = compute(it.solo, it.cost, {...c, ship: s.jpy});
    orders++; rev+=b.price; fees+=b.fees; duty+=b.duty; ship+=b.ship;
    pack+=b.pack; refund+=b.refund; profit+=b.profit;
  }
  const cost = items.reduce((a,i)=>a+i.cost, 0);
  /* 売れ残りの原価を引く。ここを引かないとセットとの比較が成立しない */
  return {label:"個別に売る", orders, rev, fees, duty, ship, pack, cost, refund,
          profit: profit - dead, unsold,
          margin: rev ? (profit - dead)/rev : 0};
}

function sellAsBundle(items, setPrice, packParcel, c){
  const s = bundleShip(packParcel, c);
  const cost = items.reduce((a,i)=>a+i.cost, 0);
  const b = compute(setPrice, cost, {...c, ship: s.jpy});
  return {label:"セットで売る", orders:1, rev:b.price, fees:b.fees, duty:b.duty,
          ship:b.ship, pack:b.pack, cost:b.cost, refund:b.refund, profit:b.profit,
          unsold:[], margin:b.margin, quotable:s.quotable, chg:s.chg, byVol:s.byVol};
}

/* 個別売却と同じ利益を出すのに必要なセット売価。
   P = (G + c + S + K + C − C·k) / (1 − f − d) */
function breakevenSetPrice(items, packParcel, c){
  const target = sellSeparately(items, c).profit;
  const s = bundleShip(packParcel, c);
  const cost = items.reduce((a,i)=>a+i.cost, 0);
  const k = c.taxable ? 0.10/1.10 : 0;
  const denom = 1 - effFee(c) - c.duty;
  if (denom <= 0) return Infinity;
  return Math.max(0, (target + c.per + s.jpy + c.pack + cost - cost*k) / denom / c.fx);
}

/* 表を作り直さずに判定セルだけ更新する（入力中のフォーカスを守る） */

/* ===== eBayレポートの取り込み（ingest.py と同一） ===== */
const ING_ALIAS = {
  sku:      ["customlabel","customlabelsku","sku"],
  item_id:  ["itemnumber","itemid","item"],
  title:    ["title","itemtitle"],
  listed_on:["startdate","starttime","startdatetime","listeddate"],
  views:    ["views","viewcount","pageviews"],
  watchers: ["watchers","watchcount"],
  sold:     ["soldquantity","quantitysold","sold","totalsold"],
};
const MONTHS = {jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
const ingNorm = s => String(s||"").trim().toLowerCase().replace(/[^a-z0-9]/g,"");

function ingPick(row, key){
  const normed = {};
  for (const k in row) if (k) normed[ingNorm(k)] = row[k];
  for (const a of ING_ALIAS[key]) if (normed[a] !== undefined && String(normed[a]).trim())
    return String(normed[a]).trim();
  return "";
}
/* Aug-23-2026 10:12:33 PDT / 2026-08-23 / 08/23/2026 を吸収する */
function ingDate(text){
  const head = String(text||"").trim().split(/\s+/)[0].replace(/,$/,"");
  if (!head) return null;
  let m = head.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if (m) return `${m[1]}-${String(m[2]).padStart(2,"0")}-${String(m[3]).padStart(2,"0")}`;
  m = head.match(/^([A-Za-z]{3})[-\s](\d{1,2})[-,\s]+(\d{4})$/);
  if (m && MONTHS[m[1].toLowerCase()])
    return `${m[3]}-${String(MONTHS[m[1].toLowerCase()]).padStart(2,"0")}-${String(m[2]).padStart(2,"0")}`;
  m = head.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
  if (m) return `${m[3]}-${String(m[1]).padStart(2,"0")}-${String(m[2]).padStart(2,"0")}`;
  return null;
}
const ingInt = t => { const n = parseFloat(String(t||"").replace(/,/g,"")); return isFinite(n) ? Math.trunc(n) : 0; };

/* 貼られたテキストがeBayのレポートかどうかを見分ける */
function looksLikeEbayReport(text){
  const head = (text.split(/\r?\n/).slice(0,12).join(",")).toLowerCase();
  const cells = head.split(",").map(ingNorm);
  return cells.includes("itemnumber") ||
    (cells.includes("customlabel") && (cells.includes("watchers") || cells.includes("views")));
}
function ingestEbayReport(text, observedOn){
  const lines = text.split(/\r?\n/);
  let start = 0;
  for (let i = 0; i < Math.min(12, lines.length); i++){
    const cells = lines[i].split(",").map(ingNorm);
    if (cells.includes("itemnumber") || cells.includes("title")){ start = i; break; }
  }
  const rows = parseCsv(lines.slice(start).join("\n"));
  const header = rows.length ? Object.keys(rows[0]).map(ingNorm) : [];
  const missing = [["views","Views"],["watchers","Watchers"],["sold","Sold quantity"],
                   ["listed_on","Start date"]]
    .filter(([k]) => header.length && !ING_ALIAS[k].some(a => header.includes(a)))
    .map(([,label]) => label);

  const out = []; let noSku = 0, noDate = 0;
  for (const r of rows){
    const sku = ingPick(r,"sku") || ingPick(r,"item_id");
    if (!sku){ noSku++; continue; }
    const listed = ingDate(ingPick(r,"listed_on"));
    if (!listed){ noDate++; continue; }
    out.push({sku, title: ingPick(r,"title"), listed_on: listed, observed_on: observedOn,
              views: String(ingInt(ingPick(r,"views"))),
              watchers: String(ingInt(ingPick(r,"watchers"))),
              sold: String(ingInt(ingPick(r,"sold")))});
  }
  return {rows: out, noSku, noDate, missing};
}
/* 同じSKU・同じ観測日は上書きし、それ以外は足す（取り直しても二重にならない） */
function mergeObsRows(existing, fresh){
  const key = o => o.sku + "|" + o.observed_on;
  const map = new Map(existing.map(o => [key(o), o]));
  fresh.forEach(o => map.set(key(o), o));
  return [...map.values()].sort((a,b) =>
    a.observed_on.localeCompare(b.observed_on) || a.sku.localeCompare(b.sku));
}
const OBS_COLS = ["sku","title","listed_on","observed_on","views","watchers","sold"];
/* 観測はこの端末に貯める。毎週レポートを貼るだけで前回比が出るようにするため、
   貼られたレポートで上書きせず、貯めてある行に足す。 */
/* 保存先はツールごとに分ける。eBayの観測とShopeeの観測が混ざると
   「先週から売れていない」の判断が壊れる。 */
const OBSKEY = (typeof TOOL_ID !== "undefined" ? TOOL_ID : "blueocean") + ".obs";
function loadObs(){
  try{ const a = JSON.parse(localStorage.getItem(OBSKEY) || "[]"); return Array.isArray(a) ? a : []; }
  catch(e){ return []; }
}
function saveObs(rows){
  try{ localStorage.setItem(OBSKEY, JSON.stringify(rows)); return true; }catch(e){ return false; }
}
function obsRowsToCsv(rows){
  const e = v => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g,'""')}"` : String(v ?? "");
  return [OBS_COLS.join(",")].concat(rows.map(r => OBS_COLS.map(k => e(r[k])).join(","))).join("\n");
}

/* ===== 軸2の判定（promotion.py と同一） ===== */

/* ===== 軸2（promotion.py と同一） ===== */
const ACT = {
  promote:{cls:"good", label:"PROMOTE", desc:"有在庫化する"},
  reprice:{cls:"probe",label:"REPRICE", desc:"価格を見直す"},
  retitle:{cls:"probe",label:"RETITLE", desc:"検索語を直す"},
  drop:{cls:"red",     label:"DROP",    desc:"出品を畳む"},
  keep:{cls:"dim",     label:"KEEP",    desc:"観察継続"},
};
const P2 = {promoteSold:1, promoteWatch:3, watchWindow:14, repriceViews:50,
            retitleDays:30, retitleViews:10, dropDays:90};

function decide(o){
  const d = o.days, mk = (a,r) => ({action:a, reason:r, o});
  if (o.sold >= P2.promoteSold)
    return mk("promote", `${o.sold}件 販売済み。需要が確定したので有在庫化し、ハンドリングを1〜2日に短縮する`);
  if (o.watchers >= P2.promoteWatch && d <= P2.watchWindow)
    return mk("promote", `${d}日で ウォッチ${o.watchers}件。購入意欲のある層が付いている`);
  if (o.views >= P2.repriceViews && o.watchers === 0)
    return mk("reprice", `閲覧${o.views}件に対しウォッチ0。露出はあるので価格が原因`);
  if (d >= P2.retitleDays && o.views < P2.retitleViews)
    return mk("retitle", `${d}日で閲覧${o.views}件。露出不足。海外バイヤーが実際に打つ語彙にタイトルを組み直す`);
  if (d >= P2.dropDays && o.sold === 0 && o.watchers === 0)
    return mk("drop", `${d}日間 無反応。出品を終了して枠を空ける`);
  return mk("keep", `観察継続（${d}日目）`);
}


/* ===== HTMLエスケープ ===== */
function esc(s){ return String(s).replace(/[&<>"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch])); }
