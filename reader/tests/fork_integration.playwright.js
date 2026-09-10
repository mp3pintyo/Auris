'use strict';

const assert = require('node:assert/strict');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const baseUrl = process.env.AURIS_BASE_URL || 'http://127.0.0.1:17861';
const screenshotDir = process.env.AURIS_SCREENSHOT_DIR || os.tmpdir();

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', error => errors.push(error.message));

  await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' });
  assert.match(await page.locator('.empty-library, body').first().textContent(), /PRC\/MOBI|Magyar próbakönyv/);
  assert.match(await page.locator('#file-input').getAttribute('accept'), /\.mobi/);
  await page.screenshot({ path: path.join(screenshotDir, 'auris-library-fork-integration.png'), fullPage: true });

  await page.goto(`${baseUrl}/voice-studio/1`, { waitUntil: 'networkidle' });
  await page.locator('#voice-preview-text').waitFor();
  assert.equal(await page.locator('#voice-preview-text').getAttribute('maxlength'), '1500');
  await page.locator('.narrator-card .technical-panel summary').click();
  assert.equal(await page.locator('#narrator-download-btn').isVisible(), true);
  assert.equal(await page.getByText('Profil importálása', { exact: true }).isVisible(), true);
  await page.screenshot({ path: path.join(screenshotDir, 'auris-voice-studio-fork-integration.png'), fullPage: true });

  await page.goto(`${baseUrl}/settings`, { waitUntil: 'networkidle' });
  await page.getByRole('tab', { name: 'Tárhely és mentés' }).click();
  await page.locator('#audio-cache-summary').waitFor();
  assert.match(await page.locator('#audio-cache-summary').textContent(), /WAV/);
  assert.equal(await page.locator('#audio-cache-cleanup').isVisible(), true);
  await page.screenshot({ path: path.join(screenshotDir, 'auris-settings-cache.png'), fullPage: true });

  assert.deepEqual(errors, []);
  await browser.close();
  process.stdout.write(`Fork integration Playwright QA passed. Screenshots: ${screenshotDir}\n`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
