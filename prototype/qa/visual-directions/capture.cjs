const { chromium } = require('../../../frontend/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');

(async () => {
  const prototype = path.resolve(__dirname, '../..');
  const sourceFiles = ['01-core-learning.html', 'assets/style.css', 'assets/refined-footer.css', 'assets/ui.js', 'assets/screens.js', 'assets/footer-theme.js', 'assets/app.js'];
  const hashes = () => Object.fromEntries(sourceFiles.map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(path.join(prototype, file))).digest('hex')]));
  const before = hashes();
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1200 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const target = pathToFileURL(path.join(prototype, '08-visual-directions.html')).href;
    await page.goto(target);
    console.log('Preview loaded');
    await page.evaluate(() => Promise.all(Array.from(document.images, image => { image.loading = 'eager'; return image.decode().catch(() => {}); })));
    const checks = [];
    for (const [screen, filename] of [['L02', '01-document'], ['L09', '02-question'], ['L15', '03-result']]) {
      console.log(`Capturing ${screen}`);
      await page.locator(`[data-screen="${screen}"]`).click();
      await page.evaluate(() => Promise.all(Array.from(document.images, image => { image.loading = 'eager'; return image.decode().catch(() => {}); })));
      await page.locator('.proposal-grid').screenshot({ path: path.join(__dirname, `${filename}.png`) });
      console.log(`Captured ${screen}`);
      checks.push(await page.evaluate(() => ({
        screen: document.querySelector('[data-screen][aria-pressed="true"]').dataset.screen,
        phones: document.querySelectorAll('.phone').length,
        imagesLoaded: [...document.images].every(image => image.complete && image.naturalWidth > 0),
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        scrollAreas: [...document.querySelectorAll('.phone-scroll')].map(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth, height: el.clientHeight, scrollHeight: el.scrollHeight })),
        headers: [...document.querySelectorAll('.mini-bar')].map(el => getComputedStyle(el).backgroundColor)
      })));
    }
    await page.locator('.original-toggle').click();
    checks.push({ originalToggle: await page.locator('.proposal.original').count() === 3 });
    await page.locator('.original-toggle').click();
    checks.push({ restoredThemes: await page.locator('.theme-a, .theme-b, .theme-c').count() === 3 });
    for (const width of [1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const screen of ['L02', 'L09', 'L15']) {
        await page.locator(`[data-screen="${screen}"]`).click();
        checks.push(await page.evaluate(() => ({ viewport: innerWidth, screen: document.querySelector('[data-screen][aria-pressed="true"]').dataset.screen, horizontalOverflow: document.documentElement.scrollWidth > innerWidth, phoneOverflow: [...document.querySelectorAll('.phone-scroll')].some(el => el.scrollWidth > el.clientWidth + 1) })));
      }
      if (width === 390) {
        await page.locator('[data-screen="L02"]').click();
        await page.screenshot({ path: path.join(__dirname, '04-mobile.png'), fullPage: true });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1200 });
    await page.goto(pathToFileURL(path.join(prototype, '01-core-learning.html')).href + '?screen=L02');
    await page.locator('.phone').screenshot({ path: path.join(__dirname, '00-original-document.png') });
    const after = hashes();
    const report = { errors, checks, originalsUnchanged: JSON.stringify(before) === JSON.stringify(after), originalHashes: after };
    fs.writeFileSync(path.join(__dirname, 'verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
    if (errors.length || checks.some(check => check.horizontalOverflow || check.phoneOverflow || check.imagesLoaded === false) || !report.originalsUnchanged) process.exitCode = 1;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
