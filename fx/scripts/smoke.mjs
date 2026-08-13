import { chromium } from "playwright-core";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const EXE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const WEB = join(process.cwd(), "fx", "web");

const b = await chromium.launch({ executablePath: EXE, args: ["--no-sandbox"] });
let fail = 0;
for (const [file, checks] of [
  ["fx_candlestick.html", async (p) => {
    // switch to GOLD, 1Y period; ensure canvas drew
    await p.click("text=ゴールド");
    await p.click("text=1年");
    const foot = await p.textContent("#foot");
    return { foot };
  }],
  ["fx_dashboard.html", async (p) => {
    await p.click("#syms >> text=ポンド円");
    await p.fill("#openin", "190");
    await p.selectOption("#f-dow", "水");
    const stats = await p.$$eval("#stats .stat .v", els => els.map(e => e.textContent));
    const rangeRows = await p.$$eval("#rangetbl tbody tr", els => els.length);
    const seasonBars = await p.$$eval("#s-dow-hl .bar", els => els.length);
    // date search on a known-present date
    await p.fill("#datein", "2026-08-12");
    const day = await p.textContent("#dayout");
    return { stats, rangeRows, seasonBars, day, foot: await p.textContent("#foot") };
  }],
]) {
  const p = await b.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(String(e)));
  p.on("console", (m) => { if (m.type() === "error") errors.push("console:" + m.text()); });
  await p.goto(pathToFileURL(join(WEB, file)).href);
  await p.waitForTimeout(400);
  const info = await checks(p);
  await p.waitForTimeout(200);
  const shot = join(WEB, file.replace(".html", ".png"));
  await p.screenshot({ path: shot, fullPage: true });
  if (errors.length) { fail++; console.log(`✗ ${file} ERRORS:`, errors.slice(0, 5)); }
  else console.log(`✓ ${file}`, JSON.stringify(info));
  await p.close();
}
await b.close();
process.exit(fail ? 1 : 0);
