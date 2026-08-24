/* ④追う の中身。観測を貯めて、前回比つきで次の一手を出す。

   貼られたレポートで textarea を置き換えると、先週ぶんが消えて
   「前回比」が永久に出ない。貯めてある行に足す。 */

function bootTrack(){
  $("tr-date").value = todayISO();
  $("tr-src").textContent = TRACK_SOURCE_LABEL;
  $("tr-guide").innerHTML = TRACK_GUIDE_HTML;

  const stored = loadObs();
  if (stored.length){
    $("tr-in").value = obsRowsToCsv(stored);
    $("tr-hint").textContent = "この端末に " + stored.length + "件 貯まっています。";
  } else {
    $("tr-in").value = SAMPLE_OBS;
    $("tr-hint").textContent = "まだ何も貯まっていません。いまはサンプルが入っています。";
  }

  $("tr-ingest").addEventListener("click", () => {
    const text = $("tr-in").value.trim();
    if (!text){ toast("取り込む中身がありません"); return; }
    let fresh;
    if (looksLikeEbayReport(text)){
      fresh = ingestEbayReport(text, $("tr-date").value || todayISO());
      if (!fresh.length){
        $("tr-out").innerHTML = '<div class="warn stop"><b>レポートとしては読めましたが、1行も取り込めませんでした。</b>SKU（カスタムラベル）の列が空になっていないか確かめてください。</div>';
        return;
      }
    } else {
      fresh = parseCsv(text).map(r => ({
        sku:r.sku||"", title:r.title||"", listed_on:r.listed_on||"",
        observed_on:r.observed_on || $("tr-date").value || todayISO(),
        views:+r.views||0, watchers:+r.watchers||0, sold:+r.sold||0,
      })).filter(r => r.sku);
    }
    const merged = mergeObsRows(loadObs(), fresh);
    saveObs(merged);
    $("tr-in").value = obsRowsToCsv(merged);
    $("tr-hint").textContent = fresh.length + "件を取り込み、合計 " + merged.length + "件になりました。";
    toast(fresh.length + "件を取り込みました");
    runTrack();
  });

  $("tr-run").addEventListener("click", runTrack);
  $("tr-clear").addEventListener("click", () => {
    if (!confirm("この端末に貯めた観測データを全部消します。よろしいですか？")) return;
    saveObs([]); $("tr-in").value = ""; $("tr-hint").textContent = "消しました。";
    $("tr-out").innerHTML = "";
  });

  runTrack();
}

function runTrack(){
  const rows = parseCsv($("tr-in").value);
  if (!rows.length){
    $("tr-out").innerHTML = '<p class="hint">観測データを貼って「取り込む」を押してください。</p>';
    return;
  }
  /* 同じSKUの最新2件を拾って前回比を出す */
  const bySku = {};
  rows.forEach(r => {
    const k = r.sku || r.title;
    (bySku[k] = bySku[k] || []).push(r);
  });

  const ORDER = {promote:0, reprice:1, retitle:2, drop:3, keep:4};
  const items = Object.keys(bySku).map(k => {
    const hist = bySku[k].slice().sort((a,b) =>
      String(a.observed_on).localeCompare(String(b.observed_on)));
    const cur = hist[hist.length-1], prev = hist.length > 1 ? hist[hist.length-2] : null;
    const a = new Date(cur.listed_on), b = new Date(cur.observed_on);
    const days = (isFinite(a) && isFinite(b))
      ? Math.max(0, Math.round((b-a)/86400000)) : 0;
    const o = {sku:cur.sku, title:cur.title || cur.sku, days:days,
               views:+cur.views||0, watchers:+cur.watchers||0, sold:+cur.sold||0};
    const d = decide(o);
    let delta = "";
    if (prev){
      const dv = o.views - (+prev.views||0), dw = o.watchers - (+prev.watchers||0),
            ds = o.sold - (+prev.sold||0);
      const bits = [];
      if (dv) bits.push("閲覧 " + (dv>0?"+":"") + dv);
      if (dw) bits.push("ウォッチ " + (dw>0?"+":"") + dw);
      if (ds) bits.push("販売 " + (ds>0?"+":"") + ds);
      delta = bits.length
        ? "前回（" + prev.observed_on + "）から " + bits.join(" / ")
        : "前回（" + prev.observed_on + "）から動きなし";
      if (!bits.length && days >= 14)
        delta += "。<b>2週間以上動いていないなら、放置ではなく手を入れる番です。</b>";
    } else {
      delta = "前回の観測がありません。来週もう一度貼ると前回比が出ます。";
    }
    return {d, o, delta};
  }).sort((x,y) => ORDER[x.d.action] - ORDER[y.d.action] || y.o.views - x.o.views);

  const tally = {};
  items.forEach(x => tally[x.d.action] = (tally[x.d.action]||0)+1);

  $("tr-out").innerHTML =
      '<div class="grid-bar" style="border:1px solid var(--rule); border-radius:4px 4px 0 0">'
    + '<div class="tally">' + Object.keys(ORDER).filter(k => tally[k]).map(k =>
        '<button style="color:var(--' + ACT[k].cls + ')" aria-pressed="false"><b>'
        + esc(ACT[k].desc) + '</b>' + tally[k] + '</button>').join("") + '</div>'
    + '<span class="count"><b>' + items.length + '</b> 件</span></div>'
    + '<div class="grid-wrap" style="border-radius:0 0 4px 4px"><div style="max-height:60vh;overflow:auto">'
    + '<table class="mini"><thead><tr><th>次の一手</th><th>商品</th>'
    + '<th class="num">経過</th><th class="num">閲覧</th><th class="num">ウォッチ</th>'
    + '<th class="num">販売</th><th>理由</th></tr></thead><tbody>'
    + items.map(x => {
        const a = ACT[x.d.action];
        return '<tr><td><span class="v v-' + (a.cls === "good" ? "blue" : a.cls === "dim" ? "excl" : a.cls)
          + '">' + esc(a.desc) + '</span></td>'
          + '<td>' + esc(x.o.title) + '</td>'
          + '<td class="num">' + x.o.days + '日</td>'
          + '<td class="num">' + x.o.views + '</td>'
          + '<td class="num">' + x.o.watchers + '</td>'
          + '<td class="num">' + x.o.sold + '</td>'
          + '<td>' + esc(x.d.reason) + '<br><span class="hint">' + x.delta + '</span></td></tr>';
      }).join("")
    + '</tbody></table></div></div>';
}
