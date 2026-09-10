const { chromium } = require("playwright");
const assert = require("node:assert/strict");
(async () => {
  const base = process.env.AURIS_QA_URL || "http://127.0.0.1:17861";
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 768, height: 1024 },
    });
    const marker = await page.request.get(base + "/api/qa-fixture");
    assert.equal(marker.ok() && (await marker.json()).fixture, true);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    await page.goto(base + "/reader/1");
    await page.locator(".sentence").first().waitFor();
    assert.equal(
      await page
        .locator("#toc-sidebar")
        .evaluate((e) => e.classList.contains("collapsed")),
      true,
      "tablet TOC starts closed",
    );
    await page.locator("#export-btn").click();
    await page.route("**/api/books/*/export/chapter/*", (route) =>
      route.fulfill({ json: { job_id: "qa-terminal" } }),
    );
    for (const state of ["cancelled", "interrupted"]) {
      await page.route("**/api/export/status/qa-terminal", (route) =>
        route.fulfill({ json: { state, total: 1, done: 0 } }),
      );
      await page.locator("#do-export-btn").click();
      await page.waitForFunction(
        () =>
          !document.getElementById("do-export-btn").disabled && !_exportBusy,
      );
      assert.ok(
        (await page.locator("#export-status").innerText()).includes(
          "Feladatok",
        ),
      );
      await page.unroute("**/api/export/status/qa-terminal");
      await page.route("**/api/chapter-generation/status/qa-chapter", (route) =>
        route.fulfill({ json: { state, total: 1, done: 0 } }),
      );
      await page.evaluate(() =>
        monitorChapterGeneration("qa-chapter", currentChapterId),
      );
      assert.equal(await page.evaluate(() => _exportBusy), false);
      assert.equal(await page.evaluate(() => _activeChapterGeneration), null);
      await page.unroute("**/api/chapter-generation/status/qa-chapter");
    }
    assert.deepEqual(errors, []);
    await page.screenshot({
      path: require("node:path").join(
        require("node:os").tmpdir(),
        "auris-job-terminal-tablet.png",
      ),
      fullPage: true,
    });
    console.log(
      "Cancelled/interrupted release reader controls; tablet TOC closed; console errors 0",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
