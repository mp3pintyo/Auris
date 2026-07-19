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

document.getElementById('file-input').addEventListener('change', async function() {
  const file = this.files[0];
  if (!file) return;
  const status = document.getElementById('import-status');
  status.textContent = `Importing “${file.name}”…`;
  status.className = 'import-status';
  status.classList.remove('hidden');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/api/books/import', { method: 'POST', body: fd });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    status.textContent = `“${d.title}” imported — ${d.chapters} sections. Analyzing characters and dialogue speakers…`;
    loadBooks();
    pollCharacterAnalysis(d.book_id, status);
  } catch(e) {
    status.textContent = e.message;
    status.className = 'import-status error';
  }
  this.value = '';
});

async function pollCharacterAnalysis(bookId, statusEl) {
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    try {
      const d = await fetch(`/api/books/${bookId}/character-analysis`).then(r => r.json());
      if (d.error) throw new Error(d.error);
      statusEl.textContent = d.message || 'Analyzing characters and dialogue speakers…';
      loadBooks();
      if (d.status === 'complete') {
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
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadBooks();
