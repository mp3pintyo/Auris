// Reference check UX. Requires the isolated ui_fixture_server.py and local Playwright:
//   set AURIS_QA_DATA=<dir> & set AURIS_QA_PORT=17896 & .venv\Scripts\python.exe tests\ui_fixture_server.py
//   set AURIS_QA_URL=http://127.0.0.1:17896 & node tests\reference_check.playwright.cjs
// The check endpoint is answered by the test (no speech recognizer); trimming runs for real.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const base = process.env.AURIS_QA_URL || 'http://127.0.0.1:17896';
const out = process.env.AURIS_QA_SHOTS || path.join(os.tmpdir(), 'auris-reference-check-qa');
fs.mkdirSync(out, { recursive: true });

function toneWav(seconds, rate = 24000) {
  const n = Math.round(seconds * rate);
  const buffer = Buffer.alloc(44 + n * 2);
  buffer.write('RIFF', 0); buffer.writeUInt32LE(36 + n * 2, 4); buffer.write('WAVE', 8);
  buffer.write('fmt ', 12); buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24); buffer.writeUInt32LE(rate * 2, 28); buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36); buffer.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i += 1) buffer.writeInt16LE(Math.round(Math.sin(i / 8) * 8000), 44 + i * 2);
  return buffer;
}

const LONG_REPORT = {
  duration: 30.0, ok: false, cer: null, heard: 'Első mondat. Második mondat.',
  suggested_text: 'Első mondat. Második mondat.', ref_text: 'Első mondat. Második mondat.', ref_text_saved: true,
  issues: [{ code: 'too_long', level: 'error', message: 'A felvétel 30,0 s hosszú. 15 másodperc felett a klón romlik.' }],
  candidates: [
    { start: 2.0, end: 14.5, duration: 12.5, text: 'Első mondat.' },
    { start: 14.5, end: 26.0, duration: 11.5, text: 'Második mondat, amely jóval hosszabb, hogy a sortörés is látszódjon keskeny kijelzőn.' },
  ],
};
const OK_REPORT = { duration: 12.5, ok: true, cer: 0, issues: [], candidates: [], ref_text_saved: false, ref_text: 'Első mondat.' };

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = [];
  try {
    const api = await browser.newContext();
    assert.equal((await (await api.request.get(`${base}/api/qa-fixture`)).json()).fixture, true);
    const preview = await (await api.request.post(`${base}/api/import/preview`, { multipart: {
      file: { name: 'referencia.txt', mimeType: 'text/plain', buffer: Buffer.from(`Referencia próba ${Date.now()}\n\nElső fejezet\n\nSzöveg.`) },
    } })).json();
    const imported = await (await api.request.post(`${base}/api/import/confirm`, { data: { token: preview.token, title: 'Referencia próba', narration_mode: 'single' } })).json();
    const bookId = imported.book_id || imported.id;
    assert.ok(bookId, JSON.stringify(imported));
    const upload = await api.request.post(`${base}/api/books/${bookId}/narrator-ref-audio`, { multipart: {
      file: { name: 'hosszu.wav', mimeType: 'audio/wav', buffer: toneWav(30) }, ref_text: '', clean: '0',
    } });
    assert.equal(upload.status(), 200, await upload.text());

    for (const [label, viewport] of [['desktop', { width: 1365, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
      const page = await (await browser.newContext({ viewport })).newPage();
      page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
      page.on('console', (m) => { if (m.type() === 'error') errors.push(`${label}: ${m.text()}`); });
      let checks = 0;
      await page.route('**/narrator-ref-audio/check', async (route) => {
        checks += 1;
        await new Promise((resolve) => setTimeout(resolve, 300));
        await route.fulfill({ json: checks === 1 ? LONG_REPORT : OK_REPORT });
      });
      await page.goto(`${base}/voice-studio/${bookId}`);
      const button = page.locator('#check-ref-narrator');
      assert.equal(await button.isDisabled(), false);
      await button.click();
      const panel = page.locator('#ref-check-narrator');
      await panel.waitFor({ state: 'visible' });
      await page.waitForFunction(() => document.querySelector('#ref-check-narrator').classList.contains('is-error'));
      assert.match(await panel.innerText(), /rontja a klónt/);
      assert.match(await panel.innerText(), /beszédfelismerő töltötte ki/);
      assert.equal(await page.locator('#narrator-ref-text').inputValue(), LONG_REPORT.ref_text);
      assert.equal(await panel.locator('.reference-cut').count(), 2);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no horizontal scroll');
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, `${label}-01-long-reference.png`) });

      if (label === 'desktop') {
        await page.route('**/narrator-ref-audio/audition', async (route) => {
          const body = route.request().postDataJSON();
          assert.equal(body.candidates.length, 2);
          await new Promise((resolve) => setTimeout(resolve, 300));
          await route.fulfill({ json: { sentences: 4, takes: 2, recommended: 1, results: [
            { index: 0, start: 2, end: 14.5, text: 'Első mondat.', similarity: 0.871, wer: 0.031, recommended: false },
            { index: 1, start: 14.5, end: 26, text: 'Második mondat.', similarity: 0.899, wer: 0.0, recommended: true },
          ] } });
        });
        await panel.locator('[data-action=ref-audition]').click();
        await panel.locator('.reference-cut.is-recommended').waitFor();
        assert.match(await panel.locator('.reference-cut.is-recommended').innerText(), /Ajánlott/);
        assert.match(await panel.locator('.reference-cut').first().innerText(), /Hasonlóság 0,871 · szóhiba 3,1 %/);
        assert.equal(await panel.locator('[data-action=ref-audition]').count(), 0);
        await page.screenshot({ path: path.join(out, `${label}-01b-audition.png`) });
        await panel.locator('[data-action=ref-span-use]').first().click();
        await page.waitForFunction(() => document.querySelector('#ref-check-narrator').classList.contains('is-ok'));
        assert.match(await page.locator('#narrator-ref-name').innerText(), /2,0–14,5 s/);
        assert.equal(await page.locator('#narrator-ref-text').inputValue(), 'Első mondat.');
        assert.match(await panel.innerText(), /rendben \(12,5 s\)/);
        await page.screenshot({ path: path.join(out, `${label}-02-trimmed.png`) });
      }
      await page.close();
    }
    assert.deepEqual(errors, []);
    console.log(`reference check UX OK; screenshots in ${out}`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
