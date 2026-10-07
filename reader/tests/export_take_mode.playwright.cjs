// Export quality selector. Requires the isolated ui_fixture_server.py and local Playwright:
//   set AURIS_QA_DATA=<dir> & set AURIS_QA_PORT=17896 & .venv\Scripts\python.exe tests\ui_fixture_server.py
//   set AURIS_QA_URL=http://127.0.0.1:17896 & node tests\export_take_mode.playwright.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const base = process.env.AURIS_QA_URL || 'http://127.0.0.1:17896';
const out = process.env.AURIS_QA_SHOTS || path.join(os.tmpdir(), 'auris-export-take-qa');
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [];
  try {
    const api = await browser.newContext();
    const preview = await (await api.request.post(`${base}/api/import/preview`, { multipart: {
      file: { name: 'export.txt', mimeType: 'text/plain', buffer: Buffer.from(`Export próba ${Date.now()}\n\nElső fejezet\n\nEgy mondat.`) },
    } })).json();
    const imported = await (await api.request.post(`${base}/api/import/confirm`, { data: { token: preview.token, title: 'Export próba', narration_mode: 'single' } })).json();
    const bookId = imported.book_id || imported.id;

    let remembered;
    for (const [label, viewport] of [['desktop', { width: 1365, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
      // The mobile pass starts from the desktop pass's storage: the choice is remembered.
      const context = await browser.newContext({ viewport, storageState: remembered });
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
      page.on('console', (m) => { if (m.type() === 'error') errors.push(`${label}: ${m.text()}`); });
      const bodies = [];
      await page.route('**/export/chapter/**', async (route) => {
        bodies.push(route.request().postDataJSON());
        await route.fulfill({ json: { error: 'Teszt: az export nem indul el.' } });
      });
      await page.goto(`${base}/reader/${bookId}`);
      await page.locator('#export-btn').click();
      const select = page.locator('#export-take-mode');
      await select.waitFor({ state: 'visible' });
      assert.equal(await select.inputValue(), remembered ? 'similar10' : 'normal');
      if (!remembered) await select.selectOption('similar10');
      await select.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, `${label}-export-quality.png`) });
      await page.locator('#do-export-btn').click();
      await page.waitForFunction(() => document.getElementById('export-status')?.textContent.includes('Teszt'));
      assert.equal(bodies.length, 1);
      assert.equal(bodies[0].take_mode, 'similar10');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no horizontal scroll');
      remembered = await context.storageState();
      await context.close();
    }
    assert.deepEqual(errors, []);
    console.log(`export take mode UX OK; screenshots in ${out}`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
