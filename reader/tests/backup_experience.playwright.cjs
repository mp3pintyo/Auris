// Only the isolated ui_fixture_server.py is accepted; this replaces its test library.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
(async () => {
  const base = process.env.AURIS_QA_URL || "http://127.0.0.1:17861";
  const out =
    process.env.AURIS_QA_OUTPUT ||
    path.join(
      require("node:os").tmpdir(),
      "auris-implementation-qa",
      "screens",
    );
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  try {
    const marker = await page.request.get(base + "/api/qa-fixture");
    assert.equal(marker.ok() && (await marker.json()).fixture, true);
    const books = await (await page.request.get(base + "/api/books")).json();
    assert.ok(books.length, "run browser_experience.cjs first");
    const book = books[0];
    await page.goto(base + "/settings#storage");
    await page.locator("#settings-storage").waitFor({ state: "visible" });
    await page.locator("#backup-audio").check();
    const downloaded = page.waitForEvent("download");
    await page.locator("#backup-btn").click();
    const backup = await downloaded;
    const archive = path.join(out, "qa-backup.zip");
    await backup.saveAs(archive);
    const edited = await page.request.patch(
      base + `/api/books/${book.id}/metadata`,
      { data: { title: "Ideiglenes cím" } },
    );
    assert.equal(edited.ok(), true);
    await page.locator("#restore-file").setInputFiles(archive);
    await page.locator("#restore-confirm").fill("VISSZAÁLLÍTÁS");
    await page.locator("#restore-btn").click();
    await page.waitForFunction(() =>
      document
        .getElementById("storage-message")
        .textContent.includes("könyv visszaállítva"),
    );
    const restored = await (await page.request.get(base + "/api/books")).json();
    assert.equal(restored.find((b) => b.id === book.id).title, book.title);
    assert.equal(
      (await (await page.request.get(base + "/api/jobs")).json()).length,
      0,
    );
    await page.screenshot({
      path: path.join(out, "08-backup-restored.png"),
      fullPage: true,
    });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, books: restored.length, errors }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
