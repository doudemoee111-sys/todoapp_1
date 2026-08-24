/* ③出す（Shopee）。shopee.py と同じ枠・価格改定の規則。 */

/* 台湾だけ新規枠が半分。日本製の主戦場なのに最も枠が狭い。 */
const SHOP_LIMITS = {
  shopee_tw:  {new:500,  preferred:10000, max:20000, preorder:100},
  shopee_sg:  {new:1000, preferred:10000, max:20000, preorder:100},
  shopee_my:  {new:1000, preferred:10000, max:20000, preorder:100},
  shopee_ph:  {new:1000, preferred:10000, max:20000, preorder:100},
  shopee_sea: {new:1000, preferred:10000, max:20000, preorder:100},
};

function planSlots(market, tier, listed, preListed, want){
  const L = SHOP_LIMITS[market];
  const limit = L[tier];
  const room = Math.max(0, limit - listed);
  const preRoom = Math.max(0, L.preorder - preListed);
  const forced = Math.max(0, preListed - L.preorder);
  const canAdd = Math.min(room, preRoom + Math.max(0, listed - preListed >= 0 ? room : 0));
  const notes = [];

  if (forced) notes.push({lv:"stop", t:"プレオーダーが上限 " + L.preorder + "点 を " + forced
    + "点 超えています。<b>超過分はShopeeが売上の低い順に自動削除します。</b>"
    + "自分で落とさなければ、残すものを機械に選ばれることになります。"});
  if (room <= 0) notes.push({lv:"stop", t:"出品枠 " + limit.toLocaleString()
    + "点 が埋まっています。1つ入れるには1つ落とすしかありません。"
    + "実績を積むか Preferred Seller を取ると枠が増えます。"});
  else if (room < limit * 0.1) notes.push({lv:"warn", t:"出品枠の残りが " + room
    + "点。入れ替えの準備を始めてください。"});
  if (want > room) notes.push({lv:"warn", t:"入れたい候補 " + want.toLocaleString()
    + "点 に対して、入れられるのは " + room.toLocaleString() + "点 まで。"
    + "<b>判定の良い順に絞ってください。</b>枠が少ない市場では「全部出す」ができないので、"
    + "選ぶこと自体が仕事になります。"});
  if (market === "shopee_tw" && tier === "new") notes.push({lv:"warn",
    t:"台湾は新規開店時の枠が500点で、他市場（1,000点）の半分です。"
      + "日本製品の主戦場なのに最も狭いので、ここでは点数より単価で稼ぐ設計にしてください。"});

  return {limit, room, preLimit:L.preorder, preRoom, forced, canAdd:room, notes};
}

function bootListShopee(){
  $("sl-run").addEventListener("click", renderSlots);
  $("mu-run").addEventListener("click", renderMassUpload);
  $("mu-dl").addEventListener("click", () => download(TOOL_ID + "-upload.csv", MU_CSV));
  $("rp-run").addEventListener("click", renderReprice);
  renderSlots(); renderReprice();
}

function renderSlots(){
  const c = cfg();
  if (!SHOP_LIMITS[c.market]){
    $("sl-out").innerHTML = '<div class="warn stop"><b>設定の販売先が Shopee ではありません。</b>右上の設定で Shopee の市場を選んでください。</div>';
    return;
  }
  const tier = $("sl-tier").value;
  const listed = +$("sl-listed").value || 0;
  const pre = +$("sl-pre").value || 0;
  let want = +$("sl-want").value || 0;
  let wantNote = "";
  if (!want && GRID){
    want = GRID.rows.filter((r,i) => {
      const v = GRID.at(i).verdict; return v === "blue" || v === "probe";
    }).length;
    wantNote = "（②選ぶ で「出せる」「小さく試す」になった " + want + "件を使用）";
  }
  const p = planSlots(c.market, tier, listed, pre, want);

  const bar = (used, total, cls) => {
    const pct = Math.min(100, total ? used/total*100 : 0);
    return '<div style="height:8px;background:var(--card3);border-radius:4px;overflow:hidden">'
      + '<div style="height:100%;width:' + pct.toFixed(1) + '%;background:var(--' + cls + ')"></div></div>';
  };

  $("sl-out").innerHTML =
      '<div class="cols" style="margin-top:6px">'
    + '<div><div class="hint">出品枠（' + esc(PROFILES[c.market].label) + ' / '
      + esc({new:"新規開店", preferred:"Preferred Seller", max:"実績上限"}[tier]) + '）</div>'
    + '<div style="font-family:var(--mono);font-size:20px;margin:4px 0">'
      + listed.toLocaleString() + ' / ' + p.limit.toLocaleString() + '</div>'
    + bar(listed, p.limit, p.room <= 0 ? "red" : (p.room < p.limit*0.1 ? "probe" : "blue"))
    + '<div class="hint">残り ' + p.room.toLocaleString() + '点</div></div>'
    + '<div><div class="hint">プレオーダー（無在庫）枠</div>'
    + '<div style="font-family:var(--mono);font-size:20px;margin:4px 0">'
      + pre.toLocaleString() + ' / ' + p.preLimit.toLocaleString() + '</div>'
    + bar(pre, p.preLimit, p.forced ? "red" : (p.preRoom < 20 ? "probe" : "blue"))
    + '<div class="hint">' + (p.forced ? p.forced + "点 超過" : "残り " + p.preRoom + "点") + '</div></div>'
    + '<div><div class="hint">これから入れたい' + esc(wantNote) + '</div>'
    + '<div style="font-family:var(--mono);font-size:20px;margin:4px 0">'
      + want.toLocaleString() + '点</div>'
    + '<div class="hint">' + (want > p.room
        ? '<b style="color:var(--red)">' + (want - p.room).toLocaleString() + '点 入りません</b>'
        : "全部入ります") + '</div></div>'
    + '</div>'
    + p.notes.map(n => '<div class="warn ' + (n.lv === "stop" ? "stop" : "") + '">' + n.t + '</div>').join("");
}

let MU_CSV = "";

function renderMassUpload(){
  const c = cfg();
  if (!GRID || !GRID.rows.length){
    $("mu-out").innerHTML = '<div class="warn stop"><b>②選ぶ に商品がありません。</b>先に①探す で読み込んでください。</div>';
    return;
  }
  const want = $("mu-only").value.split(",");
  const limit = Math.max(1, +$("mu-limit").value || 500);
  const picked = [];
  const skipped = {noPrice:0, verdict:0};

  GRID.rows.forEach((r, i) => {
    const res = GRID.at(i);
    if (want.indexOf(res.verdict) < 0){ skipped.verdict++; return; }
    const cc = {...c, ship: res.ship == null ? c.ship : res.ship};
    const floor = listPriceForMargin(+r.cost_incl_tax_jpy || 0, c.target, cc, cc.ship);
    if (!isFinite(floor) || floor <= 0){ skipped.noPrice++; return; }
    picked.push({r, res, floor});
  });

  picked.sort((a,b) => (b.res.score || 0) - (a.res.score || 0));
  const use = picked.slice(0, limit);

  const cols = ["sku","name","price_usd","stock","weight_g","length_cm","width_cm",
                "height_cm","cost_incl_tax_jpy","shipping_jpy","margin_at_price","source_url"];
  const e = v => /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g,'""') + '"' : String(v ?? "");
  MU_CSV = [cols.join(",")].concat(use.map(x => {
    const cc = {...c, ship: x.res.ship == null ? c.ship : x.res.ship};
    const b = compute(x.floor, +x.r.cost_incl_tax_jpy || 0, cc);
    return [x.r.sku, x.r.title_ja, x.floor.toFixed(2), 1, x.r.weight_g,
            x.r.length_cm, x.r.width_cm, x.r.height_cm, x.r.cost_incl_tax_jpy,
            Math.round(cc.ship), (b.margin*100).toFixed(1), x.r.source_url]
      .map(e).join(",");
  })).join("\n");

  $("mu-dl").disabled = !use.length;
  $("mu-out").innerHTML =
      '<div class="warn ' + (use.length ? "ok" : "stop") + '"><b>'
    + use.length.toLocaleString() + '件を書き出せます。</b>'
    + (picked.length > use.length
        ? ' 判定を満たしたのは ' + picked.length.toLocaleString() + '件ですが、上限 '
          + limit.toLocaleString() + '件で切りました（判定の良い順）。' : "")
    + '</div>'
    + ((skipped.verdict || skipped.noPrice)
        ? '<div class="warn"><b>外したもの</b><ul>'
          + (skipped.verdict ? '<li>判定が対象外：' + skipped.verdict.toLocaleString() + '件</li>' : "")
          + (skipped.noPrice ? '<li>目標利益率に届く売価が存在しない：' + skipped.noPrice.toLocaleString() + '件</li>' : "")
          + '</ul></div>' : "")
    + (use.length ? '<pre class="out">' + esc(MU_CSV.split("\n").slice(0, 6).join("\n"))
        + (use.length > 5 ? "\n… 他 " + (use.length - 5).toLocaleString() + "行" : "") + '</pre>' : "");
}

/* 価格改定。在庫切れを利益率より先に見る。順序を逆にすると、
   買えない商品の値段を熱心に直すことになる。 */
const RP_ACT = {
  stop:  {cls:"red",   label:"止める",   why:"仕入元が切れている"},
  raise: {cls:"probe", label:"値上げ",   why:"いまの売価では目標に届かない"},
  lower: {cls:"blue",  label:"値下げ可", why:"目標より余裕がある"},
  hold:  {cls:"excl",  label:"据え置き", why:"目標どおり"},
};

function renderReprice(){
  const c = cfg();
  const rows = parseCsv($("rp-in").value);
  if (!rows.length){
    $("rp-out").innerHTML = '<p class="hint">出品中の商品を貼ってください。</p>';
    return;
  }
  const ORDER = {stop:0, raise:1, lower:2, hold:3};
  const items = rows.map(r => {
    const cost = +r.cost_incl_tax_jpy || 0;
    const price = +r.price_usd || 0;
    const parcel = parcelOf(r.weight_g, r.length_cm, r.width_cm, r.height_cm);
    const sf = shipFor(c, parcel);
    const ship = sf.ship == null ? c.ship : sf.ship;
    const cc = {...c, ship};
    const b = compute(price, cost, cc);
    const floor = listPriceForMargin(cost, c.target, cc, ship);
    const avail = String(r.available ?? "1").trim();
    let act;
    if (avail === "0" || /^(no|false)$/i.test(avail)) act = "stop";
    else if (!isFinite(floor)) act = "raise";
    else if (price < floor) act = "raise";
    else if (price > floor * 1.15) act = "lower";
    else act = "hold";
    return {r, price, cost, ship, b, floor, act};
  }).sort((a,b) => ORDER[a.act] - ORDER[b.act] || a.b.margin - b.b.margin);

  const urgent = items.filter(x => x.act === "stop" || x.act === "raise").length;

  $("rp-out").innerHTML =
      (urgent ? '<div class="warn stop"><b>いますぐ手を入れる行が ' + urgent
        + '件あります。</b>止めるべきものが先、次に値上げです。</div>'
       : '<div class="warn ok"><b>いますぐ直す行はありません。</b></div>')
    + '<div class="scrollx"><table class="mini"><thead><tr>'
    + '<th>手</th><th>商品</th><th class="num">現在価格</th><th class="num">下限価格</th>'
    + '<th class="num">仕入</th><th class="num">送料</th><th class="num">利益率</th><th>理由</th>'
    + '</tr></thead><tbody>'
    + items.map(x => {
        const a = RP_ACT[x.act];
        return '<tr><td><span class="v v-' + a.cls + '">' + esc(a.label) + '</span></td>'
          + '<td>' + esc(x.r.title || x.r.sku) + '</td>'
          + '<td class="num">$' + x.price.toFixed(2) + '</td>'
          + '<td class="num">' + (isFinite(x.floor) ? "$" + x.floor.toFixed(2) : "—") + '</td>'
          + '<td class="num">' + yen(x.cost) + '</td>'
          + '<td class="num">' + yen(x.ship) + '</td>'
          + '<td class="num" style="color:var(--' + (x.b.margin >= c.target ? "blue"
              : x.b.margin > 0 ? "probe" : "red") + ')">' + (x.b.margin*100).toFixed(1) + '%</td>'
          + '<td class="hint">' + esc(a.why)
          + (x.act === "raise" && isFinite(x.floor)
              ? "。$" + (x.floor - x.price).toFixed(2) + " 上げれば目標に届きます" : "")
          + (x.act === "lower" && isFinite(x.floor)
              ? "。$" + (x.price - x.floor).toFixed(2) + " まで下げられます" : "")
          + '</td></tr>';
      }).join("")
    + '</tbody></table></div>';
}
