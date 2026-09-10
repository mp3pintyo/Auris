// Run against the isolated fixture server, never a personal library.
// NODE_PATH must resolve a local Playwright install; AURIS_QA_URL defaults to 17861.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

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
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  const shot = async (name) => {
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.join(out, name + ".png"),
      fullPage: false,
    });
  };
  try {
    const marker = await page.request.get(base + "/api/qa-fixture");
    assert.equal(
      marker.ok() && (await marker.json()).fixture,
      true,
      "Requires isolated fixture server",
    );
    await page.goto(base + "/");
    await page
      .getByRole("heading", { name: "Könyvtár", exact: true })
      .waitFor();
    await page.locator(".loading-spinner").waitFor({ state: "detached" });
    await shot("01-library");
    const unique = Date.now();
    const text = `Próbatörténet ${unique}\n\nI. FEJEZET\n\nGorcsev belépett a csendes szobába. Az ablakon túl ősz volt, a fák levelei sárgán ragyogtak. A könyv az asztalon feküdt, és egy új történetre várt.\n\nII. FEJEZET\n\nMásnap Gorcsev útnak indult. A városban mindenkinek akadt dolga, mégis volt idő egy rövid beszélgetésre. A történet lassan folytatódott a folyó mellett.`;
    await page
      .locator("#file-input")
      .setInputFiles({
        name: "magyar-proba.txt",
        mimeType: "text/plain",
        buffer: Buffer.from(text),
      });
    await page.locator("#import-dialog").waitFor({ state: "visible" });
    await shot("02-import-preview");
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#import-dialog").isVisible(),
      false,
      "Escape closes native import dialog",
    );
    await page
      .locator("#file-input")
      .setInputFiles({
        name: "magyar-proba.txt",
        mimeType: "text/plain",
        buffer: Buffer.from(text),
      });
    await page.locator("#import-dialog").waitFor({ state: "visible" });
    const title = "Magyar tesztkönyv " + unique;
    await page.locator("#import-title").fill(title);
    await page.locator("#import-author").fill("Teszt Szerző");
    await page.locator("#import-language").selectOption("hu");
    await page.getByRole("button", { name: "Hozzáadás", exact: true }).click();
    await page.locator("#import-dialog").waitFor({ state: "hidden" });
    await page.locator("#library-search").fill(title);
    await page.locator(".book-card").first().waitFor();
    assert.equal(await page.locator(".book-card").count(), 1);
    await page.getByRole("button", { name: "Adatok", exact: true }).click();
    await page.locator("#details-collection").fill("Próbák");
    await page
      .locator("#book-details")
      .getByRole("button", { name: "Mentés", exact: true })
      .click();
    await page.locator("#book-details").waitFor({ state: "hidden" });
    await page.locator("#library-collection").selectOption({ label: "Próbák" });
    const readerPath = await page
      .locator(".book-actions a")
      .first()
      .getAttribute("href");
    const bid = readerPath.split("/").pop();
    await page.goto(base + "/settings#dictionary");
    await page.locator("#settings-dictionary").waitFor({ state: "visible" });
    await page
      .locator("#dictionary-book option")
      .filter({ hasText: title })
      .waitFor({ state: "attached" });
    await page.locator("#dictionary-book").selectOption(bid);
    await page.locator("#dictionary-source").fill("Gorcsev");
    await page.locator("#dictionary-replacement").fill("Gorcsef");
    await page
      .getByRole("button", { name: "Szabály mentése", exact: true })
      .click();
    await page.locator(".dictionary-row").first().waitFor();
    await page
      .getByRole("button", { name: "Felolvasandó szöveg ellenőrzése" })
      .click();
    await page.waitForFunction(() =>
      document
        .getElementById("dictionary-preview-output")
        .textContent.includes("Gorcsef"),
    );
    await shot("03-dictionary");
    await page.goto(base + readerPath);
    await page.locator(".sentence").first().waitFor();
    await shot("04-reader");
    assert.ok(
      (await page.locator("#chapter-content").innerText()).includes("Gorcsev"),
      "original spelling stays visible",
    );
    await page.locator("#export-btn").click();
    await page.locator("#export-preset").selectOption("book-m4b");
    await page.locator("#do-export-btn").click();
    const resultLink = page.locator('#export-links a[href^="/api/"]').first();
    await resultLink.waitFor({ timeout: 60000 });
    const downloadUrl = await resultLink.getAttribute("href");
    const download = await page.request.get(base + downloadUrl);
    assert.equal(download.ok(), true, "completed export downloads");
    assert.ok((await download.body()).length > 100, "export is nonempty");
    await shot("04b-export-complete");
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await page.locator(".sentence").first().waitFor();
    await shot("05-reader-mobile");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    );
    assert.equal(overflow, false, "no horizontal mobile overflow");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + "/settings#setup");
    await page.locator("#settings-setup").waitFor({ state: "visible" });
    await shot("06-setup");
    await page.goto(base + "/jobs");
    await page
      .getByRole("heading", { name: "Feladatok", exact: true })
      .waitFor();
    await shot("07-jobs");
    fs.writeFileSync(
      path.join(out, "console-errors.json"),
      JSON.stringify(errors, null, 2),
    );
    assert.deepEqual(errors, [], "browser errors");
    console.log(
      JSON.stringify({ ok: true, book_id: bid, screens: out, errors }),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
