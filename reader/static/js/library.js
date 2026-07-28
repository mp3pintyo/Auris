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
        <p class="sub">Import an EPUB, PDF, DOCX, or TXT file to get started.</p>
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
      <div class="book-cover">${coverHtml}</div>
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
        <button class="del-btn" onclick="deleteBook(event,${b.id})">Remove</button>
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
