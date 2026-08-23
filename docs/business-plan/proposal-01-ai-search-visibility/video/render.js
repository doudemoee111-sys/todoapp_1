const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const FPS = 25;
const OUT = path.join(__dirname, "frames");

(async () => {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({
    executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--force-device-scale-factor=1"],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto("file://" + path.join(__dirname, "scene.html"));
  await page.waitForFunction(() => typeof window.renderFrame === "function");
  await page.waitForTimeout(600); // let webfonts settle

  const total = await page.evaluate(() => window.VIDEO_TOTAL);
  const frames = Math.round(total * FPS);
  console.log(`rendering ${frames} frames @ ${FPS}fps (${total}s)`);

  for (let i = 0; i < frames; i++) {
    const t = i / FPS;
    await page.evaluate((tt) => window.renderFrame(tt), t);
    await page.screenshot({
      path: path.join(OUT, `f${String(i).padStart(5, "0")}.png`),
      animations: "disabled",
    });
    if (i % 100 === 0) console.log(`  ${i}/${frames}`);
  }

  await browser.close();
  console.log("frames done");
})();
