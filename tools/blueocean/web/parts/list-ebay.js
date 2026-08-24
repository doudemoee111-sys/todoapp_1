/* ③出す（eBay）。値決めとセット販売。 */

function bootListEbay(){
  $("lp-run").addEventListener("click", renderListPrice);
  $("bd-run").addEventListener("click", renderBundle);
  renderListPrice(); renderBundle();
}

/* ②選ぶ で行を選んだら、その数字を持ってくる。同じ数字を2回入れさせない。 */
function fillListFromRow(r){
  if (!r) return;
  $("lp-cost").value  = r.cost_incl_tax_jpy || "";
  $("lp-g").value     = r.weight_g || "";
  $("lp-l").value     = r.length_cm || "";
  $("lp-w").value     = r.width_cm || "";
  $("lp-h").value     = r.height_cm || "";
  $("lp-price").value = r.market_price_usd || "";
  $("lp-who").textContent = "選択中：" + (r.title_ja || r.sku || "");
  renderListPrice();
}

function renderListPrice(){
  const c = cfg();
  const cost = +$("lp-cost").value || 0;
  const parcel = parcelOf($("lp-g").value, $("lp-l").value, $("lp-w").value, $("lp-h").value);
  const sf = shipFor(c, parcel);

  if (sf.ship === null){
    $("lp-out").innerHTML = '<div class="warn stop"><b>この重量・寸法で使える配送手段がありません。</b>重量か寸法が上限を超えています。梱包を見直すか、別の手段を設定で選んでください。</div>';
    return;
  }
  const cc = {...c, ship: sf.ship};
  const floor = listPriceForMargin(cost, c.target, cc, sf.ship);
  const asked = +$("lp-price").value || 0;
  const use = asked > 0 ? asked : floor;

  if (!isFinite(floor)){
    $("lp-out").innerHTML = '<div class="warn stop"><b>この条件では目標利益率に届く売価が存在しません。</b>手数料と関税の合計が目標利益率を食い切っています。目標を下げるか、市場を変えてください。</div>';
    return;
  }

  const b = compute(use, cost, cc);
  const ri = returnImpact(use, cost, c, sf.ship, {sellerPays:true, recovered:true});
  const riLost = returnImpact(use, cost, c, sf.ship, {sellerPays:true, recovered:false});
  const fx = breakevenFx(use, cost, c, sf.ship);
  const duty = breakevenDuty(use, cost, c, sf.ship);

  const rows = [
    ["売価", yen(b.price) + "円", "$" + use.toFixed(2)],
    ["販売手数料", "−" + yen(b.fees) + "円", (effFee(cc)*100).toFixed(1) + "%＋固定 " + yen(c.per) + "円"],
    ["関税（セラー負担）", "−" + yen(b.duty) + "円", (c.duty*100).toFixed(1) + "%"],
    ["送料", "−" + yen(b.ship) + "円",
      sf.quote ? CLABEL[sf.quote.carrier] + " / 課金重量 " + sf.quote.chg + "g"
        + (sf.quote.byVolume ? "（容積で課金）" : "") : "固定値"],
    ["梱包", "−" + yen(b.pack) + "円", ""],
    ["仕入", "−" + yen(b.cost) + "円", ""],
    ["消費税還付", "＋" + yen(b.refund) + "円", c.taxable ? "税込仕入の 10/110" : "免税事業者なので0"],
    ["<b>手残り</b>", "<b>" + yen(b.profit) + "円</b>", "<b>利益率 " + (b.margin*100).toFixed(1) + "%</b>"],
  ];

  const ladder = [0, .05, .10, .15, .20].map(d => {
    const p = use * (1-d);
    const x = compute(p, cost, cc);
    /* 目標ちょうどを「目標割れ」と言わない。0.2 を浮動小数で作ると
       0.19999… になることがあるので、表示の桁（0.1%）ぶん余裕を持たせる。 */
    return {d, p, m: x.margin, ok: x.margin >= c.target - 5e-4};
  });

  $("lp-out").innerHTML =
      '<div class="warn ' + (b.margin >= c.target - 5e-4 ? "ok" : (b.profit > 0 ? "" : "stop")) + '">'
    + (asked > 0
        ? '<b>$' + use.toFixed(2) + ' で出すと、手残りは ' + yen(b.profit) + '円（利益率 '
          + (b.margin*100).toFixed(1) + '%）。</b>'
          + (b.margin >= c.target - 5e-4 ? "目標を満たしています。"
             : "目標 " + (c.target*100).toFixed(0) + "% には届きません。下限は $"
               + floor.toFixed(2) + " です。")
        : '<b>目標利益率 ' + (c.target*100).toFixed(0) + '% を満たす下限は $'
          + floor.toFixed(2) + '（' + yen(floor*c.fx) + '円）。</b>'
          + 'これより下げると目標を割ります。')
    + '</div>'

    + '<div class="cols">'
    + '<div><h3 style="font-size:13px;margin:14px 0 6px">内訳</h3>'
    + '<div class="scrollx"><table class="mini"><tbody>'
    + rows.map(r => '<tr><td>' + r[0] + '</td><td class="num">' + r[1] + '</td>'
        + '<td class="hint">' + r[2] + '</td></tr>').join("")
    + '</tbody></table></div></div>'

    + '<div><h3 style="font-size:13px;margin:14px 0 6px">値下げの余地</h3>'
    + '<div class="scrollx"><table class="mini"><thead><tr><th>値引き</th>'
    + '<th class="num">売価</th><th class="num">利益率</th><th></th></tr></thead><tbody>'
    + ladder.map(l => '<tr><td>' + (l.d*100).toFixed(0) + '%</td>'
        + '<td class="num">$' + l.p.toFixed(2) + '</td>'
        + '<td class="num">' + (l.m*100).toFixed(1) + '%</td>'
        + '<td><span class="v v-' + (l.ok ? "blue" : (l.m > 0 ? "probe" : "red")) + '">'
        + (l.ok ? "目標内" : (l.m > 0 ? "目標割れ" : "赤字")) + '</span></td></tr>').join("")
    + '</tbody></table></div>'
    + '<p class="hint">オファーが来たときに、どこまで受けてよいかの線です。</p></div>'
    + '</div>'

    + '<h3 style="font-size:13px;margin:16px 0 6px">この値決めが壊れる条件</h3>'
    + '<div class="scrollx"><table class="mini"><tbody>'
    + '<tr><td>為替</td><td class="num">' + (isFinite(fx) ? fx.toFixed(1) + " 円/$" : "—")
      + '</td><td class="hint">これを下回ると赤字。いまは ' + c.fx + ' 円/$</td></tr>'
    + '<tr><td>関税率</td><td class="num">' + (duty*100).toFixed(1) + '%</td>'
      + '<td class="hint">これを超えると赤字。いまの想定は ' + (c.duty*100).toFixed(1) + '%</td></tr>'
    + '<tr><td>返品（商品が戻る）</td><td class="num">'
      + (ri.rate > 0 ? (ri.rate*100).toFixed(1) + "%" : "—") + '</td>'
      + '<td class="hint">1件あたり ' + yen(ri.loss) + '円の損失。'
      + (isFinite(ri.oneIn) ? Math.floor(ri.oneIn) + '件に1件までなら期待値は黒字' : "") + '</td></tr>'
    + '<tr><td>返品（商品が戻らない）</td><td class="num">'
      + (riLost.rate > 0 ? (riLost.rate*100).toFixed(1) + "%" : "—") + '</td>'
      + '<td class="hint">1件あたり ' + yen(riLost.loss) + '円の損失</td></tr>'
    + '</tbody></table></div>'
    + (ri.fragile ? '<div class="warn"><b>返品1件で、売上数件ぶんの利益が消えます。</b>'
        + '説明文と写真で状態を過剰なほど正確に書いてください。ここが薄利の一番の穴です。</div>' : "")
    + (sf.quote && sf.quote.warnings && sf.quote.warnings.length
        ? '<div class="warn"><b>送料の注意</b><ul>'
          + sf.quote.warnings.map(w => "<li>" + w + "</li>").join("") + '</ul></div>' : "");
}

function renderBundle(){
  const c = cfg();
  const rows = parseCsv($("bd-in").value);
  if (!rows.length){
    $("bd-out").innerHTML = '<p class="hint">構成品を入れてください。</p>';
    return;
  }
  const items = rows.map(r => ({
    name: r.name || "(名称なし)",
    cost: +r.cost_incl_tax_jpy || 0,
    solo: +r.solo_price_usd || 0,
    g: +r.weight_g || 0, l: +r.length_cm || 0, w: +r.width_cm || 0, h: +r.height_cm || 0,
  }));
  const pack = parcelOf($("bd-g").value, $("bd-l").value, $("bd-w").value, $("bd-h").value);
  const setPrice = +$("bd-price").value || 0;

  const sep = sellSeparately(items, c);
  const set = sellAsBundle(items, setPrice, pack, c);
  const be  = breakevenSetPrice(items, pack, c);
  const s   = bundleShip(pack, c);

  const win = set.profit > sep.profit;
  const line = (a, b) => '<tr><td>' + a[0] + '</td><td class="num">' + a[1]
    + '</td><td class="num">' + b + '</td></tr>';

  $("bd-out").innerHTML =
      '<div class="warn ' + (win ? "ok" : "") + '"><b>'
    + (win
        ? "束ねたほうが " + yen(set.profit - sep.profit) + "円 多く残ります。"
        : "1点ずつ売ったほうが " + yen(sep.profit - set.profit) + "円 多く残ります。")
    + '</b> セットの損益分岐は $' + (isFinite(be) ? be.toFixed(2) : "—")
    + '（これを下回るとセットで売る意味がなくなります）。</div>'
    + (!s.quotable ? '<div class="warn"><b>この梱包サイズでは送料が出せませんでした。</b>'
        + '市場の固定値 ' + yen(c.ship) + '円 で計算しています。重量・寸法を見直してください。</div>' : "")
    + (sep.unsold.length ? '<div class="warn"><b>単品では売れない見込みの品：</b>'
        + sep.unsold.map(esc).join("、") + '。'
        + '1点ずつ売る場合、これらの仕入は回収できないものとして計算しています。</div>' : "")
    + '<div class="scrollx"><table class="mini"><thead><tr><th></th>'
    + '<th class="num">1点ずつ売る</th><th class="num">束ねて売る</th></tr></thead><tbody>'
    + line(["注文件数", sep.orders + "件"], set.orders + "件")
    + line(["売上", yen(sep.rev) + "円"], yen(set.rev) + "円")
    + line(["手数料", "−" + yen(sep.fees) + "円"], "−" + yen(set.fees) + "円")
    + line(["関税", "−" + yen(sep.duty) + "円"], "−" + yen(set.duty) + "円")
    + line(["送料", "−" + yen(sep.ship) + "円"], "−" + yen(set.ship) + "円")
    + line(["梱包", "−" + yen(sep.pack) + "円"], "−" + yen(set.pack) + "円")
    + line(["仕入", "−" + yen(sep.cost) + "円"], "−" + yen(set.cost) + "円")
    + line(["消費税還付", "＋" + yen(sep.refund) + "円"], "＋" + yen(set.refund) + "円")
    + line(["<b>手残り</b>", "<b>" + yen(sep.profit) + "円</b>"], "<b>" + yen(set.profit) + "円</b>")
    + '</tbody></table></div>'
    + '<p class="hint">送料は' + (s.quotable
        ? "課金重量 " + s.chg + "g" + (s.byVol ? "（容積で課金）" : "") + " で計算"
        : "固定値") + '。束ねると注文が1件になるので、注文ごとの固定費と送料が1回で済みます。</p>';
}
