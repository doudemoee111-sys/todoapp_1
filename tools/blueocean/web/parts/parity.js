/* Python 側と同じ入力を食わせて、同じ数字が出るかを見るための口。
   tests/test_parity.py から node で叩かれる。 */
const fs = require("fs");
eval(fs.readFileSync(__dirname + "/core.js", "utf8"));

const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};

out.profit = cases.profit.map(x => {
  const r = compute(x.price, x.cost, x.c);
  return {profit: Math.round(r.profit * 100) / 100,
          margin: Math.round(r.margin * 1e6) / 1e6,
          refund: Math.round(r.refund * 100) / 100};
});
out.maxCost = cases.maxCost.map(x => Math.round(maxCost(x.price, x.c, x.target) * 100) / 100);
out.ship = cases.ship.map(x => {
  const q = quoteOne(parcelOf(x.g, x.l, x.w, x.h), x.zone, x.carrier);
  return q.error ? {error: true} : {jpy: q.jpy, chg: q.chg, vol: !!q.byVolume};
});
out.domestic = cases.domestic.map(x => domesticLegJpy(parcelOf(x.g, x.l, x.w, x.h)));
out.listPrice = cases.listPrice.map(x =>
  Math.round(listPriceForMargin(x.cost, x.margin, x.c, x.ship) * 100) / 100);
out.breakevenFx = cases.breakevenFx.map(x => {
  const v = breakevenFx(x.price, x.cost, x.c, x.ship);
  return v === null ? null : Math.round(v * 100) / 100;
});
out.breakevenDuty = cases.breakevenDuty.map(x => {
  const v = breakevenDuty(x.price, x.cost, x.c, x.ship);
  return v === null ? null : Math.round(v * 1e6) / 1e6;
});
out.returnImpact = cases.returnImpact.map(x => {
  const r = returnImpact(x.price, x.cost, x.c, x.ship, x.opt);
  return {tolerable: Math.round(r.rate * 1e6) / 1e6,
          loss: Math.round(r.loss * 100) / 100};
});
out.bundle = cases.bundle.map(x => {
  const sep = sellSeparately(x.items, x.c);
  const set = sellAsBundle(x.items, x.setPrice, parcelOf(x.pack.g, x.pack.l, x.pack.w, x.pack.h), x.c);
  return {sep: Math.round(sep.profit * 100) / 100,
          set: Math.round(set.profit * 100) / 100};
});
out.verdict = cases.verdict.map(x => {
  const r = scoreOne(x.row, x.c);
  return {verdict: r.verdict, cap: Math.round(r.cap)};
});

process.stdout.write(JSON.stringify(out));
