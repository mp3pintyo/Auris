// Requires the isolated fixture server, with AURIS_QA_AUDIO_SECONDS=8.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const base = process.env.AURIS_QA_URL || 'http://127.0.0.1:17863';
  const out = path.join(require('node:os').tmpdir(), 'auris-33-qa', 'screens');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const page = await browser.newPage({viewport: {width: 1365, height: 1000}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    assert.equal((await (await page.request.get(base + '/api/qa-fixture')).json()).fixture, true);
    const preview = await (await page.request.post(base + '/api/import/preview', {multipart: {
      file: {name: 'folytatas.txt', mimeType: 'text/plain', buffer: Buffer.from(`Folyatatás ${Date.now()}\n\nElső fejezet\n\nEz egy hosszabb magyar mondat, amelynek a közepén megállítjuk a lejátszást, majd az oldal újratöltése után ugyaninnen folytatjuk.`)}
    }})).json();
    const imported = await (await page.request.post(base + '/api/import/confirm', {data: {token: preview.token, title: 'Pontos folytatás', narration_mode: 'single'}})).json();
    const bid = imported.book_id || imported.id;
    assert.ok(bid, JSON.stringify(imported));
    await page.goto(base + '/');
    await page.waitForFunction(() => typeof libraryBooks !== 'undefined' && libraryBooks.length > 0);
    await page.evaluate(id => openBookDetails(id), bid);
    await page.locator('#details-series').fill('Magyar sorozat');
    await page.locator('#details-series-index').fill('2.5');
    await page.locator('#details-publisher').fill('Próba kiadó');
    await page.locator('#details-published').fill('2026');
    await page.locator('#details-description').fill('Árvíztűrő tükörfúrógép – könyvleírás.');
    await page.screenshot({path: path.join(out, 'metadata.png')});
    await page.locator('#book-details button[type=submit], #book-details .modal-footer .btn-primary').click();
    await page.locator('#book-details').waitFor({state: 'hidden'});
    const book = await (await page.request.get(base + '/api/books/' + bid + '/metadata')).json();
    assert.equal(book.series_index, '2.5');
    assert.equal(book.publisher, 'Próba kiadó');
    await page.locator('#import-options summary').click();
    await page.locator('#import-ocr').check();
    await page.locator('#import-ocr-language').selectOption('hun+eng');
    await page.screenshot({path: path.join(out, 'import-tools.png')});
    if (process.env.AURIS_QA_OCR_FILE) {
      await page.locator('#import-ocr-language').selectOption('hun');
      await page.locator('#file-input').setInputFiles(process.env.AURIS_QA_OCR_FILE);
      await page.locator('#import-dialog').waitFor({state: 'visible'});
      assert.ok((await page.locator('#import-sample').textContent()).includes('Árvíztűrő tükörfúrógép'));
      await page.screenshot({path: path.join(out, 'hungarian-ocr.png')});
      await page.keyboard.press('Escape');
    }

    await page.goto(base + '/reader/' + bid);
    await page.waitForFunction(() => typeof segments !== 'undefined' && segments.length > 0);
    await page.evaluate(async () => { await playSegment(0); audio.currentTime = 3.25; pausePlayback(); flushProgressSave({force: true}); });
    await page.waitForTimeout(400);
    let saved = await (await page.request.get(base + `/api/books/${bid}/progress`)).json();
    assert.ok(saved.offset_sec >= 3 && saved.offset_sec < 4, JSON.stringify(saved));
    assert.ok(saved.cache_key);
    await page.reload();
    await page.waitForFunction(() => typeof _savedAudioResume !== 'undefined' && _savedAudioResume?.offset > 0);
    await page.evaluate(async () => { await resumePlayback(); pausePlayback(); });
    const resumed = await page.evaluate(() => audio.currentTime);
    assert.ok(resumed >= 3 && resumed < 4, `resumed at ${resumed}`);
    await page.screenshot({path: path.join(out, 'resume.png')});

    await page.goto(base + '/settings');
    await page.locator('[data-settings-target=storage]').click();
    await page.waitForFunction(() => typeof backupScheduleLoaded !== 'undefined' && backupScheduleLoaded);
    await page.locator('#backup-frequency').selectOption('daily');
    await page.locator('#backup-keep').fill('3');
    await page.getByRole('button', {name: 'Ütemezés mentése', exact: true}).click();
    await page.waitForFunction(() => document.getElementById('backup-schedule-message').textContent.includes('mentve'));
    const previousSuccess = (await (await page.request.get(base + '/api/backup/schedule')).json()).last_success || 0;
    await page.locator('#backup-run-now').click();
    await page.waitForFunction(async previous => { const s = await (await fetch('/api/backup/schedule')).json(); return s.last_success > previous && !s.running; }, previousSuccess);
    await page.evaluate(() => loadBackupSchedule());
    let state = await (await page.request.get(base + '/api/backup/schedule')).json();
    assert.equal(state.keep, 3);
    assert.ok(state.last_success);
    assert.equal(state.last_error, '');
    assert.equal((await page.request.get(base + state.files[0].download)).status(), 200);
    await page.locator('#backup-schedule-status').evaluate(el => el.scrollIntoView({block: 'center'}));
    await page.waitForTimeout(600);
    await page.screenshot({path: path.join(out, 'scheduled-backup.png')});
    await page.goto(base + '/docs#import-tools');
    await page.locator('#import-tools').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#import-tools').count(), 1);
    const docLinks = await page.evaluate(() => {
      const ids = Array.from(document.querySelectorAll('[id]'), el => el.id);
      return {duplicates: ids.filter((id, i) => ids.indexOf(id) !== i),
        broken: Array.from(document.querySelectorAll('.docs-toc a[href^="#"]'), el => el.hash.slice(1)).filter(id => !ids.includes(id))};
    });
    assert.deepEqual(docLinks, {duplicates: [], broken: []});
    await page.screenshot({path: path.join(out, 'docs.png')});
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(base + '/');
    await page.locator('#import-options summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({path: path.join(out, 'mobile-import.png')});
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, resumed, screenshots: out, consoleErrors: errors}));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
