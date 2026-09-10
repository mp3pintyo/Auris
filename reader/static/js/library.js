let libraryBooks = [],
  importPreview = null,
  importSettings = null,
  deletingBook = null;
const $ = (id) => document.getElementById(id);
function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
async function api(url, options) {
  const r = await fetch(url, options);
  let d;
  try {
    d = await r.json();
  } catch {
    throw new Error("A szerver válasza nem olvasható. Próbáld újra.");
  }
  if (!r.ok) throw new Error(d.error || "A művelet nem sikerült.");
  return d;
}
function post(url, data) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
function status(message, error = false) {
  $("import-status").textContent = message;
  $("import-status").className = "import-status" + (error ? " error" : "");
}
function effectiveState(b) {
  return (
    b.reading_state ||
    (b.last_read || b.progress_chapter_id ? "reading" : "new")
  );
}
async function loadBooks() {
  try {
    libraryBooks = await api("/api/books");
    const selected = $("library-collection").value;
    $("library-collection").innerHTML =
      '<option value="">Mindegyik</option>' +
      [...new Set(libraryBooks.map((b) => b.collection).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, "hu"))
        .map((c) => `<option>${esc(c)}</option>`)
        .join("");
    $("library-collection").value = selected;
    renderBooks();
  } catch (e) {
    $("book-grid").innerHTML =
      `<p role="alert">${esc(e.message)} <button class="btn btn-ghost" onclick="loadBooks()">Újrapróbálás</button></p>`;
  }
}
function renderBooks() {
  const query = $("library-search").value.toLocaleLowerCase("hu"),
    state = $("library-state").value,
    collection = $("library-collection").value;
  const books = libraryBooks.filter(
    (b) =>
      `${b.title} ${b.author} ${b.series || ""} ${b.collection || ""}`
        .toLocaleLowerCase("hu")
        .includes(query) &&
      (state === "all" || effectiveState(b) === state) &&
      (!collection || b.collection === collection),
  );
  const sort = $("library-sort").value;
  books.sort((a, b) =>
    sort === "title" || sort === "author"
      ? String(a[sort] || "").localeCompare(String(b[sort] || ""), "hu")
      : String(
          b[sort === "added" ? "added_at" : "last_read"] || b.added_at,
        ).localeCompare(
          String(a[sort === "added" ? "added_at" : "last_read"] || a.added_at),
        ),
  );
  $("library-count").textContent =
    `${books.length} / ${libraryBooks.length} könyv`;
  const recent = libraryBooks
    .filter((b) => b.progress_chapter_id && effectiveState(b) !== "finished")
    .sort((a, b) => String(b.last_read).localeCompare(String(a.last_read)))[0];
  $("continue-card").classList.toggle("hidden", !recent);
  if (recent)
    $("continue-card").innerHTML =
      `<div><span class="eyebrow">Ahol abbahagytad</span><h2>${esc(recent.title)}</h2><p>${esc(recent.progress_chapter_title || "Mentett hely")}</p></div><a class="btn btn-primary" href="/reader/${recent.id}">Folytatom</a>`;
  if (!books.length) {
    $("book-grid").innerHTML =
      `<div class="empty-library"><p>${libraryBooks.length ? "Nincs a szűrésnek megfelelő könyv." : "Válaszd ki az első történeted."}</p><p class="sub">EPUB, PDF, TXT vagy webcikk — a tartalmat import előtt ellenőrizheted.</p></div>`;
    return;
  }
  const labels = {
    new: "Még nem kezdtem",
    reading: "Folyamatban",
    finished: "Befejeztem",
  };
  $("book-grid").innerHTML = books
    .map(
      (b) =>
        `<article class="book-card" data-id="${b.id}"><a class="book-cover" href="/reader/${b.id}" aria-label="${esc(b.title)} megnyitása">${b.cover_url ? `<img src="${b.cover_url}" alt="" loading="lazy">` : `<div class="book-cover-placeholder">${esc(b.title)}</div>`}</a><span class="book-type-badge">${esc(b.file_type)}</span><div class="book-info"><h2 class="book-title">${esc(b.title)}</h2><div class="book-author">${esc(b.author || "Ismeretlen szerző")}</div><p class="book-progress-hint">${labels[effectiveState(b)]} · ${b.total_chapters} fejezet</p>${b.series ? `<p class="book-progress-hint">${esc(b.series)}</p>` : ""}${["queued", "running"].includes(b.character_analysis_status) ? '<p class="status-warn">Szereplők elemzése folyamatban…</p>' : ""}</div><div class="book-actions"><a href="/reader/${b.id}">${b.progress_chapter_id ? "Folytatás" : "Olvasás"}</a><button onclick="openBookDetails(${b.id})">Adatok</button><button class="del-btn" onclick="deleteBook(event,${b.id})" aria-label="${esc(b.title)} eltávolítása">Eltávolítás</button></div></article>`,
    )
    .join("");
}
for (const id of [
  "library-search",
  "library-state",
  "library-sort",
  "library-collection",
])
  $(id).addEventListener("input", renderBooks);
$("file-input").addEventListener("change", async function () {
  const file = this.files[0];
  this.value = "";
  if (!file) return;
  status("A dokumentum előnézetének előkészítése…");
  const fd = new FormData();
  fd.append("file", file);
  try {
    await showImportPreview(
      await api("/api/import/preview", { method: "POST", body: fd }),
    );
    status(
      "Az előnézet elkészült. Ellenőrizd a címet, a nyelvet és a szöveget.",
    );
  } catch (e) {
    status(e.message, true);
  }
});
function openUrlDialog() {
  $("url-error").textContent = "";
  $("url-dialog").showModal();
  $("article-url").focus();
}
async function previewUrl() {
  const button = $("url-preview-btn");
  button.disabled = true;
  button.textContent = "Cikk letöltése…";
  $("url-error").textContent = "";
  try {
    const d = await post("/api/import/preview", {
      url: $("article-url").value,
    });
    $("url-dialog").close();
    await showImportPreview(d);
  } catch (e) {
    $("url-error").textContent = e.message;
  } finally {
    button.disabled = false;
    button.textContent = "Előnézet";
  }
}
async function showImportPreview(data) {
  importPreview = data;
  $("import-title").value = data.title;
  $("import-author").value = data.author;
  if (![...$("import-language").options].some((o) => o.value === data.language))
    $("import-language").add(new Option(data.language, data.language));
  $("import-language").value = data.language || "hu";
  $("import-sample").textContent = data.sample;
  $("import-source").textContent = data.source_url
    ? `Forrás: ${data.source_url}`
    : "";
  $("import-chapters-summary").textContent = `${data.chapters.length} fejezet`;
  $("import-chapters").innerHTML = data.chapters
    .map((c) => `<li>${esc(c.title)} · ${c.word_count} szó</li>`)
    .join("");
  $("import-duplicate").textContent = data.duplicate
    ? `Ez a tartalom már szerepel: ${data.duplicate.title}. Megnyithatod a könyvtárból.`
    : "";
  $("confirm-import-btn").disabled = Boolean(data.duplicate);
  $("import-error").textContent = "";
  document.querySelector('[name="narration-mode"][value="single"]').checked =
    true;
  try {
    importSettings = await api("/api/settings");
  } catch {
    importSettings = null;
  }
  updateImportNote();
  $("import-dialog").showModal();
  $("import-title").focus();
}
function updateImportNote() {
  const multi =
    document.querySelector('[name="narration-mode"]:checked').value === "multi";
  $("import-model-note").textContent = !multi
    ? "Helyi felolvasás, nyelvimodell-hívás nélkül."
    : importSettings?.llm_provider === "openai"
      ? "OpenAI-elemzés: a könyv szövege az OpenAI szolgáltatásához kerül. Ez API-költséggel jár."
      : "A szereplőelemzés a beállított helyi nyelvi modellt használja. A felolvasásra az elemzés után kerülhet sor.";
}
document
  .querySelectorAll('[name="narration-mode"]')
  .forEach((e) => e.addEventListener("change", updateImportNote));
function closeImportDialog() {
  $("import-dialog").close();
}
async function confirmImport() {
  if (!importPreview) return;
  const button = $("confirm-import-btn");
  button.disabled = true;
  button.textContent = "Hozzáadás…";
  try {
    const d = await post("/api/import/confirm", {
      token: importPreview.token,
      title: $("import-title").value,
      author: $("import-author").value,
      language: $("import-language").value,
      narration_mode: document.querySelector('[name="narration-mode"]:checked')
        .value,
    });
    $("import-dialog").close();
    status(
      `„${d.title}” hozzáadva. ${d.analysis_status === "queued" ? "A szereplőelemzés követhető a Feladatok oldalon." : "Megnyithatod és hallgathatod."}`,
    );
    await loadBooks();
  } catch (e) {
    $("import-error").textContent = e.message;
  } finally {
    button.disabled = false;
    button.textContent = "Hozzáadás";
  }
}
async function openBookDetails(id) {
  const b = libraryBooks.find((x) => x.id === id);
  if (!b) return;
  $("details-id").value = id;
  $("details-book-title").value = b.title;
  $("details-author").value = b.author;
  $("details-series").value = b.series || "";
  $("details-collection").value = b.collection || "";
  $("details-state").value = effectiveState(b);
  $("details-analysis").textContent = b.character_analysis_message || "";
  $("details-error").textContent = "";
  $("details-chapter-picker").open = false;
  $("details-chapters").textContent = "Fejezetek betöltése…";
  $("reanalyze-selected").disabled = true;
  let source = null;
  try {
    const url = new URL(b.source_url);
    if (['https:', 'http:'].includes(url.protocol)) source = url.href;
  } catch (_) {}
  $("details-source").classList.toggle("hidden", !source);
  $("details-source").href = source || '#';
  $("book-details").showModal();
  try {
    const chapters = await api(`/api/books/${id}/chapters`);
    if ($("details-id").value !== String(id)) return;
    $("details-chapters").replaceChildren();
    for (const chapter of chapters) {
      const label = document.createElement("label");
      label.className = "check-row";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = chapter.id;
      input.addEventListener("change", () => {
        $("reanalyze-selected").disabled = !document.querySelector(
          '#details-chapters input:checked',
        );
      });
      label.append(input, document.createTextNode(chapter.title));
      $("details-chapters").append(label);
    }
    if (!chapters.length) $("details-chapters").textContent = "Nincs feldolgozható fejezet.";
  } catch (e) {
    if ($("details-id").value === String(id)) $("details-chapters").textContent = e.message;
  }
}
async function saveBookDetails() {
  try {
    await api(`/api/books/${$("details-id").value}/metadata`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: $("details-book-title").value,
        author: $("details-author").value,
        series: $("details-series").value,
        collection: $("details-collection").value,
        reading_state: $("details-state").value,
      }),
    });
    $("book-details").close();
    await loadBooks();
  } catch (e) {
    $("details-error").textContent = e.message;
  }
}
async function reanalyzeBook(failedOnly, selectedOnly = false) {
  try {
    const chapterIds = Array.from(document.querySelectorAll('#details-chapters input:checked'), input => Number(input.value));
    if (selectedOnly && !chapterIds.length) throw new Error("Jelölj ki legalább egy fejezetet.");
    $("details-error").textContent = "";
    await post(`/api/books/${$("details-id").value}/reanalyze`, {
      failed_only: failedOnly,
      ...(selectedOnly ? { chapter_ids: chapterIds } : {}),
    });
    $("details-analysis").textContent =
      "Az újraelemzés elindult. A Feladatok oldalon követheted.";
  } catch (e) {
    $("details-error").textContent = e.message;
  }
}
function deleteBook(event, id) {
  event.stopPropagation();
  deletingBook = id;
  $("delete-book-name").textContent = libraryBooks.find(
    (b) => b.id === id,
  )?.title;
  $("delete-source").checked = false;
  $("delete-audio").checked = false;
  $("delete-error").textContent = "";
  $("delete-dialog").showModal();
}
async function confirmDelete() {
  try {
    const result = await post(`/api/books/${deletingBook}/remove`, {
      source: $("delete-source").checked,
      audio: $("delete-audio").checked,
    });
    $("delete-dialog").close();
    if (result.warnings?.length) status(result.warnings.join(" "), true);
    await loadBooks();
  } catch (e) {
    $("delete-error").textContent = e.message;
  }
}
loadBooks();
api("/api/setup/status")
  .then((s) => $("welcome-card").classList.toggle("hidden", s.completed))
  .catch(() => {});
setInterval(() => {
  if (
    libraryBooks.some((b) =>
      ["queued", "running"].includes(b.character_analysis_status),
    )
  )
    loadBooks();
}, 4000);
