const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('playwright');

(async () => {
  const base = process.env.AURIS_QA_URL || 'http://127.0.0.1:17861';
  const out = process.env.AURIS_SCREENSHOT_DIR;
  if (!out) throw new Error('Set AURIS_SCREENSHOT_DIR');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.AURIS_BROWSER_EXECUTABLE || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    assert.equal((await (await page.request.get(base + '/api/qa-fixture')).json()).fixture, true);
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/settings', { waitUntil: 'networkidle' });
    await page.evaluate(() => showSettingsCategory('output'));
    await page.locator('#tts-accel').selectOption('eager');
    await page.evaluate(() => saveSettings());
    await page.waitForTimeout(500);
    const saved = await (await page.request.get(base + '/api/settings')).json();
    assert.equal((saved.settings || saved).tts_accel, 'eager');
    for (const [backend, label] of [['cuda','NVIDIA CUDA'],['rocm','AMD ROCm'],['mps','Apple Metal (MPS)']]) {
      await page.evaluate(backend => refreshAccelStatus({ engine: 'omnivoice', state: 'ready',
        accel: { effective: backend === 'cuda' ? 'cuda_graph' : 'eager',
          dtype: backend === 'mps' ? 'torch.float32' : 'torch.bfloat16',
          probe: { backend, device_name: backend === 'cuda' ? 'NVIDIA GeForce RTX 3090' : '', platform: backend === 'mps' ? 'Darwin' : 'Windows' } } }), backend);
      assert.ok((await page.locator('#tts-accel-status').textContent()).includes(label));
      await page.locator('#tts-accel-hint').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, `settings-${backend}.png`) });
    }
    await page.goto(base + '/docs#performance', { waitUntil: 'networkidle' });
    await page.locator('#performance h3').filter({ hasText: 'Új mérési eredmények' }).scrollIntoViewIfNeeded();
    await page.locator('#performance-platforms').screenshot({ path: path.join(out, 'performance-docs.png') });
    const linksValid = await page.evaluate(() => [...document.querySelectorAll('a[href^="#"]')].every(a => {
      const id = a.getAttribute('href').slice(1);
      return !id || [...document.querySelectorAll('[id]')].filter(e => e.id === id).length === 1;
    }));
    assert.ok(linksValid, 'Documentation anchors resolve uniquely');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/settings', { waitUntil: 'networkidle' });
    await page.evaluate(() => showSettingsCategory('output'));
    await page.locator('#tts-accel').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#tts-accel').inputValue(), 'eager');
    await page.screenshot({ path: path.join(out, 'settings-mobile.png') });
    assert.deepEqual(errors, []);
    console.log('PASS: acceleration save, NVIDIA/AMD/MPS status, docs anchors, desktop/mobile; no console errors');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
