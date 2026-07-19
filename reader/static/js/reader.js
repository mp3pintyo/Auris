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
let _progressSaveTimer = null;
let _scrollProgressTimer = null;
let _lastSavedProgressKey = '';
let _ignoreScrollTrackingUntil = 0;

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
const ELLIPSIS_PAUSE_MS = 1500;

// Monotonic counter — incremented on every new playSegment and on stopPlayback.
// Each playSegment captures its generation at entry; stale async continuations
// bail out when their generation no longer matches the current one.
let _playGen = 0;

// Cancellation token for the background buffer loop — incremented on each
// chapter open so the previous loop exits without touching the new chapter.
let _bufferGenId = 0;
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
  if (segment?.is_dialogue && nextSegment?.is_dialogue) return DIALOGUE_TURN_PAUSE_MS;
  return DEFAULT_SEGMENT_PAUSE_MS;
}
function _swapAudio() { audio = (audio === _audioA ? _audioB : _audioA); }

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
    const wc = ch.word_count ? ch.word_count.toLocaleString() + ' words' : '';
    const badge = ch.section_type !== 'chapter'
      ? `<span class="toc-section-badge">${esc(ch.section_type)}</span>` : '';
    return `
      <div class="toc-item" data-id="${ch.id}" onclick="openChapter(${ch.id})">
        ${badge}
        <span class="toc-item-title">${esc(ch.title)}</span>
        ${wc ? `<span class="toc-item-meta">${wc}</span>` : ''}
      </div>`;
  }).join('');

  const prog = await fetch(`/api/books/${BOOK_ID}/progress`).then(r => r.json());
  const savedChapterId = Number.parseInt(prog.chapter_id, 10);
  const savedPosition = Number.parseInt(prog.position, 10);
  const hasSavedChapter = chapters.some(ch => ch.id === savedChapterId);
  if (hasSavedChapter) {
    openChapter(savedChapterId, {
      resumePosition: savedPosition,
      persistOpened: false,
      highlightOnLoad: true,
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
  segments = [];           // clear immediately so stale segments can't be played
  currentChapterId = chapterId;
  currentSegIdx    = 0;

  document.querySelectorAll('.toc-item').forEach(el => {
    el.classList.toggle('active', +el.dataset.id === chapterId);
  });

  const ch = await fetch(`/api/books/${BOOK_ID}/chapters/${chapterId}`).then(r => r.json());
  document.getElementById('chapter-title').textContent = ch.title;

  const wpm = 250;
  const minutes = Math.round((ch.word_count || 0) / wpm);
  const estEl = document.getElementById('reading-estimate');
  if (estEl) estEl.textContent = minutes > 0 ? `~${minutes} min read` : '';

  segments = await fetch(`/api/tts/segments/${BOOK_ID}/${chapterId}`).then(r => r.json());
  renderContent(segments);

  document.getElementById('chapter-content').scrollTop = 0;

  const startIdx = clampSegmentIndex(resumePosition);
  setCurrentSegment(startIdx, {
    highlight: highlightOnLoad,
    behavior: 'auto',
    save: persistOpened,
  });
  _startBackgroundBuffer(startIdx);
  _prewarmChapter();
}

// ── Content rendering ─────────────────────────────────────────────────────────

function renderContent(segs) {
  const container = document.getElementById('chapter-content');

  if (!segs || !segs.length) {
    container.innerHTML = '<div class="placeholder-text">No content available.</div>';
    return;
  }

  const html = segs.map((seg, i) => {
    const words = seg.text.split(/(\s+)/);
    const wordSpans = words.map((w, wi) => {
      if (/^\s+$/.test(w)) return w;
      return `<span class="word" data-seg="${i}" data-word="${wi}">${esc(w)}</span>`;
    }).join('');


    const charAttr = seg.character_name ? ` data-char="${esc(seg.character_name)}"` : '';
    const cls = 'sentence' + (seg.is_dialogue ? ' dialogue-sent' : '');
    return `<span class="${cls}" data-idx="${i}"${charAttr} onclick="jumpTo(${i})">${wordSpans}</span> `;
  }).join('');

  container.innerHTML = `<div>${html}</div>`;

  // Restore font prefs (font may be reset by innerHTML)
  container.style.fontSize   = fontSize + 'px';
  container.style.lineHeight = lineHeight;
  container.style.fontFamily = FONT_FAMILIES[fontFamily] || FONT_FAMILIES.serif;
}

function jumpTo(idx) {
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

async function _prewarmChapter() {
  if (!segments.length) return;
  const bufferId = _bufferGenId;
  const chapterId = currentChapterId;
  if (!await _waitForTtsReady(bufferId, chapterId)) return;
  fetchSegmentData(0);
  const frontier = segments.findIndex(s => !s.has_audio);
  if (frontier > 0) fetchSegmentData(frontier);
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

  // Fire N+1 first then N+2 so they arrive at the server TTS lock in the
  // correct order (N+1 queued before N+2).  Two-deep pipeline means a slow
  // TTS generation for N+1 overlaps with N-1's remaining play time *and*
  // N's full play time rather than just N's play time.
  fetchSegmentData(nextIdx);
  if (nextIdx + 1 < segments.length) fetchSegmentData(nextIdx + 1);

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

async function playSegment(idx) {
  if (idx >= segments.length) { stopPlayback(); return; }

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
  const charLabel = seg.character_name || 'Narrator';
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

  const n      = wordEls.length;
  const start  = audio.currentTime;

  function tick() {
    const elapsed   = (audio.currentTime - start) * speedMultiplier;
    const wordIdx   = Math.min(Math.floor((elapsed / durationSec) * n), n - 1);
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
  } else {
    btn.innerHTML = '&#9654;';
    btn.classList.add('paused');
  }
  if (segments.length) prog.textContent = `${currentSegIdx + 1} / ${segments.length}`;
}

// ── Controls ──────────────────────────────────────────────────────────────────

document.getElementById('btn-play').onclick = () => {
  if (isPlaying) {
    isPlaying = false;
    if (_interSegmentTimer) {
      clearTimeout(_interSegmentTimer);
      _interSegmentTimer = null;
    }
    stopWordHighlight();
    audio.pause();
    updatePlaybackUI();
    queueProgressSave(currentChapterId, currentSegIdx);
  } else {
    playSegment(_pendingSegmentIdx >= 0 ? _pendingSegmentIdx : currentSegIdx);
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

document.getElementById('speed-slider').oninput = function() {
  speedMultiplier = parseFloat(this.value);
  document.getElementById('speed-val').textContent = speedMultiplier.toFixed(1) + '×';
  _audioA.playbackRate = speedMultiplier;
  _audioB.playbackRate = speedMultiplier;
};

// ── Sidebar toggle ────────────────────────────────────────────────────────────

function toggleTOC() {
  document.getElementById('toc-sidebar').classList.toggle('collapsed');
}

document.getElementById('toc-toggle').onclick = toggleTOC;
document.getElementById('toc-close').onclick = toggleTOC;

function toggleBookmarkPanel() {
  document.getElementById('bookmarks-panel').classList.toggle('collapsed');
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

// ── Bookmarks ─────────────────────────────────────────────────────────────────

let _bookmarks = [];

async function loadBookmarks() {
  _bookmarks = await fetch(`/api/books/${BOOK_ID}/bookmarks`).then(r => r.json());
  renderBookmarks();
}

function renderBookmarks() {
  const list = document.getElementById('bookmark-list');
  if (!_bookmarks.length) {
    list.innerHTML = '<div style="padding:16px;font-size:.8rem;color:var(--text3);font-style:italic">No bookmarks yet.</div>';
    return;
  }
  list.innerHTML = _bookmarks.map(bm => `
    <div class="bookmark-item" onclick="gotoBookmark(${bm.chapter_id}, ${bm.segment_index})">
      <div class="bookmark-text">${esc(bm.text_excerpt || bm.label || '(no excerpt)')}</div>
      <div class="bookmark-loc">${esc(bm.chapter_title || '')} &middot; seg ${bm.segment_index + 1}</div>
      <button class="bookmark-del" onclick="removeBookmark(event,${bm.id})">&times;</button>
    </div>`).join('');
}

async function addBookmark() {
  if (!currentChapterId) { showToast('Open a chapter first.'); return; }
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
    showToast('Bookmark added');
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
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return `${m}m ${String(r).padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, '0')}m`;
}

function formatExportStatus(sr) {
  if (!sr) return 'Working…';
  const done = typeof sr.done === 'number' ? sr.done : null;
  const total = typeof sr.total === 'number' ? sr.total : null;
  let msg = sr.message || 'Working…';

  // Always rebuild a clear progress line so a stale server message cannot hide ETA.
  if (sr.state === 'running' && total != null && total > 0 && done != null) {
    msg = `Generating audio (${done}/${total})`;
    if (sr.eta_sec != null && Number.isFinite(sr.eta_sec) && done < total) {
      msg += ` · ~${formatDurationShort(sr.eta_sec)} left`;
    } else if (done < total) {
      msg += ' · working…';
    }
  } else if (
    sr.state === 'running' &&
    sr.eta_sec != null &&
    Number.isFinite(sr.eta_sec) &&
    !/left/i.test(msg)
  ) {
    msg += ` · ~${formatDurationShort(sr.eta_sec)} left`;
  }
  return msg;
}

document.getElementById('export-btn').onclick = () => {
  document.getElementById('export-dropdown').classList.toggle('hidden');
};

document.querySelectorAll('input[name="exp-mode"]').forEach(input => {
  input.addEventListener('change', () => {
    const selected = document.querySelector('input[name="exp-mode"]:checked').value;
    document.getElementById('chapter-selection-wrap')
      .classList.toggle('hidden', selected !== 'chapterwise');
  });
});

document.getElementById('do-export-btn').onclick = async () => {
  if (!currentChapterId) { showToast('Open a chapter first.'); return; }

  const mode      = document.querySelector('input[name="exp-mode"]:checked').value;
  const audioFmt  = document.querySelector('input[name="exp-audio"]:checked').value;
  const subInput  = document.querySelector('input[name="exp-sub"]:checked');
  const subFmt    = subInput ? subInput.value : 'srt';

  const status    = document.getElementById('export-status');
  const progWrap  = document.getElementById('export-progress-wrap');
  const progFill  = document.getElementById('export-progress-fill');
  const doBtn     = document.getElementById('do-export-btn');

  doBtn.disabled = true;
  progWrap.classList.add('active');
  progFill.style.width = '0%';
  status.textContent = 'Starting export…';
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
    setTimeout(() => {
      progWrap.classList.remove('active');
      progFill.style.width = '0%';
      doBtn.disabled = false;
    }, 2000);
  };

  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        audio_fmt: audioFmt,
        sub_fmt: subFmt,
        chapters: mode === 'chapterwise'
          ? document.getElementById('exp-chapters').value
          : null,
      }),
    });
    const d = await r.json();
    if (d.error) { finish(d.error); return; }

    const jobId = d.job_id;

    // Client-side ETA fallback if server has not reported one yet.
    let clientT0 = Date.now();
    let clientDone0 = null;

    while (true) {
      await new Promise(res => setTimeout(res, 500));
      let sr;
      try { sr = await fetch(`/api/export/status/${jobId}`).then(r => r.json()); }
      catch(_) { continue; }

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
        const res = sr.result;
        if (res.zip_download) {
          window.location.href = res.zip_download;
        } else {
          if (res.audio_download)    window.open(res.audio_download);
          if (res.subtitle_download) setTimeout(() => window.open(res.subtitle_download), 500);
        }
        if (res.export_path) {
          finish(`Done. ${res.chapter_count} chapter(s) saved to ${res.export_path}`);
        } else {
          finish('Done. Downloading…');
        }
        break;
      } else if (sr.state === 'failed') {
        finish('Export failed: ' + (sr.error || 'Unknown error'));
        break;
      }
    }
  } catch(e) {
    finish(e.message);
  }
};

// ── Keyboard shortcuts ────────────────────────────────────────────────────────

document.addEventListener('keydown', e => {
  const tag = document.activeElement.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

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
    case 'Escape':
      hideShortcuts();
      document.getElementById('export-dropdown').classList.add('hidden');
      break;
  }
});

function showShortcuts()  { document.getElementById('shortcuts-overlay').classList.remove('hidden'); }
function hideShortcuts()  { document.getElementById('shortcuts-overlay').classList.add('hidden'); }

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
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener('scroll', scheduleViewportProgressUpdate, { passive: true });
window.addEventListener('pagehide', () => flushProgressSave({ useBeacon: true, force: true }));
window.addEventListener('beforeunload', () => flushProgressSave({ useBeacon: true, force: true }));
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    flushProgressSave({ useBeacon: true, force: true });
  }
});

loadTOC();
