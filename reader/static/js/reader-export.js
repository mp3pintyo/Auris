// Auris reader — export panel. Classic script sharing globals with reader.js;
// loaded after reader.js by templates/reader.html.

// ── Export ────────────────────────────────────────────────────────────────────

// Pause reader TTS prewarm/buffer while an export owns the GPU.
let _exportBusy = false;

function formatDurationShort(sec) {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return '';
  const s = Math.round(sec);
  if (s < 60) return `${s} mp`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return `${m} p ${String(r).padStart(2, '0')} mp`;
  const h = Math.floor(m / 60);
  return `${h} ó ${String(m % 60).padStart(2, '0')} p`;
}

function formatExportStatus(sr) {
  if (!sr) return 'Feldolgozás…';
  const done = typeof sr.done === 'number' ? sr.done : null;
  const total = typeof sr.total === 'number' ? sr.total : null;
  let msg = sr.message || 'Feldolgozás…';

  // Always rebuild a clear progress line so a stale server message cannot hide ETA.
  if (sr.state === 'running' && total != null && total > 0 && done != null) {
    msg = `Hang készítése (${done}/${total})`;
    if (sr.eta_sec != null && Number.isFinite(sr.eta_sec) && done < total) {
      msg += ` · kb. ${formatDurationShort(sr.eta_sec)} van hátra`;
    } else if (done < total) {
      msg += ' · feldolgozás…';
    }
  } else if (
    sr.state === 'running' &&
    sr.eta_sec != null &&
    Number.isFinite(sr.eta_sec) &&
    !/hátra/i.test(msg)
  ) {
    msg += ` · kb. ${formatDurationShort(sr.eta_sec)} van hátra`;
  }
  return msg;
}

function renderExportChapterSelection() {
  const list = document.getElementById('exp-chapter-list');
  if (!list) return;
  list.innerHTML = chapters.map((chapter, index) => `
    <label>
      <input type="checkbox" name="exp-chapter" value="${index + 1}" checked>
      <span>${index + 1}. ${esc(chapter.title)}</span>
    </label>
  `).join('');
}

function setExportRadio(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (input) input.checked = true;
}

function updateExportScope() {
  const selected = document.querySelector('input[name="exp-mode"]:checked').value;
  document.getElementById('chapter-selection-wrap')
    .classList.toggle('hidden', selected !== 'chapterwise');
}

function selectAllExportChapters(checked) {
  document.querySelectorAll('input[name="exp-chapter"]')
    .forEach(input => { input.checked = checked; });
}

function applyExportPreset(preset) {
  if (preset === 'custom') return;
  if (preset === 'chapter-wav') {
    setExportRadio('exp-mode', 'chapter');
    setExportRadio('exp-audio', 'wav');
    setExportRadio('exp-sub', 'none');
  } else if (preset === 'selected-mp3') {
    setExportRadio('exp-mode', 'chapterwise');
    setExportRadio('exp-audio', 'mp3');
    setExportRadio('exp-sub', 'none');
  } else if (preset === 'book-m4b') {
    setExportRadio('exp-mode', 'chapterwise');
    setExportRadio('exp-audio', 'm4b');
    setExportRadio('exp-sub', 'none');
    selectAllExportChapters(true);
  } else if (preset === 'book-epub3') {
    setExportRadio('exp-mode', 'chapterwise');
    setExportRadio('exp-audio', 'mp3');
    setExportRadio('exp-sub', 'none');
    selectAllExportChapters(true);
  } else if (preset === 'book-abs') {
    setExportRadio('exp-mode', 'chapterwise');
    setExportRadio('exp-audio', 'm4b');
    setExportRadio('exp-sub', 'none');
    selectAllExportChapters(true);
  } else if (preset === 'book-acx') {
    setExportRadio('exp-mode', 'chapterwise');
    setExportRadio('exp-audio', 'mp3');
    setExportRadio('exp-sub', 'none');
    selectAllExportChapters(true);
  } else if (preset === 'chapter-daw') {
    setExportRadio('exp-mode', 'chapter');
    setExportRadio('exp-audio', 'wav');
    setExportRadio('exp-sub', 'none');
  }
  const packages = {
    'book-epub3': 'epub3', 'book-abs': 'audiobookshelf', 'book-acx': 'acx', 'chapter-daw': 'daw',
  };
  const packageSelect = document.getElementById('export-package');
  if (packageSelect) packageSelect.value = packages[preset] || 'none';
  const intro = document.getElementById('export-intro');
  const outro = document.getElementById('export-outro');
  const sample = document.getElementById('export-sample');
  const book = ['book-m4b', 'book-epub3', 'book-abs', 'book-acx'].includes(preset);
  if (intro) intro.checked = book;
  if (outro) outro.checked = book;
  if (sample) sample.checked = preset === 'book-acx';
  updateExportScope();
}

async function loadPublishingInfo() {
  try {
    const info = await fetch(`/api/books/${BOOK_ID}/publishing`).then(r => r.json());
    const credit = document.getElementById('export-narrator-credit');
    if (credit) credit.value = info.narrator_credit || '';
    const name = document.getElementById('export-music-name');
    if (name) name.textContent = info.bg_music_name ? `Háttérzene: ${info.bg_music_name}` : 'Nincs háttérzene';
    const level = document.getElementById('export-music-db');
    if (level) level.value = info.bg_music_db ?? -22;
    const value = document.getElementById('export-music-db-value');
    if (value) value.textContent = String(info.bg_music_db ?? -22).replace('-', '−');
  } catch (_) { /* optional panel */ }
}

async function savePublishing(patch) {
  await fetch(`/api/books/${BOOK_ID}/publishing`, {
    method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(patch),
  });
}

document.getElementById('export-narrator-credit')?.addEventListener('change', event => {
  savePublishing({narrator_credit: event.target.value});
});
document.getElementById('export-music-db')?.addEventListener('input', event => {
  document.getElementById('export-music-db-value').textContent = String(event.target.value).replace('-', '−');
});
document.getElementById('export-music-db')?.addEventListener('change', event => {
  savePublishing({bg_music_db: Number(event.target.value)});
});
document.getElementById('export-music-file')?.addEventListener('change', async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`/api/books/${BOOK_ID}/background-music`, {method: 'POST', body: form});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) showToast(data.error || 'A zene feltöltése nem sikerült.', 'err');
  event.target.value = '';
  loadPublishingInfo();
});
document.getElementById('export-music-remove')?.addEventListener('click', async () => {
  await fetch(`/api/books/${BOOK_ID}/background-music`, {method: 'DELETE'});
  loadPublishingInfo();
});
loadPublishingInfo();

function selectedExportChapters() {
  const all = [...document.querySelectorAll('input[name="exp-chapter"]')];
  const checked = all.filter(input => input.checked).map(input => input.value);
  if (!checked.length) return '';
  return checked.length === all.length ? 'all' : checked.join(',');
}

function appendExportLink(container, href, label) {
  if (!href) return;
  const link = document.createElement('a');
  link.href = href;
  link.textContent = label;
  link.setAttribute('download', '');
  container.appendChild(link);
}

function renderExportLinks(result, jobId) {
  const container = document.getElementById('export-links');
  container.replaceChildren();
  appendExportLink(container, result?.download, 'Export letöltése');
  appendExportLink(container, result?.zip_download, 'Csomag letöltése');
  appendExportLink(container, result?.audio_download, 'Hangfájl letöltése');
  appendExportLink(container, result?.subtitle_download, 'Felirat letöltése');
  const jobs = document.createElement('a');
  jobs.href = `/jobs#job-${encodeURIComponent(jobId)}`;
  jobs.textContent = 'Export megnyitása a Feladatok oldalon';
  container.appendChild(jobs);
}

document.getElementById('export-btn').onclick = () => {
  const dropdown = document.getElementById('export-dropdown');
  const open = dropdown.classList.toggle('hidden') === false;
  document.getElementById('export-btn').setAttribute('aria-expanded', String(open));
  if (open) document.getElementById('export-preset').focus();
};

document.querySelectorAll('input[name="exp-mode"]').forEach(input => {
  input.addEventListener('change', updateExportScope);
});

document.getElementById('export-preset').addEventListener('change', event => {
  applyExportPreset(event.target.value);
});
document.getElementById('select-all-chapters').addEventListener('click', () => selectAllExportChapters(true));
document.getElementById('select-no-chapters').addEventListener('click', () => selectAllExportChapters(false));

document.getElementById('do-export-btn').onclick = async () => {
  if (!currentChapterId) { showToast('Előbb nyiss meg egy fejezetet.'); return; }

  const mode      = document.querySelector('input[name="exp-mode"]:checked').value;
  const audioFmt  = document.querySelector('input[name="exp-audio"]:checked').value;
  const subInput  = document.querySelector('input[name="exp-sub"]:checked');
  const subFmt    = subInput ? subInput.value : 'none';
  const selectedChapters = mode === 'chapterwise' ? selectedExportChapters() : null;
  if (mode === 'chapterwise' && !selectedChapters) {
    showToast('Jelölj ki legalább egy fejezetet.', 'err');
    return;
  }

  const status    = document.getElementById('export-status');
  const progWrap  = document.getElementById('export-progress-wrap');
  const progFill  = document.getElementById('export-progress-fill');
  const doBtn     = document.getElementById('do-export-btn');

  doBtn.disabled = true;
  progWrap.classList.add('active');
  progFill.style.width = '0%';
  status.textContent = 'Az export indítása…';
  document.getElementById('export-links').replaceChildren();
  // Stop background single-segment prewarm so export can batch on the GPU.
  _exportBusy = true;
  _bufferGenId++;
  if (isPlaying) {
    try { stopPlayback(); } catch (_) {}
  }

  let url;
  if (mode === 'chapter')          url = `/api/books/${BOOK_ID}/export/chapter/${currentChapterId}`;
  else                             url = `/api/books/${BOOK_ID}/export/chapterwise`;

  const finish = (msg) => {
    _exportBusy = false;
    status.textContent = msg;
    progWrap.classList.remove('active');
    doBtn.disabled = false;
  };

  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        audio_fmt: audioFmt,
        sub_fmt: subFmt,
        chapters: selectedChapters,
        package: document.getElementById('export-package')?.value || 'none',
        intro: Boolean(document.getElementById('export-intro')?.checked),
        outro: Boolean(document.getElementById('export-outro')?.checked),
        sample: Boolean(document.getElementById('export-sample')?.checked),
        abs_upload: Boolean(document.getElementById('export-abs-upload')?.checked),
        take_mode: exportTakeMode(),
      }),
    });
    const d = await r.json();
    if (d.error) { finish(d.error); return; }

    const jobId = d.job_id;
    renderExportLinks(null, jobId);

    // Client-side ETA fallback if server has not reported one yet.
    let clientT0 = Date.now();
    let clientDone0 = null;

    const showProgress = (sr) => {
      if (sr.total > 0) {
        const pct = Math.min(Math.round((sr.done / sr.total) * 95), 95);
        progFill.style.width = pct + '%';
      }

      // Local ETA when server still estimating (e.g. first synth batch in flight).
      if (
        sr.state === 'running' &&
        sr.total > 0 &&
        typeof sr.done === 'number' &&
        (sr.eta_sec == null || !Number.isFinite(sr.eta_sec)) &&
        sr.done < sr.total
      ) {
        if (clientDone0 == null && sr.done > 0) {
          clientDone0 = sr.done;
          clientT0 = Date.now();
        } else if (clientDone0 != null && sr.done > clientDone0) {
          const elapsed = (Date.now() - clientT0) / 1000;
          const advanced = sr.done - clientDone0;
          if (elapsed >= 2 && advanced > 0) {
            sr.eta_sec = (sr.total - sr.done) / (advanced / elapsed);
          }
        }
      }

      status.textContent = formatExportStatus(sr);
    };

    // Progress follows server events; no fixed-interval polling.
    const sr = await Auris.watchJob(jobId, { url: `/api/export/status/${jobId}`, onUpdate: showProgress });
    if (sr.state === 'complete') {
      progFill.style.width = '100%';
      const res = sr.result || {};
      renderExportLinks(res, jobId);
      finish('Az export elkészült. A fájlok lent tölthetők le.' +
        (res.mastering_warning ? ' A hangerő-kiegyenlítés kimaradt: ' + res.mastering_warning : ''));
    } else if (sr.state === 'failed') {
      finish('Az export nem sikerült: ' + (sr.error || 'Ismeretlen hiba'));
    } else {
      finish(sr.state === 'cancelled' ? 'Az export leállítva. A Feladatok oldalon folytathatod.' : 'Az export megszakadt. A Feladatok oldalon folytathatod.');
    }
  } catch(e) {
    finish(e.message);
  }
};


// Export quality (best-of-N takes); the last choice is remembered per browser.
const TAKE_MODE_KEY = 'auris.export.takeMode';

function exportTakeMode() {
  const value = document.getElementById('export-take-mode')?.value || 'normal';
  try { localStorage.setItem(TAKE_MODE_KEY, value); } catch (_) { /* storage is optional */ }
  return value;
}

(function restoreExportTakeMode() {
  const select = document.getElementById('export-take-mode');
  if (!select) return;
  try {
    const saved = localStorage.getItem(TAKE_MODE_KEY);
    if (saved && [...select.options].some((o) => o.value === saved)) select.value = saved;
  } catch (_) { /* storage is optional */ }
})();
