/* ①探す の中身。両ツール共通。
   ブラウザから他社APIは叩けない（CORS）ので、ここは条件を組み立てて
   コマンドを出す係。実際の取得は PC 側の python -m blueocean.cli domestic。 */

const PROV = {
  rakuten: {label:"楽天市場", page:30, pages:100, env:"RAKUTEN_APP_ID", gap:1.05,
            jan:false, weight:false},
  yahoo:   {label:"Yahoo!ショッピング", page:50, pages:20, env:"YAHOO_CLIENT_ID", gap:0.25,
            jan:true, weight:false},
  /* Amazon は窓が 10×10=100件しかない。面で採る用途には向かないが、
     **重量と寸法を返すのはここだけ。** JANが一致する行にその実測を移せる。 */
  amazon:  {label:"Amazon.co.jp", page:10, pages:10, env:"AMAZON_CREATORS_CREDS", gap:1.05,
            jan:true, weight:true},
};

function qSources(){
  const s = [];
  if ($("q-rakuten").checked) s.push("rakuten");
  if ($("q-yahoo").checked) s.push("yahoo");
  if ($("q-amazon").checked) s.push("amazon");
  return s;
}

function qBands(low, high, n){
  if (n < 2) return [[low, high]];
  const lo = Math.max(low, 100);
  if (lo >= high) return [[low, high]];
  const ratio = Math.pow(high / lo, 1 / n);
  const edges = [lo];
  for (let i = 1; i < n; i++) edges.push(Math.floor(lo * Math.pow(ratio, i)));
  edges.push(high);
  const out = [];
  for (let i = 0; i < edges.length - 1; i++){
    const a = out.length ? out[out.length-1][1] + 1 : edges[i];
    if (edges[i+1] > a) out.push([a, edges[i+1]]);
  }
  if (out.length) out[0][0] = low;
  return out;
}

function renderFindPlan(){
  const srcs = qSources();
  const min = +$("q-min").value || 0, max = +$("q-max").value || 0;
  const split = Math.max(1, +$("q-split").value || 1);
  const want = Math.max(1, +$("q-max-items").value || 1);
  const bands = qBands(min, max, split);
  const out = [];

  if (!srcs.length){
    $("q-plan").innerHTML = '<div class="warn stop"><b>取得元が選ばれていません。</b>楽天かYahoo!のどちらかにチェックを入れてください。</div>';
    $("q-cmd").textContent = "";
    return;
  }
  if (!$("q-keyword").value.trim() && !$("q-genre").value.trim()){
    out.push('<div class="warn stop"><b>キーワードかジャンルIDのどちらかは必要です。</b>どちらのAPIも「条件なしで全件」は返してくれません。</div>');
  }

  /* 窓の上限。ここを黙っていると「採れたつもり」で取りこぼす。 */
  let rows = "";
  let total = 0;
  srcs.forEach(s => {
    const p = PROV[s], win = p.page * p.pages;
    const per = Math.min(want, win);
    const calls = Math.ceil(per / p.page) * bands.length;
    const secs = Math.round(calls * p.gap);
    total += per * bands.length;
    rows += '<tr><td>' + esc(p.label) + '</td>'
      + '<td class="num">' + win.toLocaleString() + '</td>'
      + '<td class="num">' + (per * bands.length).toLocaleString() + '</td>'
      + '<td class="num">' + calls.toLocaleString() + '</td>'
      + '<td class="num">' + (secs >= 60 ? Math.floor(secs/60) + "分" + (secs%60) + "秒" : secs + "秒") + '</td>'
      + '<td>' + (p.jan ? "返る" : '<span class="est">返らない</span>') + '</td>'
      + '<td>' + (p.weight ? '<b style="color:var(--blue)">返る</b>' : '<span class="est">返らない</span>') + '</td></tr>';
    if (want > win)
      out.push('<div class="warn"><b>' + esc(p.label) + 'は1クエリ ' + win.toLocaleString()
        + '件までしか辿れません。</b>' + want.toLocaleString() + '件を指定しても '
        + win.toLocaleString() + '件で打ち切られます。価格帯の分割数を増やすと、'
        + '帯ごとに別の窓になるので先まで採れます。</div>');
  });

  out.push('<div class="scrollx"><table class="mini"><thead><tr>'
    + '<th>取得元</th><th class="num">1クエリの上限</th><th class="num">この条件で採れる上限</th>'
    + '<th class="num">リクエスト数</th><th class="num">おおよその所要</th>'
    + '<th>JAN</th><th>重量</th></tr></thead><tbody>'
    + rows + '</tbody></table></div>');

  /* 重量が取れるかどうかは、このツールでは判定の質に直結する。
     取れないなら推定になり、判定は「小さく試す」で止まる。 */
  const hasWeight = srcs.some(s => PROV[s].weight);
  const hasJan    = srcs.filter(s => PROV[s].jan);
  if (hasWeight && hasJan.length > 1){
    out.push('<div class="warn ok"><b>この組み合わせなら重量が実測で入ります。</b>'
      + 'Amazonが返す登録値を、JANが一致する他社の行に移します。'
      + '安いのは他社、重さはAmazonから、という組み合わせが作れるので、'
      + '<b>判定が「小さく試す」で止まらずに「出せる」まで上がります。</b></div>');
  } else if (!hasWeight){
    out.push('<div class="warn"><b>この組み合わせでは重量が取れません。</b>'
      + '楽天もYahoo!も重量・寸法を返さないので、商品名とカテゴリからの推定になります。'
      + '推定のままだと判定は最良でも「小さく試す」止まりです。'
      + 'Amazonを足すと実測が入りますが、鍵の条件が厳しい点は上の説明をご覧ください。</div>');
  }
  if (srcs.length === 1 && srcs[0] === "amazon")
    out.push('<div class="warn"><b>Amazonだけだと1クエリ100件しか採れません。</b>'
      + 'Yahoo!も一緒に選ぶと、母数はYahoo!で稼ぎ、重量はAmazonから移す形になります。</div>');
  if ($("q-amazon").checked && $("q-rakuten").checked && !$("q-yahoo").checked)
    out.push('<div class="warn">楽天はJANを返さないので、'
      + '<b>Amazonの重量を楽天の行に移すことはできません。</b>'
      + 'Yahoo!を足すと突合できます。</div>');

  if (split > 1){
    out.push('<p class="hint">価格帯の分割：'
      + bands.map(b => b[0].toLocaleString() + "〜" + b[1].toLocaleString() + "円").join(" / ")
      + '<br>安い側ほど商品が密なので、等分ではなく等比で割っています。</p>');
  }
  if ($("q-postage").checked)
    out.push('<p class="hint">送料込みのみに絞ると原価が確定しますが、母数はかなり減ります。Yahoo!側にはこの絞り込みが無いので、楽天だけに効きます。</p>');

  $("q-plan").innerHTML = out.join("");
  renderFindCmd();
}

function renderFindCmd(){
  const g = id => $(id).value.trim();
  const a = ["python -m blueocean.cli domestic search"];
  a.push("--source " + qSources().join(","));
  if (g("q-keyword")) a.push('--keyword "' + g("q-keyword").replace(/"/g,'\\"') + '"');
  if (g("q-ng"))      a.push('--ng-keyword "' + g("q-ng").replace(/"/g,'\\"') + '"');
  if (g("q-genre"))   a.push("--genre-id " + g("q-genre"));
  if (g("q-min"))     a.push("--min-price " + g("q-min"));
  if (g("q-max"))     a.push("--max-price " + g("q-max"));
  if ($("q-cond").value !== "any") a.push("--condition " + $("q-cond").value);
  a.push("--sort " + $("q-sort").value);
  a.push("--max-items " + (g("q-max-items") || 300));
  if (+g("q-split") > 1) a.push("--split-price " + g("q-split"));
  if (+g("q-ship") > 0)  a.push("--domestic-shipping " + g("q-ship"));
  if (!$("q-stock").checked) a.push("--include-out-of-stock");
  if ($("q-postage").checked) a.push("--postage-included");
  if ($("q-cheapest").checked) a.push("--cheapest-only");
  a.push("--out items.csv");
  a.push("--candidates-out candidates.csv");
  $("q-cmd").textContent = a.join(" \\\n  ");
  $("q-note").textContent = "実行前に " + qSources().map(s => PROV[s].env).join(" と ")
    + " を設定してください。--dry-run を足すと、叩かずに送るパラメータだけ確認できます。";
}

function bootFind(applyRows){
  ["q-keyword","q-ng","q-genre","q-min","q-max","q-split","q-max-items",
   "q-cond","q-sort","q-ship"].forEach(id =>
    $(id).addEventListener("input", renderFindPlan));
  ["q-rakuten","q-yahoo","q-amazon","q-stock","q-postage","q-cheapest",
   "q-cond","q-sort"].forEach(id =>
    $(id).addEventListener("change", renderFindPlan));
  $("q-copy").addEventListener("click", () => copyText($("q-cmd"), "コマンドをコピーしました"));

  function doImport(append){
    const text = $("imp-text").value.trim();
    if (!text){ $("imp-out").innerHTML = '<div class="warn stop"><b>読み込む中身がありません。</b>CSVを貼るか、ファイルを選んでください。</div>'; return; }
    const r = importRows(text);
    if (!r.rows.length){
      $("imp-out").innerHTML = '<div class="warn stop"><b>1行も読み取れませんでした。</b>1行目が列名になっているか確かめてください。</div>';
      return;
    }
    applyRows(r.rows, append);
    $("imp-out").innerHTML =
        '<div class="warn ok"><b>' + r.rows.length.toLocaleString() + '件を読み込みました。</b>'
      + '②選ぶ に移ると一覧で見られます。</div>'
      + (r.warnings.length
          ? '<div class="warn"><b>読み込みで足りなかったもの</b><ul>'
            + r.warnings.map(w => "<li>" + w + "</li>").join("") + '</ul></div>'
          : "");
    toast(r.rows.length.toLocaleString() + "件を読み込みました");
  }
  $("imp-run").addEventListener("click", () => doImport(false));
  $("imp-add").addEventListener("click", () => doImport(true));
  $("imp-file").addEventListener("change", e => {
    const f = e.target.files[0]; if (!f) return;
    const fr = new FileReader();
    fr.onload = () => { $("imp-text").value = fr.result; doImport(false); };
    fr.readAsText(f, "utf-8");
  });
  $("imp-sample").addEventListener("click", () => {
    $("imp-text").value = SAMPLE_ROWS; doImport(false);
  });
  renderFindPlan();
}
