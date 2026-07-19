let _settings = {};
let _dlPollTimer = null;
let _settingsReady = false;
let _settingsDirty = false;

function setSettingsDirty(dirty) {
  _settingsDirty = dirty;
  const banner = document.getElementById('settings-unsaved-banner');
  if (banner) banner.classList.toggle('hidden', !dirty);
}

function markSettingsDirty() {
  if (_settingsReady) setSettingsDirty(true);
}

// ── Load ──────────────────────────────────────────────────────────────────────

async function loadSettings() {
  _settings = await fetch('/api/settings').then(r => r.json());

  // Active engine
  const engine = _settings.tts_engine || 'omnivoice';
  document.getElementById('tts-engine').value = engine;
  toggleEngineSettings(engine);

  // Model
  const src = _settings.model_source || 'local';
  const srcRadio = document.querySelector(`input[name="model_source"][value="${src}"]`);
  if (srcRadio) srcRadio.checked = true;
  document.getElementById('model-path').value  = _settings.model_path  || '';
  document.getElementById('model-repo').value  = _settings.model_repo  || 'k2-fsa/OmniVoice';
  document.getElementById('dl-dest').value     = _settings.model_path  || '';
  document.getElementById('hf-endpoint').value = _settings.hf_endpoint || '';
  toggleSource(src);

  // Higgs model and generation
  const higgsSrc = _settings.higgs_model_source || 'download';
  const higgsSrcRadio = document.querySelector(
    `input[name="higgs_model_source"][value="${higgsSrc}"]`
  );
  if (higgsSrcRadio) higgsSrcRadio.checked = true;
  document.getElementById('higgs-model-path').value = _settings.higgs_model_path || '';
  document.getElementById('higgs-model-repo').value =
    _settings.higgs_model_repo || 'multimodalart/higgs-audio-v3-tts-4b-transformers';
  document.getElementById('higgs-temperature').value = _settings.higgs_temperature ?? 0.8;
  document.getElementById('higgs-top-p').value = _settings.higgs_top_p ?? 0.95;
  document.getElementById('higgs-top-k').value = _settings.higgs_top_k ?? 50;
  document.getElementById('higgs-max-new-tokens').value = _settings.higgs_max_new_tokens ?? 1024;
  document.getElementById('higgs-seed').value = _settings.higgs_seed ?? -1;
  document.getElementById('higgs-prompt-mode').value =
    _settings.higgs_prompt_mode || 'raw';
  document.getElementById('higgs-default-emotion').value =
    _settings.higgs_default_emotion || 'none';
  document.getElementById('higgs-default-style').value =
    _settings.higgs_default_style || 'none';
  document.getElementById('higgs-default-expressive').value =
    _settings.higgs_default_expressive || 'none';
  toggleHiggsSource(higgsSrc);
  toggleHiggsPromptMode(_settings.higgs_prompt_mode || 'raw');

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
  _settingsReady = true;
  setSettingsDirty(false);
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
  if (persist) {
    localStorage.setItem('theme', theme);
    markSettingsDirty();
  }
}

// ── Font family selection ─────────────────────────────────────────────────────

function selectFontFamily(ff, persist = true) {
  document.getElementById('font-family').value = ff;
  document.querySelectorAll('.font-option').forEach(el => {
    el.classList.toggle('active', el.dataset.ff === ff);
  });
  if (persist) {
    localStorage.setItem('fontFamily', ff);
    markSettingsDirty();
  }
}

// ── Model source toggle ───────────────────────────────────────────────────────

document.querySelectorAll('input[name="model_source"]').forEach(el => {
  el.addEventListener('change', () => toggleSource(el.value));
});

function toggleSource(src) {
  document.getElementById('panel-local').classList.toggle('hidden', src !== 'local');
  document.getElementById('panel-download').classList.toggle('hidden', src !== 'download');
}

function toggleEngineSettings(engine) {
  document.querySelectorAll('.omnivoice-settings').forEach(el =>
    el.classList.toggle('hidden', engine !== 'omnivoice')
  );
  document.querySelectorAll('.higgs-settings').forEach(el =>
    el.classList.toggle('hidden', engine !== 'higgs')
  );
}

document.querySelectorAll('input[name="higgs_model_source"]').forEach(el => {
  el.addEventListener('change', () => toggleHiggsSource(el.value));
});

function toggleHiggsSource(src) {
  document.getElementById('higgs-panel-local').classList.toggle('hidden', src !== 'local');
  document.getElementById('higgs-panel-download').classList.toggle('hidden', src !== 'download');
}

function toggleHiggsPromptMode(mode) {
  document.querySelectorAll('.higgs-expressive-control').forEach(el =>
    el.classList.toggle('hidden', mode !== 'expressive')
  );
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

async function checkHiggsPath() {
  const path = document.getElementById('higgs-model-path').value.trim();
  const hint = document.getElementById('higgs-path-status');
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
    if (n > 900) {
      clearInterval(t);
      hint.textContent = 'Still loading; check the TTS status badge or server log.';
      hint.className = 'status-hint status-warn';
    }
  }, 2000);
}

async function refreshAccelStatus(st) {
  const el = document.getElementById('tts-accel-status');
  if (!el) return;
  try {
    if (!st) st = await fetch('/api/tts/status').then(r => r.json());
    const a = st.accel || {};
    const probe = a.probe || {};
    const parts = [
      `Engine: ${st.engine || 'omnivoice'}`,
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
  const higgsSrc = document.querySelector(
    'input[name="higgs_model_source"]:checked'
  )?.value || 'download';
  const payload = {
    tts_engine:       document.getElementById('tts-engine').value || 'omnivoice',
    model_source:      src,
    model_path:        document.getElementById('model-path').value.trim(),
    model_repo:        document.getElementById('model-repo').value.trim(),
    hf_endpoint:       document.getElementById('hf-endpoint').value.trim(),
    higgs_model_source: higgsSrc,
    higgs_model_path:  document.getElementById('higgs-model-path').value.trim(),
    higgs_model_repo:  document.getElementById('higgs-model-repo').value.trim(),
    higgs_temperature: parseFloat(document.getElementById('higgs-temperature').value),
    higgs_top_p:       parseFloat(document.getElementById('higgs-top-p').value),
    higgs_top_k:       parseInt(document.getElementById('higgs-top-k').value, 10),
    higgs_max_new_tokens: parseInt(
      document.getElementById('higgs-max-new-tokens').value, 10
    ),
    higgs_seed:        parseInt(document.getElementById('higgs-seed').value, 10),
    higgs_prompt_mode: document.getElementById('higgs-prompt-mode').value || 'raw',
    higgs_default_emotion: document.getElementById('higgs-default-emotion').value,
    higgs_default_style: document.getElementById('higgs-default-style').value,
    higgs_default_expressive: document.getElementById('higgs-default-expressive').value,
    narrator_instruct: document.getElementById('narrator-instruct').value.trim(),
    single_narrator_mode: document.getElementById('default-single-narrator-mode').checked,
    normalize_text:    document.getElementById('normalize-text').checked,
    tts_num_step:      parseInt(document.getElementById('tts-num-step').value, 10) || 16,
    tts_batch_size:    parseInt(document.getElementById('tts-batch-size').value, 10) || 0,
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
    setSettingsDirty(false);
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

document.querySelector('.settings-page').addEventListener('input', markSettingsDirty);
document.querySelector('.settings-page').addEventListener('change', markSettingsDirty);
loadSettings();
