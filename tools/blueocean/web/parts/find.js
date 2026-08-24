/* ①探す の中身。両ツール共通。
   ブラウザから他社APIは叩けない（CORS）ので、ここは条件を組み立てて
   コマンドを出す係。実際の取得は PC 側の python -m blueocean.cli domestic。 */

const PROV = {
  rakuten: {label:"楽天市場", page:30, pages:100, env:"RAKUTEN_APP_ID", gap:1.05},
  yahoo:   {label:"Yahoo!ショッピング", page:50, pages:20, env:"YAHOO_CLIENT_ID", gap:0.25},
};

function qSources(){
  const s = [];
  if ($("q-rakuten").checked) s.push("rakuten");
  if ($("q-yahoo").checked) s.push("yahoo");
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
      + '<td class="num">' + (secs >= 60 ? Math.floor(secs/60) + "分" + (secs%60) + "秒" : secs + "秒") + '</td></tr>';
    if (want > win)
      out.push('<div class="warn"><b>' + esc(p.label) + 'は1クエリ ' + win.toLocaleString()
        + '件までしか辿れません。</b>' + want.toLocaleString() + '件を指定しても '
        + win.toLocaleString() + '件で打ち切られます。価格帯の分割数を増やすと、'
        + '帯ごとに別の窓になるので先まで採れます。</div>');
  });

  out.push('<div class="scrollx"><table class="mini"><thead><tr>'
    + '<th>取得元</th><th>1クエリの上限</th><th>この条件で採れる上限</th>'
    + '<th>リクエスト数</th><th>おおよその所要</th></tr></thead><tbody>'
    + rows + '</tbody></table></div>');

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
  ["q-rakuten","q-yahoo","q-stock","q-postage","q-cond","q-sort"].forEach(id =>
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
