// Requires the isolated ui_fixture_server.py and a local Playwright installation.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const base = process.env.AURIS_QA_URL || 'http://127.0.0.1:17861';
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    const marker = await page.request.get(base + '/api/qa-fixture');
    assert.equal(marker.ok() && (await marker.json()).fixture, true);
    const books = await (await page.request.get(base + '/api/books')).json();
    let book, chapters;
    for (const item of books) {
      const list = await (await page.request.get(`${base}/api/books/${item.id}/chapters`)).json();
      if (list.length >= 2) { book = item; chapters = list; break; }
    }
    assert.ok(book, 'Fixture requires a book with at least two chapters');
    await page.goto(base);
    await page.locator('.loading-spinner').waitFor({ state: 'detached' });
    await page.evaluate(id => openBookDetails(id), book.id);
    await page.locator('#details-chapter-picker summary').click();
    assert.equal(await page.locator('#details-chapters input').count(), chapters.length);
    assert.equal(await page.locator('#reanalyze-selected').isDisabled(), true);
    await page.locator('#details-chapters input').nth(1).check();
    let body;
    await page.route(`**/api/books/${book.id}/reanalyze`, route => {
      body = route.request().postDataJSON();
      return route.fulfill({ json: { job_id: 'fixture-selection', status: 'pending' } });
    });
    await page.locator('#reanalyze-selected').click();
    await page.getByText('Az újraelemzés elindult. A Feladatok oldalon követheted.').waitFor();
    assert.deepEqual(body, { failed_only: false, chapter_ids: [chapters[1].id] });
    await page.screenshot({ path: path.join(require('node:os').tmpdir(), 'auris-implementation-qa', 'screens', '13-selected-reanalysis.png') });
    await page.keyboard.press('Escape');
    await page.evaluate(id => openBookDetails(id), book.id);
    assert.equal(await page.locator('#details-chapters input:checked').count(), 0);
    assert.equal(await page.locator('#reanalyze-selected').isDisabled(), true);
    assert.deepEqual(errors, []);
    console.log('PASS: selected chapter payload, empty selection, reset, console errors: 0');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
