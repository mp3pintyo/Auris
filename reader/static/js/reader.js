const BOOK_ID = window.BOOK_ID;

// ── State ─────────────────────────────────────────────────────────────────────
let chapters        = [];
let currentChapterId= null;
let segments        = [];
let currentSegIdx   = 0;
let isPlaying       = false;
let speedMultiplier = 1.0;
let fontSize        = parseInt(localStorage.getItem('fontSize') || '18');
let fontFamily      = localStorage.getItem('fontFamily') || 'serif';
let lineHeight      = parseFloat(localStorage.getItem('lineHeight') || '1.9');
let currentTheme    = localStorage.getItem('theme') || 'night';
let showSpeakerLabels = localStorage.getItem('showSpeakerLabels') === 'true';
let _progressSaveTimer = null;
let _scrollProgressTimer = null;
let _lastSavedProgressKey = '';
let _ignoreScrollTrackingUntil = 0;
let speakerCharacters = [];
let editingSpeakerSegmentIndex = null;
let editingSpeakerRangeEndIndex = null;
let speakerEditMode = false;
let _loadedSegIdx = -1;
let _sleepTimerId = null;
let _sleepMode = 'off';
let _activeModal = null;
let _modalReturnFocus = null;

// Two audio elements for gapless double-buffering
const _audioA = document.getElementById('tts-audio');
const _audioB = (() => { const a = new Audio(); a.preload = 'auto'; return a; })();
let audio = _audioA; // currently active (playing) element

// Client-side cache: segIdx -> Promise<{audio_url, duration_sec, cache_key, text}>
let _segCache = new Map();

// Which segment index is pre-buffered in the standby element, and its data
let _preloadIdx = -1;
let _preloadData = null;
let _interSegmentTimer = null;
let _pendingSegmentIdx = -1;

const DEFAULT_SEGMENT_PAUSE_MS = 350;
const DIALOGUE_TURN_PAUSE_MS = 550;
const PARAGRAPH_PAUSE_MS = 850;
const ELLIPSIS_PAUSE_MS = 1500;

// Monotonic counter — incremented on every new playSegment and on stopPlayback.
// Each playSegment captures its generation at entry; stale async continuations
// bail out when their generation no longer matches the current one.
let _playGen = 0;

// Cancellation token for the background buffer loop — incremented on each
// chapter open so the previous loop exits without touching the new chapter.
let _bufferGenId = 0;
let _prewarmFrontier = 0;
const TTS_PREWARM_CHUNK = 12;
const TTS_PREWARM_LOW_WATER = 5;
let _activeChapterGeneration = null;
// All in-flight interactive TTS requests. Stop aborts the HTTP wait and also
// asks the server-side Higgs token loop to terminate.
let _ttsAbortControllers = new Map();

function _standby() { return audio === _audioA ? _audioB : _audioA; }

function pauseAfterSegmentMs(segment, nextSegment = null) {
  const text = String(segment?.text || '')
    .trimEnd()
    .replace(/["'”’»]+\s*$/, '')
    .trimEnd();
  if (text.endsWith('...') || text.endsWith('…')) return ELLIPSIS_PAUSE_MS;
  if (segment?.ends_paragraph) return PARAGRAPH_PAUSE_MS;
  if (segment?.is_dialogue && nextSegment?.is_dialogue) return DIALOGUE_TURN_PAUSE_MS;
  return DEFAULT_SEGMENT_PAUSE_MS;
}
function _swapAudio() { audio = (audio === _audioA ? _audioB : _audioA); }

function isInteractiveElement(element) {
  return Boolean(element?.closest?.(
    'button, a, input, textarea, select, summary, [contenteditable="true"], [role="button"]'
  ));
}

function focusableElements(container) {
  return [...container.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
    'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter(element => !element.closest('.hidden') && element.getClientRects().length > 0);
}

function openModal(overlay, initialFocus) {
  if (!overlay) return;
  _modalReturnFocus = document.activeElement;
  _activeModal = overlay;
  overlay.classList.remove('hidden');
  (initialFocus || focusableElements(overlay)[0] || overlay).focus?.();
}

function closeModal(overlay) {
  if (!overlay || overlay.classList.contains('hidden')) return;
  overlay.classList.add('hidden');
  if (_activeModal === overlay) _activeModal = null;
  const returnFocus = _modalReturnFocus;
  _modalReturnFocus = null;
  returnFocus?.focus?.();
}

function trapModalFocus(event) {
  if (!_activeModal || event.key !== 'Tab') return false;
  const focusable = focusableElements(_activeModal);
  if (!focusable.length) {
    event.preventDefault();
    return true;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!focusable.includes(document.activeElement)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
  return true;
}

function clampSegmentIndex(idx, segList = segments) {
  const parsed = Number.parseInt(idx, 10);
  const safe = Number.isFinite(parsed) ? parsed : 0;
  const max = Math.max((segList?.length || 1) - 1, 0);
  return Math.max(0, Math.min(safe, max));
}

function progressKey(chapterId, position) {
  return `${chapterId}:${position}`;
}

function sendProgress(chapterId, position, options = {}) {
  const { useBeacon = false, force = false } = options;
  if (!chapterId) return;

  const clamped = clampSegmentIndex(position);
  const key = progressKey(chapterId, clamped);
  if (!force && key === _lastSavedProgressKey) return;
  _lastSavedProgressKey = key;

  const payload = JSON.stringify({ chapter_id: chapterId, position: clamped });
  const url = `/api/books/${BOOK_ID}/progress`;

  if (useBeacon && navigator.sendBeacon) {
    const ok = navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }));
    if (ok) return;
  }

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: useBeacon,
  }).catch(() => {});
}

function queueProgressSave(chapterId = currentChapterId, position = currentSegIdx) {
  if (!chapterId) return;
  clearTimeout(_progressSaveTimer);
  _progressSaveTimer = setTimeout(() => {
    sendProgress(chapterId, position);
  }, 250);
}

function flushProgressSave(options = {}) {
  clearTimeout(_progressSaveTimer);
  if (currentChapterId) {
    sendProgress(currentChapterId, currentSegIdx, options);
  }
}

function setCurrentSegment(idx, options = {}) {
  const { highlight = false, behavior = 'smooth', save = true } = options;
  currentSegIdx = clampSegmentIndex(idx);
  if (highlight) {
    highlightSegment(currentSegIdx, { behavior });
  }
  updatePlaybackUI();
  updateProgress();
  if (save) {
    queueProgressSave(currentChapterId, currentSegIdx);
  }
  return currentSegIdx;
}

// ── Theme ─────────────────────────────────────────────────────────────────────

const THEMES = ['night', 'sepia', 'paper', 'amoled'];

function applyTheme(theme) {
  THEMES.forEach(t => document.body.classList.remove('theme-' + t));
  if (theme !== 'night') document.body.classList.add('theme-' + theme);
  currentTheme = theme;
  localStorage.setItem('theme', theme);
}

function cycleTheme() {
  const next = THEMES[(THEMES.indexOf(currentTheme) + 1) % THEMES.length];
  applyTheme(next);
  showToast('Theme: ' + next.charAt(0).toUpperCase() + next.slice(1));
}

applyTheme(currentTheme);

// ── Font settings ─────────────────────────────────────────────────────────────

const FONT_FAMILIES = {
  serif: "Georgia, 'Palatino Linotype', serif",
  sans:  "'Helvetica Neue', Arial, sans-serif",
  mono:  "'Courier New', Courier, monospace",
};

function applyFontFamily(ff) {
  fontFamily = ff;
  localStorage.setItem('fontFamily', ff);
  document.getElementById('chapter-content').style.fontFamily = FONT_FAMILIES[ff] || FONT_FAMILIES.serif;
}

function changeFontSize(delta) {
  fontSize = Math.min(30, Math.max(13, fontSize + delta));
  document.getElementById('chapter-content').style.fontSize = fontSize + 'px';
  localStorage.setItem('fontSize', fontSize);
}

function applyLineHeight(lh) {
  lineHeight = lh;
  localStorage.setItem('lineHeight', lh);
  document.getElementById('chapter-content').style.lineHeight = lh;
}

// Apply saved reading preferences
(function initReadingPrefs() {
  const cc = document.getElementById('chapter-content');
  if (!cc) return;
  cc.style.fontSize    = fontSize + 'px';
  cc.style.lineHeight  = lineHeight;
  cc.style.fontFamily  = FONT_FAMILIES[fontFamily] || FONT_FAMILIES.serif;
})();

// ── TOC ───────────────────────────────────────────────────────────────────────

async function loadTOC() {
  chapters = await fetch(`/api/books/${BOOK_ID}/chapters`).then(r => r.json());
  const list = document.getElementById('toc-list');
  list.innerHTML = chapters.map(ch => {
    const wc = ch.word_count ? ch.word_count.toLocaleString('hu-HU') + ' szó' : '';
    const badge = ch.section_type !== 'chapter'
      ? `<span class="toc-section-badge">${esc(ch.section_type)}</span>` : '';
    const ready = Number(ch.audio_total) > 0 &&
      Number(ch.audio_ready) >= Number(ch.audio_total);
    return `
      <button type="button" class="toc-item" data-id="${ch.id}" onclick="openChapter(${ch.id})">
        ${badge}
        <span class="toc-item-title">${esc(ch.title)}</span>
        <span class="toc-item-details">
          <span class="toc-item-meta">${wc}</span>
          <span class="toc-ready-badge${ready ? '' : ' hidden'}">&#10003; Kész</span>
        </span>
      </button>`;
  }).join('');
  renderExportChapterSelection();

  const prog = await fetch(`/api/books/${BOOK_ID}/progress`).then(r => r.json());
  const savedChapterId = Number.parseInt(prog.chapter_id, 10);
  const savedPosition = Number.parseInt(prog.position, 10);
  const hasSavedChapter = chapters.some(ch => ch.id === savedChapterId);
  if (hasSavedChapter) {
    openChapter(savedChapterId, {
      resumePosition: savedPosition,
      persistOpened: false,
      highlightOnLoad: false,
    });
  } else if (chapters.length) {
    openChapter(chapters[0].id, {
      resumePosition: 0,
      persistOpened: false,
      highlightOnLoad: false,
    });
  }

  loadBookmarks();
}

async function openChapter(chapterId, options = {}) {
  const {
    resumePosition = 0,
    persistCurrent = true,
    persistOpened = true,
    highlightOnLoad = false,
  } = options;

  if (persistCurrent && currentChapterId && currentChapterId !== chapterId) {
    sendProgress(currentChapterId, currentSegIdx, { force: true });
  }

  stopPlayback();
  _segCache = new Map();
  _prewarmFrontier = 0;
  segments = [];           // clear immediately so stale segments can't be played
  currentChapterId = chapterId;
  currentSegIdx    = 0;
  const voiceStudioLink = document.getElementById('voice-studio-link');
  if (voiceStudioLink) {
    voiceStudioLink.href = `/voice-studio/${BOOK_ID}?chapter_id=${chapterId}`;
  }

  document.querySelectorAll('.toc-item').forEach(el => {
    el.classList.toggle('active', +el.dataset.id === chapterId);
  });

  const ch = await fetch(`/api/books/${BOOK_ID}/chapters/${chapterId}`).then(r => r.json());
  document.getElementById('chapter-title').textContent = ch.title;

  const wpm = 250;
  const minutes = Math.round((ch.word_count || 0) / wpm);
  const estEl = document.getElementById('reading-estimate');
  if (estEl) estEl.textContent = minutes > 0 ? `kb. ${minutes} perc olvasás` : '';

  [segments, speakerCharacters] = await Promise.all([
    fetch(`/api/tts/segments/${BOOK_ID}/${chapterId}`).then(r => r.json()),
    fetch(`/api/books/${BOOK_ID}/characters`).then(r => r.json()),
  ]);
  renderContent(segments);
  updateRemainingTime();
  refreshChapterGenerationPanel(chapterId);

  document.getElementById('chapter-content').scrollTop = 0;

  const startIdx = clampSegmentIndex(resumePosition);
  setCurrentSegment(startIdx, {
    highlight: highlightOnLoad,
    behavior: 'auto',
    save: persistOpened,
  });
  updateMediaSessionMetadata(ch.title);
  if (window.matchMedia('(max-width: 768px)').matches) setTOCOpen(false);
}

// ── Content rendering ─────────────────────────────────────────────────────────

function renderContent(segs) {
  const container = document.getElementById('chapter-content');

  if (!segs || !segs.length) {
    container.innerHTML = '<div class="placeholder-text">Ehhez a fejezethez nincs megjeleníthető tartalom.</div>';
    return;
  }

  const html = segs.map((seg, i) => {
    const words = seg.text.split(/(\s+)/);
    const wordSpans = words.map((w, wi) => {
      if (/^\s+$/.test(w)) return w;
      return `<span class="word" data-seg="${i}" data-word="${wi}">${esc(w)}</span>`;
    }).join('');


    const charAttr = seg.character_name ? ` data-char="${esc(seg.character_name)}"` : '';
    const speakerColor = getSpeakerColor(seg.character_name);
    const cls = [
      'sentence',
      seg.is_dialogue ? 'dialogue-sent speaker-range' : '',
      seg.speaker_candidate ? 'speaker-candidate' : '',
      seg.speaker_continuation ? 'speaker-continuation' : 'speaker-turn-start',
    ].filter(Boolean).join(' ');
    const canEditSpeaker = seg.unit_index !== null &&
      seg.unit_index !== undefined;
    const previousSegment = i > 0 ? segs[i - 1] : null;
    const continuesSameAssignedSpeaker = Boolean(
      seg.character_name &&
      previousSegment?.character_name === seg.character_name
    );
    const isManualNarration = (
      seg.speaker_source === 'manual' && !seg.character_name
    );
    const startsNarrationRange = Boolean(
      !seg.character_name && previousSegment?.character_name
    );
    const showNarrationLabel = isManualNarration || startsNarrationRange;
    const showLabel = canEditSpeaker &&
      (seg.speaker_candidate || seg.character_name || showNarrationLabel) &&
      (
        !seg.speaker_continuation ||
        !seg.character_name ||
        !continuesSameAssignedSpeaker
      );
    const speakerRangeEnd = getStoredSpeakerRangeEnd(i, segs);
    const speakerRangeLength = speakerRangeEnd - i + 1;
    const speakerLabel = showLabel
      ? `<button class="speaker-label${seg.character_name ? '' : ' unassigned'}"
           type="button"
           title="${seg.character_name
             ? `${speakerRangeLength} ${speakerRangeLength === 1 ? 'mondat' : 'mondat'} ehhez rendelve: ${esc(seg.character_name)}`
             : showNarrationLabel
               ? 'Narrációként megjelölve'
               : 'Lehetséges párbeszéd hozzárendelt beszélő nélkül'} — rámutatással kiemelhető, kattintással javítható"
           onmouseenter="previewStoredSpeakerRange(${i})"
           onmouseleave="clearStoredSpeakerRangePreview()"
           onfocus="previewStoredSpeakerRange(${i})"
           onblur="clearStoredSpeakerRangePreview()"
           onclick="event.stopPropagation();openSpeakerEditor(${i})">
           <span aria-hidden="true">${seg.speaker_source === 'manual' ? '&#10003;' : '&#10022;'}</span>
           <span class="speaker-label-text">${esc(seg.character_name || (
             showNarrationLabel ? 'Narráció' : 'Beszélő megadása'
           ))}</span>
         </button>`
      : '';
    const inlineEditor = canEditSpeaker
      ? `<select class="speaker-inline-select" aria-label="A mondat beszélője"
                 onclick="event.stopPropagation()"
                 onchange="quickAssignSpeaker(${i},this)">
           ${speakerOptions(seg.character_name)}
         </select>`
      : '';
    return `<span class="${cls}" data-idx="${i}"${charAttr}
                  style="--speaker-color:${speakerColor}"
                  onclick="jumpTo(${i})">
              ${inlineEditor}${speakerLabel}<span class="sentence-text">${wordSpans}</span>
            </span> `;
  }).join('');

  container.classList.toggle('speaker-edit-active', speakerEditMode);
  container.innerHTML = `<div class="chapter-text-flow">${html}</div>`;

  // Restore font prefs (font may be reset by innerHTML)
  container.style.fontSize   = fontSize + 'px';
  container.style.lineHeight = lineHeight;
  container.style.fontFamily = FONT_FAMILIES[fontFamily] || FONT_FAMILIES.serif;
}

function getStoredSpeakerRangeEnd(segmentIndex, sourceSegments = segments) {
  const storedName = String(sourceSegments[segmentIndex]?.character_name || '');
  if (!storedName) return segmentIndex;

  let end = segmentIndex;
  while (
    end + 1 < sourceSegments.length &&
    String(sourceSegments[end + 1]?.character_name || '') === storedName
  ) {
    end += 1;
  }
  return end;
}

function clearStoredSpeakerRangePreview() {
  document.querySelectorAll('.sentence.speaker-range-hover')
    .forEach(element => element.classList.remove('speaker-range-hover'));
}

function previewStoredSpeakerRange(segmentIndex) {
  clearStoredSpeakerRangePreview();
  const end = getStoredSpeakerRangeEnd(segmentIndex);
  for (let index = segmentIndex; index <= end; index += 1) {
    document.querySelector(`.sentence[data-idx="${index}"]`)
      ?.classList.add('speaker-range-hover');
  }
}

function jumpTo(idx) {
  if (speakerEditMode) {
    openSpeakerEditor(idx);
    return;
  }
  if (isPlaying) playSegment(idx);
  else { setCurrentSegment(idx, { highlight: true, save: true }); }
}

// ── Playback ──────────────────────────────────────────────────────────────────

// Kick off generation for segment 0 and, critically, the first segment that
// has no server-cached audio yet (the "frontier").  Firing the frontier at
// chapter-open time gives it the maximum possible lead before playback
// reaches it — without it, the chain only fires the frontier after 3–4
// cached segments play through, which is too late for slow TTS on CPU.
async function _waitForTtsReady(bufferId, chapterId) {
  while (_bufferGenId === bufferId && currentChapterId === chapterId) {
    try {
      const status = await fetch('/api/tts/status').then(r => r.json());
      if (status.state === 'ready') return true;
      if (status.state === 'error') return false;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 750));
  }
  return false;
}

function getSpeakerColor(name) {
  const character = speakerCharacters.find(item => item.name === name);
  return character?.color_hex || '#c8a46e';
}

function speakerOptions(currentName = '') {
  return [
    `<option value=""${currentName ? '' : ' selected'}>Narráció / nincs beszélő</option>`,
    ...speakerCharacters.map(character => {
      const selected = character.name === currentName ? ' selected' : '';
      return `<option value="${esc(character.name)}"${selected}>${esc(character.name)} · ${Number(character.frequency) || 0}</option>`;
    }),
    '<option value="__new__">+ Új szereplő…</option>',
  ].join('');
}

function applySpeakerLabelPreference() {
  const layout = document.getElementById('reader-layout');
  const button = document.getElementById('speaker-label-toggle');
  layout?.classList.toggle('show-speakers', showSpeakerLabels);
  if (button) {
    button.setAttribute('aria-pressed', String(showSpeakerLabels));
    button.classList.toggle('active', showSpeakerLabels);
    button.textContent = showSpeakerLabels ? 'Beszélők elrejtése' : 'Beszélők';
  }
}

document.getElementById('speaker-label-toggle')?.addEventListener('click', () => {
  showSpeakerLabels = !showSpeakerLabels;
  localStorage.setItem('showSpeakerLabels', String(showSpeakerLabels));
  applySpeakerLabelPreference();
});

function toggleSpeakerEditMode() {
  speakerEditMode = !speakerEditMode;
  const button = document.getElementById('speaker-edit-toggle');
  const banner = document.getElementById('speaker-edit-banner');
  if (button) {
    button.classList.toggle('active', speakerEditMode);
    button.textContent = speakerEditMode ? 'Beszélők szerkesztése' : 'Beszélők javítása';
  }
  if (banner) banner.classList.toggle('hidden', !speakerEditMode);
  renderContent(segments);
  highlightSegment(currentSegIdx, { behavior: 'auto' });
}

function openSpeakerEditor(segmentIndex, proposedSpeakerName = undefined) {
  const seg = segments[segmentIndex];
  if (!seg || seg.unit_index === null || seg.unit_index === undefined) return;
  clearStoredSpeakerRangePreview();
  editingSpeakerSegmentIndex = segmentIndex;

  const select = document.getElementById('speaker-editor-select');
  const currentName = proposedSpeakerName === undefined
    ? String(seg.character_name || '')
    : String(proposedSpeakerName || '');
  select.innerHTML = [
    '<option value="">Nincs beszélő / narráció</option>',
    ...speakerCharacters.map(character =>
      `<option value="${esc(character.name)}">${esc(character.name)} (${Number(character.frequency) || 0} megszólalás)</option>`
    ),
    '<option value="__new__">+ Új szereplő hozzáadása…</option>',
  ].join('');

  const known = speakerCharacters.some(character =>
    character.name.toLocaleLowerCase() === currentName.toLocaleLowerCase()
  );
  select.value = currentName && known ? currentName : (currentName ? '__new__' : '');
  document.getElementById('speaker-editor-new').value =
    currentName && !known && currentName !== '__new__' ? currentName : '';

  const initialEnd = proposedSpeakerName === undefined
    ? getStoredSpeakerRangeEnd(segmentIndex)
    : segmentIndex;
  const range = document.getElementById('speaker-range-end');
  range.min = String(segmentIndex);
  range.max = String(Math.min(segments.length - 1, segmentIndex + 200));
  range.value = String(initialEnd);
  editingSpeakerRangeEndIndex = initialEnd;
  previewSpeakerRange();
  toggleNewSpeakerInput();
  const overlay = document.getElementById('speaker-editor-overlay');
  if (select.value === '__new__') {
    openModal(overlay, document.getElementById('speaker-editor-new'));
  } else {
    openModal(overlay, select);
  }
}

function previewSpeakerRange() {
  const start = editingSpeakerSegmentIndex;
  if (start === null || start === undefined) return;
  const range = document.getElementById('speaker-range-end');
  const end = Math.max(start, clampSegmentIndex(range.value));
  range.value = String(end);
  editingSpeakerRangeEndIndex = end;

  const selected = segments.slice(start, end + 1);
  document.getElementById('speaker-editor-quote').textContent =
    selected.map(segment => segment.text).join(' ');
  document.getElementById('speaker-range-count').textContent =
    `${selected.length} mondat`;
  document.getElementById('speaker-range-end-text').textContent =
    segments[end]?.text || '';

  document.querySelectorAll('.sentence.speaker-range-preview')
    .forEach(element => element.classList.remove('speaker-range-preview'));
  for (let index = start; index <= end; index += 1) {
    document.querySelector(`.sentence[data-idx="${index}"]`)
      ?.classList.add('speaker-range-preview');
  }
}

function adjustSpeakerRange(delta) {
  const range = document.getElementById('speaker-range-end');
  const next = Number(range.value) + Number(delta || 0);
  range.value = String(Math.max(
    Number(range.min),
    Math.min(Number(range.max), next),
  ));
  previewSpeakerRange();
}

function toggleNewSpeakerInput() {
  const isNew = document.getElementById('speaker-editor-select').value === '__new__';
  document.getElementById('speaker-editor-new-wrap').classList.toggle('hidden', !isNew);
}

function closeSpeakerEditor() {
  closeModal(document.getElementById('speaker-editor-overlay'));
  document.querySelectorAll('.sentence.speaker-range-preview')
    .forEach(element => element.classList.remove('speaker-range-preview'));
  editingSpeakerSegmentIndex = null;
  editingSpeakerRangeEndIndex = null;
}

async function saveSpeakerCorrection() {
  const segmentIndex = editingSpeakerSegmentIndex;
  const seg = segments[segmentIndex];
  if (!seg) return;

  const select = document.getElementById('speaker-editor-select');
  const speakerName = select.value === '__new__'
    ? document.getElementById('speaker-editor-new').value.trim()
    : select.value;
  if (select.value === '__new__' && !speakerName) {
    showToast('Add meg a szereplő nevét.', 'err');
    document.getElementById('speaker-editor-new').focus();
    return;
  }

  const rangeEndIndex = editingSpeakerRangeEndIndex ?? segmentIndex;
  const rangeEndUnitIndex = segments[rangeEndIndex]?.unit_index;
  const saveButton = document.getElementById('speaker-editor-save');
  saveButton.disabled = true;
  try {
    await persistSpeakerCorrection(
      segmentIndex,
      speakerName,
      'range',
      rangeEndUnitIndex,
    );
    closeSpeakerEditor();
  } finally {
    saveButton.disabled = false;
  }
}

async function quickAssignSpeaker(segmentIndex, select) {
  const proposedName = select.value;
  openSpeakerEditor(segmentIndex, proposedName);
  select.value = String(segments[segmentIndex]?.character_name || '');
}

async function persistSpeakerCorrection(
  segmentIndex,
  speakerName,
  scope,
  rangeEndUnitIndex = null,
) {
  const seg = segments[segmentIndex];
  if (!seg) return;
  const container = document.getElementById('chapter-content');
  const previousScroll = container.scrollTop;
  try {
    const response = await fetch(
      `/api/books/${BOOK_ID}/chapters/${currentChapterId}/speaker-annotations`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          unit_index: seg.unit_index,
          speaker_name: speakerName || null,
          scope: scope || 'sentence',
          range_end_unit_index: rangeEndUnitIndex,
        }),
      }
    );
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'A beszélő mentése nem sikerült.');

    stopPlayback();
    _segCache = new Map();
    [segments, speakerCharacters] = await Promise.all([
      fetch(`/api/tts/segments/${BOOK_ID}/${currentChapterId}`).then(r => r.json()),
      fetch(`/api/books/${BOOK_ID}/characters`).then(r => r.json()),
    ]);
    renderContent(segments);
    container.scrollTop = previousScroll;
    setCurrentSegment(clampSegmentIndex(segmentIndex), {
      highlight: true,
      behavior: 'auto',
      save: true,
    });
    refreshChapterGenerationPanel(currentChapterId);
    const scopeMessage = result.updated_units > 1
      ? ` (${result.updated_units} mondat)`
      : '';
    showToast(speakerName
      ? `Beszélő mentve: ${speakerName}${scopeMessage}`
      : `Narrációként megjelölve${scopeMessage}.`);
  } catch (error) {
    showToast(error.message, 'err');
    renderContent(segments);
  }
}

async function _prewarmChapter() {
  if (!segments.length) return;
  if (_exportBusy) return;
  const bufferId = _bufferGenId;
  const chapterId = currentChapterId;
  if (!await _waitForTtsReady(bufferId, chapterId)) return;
  _extendPrewarm(currentSegIdx);
}

// ── Whole-chapter generation ─────────────────────────────────────────────────

function markChapterReady(chapterId, ready = true) {
  const badge = document.querySelector(
    `.toc-item[data-id="${chapterId}"] .toc-ready-badge`
  );
  if (badge) badge.classList.toggle('hidden', !ready);
}

function renderChapterGenerationStatus(state) {
  if (!state || Number(state.chapter_id) !== Number(currentChapterId)) return;
  const card = document.getElementById('chapter-generate-card');
  const btn = document.getElementById('chapter-generate-btn');
  const pctEl = document.getElementById('chapter-generate-percent');
  const fill = document.getElementById('chapter-generate-fill');
  const progress = document.getElementById('chapter-generate-progress');
  const status = document.getElementById('chapter-generate-status');
  const total = Number(state.total) || segments.length || 0;
  const done = Math.min(Number(state.done ?? state.ready) || 0, total || Infinity);
  const pct = total > 0
    ? Math.max(0, Math.min(100, Math.round((done / total) * 100)))
    : 0;
  const isComplete = state.state === 'complete' || (total > 0 && done >= total);
  const isRunning = state.state === 'pending' || state.state === 'running';
  const busyElsewhere = state.busy_job_id &&
    Number(state.busy_chapter_id) !== Number(currentChapterId);

  pctEl.textContent = `${isComplete ? 100 : pct}%`;
  fill.style.width = `${isComplete ? 100 : pct}%`;
  progress.setAttribute('aria-valuenow', String(isComplete ? 100 : pct));
  card.classList.toggle('complete', isComplete);

  if (isComplete) {
    btn.disabled = true;
    btn.innerHTML = '&#10003; Kész';
    status.textContent = `${total}/${total} szakasz elkészült`;
    markChapterReady(currentChapterId, true);
  } else if (isRunning) {
    btn.disabled = true;
    btn.textContent = 'Készítés…';
    let message = `${done}/${total} szakasz elkészült`;
    if (state.eta_sec != null && Number.isFinite(state.eta_sec) && done < total) {
      message += ` · kb. ${formatDurationShort(state.eta_sec)} van hátra`;
    }
    status.textContent = message;
  } else if (busyElsewhere) {
    btn.disabled = true;
    btn.textContent = 'A generátor foglalt';
    status.textContent = 'Egy másik fejezet hangja készül.';
  } else if (state.state === 'failed') {
    btn.disabled = false;
    btn.textContent = 'Fejezet újrapróbálása';
    status.textContent = state.error || 'A hang készítése nem sikerült.';
  } else {
    btn.disabled = !total;
    btn.textContent = done > 0 ? 'Készítés folytatása' : 'Fejezet elkészítése';
    status.textContent = total
      ? `${done}/${total} szakasz kész`
      : 'A fejezethez nincs hangszakasz.';
  }
}

async function refreshChapterGenerationPanel(chapterId) {
  try {
    const state = await fetch(
      `/api/books/${BOOK_ID}/chapters/${chapterId}/generate`
    ).then(r => r.json());
    if (Number(chapterId) !== Number(currentChapterId)) return;
    renderChapterGenerationStatus(state);
    const jobId = state.job_id || state.busy_job_id;
    const jobChapterId = state.state === 'running' || state.state === 'pending'
      ? chapterId
      : state.busy_chapter_id;
    if (jobId && (state.state === 'running' || state.state === 'pending' || state.busy_job_id)) {
      monitorChapterGeneration(jobId, jobChapterId);
    }
  } catch (_) {
    if (Number(chapterId) === Number(currentChapterId)) {
      document.getElementById('chapter-generate-status').textContent =
        'A készítés állapota nem tölthető be.';
    }
  }
}

function pauseInteractiveTtsForBulkWork() {
  _exportBusy = true;
  _bufferGenId++;
  if (isPlaying) {
    try { stopPlayback(); } catch (_) {}
  }
  for (const [idx, controller] of _ttsAbortControllers.entries()) {
    controller.abort();
    _segCache.delete(idx);
  }
  _ttsAbortControllers.clear();
}

async function monitorChapterGeneration(jobId, chapterId) {
  if (_activeChapterGeneration?.jobId === jobId) return;
  _activeChapterGeneration = { jobId, chapterId };
  _exportBusy = true;

  while (_activeChapterGeneration?.jobId === jobId) {
    await new Promise(resolve => setTimeout(resolve, 500));
    let state;
    try {
      state = await fetch(`/api/chapter-generation/status/${jobId}`).then(r => r.json());
      if (state.error && !state.state) state.state = 'failed';
    } catch (_) {
      continue;
    }

    if (Number(currentChapterId) === Number(chapterId)) {
      renderChapterGenerationStatus(state);
    }
    if (!['complete', 'failed', 'cancelled', 'interrupted'].includes(state.state)) continue;

    _activeChapterGeneration = null;
    _exportBusy = false;
    if (state.state === 'complete') {
      markChapterReady(chapterId, true);
      if (Number(currentChapterId) === Number(chapterId)) {
        segments.forEach(seg => { seg.has_audio = true; });
        showToast('A fejezet hangja elkészült.');
      }
    } else if (Number(currentChapterId) === Number(chapterId)) {
      showToast(state.state === 'cancelled' ? 'A fejezethang készítése leállítva.' : state.state === 'interrupted' ? 'A fejezethang készítése megszakadt. A Feladatok oldalon folytathatod.' : 'A fejezethang készítése nem sikerült.');
    }

    if (currentChapterId) {
      refreshChapterGenerationPanel(currentChapterId);
      if (state.state === 'complete') {
        _startBackgroundBuffer(currentSegIdx);
        _prewarmChapter();
      }
    }
    return;
  }
}

document.getElementById('chapter-generate-btn').onclick = async () => {
  if (!currentChapterId) return;
  const chapterId = currentChapterId;
  pauseInteractiveTtsForBulkWork();
  renderChapterGenerationStatus({
    chapter_id: chapterId,
    state: 'pending',
    done: segments.filter(seg => seg.has_audio).length,
    total: segments.length,
  });

  try {
    const response = await fetch(
      `/api/books/${BOOK_ID}/chapters/${chapterId}/generate`,
      { method: 'POST' },
    );
    const state = await response.json();
    if (!response.ok || state.error) {
      _exportBusy = false;
      renderChapterGenerationStatus({
        ...state,
        chapter_id: chapterId,
        state: 'failed',
        done: segments.filter(seg => seg.has_audio).length,
        total: segments.length,
      });
      _startBackgroundBuffer(currentSegIdx);
      _prewarmChapter();
      return;
    }
    renderChapterGenerationStatus(state);
    if (state.state === 'complete') {
      _exportBusy = false;
      segments.forEach(seg => { seg.has_audio = true; });
      markChapterReady(chapterId, true);
      return;
    }
    monitorChapterGeneration(state.job_id, chapterId);
  } catch (error) {
    _exportBusy = false;
    renderChapterGenerationStatus({
      chapter_id: chapterId,
      state: 'failed',
      error: error.message,
      done: segments.filter(seg => seg.has_audio).length,
      total: segments.length,
    });
    _startBackgroundBuffer(currentSegIdx);
    _prewarmChapter();
  }
};

// Keep a chunk of concurrent HTTP requests ahead of playback.  The server
// coalesces requests arriving together into one OmniVoice generate_many()
// call, so the configured GPU batch size is also used during reading.
function _extendPrewarm(fromIdx) {
  if (!segments.length) return;
  const start = Math.max(0, fromIdx);
  if (_prewarmFrontier < start) _prewarmFrontier = start;
  const target = Math.min(
    segments.length,
    Math.max(_prewarmFrontier, start) + TTS_PREWARM_CHUNK,
  );
  for (let i = _prewarmFrontier; i < target; i++) {
    fetchSegmentData(i);
  }
  _prewarmFrontier = target;
}

// Sequentially generates TTS audio for every segment from fromIdx onward.
// Waits until playback is idle before firing each request so it never
// competes with the active playback pipeline at the server TTS lock.
// Skips ahead to currentSegIdx+3 after each playback pause so it stays
// ahead of the cursor when the user is reading without playing.
async function _startBackgroundBuffer(fromIdx) {
  const myId = ++_bufferGenId;
  const myChapterId = currentChapterId;
  if (!await _waitForTtsReady(myId, myChapterId)) return;

  for (let i = fromIdx; i < segments.length; i++) {
    if (_bufferGenId !== myId || currentChapterId !== myChapterId) return;

    // Export owns the TTS engine — do not interleave single-segment synth.
    while (_exportBusy) {
      await new Promise(r => setTimeout(r, 800));
      if (_bufferGenId !== myId || currentChapterId !== myChapterId) return;
    }

    // Wait out any active playback before sending a new TTS request
    while (isPlaying) {
      await new Promise(r => setTimeout(r, 600));
      if (_bufferGenId !== myId || currentChapterId !== myChapterId) return;
      // Stay ahead of the cursor, not behind it
      i = Math.max(i, currentSegIdx + 3) - 1;
    }

    // Re-check cancellation after the wait
    if (_bufferGenId !== myId || currentChapterId !== myChapterId) return;

    // Skip segments already in the promise cache (fetched by preload or prewarm)
    if (_segCache.has(i)) {
      try { await _segCache.get(i); } catch (_) {}
      await new Promise(r => setTimeout(r, 100));
      continue;
    }

    try {
      await fetchSegmentData(i);
    } catch (_) {}

    // Small throttle between generations to let the event loop breathe
    await new Promise(r => setTimeout(r, 100));
  }
}

function fetchSegmentData(idx) {
  if (!_segCache.has(idx)) {
    const controller = new AbortController();
    _ttsAbortControllers.set(idx, controller);
    const p = fetch('/api/tts/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ book_id: BOOK_ID, chapter_id: currentChapterId, segment_index: idx }),
      signal: controller.signal,
    }).then(async r => {
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        // During export the API returns 503 export_busy — drop cache entry so we retry later.
        if (e.export_busy) _segCache.delete(idx);
        throw new Error(e.error || `HTTP ${r.status}`);
      }
      return r.json();
    }).then(data => {
      if (segments[idx]) {
        segments[idx].has_audio = true;
        segments[idx].duration_sec = Number(data.duration_sec) || segments[idx].duration_sec;
      }
      updateRemainingTime();
      return data;
    }).finally(() => {
      if (_ttsAbortControllers.get(idx) === controller) {
        _ttsAbortControllers.delete(idx);
      }
    });
    // Evict on failure so the next call retries rather than re-throwing the cached rejection.
    p.catch(() => _segCache.delete(idx));
    _segCache.set(idx, p);
  }
  return _segCache.get(idx);
}

async function _schedulePreload(playingIdx) {
  if (!isPlaying) return;
  const nextIdx = playingIdx + 1;
  if (nextIdx >= segments.length) return;

  // Refill in chunks instead of adding one isolated request per sentence.
  // This keeps real GPU batches queued even for short, alternating dialogue.
  if (nextIdx + TTS_PREWARM_LOW_WATER >= _prewarmFrontier) {
    _extendPrewarm(nextIdx);
  }

  try {
    const data = await fetchSegmentData(nextIdx);
    if (!isPlaying) return;

    if (_preloadIdx !== nextIdx) {
      const sb = _standby();
      sb.src = data.audio_url;
      sb.playbackRate = speedMultiplier;
      _preloadIdx = nextIdx;
      _preloadData = data;
    }
  } catch (e) {
    // silent — playSegment will retry via its own fetchSegmentData call
  }
}

function positionAudio(element, offsetSec, knownDuration = null) {
  const requested = Math.max(0, Number(offsetSec) || 0);
  const apply = () => {
    const duration = Number.isFinite(element.duration)
      ? element.duration
      : Number(knownDuration);
    element.currentTime = Number.isFinite(duration) && duration > 0
      ? Math.min(requested, Math.max(0, duration - 0.01))
      : requested;
  };
  if (element.readyState >= 1) {
    apply();
    return Promise.resolve();
  }
  return new Promise(resolve => {
    const finish = () => {
      element.removeEventListener('loadedmetadata', finish);
      element.removeEventListener('error', finish);
      try { apply(); } catch (_) {}
      resolve();
    };
    element.addEventListener('loadedmetadata', finish, { once: true });
    element.addEventListener('error', finish, { once: true });
  });
}

async function playSegment(idx, options = {}) {
  if (idx >= segments.length) { stopPlayback(); return; }
  const offsetSec = Math.max(0, Number(options.offsetSec) || 0);

  if (_interSegmentTimer) {
    clearTimeout(_interSegmentTimer);
    _interSegmentTimer = null;
  }
  _pendingSegmentIdx = -1;
  const gen = ++_playGen;

  isPlaying = true;
  setCurrentSegment(idx, { highlight: true, save: true });

  const seg = segments[idx];
  const charEl = document.getElementById('pb-character');
  const charLabel = seg.character_name || 'Narrátor';
  charEl.textContent = charLabel;

  try {
    let data;

    if (_preloadIdx === idx && _preloadData) {
      // Standby element already buffered — swap and play instantly
      _swapAudio();
      data = _preloadData;
      _preloadIdx = -1;
      _preloadData = null;
    } else {
      // Show buffering indicator while TTS generates
      charEl.textContent = `⏳ ${charLabel}`;
      data = await fetchSegmentData(idx);
      // Bail out if a newer playSegment or stopPlayback has since taken over
      if (gen !== _playGen || !isPlaying) return;
      charEl.textContent = charLabel;
      audio.src = data.audio_url;
    }

    audio.playbackRate = speedMultiplier;
    await positionAudio(audio, offsetSec, data.duration_sec);
    if (gen !== _playGen || !isPlaying) return;
    _loadedSegIdx = idx;
    startWordHighlight(idx, data.duration_sec);
    await audio.play();

    _schedulePreload(idx);

  } catch(e) {
    if (gen !== _playGen) return;   // stale — a newer segment took over
    charEl.textContent = e.message;
    stopPlayback();
  }
}

function _onAudioEnded() {
  stopWordHighlight();
  if (!isPlaying) return;
  const next = currentSegIdx + 1;
  if (next < segments.length) {
    const pauseMs = pauseAfterSegmentMs(segments[currentSegIdx], segments[next]);
    _pendingSegmentIdx = next;
    _interSegmentTimer = setTimeout(() => {
      _interSegmentTimer = null;
      const pendingIdx = _pendingSegmentIdx;
      _pendingSegmentIdx = -1;
      if (isPlaying) playSegment(pendingIdx);
    }, pauseMs);
  }
  else {
    queueProgressSave(currentChapterId, currentSegIdx);
    if (_sleepMode === 'chapter') {
      clearSleepTimer();
      showToast('A lejátszás a fejezet végén leállt.');
    }
    stopPlayback();
  }
}

function _onAudioError() {
  stopWordHighlight();
  if (!isPlaying) return;
  // Evict cached promise so the segment will be re-fetched on retry
  _segCache.delete(currentSegIdx);
  // Skip the broken segment rather than stopping entirely
  const next = currentSegIdx + 1;
  if (next < segments.length) playSegment(next);
  else stopPlayback();
}

_audioA.addEventListener('ended', _onAudioEnded);
_audioB.addEventListener('ended', _onAudioEnded);
_audioA.addEventListener('error', _onAudioError);
_audioB.addEventListener('error', _onAudioError);

function stopPlayback() {
  isPlaying = false;
  _bufferGenId++;        // terminate the chapter-wide background generation loop
  _playGen++;            // invalidate any in-flight playSegment coroutine
  for (const [idx, controller] of _ttsAbortControllers.entries()) {
    controller.abort();
    _segCache.delete(idx);
  }
  _ttsAbortControllers.clear();
  // Aborting fetch only disconnects the browser. This endpoint interrupts the
  // actual Higgs autoregressive token loop on the server/GPU.
  fetch('/api/tts/cancel', { method: 'POST' }).catch(() => {});
  if (_interSegmentTimer) {
    clearTimeout(_interSegmentTimer);
    _interSegmentTimer = null;
  }
  _pendingSegmentIdx = -1;
  stopWordHighlight();
  _audioA.pause();
  _audioB.pause();
  _audioA.src = '';
  _audioB.src = '';
  audio = _audioA; // reset active to primary
  _loadedSegIdx = -1;
  _preloadIdx = -1;
  _preloadData = null;
  if (currentChapterId) queueProgressSave(currentChapterId, currentSegIdx);
  const btn = document.getElementById('btn-play');
  btn.innerHTML = '&#9654;';
  btn.classList.add('paused');
  document.getElementById('pb-character').textContent = '—';
  updatePlaybackUI();
}

// ── Word-level highlighting ───────────────────────────────────────────────────

let _wordRafId = null;

function startWordHighlight(segIdx, durationSec) {
  stopWordHighlight();
  if (!durationSec) return;

  const wordEls = document.querySelectorAll(`.word[data-seg="${segIdx}"]`);
  if (!wordEls.length) return;

  const n = wordEls.length;

  function tick() {
    // audio.currentTime already advances in media time at the selected playbackRate.
    const wordIdx = AurisListening.wordIndexFromMediaTime(
      audio.currentTime,
      0,
      durationSec,
      n,
    );
    wordEls.forEach((el, i) => el.classList.toggle('playing', i === wordIdx));
    if (isPlaying && !audio.paused) _wordRafId = requestAnimationFrame(tick);
  }

  _wordRafId = requestAnimationFrame(tick);
}

function stopWordHighlight() {
  if (_wordRafId) { cancelAnimationFrame(_wordRafId); _wordRafId = null; }
  document.querySelectorAll('.word.playing').forEach(el => el.classList.remove('playing'));
}

// ── Segment highlighting & auto-scroll ────────────────────────────────────────

function highlightSegment(idx, options = {}) {
  const behavior = options.behavior || 'smooth';
  _ignoreScrollTrackingUntil = Date.now() + (behavior === 'smooth' ? 700 : 150);
  document.querySelectorAll('.sentence').forEach((el, i) => {
    el.classList.toggle('playing', i === idx);
    el.classList.toggle('spoken',  i < idx);
  });
  const active = document.querySelector(`.sentence[data-idx="${idx}"]`);
  if (active) active.scrollIntoView({ behavior, block: 'center' });
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function updateProgress() {
  if (!segments.length) return;
  const pct = ((currentSegIdx) / segments.length) * 100;
  const fill = document.getElementById('chapter-progress-fill');
  if (fill) fill.style.width = pct + '%';
}

// ── Playback UI ───────────────────────────────────────────────────────────────

function updatePlaybackUI() {
  const btn  = document.getElementById('btn-play');
  const prog = document.getElementById('pb-progress');
  if (isPlaying) {
    btn.innerHTML = '&#9646;&#9646;';
    btn.classList.remove('paused');
    btn.setAttribute('aria-label', 'Szünet');
  } else {
    btn.innerHTML = '&#9654;';
    btn.classList.add('paused');
    btn.setAttribute('aria-label', 'Lejátszás');
  }
  if (segments.length) prog.textContent = `${currentSegIdx + 1} / ${segments.length}`;
  if ('mediaSession' in navigator) {
    navigator.mediaSession.playbackState = isPlaying ? 'playing' : 'paused';
  }
  updateRemainingTime();
}

function formatClock(seconds) {
  const safe = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
    : `${minutes}:${String(secs).padStart(2, '0')}`;
}

function updateRemainingTime() {
  const element = document.getElementById('pb-remaining');
  if (!element || !segments.length) return;
  const currentTime = _loadedSegIdx === currentSegIdx ? Number(audio.currentTime) || 0 : 0;
  const remaining = AurisListening.estimateRemainingAudio(
    segments,
    currentSegIdx,
    currentTime,
    speedMultiplier,
  );
  element.textContent = `Hátralévő idő: ${remaining.estimated ? 'kb. ' : ''}${formatClock(remaining.seconds)}`;
  element.title = remaining.estimated
    ? 'Becsült idő: néhány szakasz hangja még nincs elkészítve.'
    : 'A rendelkezésre álló hangok alapján.';
  updateMediaSessionPosition();
}

function pausePlayback() {
  isPlaying = false;
  if (_interSegmentTimer) {
    clearTimeout(_interSegmentTimer);
    _interSegmentTimer = null;
  }
  stopWordHighlight();
  audio.pause();
  updatePlaybackUI();
  queueProgressSave(currentChapterId, currentSegIdx);
}

async function resumePlayback() {
  const target = AurisListening.playbackResumeTarget(
    _pendingSegmentIdx,
    currentSegIdx,
    _loadedSegIdx,
    audio.currentTime,
  );
  if (target.segmentIndex !== currentSegIdx) {
    playSegment(target.segmentIndex);
    return;
  }
  if (_loadedSegIdx === currentSegIdx && audio.src && target.offsetSec > 0) {
    isPlaying = true;
    highlightSegment(currentSegIdx);
    startWordHighlight(currentSegIdx, segments[currentSegIdx]?.duration_sec || audio.duration);
    updatePlaybackUI();
    try {
      await audio.play();
      _schedulePreload(currentSegIdx);
    } catch (error) {
      showToast(error.message, 'err');
      pausePlayback();
    }
    return;
  }
  playSegment(_pendingSegmentIdx >= 0 ? _pendingSegmentIdx : currentSegIdx);
}

async function seekAudioBy(deltaSec) {
  if (!segments.length) return;
  const sourceTime = _loadedSegIdx === currentSegIdx ? Number(audio.currentTime) || 0 : 0;
  const target = AurisListening.seekTarget(segments, currentSegIdx, sourceTime, deltaSec);
  const wasPlaying = isPlaying;

  if (target.segmentIndex === currentSegIdx && _loadedSegIdx === currentSegIdx) {
    await positionAudio(audio, target.offsetSec, segments[currentSegIdx]?.duration_sec);
    highlightSegment(currentSegIdx);
    if (wasPlaying) startWordHighlight(currentSegIdx, segments[currentSegIdx]?.duration_sec);
    updateRemainingTime();
    return;
  }

  if (wasPlaying) {
    playSegment(target.segmentIndex, { offsetSec: target.offsetSec });
    return;
  }

  setCurrentSegment(target.segmentIndex, { highlight: true, save: true });
  try {
    const data = await fetchSegmentData(target.segmentIndex);
    audio.src = data.audio_url;
    audio.playbackRate = speedMultiplier;
    await positionAudio(audio, target.offsetSec, data.duration_sec);
    _loadedSegIdx = target.segmentIndex;
    updateRemainingTime();
  } catch (error) {
    showToast(error.message, 'err');
  }
}

// ── Controls ──────────────────────────────────────────────────────────────────

document.getElementById('btn-play').onclick = () => {
  if (isPlaying) {
    pausePlayback();
  } else {
    resumePlayback();
  }
};

document.getElementById('btn-stop').onclick = () => {
  stopPlayback();
};

document.getElementById('btn-next-seg').onclick = () => {
  const next = Math.min(currentSegIdx + 1, segments.length - 1);
  if (isPlaying) playSegment(next);
  else { setCurrentSegment(next, { highlight: true, save: true }); }
};

document.getElementById('btn-prev-seg').onclick = () => {
  const prev = Math.max(currentSegIdx - 1, 0);
  if (isPlaying) playSegment(prev);
  else { setCurrentSegment(prev, { highlight: true, save: true }); }
};

document.getElementById('btn-seek-back').onclick = () => seekAudioBy(-15);
document.getElementById('btn-seek-forward').onclick = () => seekAudioBy(15);

document.getElementById('speed-slider').oninput = function() {
  speedMultiplier = parseFloat(this.value);
  document.getElementById('speed-val').textContent = speedMultiplier.toFixed(1) + '×';
  _audioA.playbackRate = speedMultiplier;
  _audioB.playbackRate = speedMultiplier;
  updateRemainingTime();
};

function clearSleepTimer() {
  if (_sleepTimerId) clearTimeout(_sleepTimerId);
  _sleepTimerId = null;
  _sleepMode = 'off';
  const select = document.getElementById('sleep-timer');
  if (select) select.value = 'off';
}

document.getElementById('sleep-timer').addEventListener('change', function setSleepTimer() {
  if (_sleepTimerId) clearTimeout(_sleepTimerId);
  _sleepTimerId = null;
  _sleepMode = this.value;
  if (_sleepMode === 'off') return;
  if (_sleepMode === 'chapter') {
    showToast('A lejátszás a fejezet végén leáll.');
    return;
  }
  const minutes = Number(_sleepMode);
  _sleepTimerId = setTimeout(() => {
    pausePlayback();
    clearSleepTimer();
    showToast('Az elalvásidőzítő leállította a lejátszást.');
  }, minutes * 60 * 1000);
  showToast(`Elalvásidőzítő: ${minutes} perc.`);
});

// ── Sidebar toggle ────────────────────────────────────────────────────────────

function setTOCOpen(open) {
  document.getElementById('toc-sidebar').classList.toggle('collapsed', !open);
  document.getElementById('toc-toggle').setAttribute('aria-expanded', String(open));
}

function toggleTOC() {
  const toc = document.getElementById('toc-sidebar');
  setTOCOpen(toc.classList.contains('collapsed'));
}

document.getElementById('toc-toggle').onclick = toggleTOC;
document.getElementById('toc-close').onclick = toggleTOC;

function toggleBookmarkPanel() {
  document.getElementById('bookmarks-panel').classList.toggle('collapsed');
}

function updateMediaSessionMetadata(chapterTitle) {
  if (!('mediaSession' in navigator) || !('MediaMetadata' in window)) return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: chapterTitle || window.BOOK_TITLE,
    album: window.BOOK_TITLE,
    artist: 'Auris',
  });
}

function updateMediaSessionPosition() {
  if (!('mediaSession' in navigator) || typeof navigator.mediaSession.setPositionState !== 'function') return;
  const duration = Number(segments[currentSegIdx]?.duration_sec || audio.duration);
  if (!Number.isFinite(duration) || duration <= 0 || _loadedSegIdx !== currentSegIdx) return;
  try {
    navigator.mediaSession.setPositionState({
      duration,
      playbackRate: speedMultiplier,
      position: Math.min(Math.max(0, Number(audio.currentTime) || 0), duration),
    });
  } catch (_) {}
}

function initMediaSession() {
  if (!('mediaSession' in navigator)) return;
  const handlers = {
    play: () => resumePlayback(),
    pause: () => pausePlayback(),
    stop: () => stopPlayback(),
    previoustrack: () => document.getElementById('btn-prev-seg').click(),
    nexttrack: () => document.getElementById('btn-next-seg').click(),
    seekbackward: details => seekAudioBy(-(details.seekOffset || 15)),
    seekforward: details => seekAudioBy(details.seekOffset || 15),
    seekto: details => {
      if (_loadedSegIdx !== currentSegIdx) return;
      positionAudio(audio, details.seekTime, segments[currentSegIdx]?.duration_sec)
        .then(updateRemainingTime);
    },
  };
  Object.entries(handlers).forEach(([action, handler]) => {
    try { navigator.mediaSession.setActionHandler(action, handler); } catch (_) {}
  });
}

// ── Progress persistence ──────────────────────────────────────────────────────

function updateProgressFromViewport() {
  if (!segments.length || isPlaying || Date.now() < _ignoreScrollTrackingUntil) return;

  const sentenceEls = document.querySelectorAll('.sentence');
  if (!sentenceEls.length) return;

  const viewportCenter = window.innerHeight * 0.35;
  let bestIdx = currentSegIdx;
  let bestDistance = Number.POSITIVE_INFINITY;

  sentenceEls.forEach((el, idx) => {
    const rect = el.getBoundingClientRect();
    const mid = rect.top + (rect.height / 2);
    const distance = Math.abs(mid - viewportCenter);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIdx = idx;
    }
  });

  if (bestIdx !== currentSegIdx) {
    currentSegIdx = bestIdx;
    updatePlaybackUI();
    updateProgress();
    queueProgressSave(currentChapterId, currentSegIdx);
  }
}

function scheduleViewportProgressUpdate() {
  if (!segments.length || isPlaying || Date.now() < _ignoreScrollTrackingUntil) return;
  clearTimeout(_scrollProgressTimer);
  _scrollProgressTimer = setTimeout(updateProgressFromViewport, 120);
}

// ── Whole-book search ────────────────────────────────────────────────────────

function openBookSearch() {
  const overlay = document.getElementById('book-search-overlay');
  openModal(overlay, document.getElementById('book-search-input'));
}

function closeBookSearch() {
  closeModal(document.getElementById('book-search-overlay'));
}

async function searchBook(query) {
  const status = document.getElementById('book-search-status');
  const list = document.getElementById('book-search-results');
  const normalized = String(query || '').trim();
  if (normalized.length < 2) {
    status.textContent = 'Adj meg legalább két karaktert.';
    list.replaceChildren();
    return;
  }

  status.textContent = 'Keresés…';
  list.replaceChildren();
  try {
    const response = await fetch(`/api/books/${BOOK_ID}/search?q=${encodeURIComponent(normalized)}`);
    const results = await response.json();
    if (!response.ok) throw new Error(results.error || 'A keresés nem sikerült.');
    status.textContent = results.length ? `${results.length} találat` : 'Nincs találat.';
    results.forEach(result => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'search-result';
      const title = document.createElement('span');
      title.className = 'search-result-title';
      title.textContent = result.chapter_title || 'Névtelen fejezet';
      const excerpt = document.createElement('span');
      excerpt.className = 'search-result-excerpt';
      excerpt.textContent = result.excerpt || '';
      button.append(title, excerpt);
      button.addEventListener('click', () => {
        closeBookSearch();
        openChapter(Number(result.chapter_id), {
          resumePosition: Number(result.segment_index) || 0,
          persistCurrent: true,
          persistOpened: true,
          highlightOnLoad: true,
        });
      });
      list.appendChild(button);
    });
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById('book-search-btn').addEventListener('click', openBookSearch);
document.getElementById('book-search-close').addEventListener('click', closeBookSearch);
document.getElementById('book-search-overlay').addEventListener('click', event => {
  if (event.target === event.currentTarget) closeBookSearch();
});
document.getElementById('book-search-form').addEventListener('submit', event => {
  event.preventDefault();
  searchBook(document.getElementById('book-search-input').value);
});

// ── Bookmarks ─────────────────────────────────────────────────────────────────

let _bookmarks = [];

async function loadBookmarks() {
  _bookmarks = await fetch(`/api/books/${BOOK_ID}/bookmarks`).then(r => r.json());
  renderBookmarks();
}

function renderBookmarks() {
  const list = document.getElementById('bookmark-list');
  if (!_bookmarks.length) {
    list.innerHTML = '<div style="padding:16px;font-size:.8rem;color:var(--text3);font-style:italic">Még nincs könyvjelző.</div>';
    return;
  }
  list.innerHTML = _bookmarks.map(bm => `
    <div class="bookmark-item">
      <button class="bookmark-goto" type="button" onclick="gotoBookmark(${bm.chapter_id}, ${bm.segment_index})">
        <span class="bookmark-text">${esc(bm.text_excerpt || bm.label || '(nincs részlet)')}</span>
        <span class="bookmark-loc">${esc(bm.chapter_title || '')} &middot; ${bm.segment_index + 1}. szakasz</span>
      </button>
      <button class="bookmark-del" aria-label="Könyvjelző törlése" onclick="removeBookmark(event,${bm.id})">&times;</button>
    </div>`).join('');
}

async function addBookmark() {
  if (!currentChapterId) { showToast('Előbb nyiss meg egy fejezetet.'); return; }
  const seg = segments[currentSegIdx];
  const excerpt = seg ? seg.text.slice(0, 120) : '';
  const r = await fetch(`/api/books/${BOOK_ID}/bookmarks`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      chapter_id:    currentChapterId,
      segment_index: currentSegIdx,
      text_excerpt:  excerpt,
    }),
  });
  if (r.ok) {
    showToast('Könyvjelző hozzáadva.');
    loadBookmarks();
    const btn = document.getElementById('bookmark-btn');
    btn.textContent = '★';
    setTimeout(() => { btn.textContent = '☆'; }, 1500);
  }
}

async function removeBookmark(e, id) {
  e.stopPropagation();
  await fetch(`/api/books/${BOOK_ID}/bookmarks/${id}`, { method: 'DELETE' });
  loadBookmarks();
}

function gotoBookmark(chapterId, segIdx) {
  if (chapterId !== currentChapterId) {
    openChapter(chapterId, {
      resumePosition: segIdx,
      persistCurrent: true,
      persistOpened: true,
      highlightOnLoad: true,
    });
  } else {
    jumpTo(segIdx);
  }
}

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
  }
  updateExportScope();
}

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
      }),
    });
    const d = await r.json();
    if (d.error) { finish(d.error); return; }

    const jobId = d.job_id;
    renderExportLinks(null, jobId);

    // Client-side ETA fallback if server has not reported one yet.
    let clientT0 = Date.now();
    let clientDone0 = null;

    while (true) {
      await new Promise(res => setTimeout(res, 500));
      let sr;
      try { sr = await fetch(`/api/export/status/${jobId}`).then(r => r.json()); }
      catch(_) { continue; }
      if (sr.error && !sr.state) sr.state = 'failed';

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

      if (sr.state === 'complete') {
        progFill.style.width = '100%';
        const res = sr.result || {};
        renderExportLinks(res, jobId);
        finish('Az export elkészült. A fájlok lent tölthetők le.');
        break;
      } else if (sr.state === 'failed') {
        finish('Az export nem sikerült: ' + (sr.error || 'Ismeretlen hiba'));
        break;
      } else if (['cancelled', 'interrupted'].includes(sr.state)) {
        finish(sr.state === 'cancelled' ? 'Az export leállítva. A Feladatok oldalon folytathatod.' : 'Az export megszakadt. A Feladatok oldalon folytathatod.');
        break;
      }
    }
  } catch(e) {
    finish(e.message);
  }
};

// ── Keyboard shortcuts ────────────────────────────────────────────────────────

document.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === 'Tab' && trapModalFocus(e)) return;
  if (e.key === 'Escape') {
    closeSpeakerEditor();
    closeBookSearch();
    hideShortcuts();
    const exportDropdown = document.getElementById('export-dropdown');
    if (!exportDropdown.classList.contains('hidden')) {
      exportDropdown.classList.add('hidden');
      document.getElementById('export-btn').setAttribute('aria-expanded', 'false');
      document.getElementById('export-btn').focus();
    }
    if (window.matchMedia('(max-width: 768px)').matches) {
      setTOCOpen(false);
      document.getElementById('bookmarks-panel').classList.add('collapsed');
    }
    return;
  }
  if (_activeModal || isInteractiveElement(document.activeElement)) return;

  switch(e.key) {
    case ' ':
      e.preventDefault();
      document.getElementById('btn-play').click();
      break;
    case 'ArrowLeft':
      e.preventDefault();
      document.getElementById('btn-prev-seg').click();
      break;
    case 'ArrowRight':
      e.preventDefault();
      document.getElementById('btn-next-seg').click();
      break;
    case 'b': case 'B':
      addBookmark();
      break;
    case 't': case 'T':
      cycleTheme();
      break;
    case 'c': case 'C':
      document.getElementById('toc-toggle').click();
      break;
    case 'm': case 'M':
      toggleBookmarkPanel();
      break;
    case '?':
      showShortcuts();
      break;
  }
});

function showShortcuts() {
  const overlay = document.getElementById('shortcuts-overlay');
  openModal(overlay, overlay.querySelector('.shortcuts-panel'));
}
function hideShortcuts() {
  closeModal(document.getElementById('shortcuts-overlay'));
}

// ── Toasts ────────────────────────────────────────────────────────────────────

function showToast(msg, type = 'ok') {
  const tc   = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  tc.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener('scroll', scheduleViewportProgressUpdate, { passive: true });
window.addEventListener('pagehide', () => {
  flushProgressSave({ useBeacon: true, force: true });
  _bufferGenId++;
  for (const controller of _ttsAbortControllers.values()) controller.abort();
  _ttsAbortControllers.clear();
  navigator.sendBeacon('/api/tts/cancel');
});
window.addEventListener('beforeunload', () => flushProgressSave({ useBeacon: true, force: true }));
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    flushProgressSave({ useBeacon: true, force: true });
  }
});

_audioA.addEventListener('timeupdate', updateRemainingTime);
_audioB.addEventListener('timeupdate', updateRemainingTime);
setTOCOpen(!window.matchMedia('(max-width: 768px)').matches);
applySpeakerLabelPreference();
applyExportPreset(document.getElementById('export-preset').value);
initMediaSession();

loadTOC();
