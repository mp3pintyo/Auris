const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.AURIS_BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      let data = {title: 'Próbafejezet', revision: 0, can_restore: false, speed_supported: false, blocks: [{kind: 'heading', text: 'Első cím', speed: 1.2}, {kind: 'paragraph', text: 'Hibás OCR szöveg. Második mondat.'}]};
      let writes = 0;
      await page.route('http://auris.test/**', async route => {
        const request = route.request();
        if (request.url().endsWith('/editor')) {
          if (request.method() === 'PUT') { const body = request.postDataJSON(); assert.equal(body.revision, data.revision); data = {...body, revision: data.revision + 1, can_restore: true, speed_supported: false, annotations_removed: 2}; writes++; }
          return route.fulfill({json: data});
        }
        if (request.url().endsWith('/progress')) return route.fulfill({json: {chapter_id: 2, position: 1}});
        if (request.url().endsWith('/chapters')) return route.fulfill({json: [{id: 2, title: data.title}]});
        return route.fulfill({contentType: 'text/html', body: '<button id="text-editor-open">Szöveg szerkesztése</button>'});
      });
      await page.goto('http://auris.test/');
      await page.addStyleTag({content: ':root {--bg:#171820;--bg2:#252631;--text:#eee;--text2:#bbb;--border:#555} .btn{padding:8px} body{background:#171820}'});
      await page.addStyleTag({path: path.resolve(__dirname, '../static/css/text-editor.css')});
      await page.addScriptTag({content: 'const BOOK_ID=1; let currentChapterId=2,currentSegIdx=1,chapters=[]; function stopPlayback(){} async function openChapter(){}'});
      await page.addScriptTag({path: path.resolve(__dirname, '../static/js/text-editor.js')});
      await page.locator('#text-editor-open').click();
      await page.locator('.editor-block').nth(1).waitFor();
      assert.equal(await page.locator('.editor-block details[open]').count(), 0);
      assert.equal(await page.locator('[data-field="speed"]').first().isDisabled(), true);
      await page.locator('.editor-block textarea').nth(1).fill('Javított OCR szöveg. Második mondat.');
      page.once('dialog', dialog => dialog.dismiss());
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#text-editor').evaluate(el => el.open), true);
      await page.locator('[data-action="save"]').click();
      await page.waitForFunction(() => document.querySelector('#editor-status').textContent.startsWith('Elmentve'));
      assert.equal(writes, 1);
      assert.equal(data.blocks[0].speed, 1.2, 'Disabled unsupported speed must preserve stored value.');
      assert.match(await page.locator('#editor-status').innerText(), /2 beszélő-hozzárendelést/);
      assert.match(data.blocks[1].text, /^Javított/);
      await page.locator('.editor-block summary').nth(1).click();
      await page.locator('.editor-block [data-field="pause_ms"]').nth(1).fill('0');
      await page.locator('[data-action="save"]').click();
      await page.waitForFunction(() => document.querySelector('#editor-status').textContent.startsWith('Elmentve'));
      assert.equal(data.blocks[1].pause_ms, 0);
      await page.locator('.editor-block summary').nth(1).click();
      await page.locator('.editor-block textarea').nth(1).fill('a'.repeat(1501));
      await page.locator('[data-action="preview"]').nth(1).click();
      assert.match(await page.locator('#editor-status').innerText(), /1500 karakteres/);
      await page.locator('.editor-block textarea').nth(1).fill(data.blocks[1].text);
      assert.equal(await page.locator('#text-editor').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
      await page.screenshot({path: path.join(os.tmpdir(), `auris-text-editor-${viewport.width}.png`), fullPage: true});
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('Text editor desktop/mobile checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
