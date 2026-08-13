// Shared logic for both pages. Expects globals RAW (compact OHLC arrays) and
// SYMS (symbol metadata) to be defined before this script runs.
const WD = ["日", "月", "火", "水", "木", "金", "土"];

function symMeta(key) { return SYMS.find((s) => s.key === key) || SYMS[0]; }

function fmt(key, v) {
  if (v == null || !isFinite(v)) return "–";
  const d = symMeta(key).decimals;
  return Number(v).toLocaleString("ja-JP", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function fmtSigned(key, v) {
  if (v == null || !isFinite(v)) return "–";
  return (v > 0 ? "+" : v < 0 ? "" : "") + fmt(key, v);
}

// Turn compact [date,o,h,l,c] rows into rich records with derived fields.
function derive(key) {
  const raw = RAW[key] || [];
  return raw.map(([date, o, h, l, c]) => {
    const dt = new Date(date + "T00:00:00Z");
    const dow = dt.getUTCDay();
    const dom = dt.getUTCDate();
    return {
      date, o, h, l, c,
      hl: h - l,            // 値幅 (high-low)
      oc: c - o,            // 騰落 (close-open)
      up: h - o,            // 上ヒゲ含む上昇余地
      down: o - l,          // 下降余地
      dow,                  // 0=日 .. 6=土
      month: dt.getUTCMonth() + 1,
      wom: Math.floor((dom - 1) / 7) + 1, // 第N週
      weekend: dow === 0 || dow === 6,
    };
  });
}

// --- statistics -----------------------------------------------------------
function mean(a) { return a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN; }
function std(a) {
  if (a.length < 2) return NaN;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1));
}

// --- candlestick chart ----------------------------------------------------
// Renders into a <canvas>; wires a floating tooltip and redraws on resize.
function makeChart(canvas, tooltip) {
  let rows = [], key = "USDJPY", bars = [];
  const state = { rows, key };

  function draw() {
    const rows = state.rows, key = state.key;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth, cssH = canvas.clientHeight;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    bars = [];
    if (!rows.length) return;

    const padL = 8, padR = 62, padT = 12, padB = 26;
    const plotW = cssW - padL - padR, plotH = cssH - padT - padB;
    let lo = Infinity, hi = -Infinity;
    for (const r of rows) { if (r.l < lo) lo = r.l; if (r.h > hi) hi = r.h; }
    const pad = (hi - lo) * 0.06 || hi * 0.001;
    lo -= pad; hi += pad;
    const y = (p) => padT + (hi - p) / (hi - lo) * plotH;

    const css = getComputedStyle(document.documentElement);
    const cGrid = css.getPropertyValue("--chart-grid").trim() || "#ddd";
    const cText = css.getPropertyValue("--chart-axis").trim() || "#888";
    const cUp = css.getPropertyValue("--chart-up").trim() || "#2f7a52";
    const cDown = css.getPropertyValue("--chart-down").trim() || "#c14953";
    const cBg = css.getPropertyValue("--surface").trim() || "#fff";

    // horizontal gridlines + price axis
    ctx.font = "11px ui-monospace, monospace";
    ctx.textBaseline = "middle";
    ctx.strokeStyle = cGrid; ctx.fillStyle = cText; ctx.lineWidth = 1;
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const p = lo + (hi - lo) * (i / ticks);
      const yy = Math.round(y(p)) + 0.5;
      ctx.globalAlpha = 0.5;
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.textAlign = "left";
      ctx.fillText(fmt(key, p), padL + plotW + 6, yy);
    }

    const n = rows.length;
    const slot = plotW / n;
    const bw = Math.max(1, Math.min(14, slot * 0.7));
    ctx.textAlign = "center";
    const labelEvery = Math.ceil(n / 8);
    for (let i = 0; i < n; i++) {
      const r = rows[i];
      const cx = padL + slot * (i + 0.5);
      const up = r.c >= r.o;
      const col = up ? cUp : cDown;
      ctx.strokeStyle = col; ctx.fillStyle = up ? cBg : col; ctx.lineWidth = 1;
      // wick
      ctx.beginPath(); ctx.moveTo(cx, y(r.h)); ctx.lineTo(cx, y(r.l)); ctx.stroke();
      // body — hollow for 陽線, filled for 陰線
      const yo = y(r.o), yc = y(r.c);
      const top = Math.min(yo, yc), h = Math.max(1, Math.abs(yc - yo));
      ctx.beginPath(); ctx.rect(cx - bw / 2, top, bw, h);
      ctx.fill(); ctx.stroke();
      bars.push({ x: cx, i, r });
      // x labels
      if (i % labelEvery === 0 || i === n - 1) {
        ctx.fillStyle = cText;
        ctx.fillText(r.date.slice(2), cx, cssH - 8);
      }
    }
  }

  function onMove(ev) {
    if (!bars.length) { tooltip.style.opacity = 0; return; }
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    let best = bars[0], bd = Infinity;
    for (const b of bars) { const d = Math.abs(b.x - mx); if (d < bd) { bd = d; best = b; } }
    const r = best.r, key = state.key;
    tooltip.innerHTML =
      `<b>${r.date} (${WD[r.dow]})</b>` +
      `<span>始 <em>${fmt(key, r.o)}</em></span>` +
      `<span>高 <em>${fmt(key, r.h)}</em></span>` +
      `<span>安 <em>${fmt(key, r.l)}</em></span>` +
      `<span>終 <em>${fmt(key, r.c)}</em></span>` +
      `<span>幅 <em>${fmt(key, r.hl)}</em> / 騰落 <em>${fmtSigned(key, r.oc)}</em></span>`;
    tooltip.style.opacity = 1;
    const tw = tooltip.offsetWidth;
    let left = best.x + 12;
    if (left + tw > rect.width) left = best.x - tw - 12;
    tooltip.style.left = Math.max(4, left) + "px";
    tooltip.style.top = Math.min(rect.height - tooltip.offsetHeight - 4, ev.clientY - rect.top + 12) + "px";
  }
  canvas.addEventListener("mousemove", onMove);
  canvas.addEventListener("mouseleave", () => { tooltip.style.opacity = 0; });
  canvas.addEventListener("touchstart", (e) => { if (e.touches[0]) onMove(e.touches[0]); }, { passive: true });
  canvas.addEventListener("touchmove", (e) => { if (e.touches[0]) onMove(e.touches[0]); }, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(() => draw()).observe(canvas);

  return {
    set(key, rows) { state.key = key; state.rows = rows; draw(); },
    redraw: draw,
  };
}

// period filter helpers (business-day counts)
const PERIODS = [
  { id: "1M", label: "1ヶ月", n: 22 },
  { id: "3M", label: "3ヶ月", n: 66 },
  { id: "6M", label: "6ヶ月", n: 132 },
  { id: "1Y", label: "1年", n: 252 },
  { id: "ALL", label: "全期間", n: Infinity },
];
function lastN(rows, n) { return n === Infinity ? rows : rows.slice(Math.max(0, rows.length - n)); }
