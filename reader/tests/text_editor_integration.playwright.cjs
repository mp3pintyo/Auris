const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const url = process.env.AURIS_READER_URL;
if (!url) throw new Error('Set AURIS_READER_URL to an isolated fixture reader page. This test edits and restores its chapter.');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    for (const viewport of [{width: 1440, height: 1000}, {width: 390, height: 844}]) {
      const page = await browser.newPage({viewport});
      const errors = [], speech = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      page.on('request', request => { if (request.method() === 'POST' && /tts\/generate|editor\/preview/.test(request.url())) speech.push(request.url()); });
      await page.goto(url, {waitUntil: 'networkidle'});
      await page.locator('#chapter-content .sentence').first().waitFor();
      assert.ok(await page.locator('#chapter-content [role="heading"]').count() >= 1);
      assert.ok(await page.locator('.text-paragraph-break').count() >= 1);
      await page.locator('#text-editor-open').click();
      await page.locator('.editor-block').first().waitFor();
      const textareas = page.locator('.editor-block textarea');
      const original = await textareas.last().inputValue();
      const count = await textareas.count();
      assert.equal(await page.locator('.editor-block details[open]').count(), 0);
      await textareas.last().fill('Javított ellenőrző szöveg. A bekezdés megmarad.');
      page.once('dialog', dialog => dialog.dismiss());
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#text-editor').evaluate(el => el.open), true);
      await page.locator('.editor-block summary').last().click();
      await page.locator('[data-field="pause_ms"]').last().fill('1250');
      const savedResponse = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().endsWith('/editor'));
      await page.locator('[data-action="save"]').click();
      const saved = await (await savedResponse).json();
      assert.equal(saved.blocks.at(-1).pause_ms, 1250);
      await page.waitForFunction(() => document.querySelector('#editor-status').textContent.startsWith('Elmentve'));
      assert.match(await page.locator('#chapter-content').innerText(), /Javított ellenőrző szöveg/);
      await page.locator('.editor-block summary').last().click();
      await page.screenshot({path: path.join(os.tmpdir(), `auris-text-editor-integrated-${viewport.width}.png`), fullPage: true});
      assert.equal(await page.locator('#text-editor').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
      page.once('dialog', dialog => dialog.accept());
      await page.locator('[data-action="restore"]').click();
      await page.waitForFunction(() => document.querySelector('#editor-status').textContent.startsWith('Az előző változat visszaállítva'));
      assert.equal(await textareas.count(), count);
      assert.equal(await textareas.last().inputValue(), original);
      await page.locator('[data-action="close"]').first().click();
      assert.match(await page.locator('#chapter-content').innerText(), new RegExp(original.slice(0, 12)));
      assert.deepEqual(speech, [], 'Editing must not automatically start speech synthesis.');
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('Integrated text editor GET/PUT/restore, rendering, desktop/mobile passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
