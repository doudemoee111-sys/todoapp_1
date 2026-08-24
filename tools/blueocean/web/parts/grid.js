/* 商品一覧。**この画面の主役。**
   数千行を扱うので、見えている範囲だけを描く（仮想スクロール）。
   全行を DOM に置くと 3,000 行あたりで入力のたびに固まる。

   列の定義は呼び出し側が渡す。編集できる列はその場で書き換えて、
   その行だけ計算し直す（全行の再計算はしない）。 */

const GRID_BUF = 8;          /* 画面外に余分に描く行数 */

function Grid(opts){
  this.root      = opts.root;                 /* .grid-wrap */
  this.cols      = opts.cols;
  this.rows      = [];                        /* 元データ（編集で書き換わる） */
  this.view      = [];                        /* 絞り込み・並べ替え後の添字 */
  this.calc      = opts.calc;                 /* row -> {verdict, ...} */
  this.onSelect  = opts.onSelect || function(){};
  this.onChange  = opts.onChange || function(){};
  this.sortKey   = opts.sortKey || "verdict";
  this.sortDir   = 1;
  this.q         = "";
  this.only      = "";                        /* 判定での絞り込み */
  this.sel       = -1;
  this.calcCache = new Map();
  this._build();
}

Grid.prototype._build = function(){
  const self = this;
  const width = this.cols.reduce((a,c) => a + c.w, 0);

  this.root.innerHTML =
    '<div class="grid-bar">'
  +   '<input type="text" class="g-q" placeholder="商品名・型番で絞り込み">'
  +   '<div class="tally g-tally"></div>'
  +   '<span class="count g-count"></span>'
  + '</div>'
  + '<div class="gscroll g-scroll"><div class="gtable" style="width:' + width + 'px">'
  +   '<div class="ghead g-head"></div>'
  +   '<div class="gbody g-body"></div>'
  + '</div></div>'
  + '<div class="detail g-detail" hidden></div>';

  this.$scroll = this.root.querySelector(".g-scroll");
  this.$head   = this.root.querySelector(".g-head");
  this.$body   = this.root.querySelector(".g-body");
  this.$count  = this.root.querySelector(".g-count");
  this.$tally  = this.root.querySelector(".g-tally");
  this.$detail = this.root.querySelector(".g-detail");

  this.$head.innerHTML = this.cols.map(function(c){
    return '<div class="c" data-k="' + c.k + '" style="width:' + c.w + 'px"'
         + (c.title ? ' title="' + esc(c.title) + '"' : '')
         + '>' + esc(c.label) + '<span class="ar"></span></div>';
  }).join("");

  this.$head.addEventListener("click", function(e){
    const c = e.target.closest(".c"); if (!c) return;
    const k = c.dataset.k;
    if (self.sortKey === k) self.sortDir *= -1;
    else { self.sortKey = k; self.sortDir = 1; }
    self.apply();
  });

  this.root.querySelector(".g-q").addEventListener("input", function(e){
    self.q = e.target.value.trim().toLowerCase();
    self.apply();
  });

  this.$scroll.addEventListener("scroll", function(){ self._paint(); });

  /* 編集は行を作り直さずに値だけ差し替える。作り直すとフォーカスが飛ぶ。 */
  this.$body.addEventListener("input", function(e){
    const inp = e.target.closest("input[data-k]"); if (!inp) return;
    const i = +inp.closest(".grow").dataset.i;
    self.rows[i][inp.dataset.k] = inp.value;
    self.calcCache.delete(i);
    self._repaintRow(i);
    self.onChange(self);
  });

  this.$body.addEventListener("click", function(e){
    if (e.target.closest("input,a")) return;
    const r = e.target.closest(".grow"); if (!r) return;
    self.select(+r.dataset.i);
  });
};

Grid.prototype.setRows = function(rows){
  this.rows = rows;
  this.calcCache.clear();
  this.sel = -1;
  this.$detail.hidden = true;
  this.apply();
};

Grid.prototype.at = function(i){
  if (!this.calcCache.has(i)) this.calcCache.set(i, this.calc(this.rows[i]));
  return this.calcCache.get(i);
};

Grid.prototype.recalcAll = function(){
  this.calcCache.clear();
  this.apply();
};

const GRID_VORDER = {blue:0, probe:1, thin:2, red:3, excl:4};

Grid.prototype.apply = function(){
  const self = this;
  const q = this.q, only = this.only;
  this.view = [];
  for (let i = 0; i < this.rows.length; i++){
    if (q){
      const hay = ((this.rows[i].title_ja || "") + " " + (this.rows[i].sku || "")).toLowerCase();
      if (hay.indexOf(q) < 0) continue;
    }
    if (only && this.at(i).verdict !== only) continue;
    this.view.push(i);
  }

  const col = this.cols.filter(function(c){ return c.k === self.sortKey; })[0];
  const dir = this.sortDir;
  this.view.sort(function(a,b){
    const va = self._sortVal(a, col), vb = self._sortVal(b, col);
    if (va === vb) return a - b;
    if (va === null) return 1;              /* 空欄は常に最後 */
    if (vb === null) return -1;
    return (va < vb ? -1 : 1) * dir;
  });

  this.$head.querySelectorAll(".c").forEach(function(c){
    c.querySelector(".ar").textContent =
      c.dataset.k === self.sortKey ? (dir > 0 ? " ▲" : " ▼") : "";
  });

  this.$body.style.height = (this.view.length * 38) + "px";
  this._renderTally();
  this.$count.innerHTML = this.view.length === this.rows.length
    ? "<b>" + this.rows.length.toLocaleString() + "</b> 件"
    : "<b>" + this.view.length.toLocaleString() + "</b> / "
      + this.rows.length.toLocaleString() + " 件";
  this._paint();
};

Grid.prototype._sortVal = function(i, col){
  if (!col) return 0;
  const r = this.rows[i];
  if (col.sort) return col.sort(r, this.at(i));
  if (col.k === "verdict") return GRID_VORDER[this.at(i).verdict];
  const v = r[col.k];
  if (v === "" || v === undefined || v === null) return null;
  return col.num ? +v : String(v);
};

Grid.prototype._renderTally = function(){
  const self = this, n = {};
  for (let i = 0; i < this.rows.length; i++){
    const v = this.at(i).verdict;
    n[v] = (n[v] || 0) + 1;
  }
  this.$tally.innerHTML = Object.keys(GRID_VORDER)
    .filter(function(k){ return n[k]; })
    .map(function(k){
      const v = VERDICT[k];
      return '<button data-v="' + k + '" aria-pressed="' + (self.only === k) + '"'
           + ' style="color:var(--' + v.cls + ')" title="' + esc(v.desc) + '">'
           + '<b>' + esc(v.label) + '</b>' + n[k] + '</button>';
    }).join("");
  this.$tally.querySelectorAll("button").forEach(function(b){
    b.addEventListener("click", function(){
      self.only = (self.only === b.dataset.v) ? "" : b.dataset.v;
      self.apply();
    });
  });
};

Grid.prototype._paint = function(){
  const top = this.$scroll.scrollTop;
  const h   = this.$scroll.clientHeight;
  const a   = Math.max(0, Math.floor(top / 38) - GRID_BUF);
  const b   = Math.min(this.view.length, Math.ceil((top + h) / 38) + GRID_BUF);

  if (!this.view.length){
    this.$body.innerHTML = '<div class="gempty">'
      + (this.rows.length ? "この条件に合う行がありません。" : "まだ商品がありません。①探す で読み込んでください。")
      + '</div>';
    return;
  }
  let out = "";
  for (let v = a; v < b; v++) out += this._rowHtml(this.view[v], v);
  this.$body.innerHTML = out;
};

Grid.prototype._rowHtml = function(i, v){
  const r = this.rows[i], res = this.at(i);
  const cells = this.cols.map(function(c){
    return '<div class="c ' + (c.num ? "num" : "txt") + '" style="width:' + c.w + 'px">'
         + c.cell(r, res, i) + '</div>';
  }).join("");
  return '<div class="grow' + (this.sel === i ? ' sel' : '') + '" data-i="' + i
       + '" style="top:' + (v * 38) + 'px">' + cells + '</div>';
};

Grid.prototype._repaintRow = function(i){
  const el = this.$body.querySelector('.grow[data-i="' + i + '"]');
  if (!el) return;
  const r = this.rows[i], res = this.at(i);
  const cs = el.querySelectorAll(".c");
  this.cols.forEach(function(c, k){
    if (c.edit) return;                       /* 入力欄は触らない */
    cs[k].innerHTML = c.cell(r, res, i);
  });
  if (this.sel === i) this._renderDetail(i);
  this._renderTally();
};

Grid.prototype.select = function(i){
  this.sel = i;
  this._paint();                 /* 選択行に色を付ける */
  this._renderDetail(i);
  this.onSelect(this.rows[i], this.at(i), i);
};

Grid.prototype._renderDetail = function(i){
  const r = this.rows[i], res = this.at(i);
  const v = VERDICT[res.verdict];
  this.$detail.hidden = false;
  this.$detail.innerHTML =
      '<h4><span class="v v-' + v.cls + '">' + esc(v.label) + '</span> '
    + esc(r.title_ja || r.sku || "(名称なし)") + '</h4>'
    + '<ul>' + res.reasons.map(function(x){ return "<li>" + esc(x) + "</li>"; }).join("") + '</ul>'
    + (res.flip ? '<div class="flip">↕ ' + esc(res.flip) + '</div>' : "")
    + (r.source_url ? '<p class="hint"><a href="' + esc(r.source_url)
        + '" target="_blank" rel="noopener">仕入元を開く</a></p>' : "");
};

/* 表示ヘルパ */
function gNum(v, suffix){
  if (v === "" || v === null || v === undefined || isNaN(+v)) return '<span class="est">—</span>';
  return (+v).toLocaleString("ja-JP") + (suffix || "");
}
function gEdit(k, v, ph){
  return '<input data-k="' + k + '" value="' + esc(v == null ? "" : v) + '"'
       + ' inputmode="decimal" placeholder="' + (ph || "") + '">';
}
