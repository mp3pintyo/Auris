let _settings = {};
let _dlPollTimer = null;

// ── Load ──────────────────────────────────────────────────────────────────────

async function loadSettings() {
  _settings = await fetch('/api/settings').then(r => r.json());

  // Model
  const src = _settings.model_source || 'local';
  const srcRadio = document.querySelector(`input[name="model_source"][value="${src}"]`);
  if (srcRadio) srcRadio.checked = true;
  document.getElementById('model-path').value  = _settings.model_path  || '';
  document.getElementById('model-repo').value  = _settings.model_repo  || 'k2-fsa/OmniVoice';
  document.getElementById('dl-dest').value     = _settings.model_path  || '';
  document.getElementById('hf-endpoint').value = _settings.hf_endpoint || '';
  toggleSource(src);

  // Narrator
  document.getElementById('narrator-instruct').value = _settings.narrator_instruct || '';
  document.getElementById('default-single-narrator-mode').checked = Boolean(_settings.single_narrator_mode);

  // TTS text processing (default true when unset)
  document.getElementById('normalize-text').checked = _settings.normalize_text !== false;

  // Export / TTS quality
  const steps = String(_settings.tts_num_step ?? 16);
  const stepSelect = document.getElementById('tts-num-step');
  if (stepSelect) {
    if (![...stepSelect.options].some(o => o.value === steps)) {
      stepSelect.value = '16';
    } else {
      stepSelect.value = steps;
    }
  }
  const batch = String(_settings.tts_batch_size ?? 0);
  const batchSelect = document.getElementById('tts-batch-size');
  if (batchSelect) {
    if (![...batchSelect.options].some(o => o.value === batch)) {
      batchSelect.value = '0';
    } else {
      batchSelect.value = batch;
    }
  }
  const coal = String(_settings.tts_coalesce_chars ?? 720);
  const coalSelect = document.getElementById('tts-coalesce-chars');
  if (coalSelect) {
    if (![...coalSelect.options].some(o => o.value === coal)) {
      coalSelect.value = '720';
    } else {
      coalSelect.value = coal;
    }
  }
  const accel = String(_settings.tts_accel ?? 'auto');
  const accelSelect = document.getElementById('tts-accel');
  if (accelSelect) {
    if (![...accelSelect.options].some(o => o.value === accel)) {
      accelSelect.value = 'auto';
    } else {
      accelSelect.value = accel;
    }
  }
  const workers = String(_settings.tts_export_workers ?? 0);
  const workerSelect = document.getElementById('tts-export-workers');
  if (workerSelect) {
    workerSelect.value = [...workerSelect.options].some(o => o.value === workers)
      ? workers : '0';
  }
  document.getElementById('audio-format').value    = _settings.audio_format    || 'wav';
  document.getElementById('subtitle-format').value = _settings.subtitle_format || 'ass';

  refreshAccelStatus();

  // UI — theme
  selectTheme(_settings.theme || 'night', false);

  // UI — font family
  selectFontFamily(_settings.font_family || 'serif', false);

  // UI — font size
  const fs = _settings.font_size || 18;
  document.getElementById('font-size').value = fs;
  document.getElementById('font-size-val').textContent = fs + 'px';

  // UI — line height
  const lh = _settings.line_height || 1.9;
  document.getElementById('line-height').value = lh;
  document.getElementById('line-height-val').textContent = parseFloat(lh).toFixed(1);

  checkSpacy();
  checkExistingDownload();
}

// ── Theme selection ───────────────────────────────────────────────────────────

function selectTheme(theme, persist = true) {
  document.getElementById('theme-select').value = theme;
  document.querySelectorAll('.theme-swatch').forEach(el => {
    el.classList.toggle('active', el.dataset.theme === theme);
  });
  // Apply immediately to body
  ['night', 'sepia', 'paper', 'amoled'].forEach(t =>
    document.body.classList.remove('theme-' + t)
  );
  if (theme !== 'night') document.body.classList.add('theme-' + theme);
  if (persist) localStorage.setItem('theme', theme);
}

// ── Font family selection ─────────────────────────────────────────────────────

function selectFontFamily(ff, persist = true) {
  document.getElementById('font-family').value = ff;
  document.querySelectorAll('.font-option').forEach(el => {
    el.classList.toggle('active', el.dataset.ff === ff);
  });
  if (persist) localStorage.setItem('fontFamily', ff);
}

// ── Model source toggle ───────────────────────────────────────────────────────

document.querySelectorAll('input[name="model_source"]').forEach(el => {
  el.addEventListener('change', () => toggleSource(el.value));
});

function toggleSource(src) {
  document.getElementById('panel-local').classList.toggle('hidden', src !== 'local');
  document.getElementById('panel-download').classList.toggle('hidden', src !== 'download');
}

// ── Path checker ──────────────────────────────────────────────────────────────

async function checkPath() {
  const path = document.getElementById('model-path').value.trim();
  const hint = document.getElementById('path-status');
  hint.textContent = 'Checking…';
  const r = await fetch('/api/settings/check-model-path', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ path }),
  });
  const d = await r.json();
  if (!d.exists) {
    hint.textContent = 'Path does not exist.';
    hint.className = 'status-hint status-error';
  } else if (!d.has_config) {
    hint.textContent = 'Directory exists but no config.json found.';
    hint.className = 'status-hint status-warn';
  } else {
    hint.textContent = 'Valid model directory.';
    hint.className = 'status-hint status-ok';
  }
}

// ── HuggingFace download ──────────────────────────────────────────────────────

async function startDownload() {
  const repo = document.getElementById('model-repo').value.trim();
  const dest = document.getElementById('dl-dest').value.trim();
  const hfep = document.getElementById('hf-endpoint').value.trim();
  if (!dest) { alert('Please enter a download destination path.'); return; }

  document.getElementById('dl-progress-wrap').classList.remove('hidden');
  document.getElementById('dl-btn').disabled = true;

  await fetch('/api/settings/model-download', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ repo_id: repo, dest, hf_endpoint: hfep }),
  });
  pollDownload();
}

function pollDownload() {
  if (_dlPollTimer) clearInterval(_dlPollTimer);
  _dlPollTimer = setInterval(async () => {
    const d   = await fetch('/api/settings/model-download/progress').then(r => r.json());
    const bar = document.getElementById('dl-bar');
    const msg = document.getElementById('dl-msg');
    bar.style.width  = d.pct + '%';
    msg.textContent  = d.message;

    if (d.status === 'done') {
      clearInterval(_dlPollTimer);
      document.getElementById('dl-btn').disabled = false;
      msg.className = 'progress-msg status-ok';
      document.getElementById('model-path').value = d.dest;
      document.getElementById('dl-dest').value    = d.dest;
    } else if (d.status === 'error') {
      clearInterval(_dlPollTimer);
      document.getElementById('dl-btn').disabled = false;
      msg.className = 'progress-msg status-error';
    }
  }, 2000);
}

async function checkExistingDownload() {
  const d = await fetch('/api/settings/model-download/progress').then(r => r.json());
  if (d.status === 'downloading') {
    document.getElementById('dl-progress-wrap').classList.remove('hidden');
    document.getElementById('dl-btn').disabled = true;
    pollDownload();
  }
}

// ── TTS reload ────────────────────────────────────────────────────────────────

async function reloadTTS() {
  const hint = document.getElementById('tts-reload-hint');
  hint.textContent  = 'Reloading…';
  hint.className    = 'status-hint status-warn';
  await fetch('/api/settings/tts-reload', { method: 'POST' });
  hint.textContent  = 'Reloading in background…';
  hint.className    = 'status-hint status-ok';
  // Poll until ready so accel status updates.
  let n = 0;
  const t = setInterval(async () => {
    n += 1;
    try {
      const st = await fetch('/api/tts/status').then(r => r.json());
      if (st.state === 'ready') {
        clearInterval(t);
        hint.textContent = 'Model ready.';
        refreshAccelStatus(st);
      } else if (st.state === 'error') {
        clearInterval(t);
        hint.textContent = 'Load failed: ' + (st.message || 'error');
        hint.className = 'status-hint status-error';
      }
    } catch (_) {}
    if (n > 60) clearInterval(t);
  }, 1000);
}

async function refreshAccelStatus(st) {
  const el = document.getElementById('tts-accel-status');
  if (!el) return;
  try {
    if (!st) st = await fetch('/api/tts/status').then(r => r.json());
    const a = st.accel || {};
    const probe = a.probe || {};
    const parts = [
      `Active: ${a.effective || 'off'}`,
      a.message || '',
      probe.triton ? 'triton:yes' : 'triton:no',
      probe.omnivoice_triton ? 'omnivoice-triton:yes' : 'omnivoice-triton:no',
      `os:${probe.platform || '?'}`,
    ].filter(Boolean);
    el.textContent = parts.join(' · ');
  } catch (_) {
    el.textContent = '';
  }
}

// ── spaCy ─────────────────────────────────────────────────────────────────────

async function checkSpacy() {
  const block      = document.getElementById('spacy-status-block');
  const installSec = document.getElementById('spacy-install-section');
  const d = await fetch('/api/settings/spacy-status').then(r => r.json());

  if (!d.installed) {
    block.innerHTML = '<span class="status-error">spaCy not installed.</span> Run: <code>pip install spacy</code> then restart the app.';
    installSec.classList.remove('hidden');
  } else if (!d.model_installed) {
    block.innerHTML = '<span class="status-warn">spaCy installed but <code>en_core_web_sm</code> model is missing.</span>';
    installSec.classList.remove('hidden');
  } else {
    block.innerHTML = '<span class="status-ok">spaCy + en_core_web_sm ready.</span>';
    installSec.classList.add('hidden');
  }

  if (d.error) block.innerHTML += `<br><span class="muted" style="font-size:.8rem">${esc(d.error)}</span>`;
}

async function installSpacy() {
  const btn  = document.getElementById('spacy-install-btn');
  const hint = document.getElementById('spacy-install-hint');
  btn.disabled     = true;
  hint.textContent = 'Installing… this may take a minute.';
  hint.className   = 'status-hint status-warn';

  const r = await fetch('/api/settings/spacy-install', { method: 'POST' });
  const d = await r.json();

  if (d.ok) {
    hint.textContent = 'Installed successfully.';
    hint.className   = 'status-hint status-ok';
    checkSpacy();
  } else {
    hint.textContent = d.message || 'Installation failed.';
    hint.className   = 'status-hint status-error';
    btn.disabled     = false;
  }
}

// ── Save ──────────────────────────────────────────────────────────────────────

async function saveSettings() {
  const src = document.querySelector('input[name="model_source"]:checked')?.value || 'local';
  const payload = {
    model_source:      src,
    model_path:        document.getElementById('model-path').value.trim(),
    model_repo:        document.getElementById('model-repo').value.trim(),
    hf_endpoint:       document.getElementById('hf-endpoint').value.trim(),
    narrator_instruct: document.getElementById('narrator-instruct').value.trim(),
    single_narrator_mode: document.getElementById('default-single-narrator-mode').checked,
    normalize_text:    document.getElementById('normalize-text').checked,
    tts_num_step:      parseInt(document.getElementById('tts-num-step').value, 10) || 16,
    tts_batch_size:    parseInt(document.getElementById('tts-batch-size').value, 10) || 0,
    tts_coalesce_chars: parseInt(document.getElementById('tts-coalesce-chars').value, 10) || 0,
    tts_accel:         document.getElementById('tts-accel')?.value || 'auto',
    tts_export_workers: parseInt(
      document.getElementById('tts-export-workers')?.value || '0', 10
    ) || 0,
    audio_format:      document.getElementById('audio-format').value,
    subtitle_format:   document.getElementById('subtitle-format').value,
    theme:             document.getElementById('theme-select').value,
    font_family:       document.getElementById('font-family').value,
    font_size:         parseInt(document.getElementById('font-size').value) || 18,
    line_height:       parseFloat(document.getElementById('line-height').value) || 1.9,
  };

  const hint = document.getElementById('save-hint');
  const r = await fetch('/api/settings', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const d = await r.json();
  if (d.ok) {
    hint.textContent = 'Saved.';
    hint.className   = 'status-hint status-ok';
    localStorage.setItem('theme',      payload.theme);
    localStorage.setItem('fontFamily', payload.font_family);
    localStorage.setItem('fontSize',   payload.font_size);
    localStorage.setItem('lineHeight', payload.line_height);
  } else {
    hint.textContent = 'Save failed.';
    hint.className   = 'status-hint status-error';
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Init ──────────────────────────────────────────────────────────────────────

loadSettings();
