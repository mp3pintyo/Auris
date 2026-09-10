const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const readerUrl = process.env.AURIS_READER_URL;
if (!readerUrl) {
  throw new Error('Set AURIS_READER_URL to an isolated /reader/<id> test page.');
}

const screenshotDir = process.env.AURIS_SCREENSHOT_DIR || os.tmpdir();
const browserExecutable = process.env.AURIS_BROWSER_EXECUTABLE ||
  'C:/Program Files/Google/Chrome/Application/chrome.exe';

async function openReader(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.goto(readerUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('#chapter-content .sentence').first().waitFor({ timeout: 20_000 });
  return { context, page, consoleErrors };
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: browserExecutable,
  });
  try {
    const desktop = await openReader(browser, { width: 1440, height: 900 });
    const { page } = desktop;
    assert.match(await page.title(), /Auris/);
    assert.ok((await page.locator('#chapter-content').innerText()).trim().length > 20);

    const speakerLabels = page.locator('.speaker-label');
    if (!await speakerLabels.count()) {
      await page.evaluate(() => {
        speakerCharacters = [{ name: 'Anna', frequency: 2, color_hex: '#c8a46e' }];
        segments = [
          {
            segment_index: 0, text: 'Az első megszólalás.', character_name: 'Anna',
            is_dialogue: true, has_audio: false, duration_sec: null, cache_key: null,
            unit_index: 0, speaker_candidate: true, speaker_source: 'manual',
            speaker_turn_index: 0, speaker_continuation: false, ends_paragraph: false,
          },
          {
            segment_index: 1, text: 'A második mondat is hozzá tartozik.', character_name: 'Anna',
            is_dialogue: true, has_audio: false, duration_sec: null, cache_key: null,
            unit_index: 1, speaker_candidate: true, speaker_source: 'manual',
            speaker_turn_index: 0, speaker_continuation: true, ends_paragraph: true,
          },
          {
            segment_index: 2, text: 'Ez már narráció.', character_name: null,
            is_dialogue: false, has_audio: false, duration_sec: null, cache_key: null,
            unit_index: 2, speaker_candidate: false, speaker_source: null,
            speaker_turn_index: null, speaker_continuation: false, ends_paragraph: true,
          },
        ];
        renderContent(segments);
        showSpeakerLabels = false;
        applySpeakerLabelPreference();
      });
    }
    assert.equal(await speakerLabels.first().isVisible(), false);
    if (await page.locator('#speaker-label-toggle').count()) {
      await page.locator('#speaker-label-toggle').click();
    } else {
      await page.evaluate(() => {
        showSpeakerLabels = true;
        applySpeakerLabelPreference();
      });
    }
    assert.equal(await speakerLabels.first().isVisible(), true);
    await speakerLabels.first().click();
    assert.match(await page.locator('#speaker-editor-quote').innerText(), /első.*második/is);
    const range = await page.locator('#speaker-range-end').evaluate(input => ({
      min: Number(input.min),
      max: Number(input.max),
      value: Number(input.value),
    }));
    assert.equal(range.value, range.min + 1);
    assert.ok(range.value <= range.max);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#speaker-editor-overlay').evaluate(el => el.classList.contains('hidden')), true);
    await page.evaluate(() => {
      segments[2].speaker_source = 'manual';
      renderContent(segments);
      showSpeakerLabels = true;
      applySpeakerLabelPreference();
    });
    assert.equal(
      (await page.locator('.sentence[data-idx="2"] .speaker-label').innerText()).trim(),
      'Narráció',
    );
    await page.evaluate(() => localStorage.removeItem('showSpeakerLabels'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#chapter-content .sentence').first().waitFor({ timeout: 20_000 });

    await page.locator('#book-search-btn').click();
    assert.equal(await page.locator('#book-search-input').evaluate(el => el === document.activeElement), true);
    await page.locator('#book-search-close').focus();
    await page.keyboard.press('Shift+Tab');
    assert.equal(
      await page.locator('#book-search-form button[type="submit"]').evaluate(el => el === document.activeElement),
      true,
    );

    const query = await page.locator('.sentence-text').first().innerText()
      .then(text => (text.match(/[\p{L}\p{N}]{2,}/u) || [''])[0]);
    assert.ok(query.length >= 2);
    await page.locator('#book-search-input').fill(query);
    await page.locator('#book-search-form').evaluate(form => form.requestSubmit());
    await page.locator('.search-result').first().waitFor({ timeout: 10_000 });
    assert.match(await page.locator('#book-search-status').innerText(), /találat/);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#book-search-overlay').evaluate(el => el.classList.contains('hidden')), true);
    assert.equal(await page.locator('#book-search-btn').evaluate(el => el === document.activeElement), true);

    await page.locator('#export-btn').focus();
    await page.keyboard.press('Space');
    assert.equal(await page.locator('#btn-play').getAttribute('aria-label'), 'Lejátszás');
    assert.equal(await page.locator('#export-dropdown').evaluate(el => el.classList.contains('hidden')), false);
    await page.locator('#export-preset').selectOption('book-m4b');
    assert.equal(await page.locator('input[name="exp-mode"][value="chapterwise"]').isChecked(), true);
    assert.equal(await page.locator('input[name="exp-audio"][value="m4b"]').isChecked(), true);
    assert.equal(await page.locator('#exp-chapter-list input').count(), await page.locator('.toc-item').count());
    const chapterListLayout = await page.locator('#exp-chapter-list').evaluate(list => {
      const bounds = list.getBoundingClientRect();
      return [...list.querySelectorAll('label span')].map(span => {
        const rect = span.getBoundingClientRect();
        return {
          text: span.textContent.trim(),
          width: rect.width,
          inside: rect.left >= bounds.left && rect.right <= bounds.right,
        };
      });
    });
    assert.ok(
      chapterListLayout.every(item => item.text && item.width > 20 && item.inside),
      `Chapter selection layout: ${JSON.stringify(chapterListLayout)}`,
    );

    await page.screenshot({
      path: path.join(screenshotDir, 'auris-reader-desktop.png'),
      fullPage: false,
    });
    assert.deepEqual(desktop.consoleErrors, []);
    await desktop.context.close();

    const mobile = await openReader(browser, { width: 390, height: 844 });
    assert.equal(
      await mobile.page.locator('#toc-sidebar').evaluate(el => el.classList.contains('collapsed')),
      true,
    );
    const touchSizes = await mobile.page.locator('.playback-bar button:visible').evaluateAll(buttons =>
      buttons.map(button => {
        const rect = button.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      })
    );
    const touchMedia = await mobile.page.evaluate(() => ({
      width: innerWidth,
      narrow: matchMedia('(max-width: 760px)').matches,
      styles: [...document.styleSheets].map(sheet => sheet.href),
    }));
    assert.ok(touchSizes.length >= 6);
    assert.ok(
      touchSizes.every(size => size.width >= 44 && size.height >= 44),
      `Playback touch targets: ${JSON.stringify(touchSizes)}; ${JSON.stringify(touchMedia)}`,
    );
    await mobile.page.screenshot({
      path: path.join(screenshotDir, 'auris-reader-mobile.png'),
      fullPage: false,
    });
    assert.deepEqual(mobile.consoleErrors, []);
    await mobile.context.close();
  } finally {
    await browser.close();
  }
  process.stdout.write(`Reader Playwright QA passed. Screenshots: ${screenshotDir}\n`);
})().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
