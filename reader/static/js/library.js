async function loadBooks() {
  const grid = document.getElementById('book-grid');
  const books = await fetch('/api/books').then(r => r.json());

  const countEl = document.getElementById('library-count');
  if (countEl) countEl.textContent = books.length
    ? books.length + (books.length === 1 ? ' title' : ' titles')
    : '';

  if (!books.length) {
    grid.innerHTML = `
      <div class="empty-library">
        <p>Your library is empty.</p>
        <p class="sub">Import an EPUB, PDF, or TXT file to get started.</p>
      </div>`;
    return;
  }

  grid.innerHTML = books.map(b => {
    const coverHtml = b.cover_url
      ? `<img src="${b.cover_url}" alt="" loading="lazy">`
      : `<div class="book-cover-placeholder">${esc(b.title)}</div>`;
    const hasProgress = Number.isInteger(b.progress_chapter_id) || Number.isInteger(Number.parseInt(b.progress_chapter_id, 10));
    const progressPosition = Math.max(0, Number.parseInt(b.progress_position, 10) || 0);
    const actionLabel = hasProgress ? 'Continue' : 'Read';
    const progressMeta = hasProgress
      ? `<div class="book-progress-hint">Continue from ${esc(b.progress_chapter_title || 'saved position')} &middot; seg ${progressPosition + 1}</div>`
      : '';
    const analysisState = b.character_analysis_status || '';
    const analysisMeta = ['queued', 'running'].includes(analysisState)
      ? `<div class="book-progress-hint status-warn">${esc(b.character_analysis_message || 'Analyzing characters…')}</div>`
      : analysisState === 'failed'
        ? `<div class="book-progress-hint status-error">Character analysis failed: ${esc(b.character_analysis_message)}</div>`
        : analysisState === 'complete'
          ? `<div class="book-progress-hint status-ok">${esc(b.character_analysis_message || 'Character analysis complete.')}</div>`
          : analysisState === 'partial'
            ? `<div class="book-progress-hint status-warn">${esc(b.character_analysis_message || 'Character analysis partially complete.')}</div>`
            : analysisState === 'skipped'
              ? `<div class="book-progress-hint">${esc(b.character_analysis_message || 'Single narrator — no character analysis.')}</div>`
          : '';

    return `
    <div class="book-card" data-id="${b.id}">
      <div class="book-cover">
        ${coverHtml}
        <button class="card-edit" title="Edit book details"
                aria-label="Edit details for ${esc(b.title)}"
                onclick="openEditDialog(event,${b.id})">&#9998;</button>
        <button class="card-remove" title="Remove from library"
                aria-label="Remove ${esc(b.title)} from library"
                onclick="deleteBook(event,${b.id})">&times;</button>
      </div>
      <span class="book-type-badge">${esc(b.file_type)}</span>
      <div class="book-info">
        <div class="book-title">${esc(b.title)}</div>
        <div class="book-author">${esc(b.author || 'Unknown')}</div>
        <div class="book-author" style="margin-top:3px;font-size:.68rem">
          ${b.total_chapters} section${b.total_chapters !== 1 ? 's' : ''}
        </div>
        ${progressMeta}
        ${analysisMeta}
      </div>
      <div class="book-actions">
        <a href="/reader/${b.id}">${actionLabel}</a>
      </div>
    </div>`;
  }).join('');
}

async function deleteBook(e, id) {
  e.stopPropagation();
  if (!confirm('Remove this book from the library?')) return;
  await fetch(`/api/books/${id}`, { method: 'DELETE' });
  loadBooks();
}

let editingBookId = null;
let editingOriginalLanguage = '';

async function openEditDialog(e, id) {
  // The whole card is a link to the reader, so this click must not open it.
  e.stopPropagation();
  e.preventDefault();
  const books = await fetch('/api/books').then(r => r.json());
  const book = books.find(b => b.id === id);
  if (!book) {
    // The book was removed elsewhere (another tab, another device) between
    // the grid rendering and this click. Refresh instead of silently doing
    // nothing, so the grid stops showing a card whose edit button is dead.
    alert('This book was removed. Refreshing the library.');
    loadBooks();
    return;
  }

  editingBookId = id;
  // Normalized the same way the server compares it: stored languages are not
  // guaranteed lowercase (the EPUB parser writes the raw dc:language prefix),
  // so without this a book stored as "EN" would make an unrelated edit look
  // like a language change and warn about discarding audio that never moved.
  editingOriginalLanguage = (book.language || '').trim().toLowerCase();
  document.getElementById('edit-title').value = book.title || '';
  document.getElementById('edit-author').value = book.author || '';
  document.getElementById('edit-language').value = book.language || '';
  const status = document.getElementById('edit-status');
  status.textContent = '';
  status.className = 'import-status hidden';
  document.getElementById('edit-dialog').classList.remove('hidden');
  document.getElementById('edit-title').focus();
}

function closeEditDialog() {
  document.getElementById('edit-dialog').classList.add('hidden');
  editingBookId = null;
}

async function saveBookEdits() {
  if (editingBookId === null) return;
  const title = document.getElementById('edit-title').value.trim();
  const author = document.getElementById('edit-author').value.trim();
  const language = document.getElementById('edit-language').value.trim().toLowerCase();
  const status = document.getElementById('edit-status');
  const button = document.getElementById('save-edit-btn');

  if (!title) {
    status.textContent = 'Title cannot be empty.';
    status.className = 'import-status error';
    return;
  }
  // Only warn when the language actually changed, since that is the only
  // edit that discards generated audio.
  if (language !== editingOriginalLanguage &&
      !confirm('Changing the language discards this book’s generated audio '
               + 'so it can be read again with the new pronunciation. Continue?')) {
    return;
  }

  button.disabled = true;
  try {
    // Omit language entirely when there is nothing meaningful to send: a
    // book with no stored language opens the dialog with an empty language
    // field, and always sending it would fail the endpoint's format check
    // for a field the user never touched, blocking even a title-only fix.
    const payload = { title, author };
    if (language || editingOriginalLanguage) payload.language = language;
    const r = await fetch(`/api/books/${editingBookId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Save failed');
    if (d.segments_cleared) {
      alert('Language changed. This book’s generated audio was cleared and '
            + 'will be regenerated with the new pronunciation.');
    }
    closeEditDialog();
    loadBooks();
  } catch (err) {
    status.textContent = err.message;
    status.className = 'import-status error';
  } finally {
    button.disabled = false;
  }
}

let pendingImportFile = null;
let importSettings = null;

function activeCharacterModel(settings) {
  const provider = settings?.llm_provider === 'openai' ? 'openai' : 'local';
  if (provider === 'openai') {
    return {
      configured: Boolean(settings.openai_api_key && settings.openai_model),
      providerLabel: 'OpenAI',
      model: settings.openai_model || '',
      missingMessage: 'Character voices require an OpenAI API key and model in Settings.',
    };
  }
  return {
    configured: Boolean(settings?.llm_base_url && settings?.llm_model),
    providerLabel: 'Local server',
    model: settings?.llm_model || '',
    missingMessage: 'Character voices require a local language model in Settings.',
  };
}

document.getElementById('file-input').addEventListener('change', function() {
  const file = this.files[0];
  this.value = '';
  if (!file) return;
  openImportDialog(file);
});

async function openImportDialog(file) {
  pendingImportFile = file;
  document.getElementById('import-file-name').textContent = file.name;
  document.getElementById('import-file-size').textContent = formatFileSize(file.size);
  document.getElementById('import-file-type').textContent =
    (file.name.split('.').pop() || 'BOOK').toUpperCase();
  document.querySelector('input[name="narration-mode"][value="single"]').checked = true;
  document.getElementById('import-dialog').classList.remove('hidden');

  try {
    importSettings = await fetch('/api/settings').then(r => r.json());
    const activeModel = activeCharacterModel(importSettings);
    const note = document.getElementById('import-model-note');
    note.className =
      `import-model-note ${activeModel.configured ? 'ready' : 'warning'}`;
    note.textContent = activeModel.configured
      ? `Character analysis: ${activeModel.providerLabel} · ${activeModel.model}`
      : activeModel.missingMessage;
  } catch (_) {
    document.getElementById('import-model-note').textContent =
      'Could not read language-model settings.';
  }
}

function closeImportDialog() {
  document.getElementById('import-dialog').classList.add('hidden');
  pendingImportFile = null;
}

async function confirmImport() {
  const file = pendingImportFile;
  if (!file) return;
  const mode = document.querySelector('input[name="narration-mode"]:checked').value;
  const button = document.getElementById('confirm-import-btn');
  const status = document.getElementById('import-status');
  status.textContent = `Importing “${file.name}”…`;
  status.className = 'import-status';
  status.classList.remove('hidden');
  const fd = new FormData();
  fd.append('file', file);
  fd.append('narration_mode', mode);
  button.disabled = true;
  button.textContent = 'Importing…';
  try {
    const r = await fetch('/api/books/import', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Import failed');
    closeImportDialog();
    status.textContent = mode === 'multi'
      ? `“${d.title}” imported — ${d.chapters} sections. Analyzing dialogue speakers…`
      : `“${d.title}” imported — ${d.chapters} sections. Ready with one narrator.`;
    loadBooks();
    if (mode === 'multi') pollCharacterAnalysis(d.book_id, status);
  } catch(e) {
    status.textContent = e.message;
    status.className = 'import-status error';
  } finally {
    button.disabled = false;
    button.textContent = 'Import book';
  }
}

async function pollCharacterAnalysis(bookId, statusEl) {
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    try {
      const d = await fetch(`/api/books/${bookId}/character-analysis`).then(r => r.json());
      if (d.error) throw new Error(d.error);
      statusEl.textContent = d.message || 'Analyzing characters and dialogue speakers…';
      loadBooks();
      if (d.status === 'complete' || d.status === 'partial' || d.status === 'skipped') {
        statusEl.className = 'import-status';
        return;
      }
      if (d.status === 'failed') {
        statusEl.className = 'import-status error';
        return;
      }
    } catch (error) {
      statusEl.textContent = `Character analysis status error: ${error.message}`;
      statusEl.className = 'import-status error';
      return;
    }
  }
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

loadBooks();
