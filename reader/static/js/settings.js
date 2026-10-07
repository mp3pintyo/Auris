let _settings = {};
let _dlPollTimer = null;
let _settingsReady = false;
let _settingsDirty = false;
const OPENAI_TEXT_MODEL_PREFIXES = [
  'gpt-', 'o1', 'o3', 'o4', 'chatgpt-', 'chat-'
];

function setSettingsDirty(dirty) {
  _settingsDirty = dirty;
  const banner = document.getElementById('settings-unsaved-banner');
  if (banner) banner.classList.toggle('hidden', !dirty);
}

function markSettingsDirty(event) {
  if (event?.target?.closest('#settings-setup, #settings-dictionary, #settings-storage')) return;
  if (_settingsReady) setSettingsDirty(true);
}

function showSettingsCategory(category, updateHash = true) {
  const target = document.querySelector(
    `[data-settings-category="${category}"]`
  );
  if (!target) return;
  document.querySelector('.settings-footer').hidden = ['setup', 'dictionary', 'storage'].includes(category);
  document.querySelectorAll('[data-settings-category]').forEach(panel => {
    const active = panel === target;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
  document.querySelectorAll('[data-settings-target]').forEach(button => {
    const active = button.dataset.settingsTarget === category;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (updateHash) {
    history.replaceState(null, '', `#${category}`);
  }
}

function ensureModelOption(select, model) {
  if (!select || !model) return;
  if (![...select.options].some(option => option.value === model)) {
    select.add(new Option(model, model));
  }
  select.value = model;
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
  document.getElementById('higgs-max-new-tokens').value = _settings.higgs_max_new_tokens ?? 2048;
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

  // Additional engines
  const setValue = (id, value) => { const el = document.getElementById(id); if (el) el.value = value; };
  setValue('piper-voice', _settings.piper_voice || 'anna');
  setValue('supertonic-voice', _settings.supertonic_voice || 'F1');
  setValue('supertonic-steps', _settings.supertonic_steps ?? 10);
  setValue('moss-seed', _settings.moss_seed ?? 1234);
  setValue('moss-temperature', _settings.moss_temperature ?? 1.7);
  setValue('moss-top-p', _settings.moss_top_p ?? 0.8);
  setValue('moss-top-k', _settings.moss_top_k ?? 25);

  // Character / dialogue-speaker detection
  const detectionMode = _settings.character_detection_mode || 'legacy';
  const llmProvider = _settings.llm_provider || 'local';
  document.getElementById('character-detection-mode').value = detectionMode;
  document.getElementById('llm-provider').value = llmProvider;
  document.getElementById('llm-base-url').value =
    _settings.llm_base_url || 'http://127.0.0.1:1234/v1';
  ensureModelOption(document.getElementById('llm-model'), _settings.llm_model || '');
  document.getElementById('llm-api-key').value = _settings.llm_api_key || '';
  document.getElementById('openai-api-key').value = _settings.openai_api_key || '';
  ensureModelOption(
    document.getElementById('openai-model'), _settings.openai_model || ''
  );
  document.getElementById('llm-timeout-sec').value = _settings.llm_timeout_sec ?? 600;
  document.getElementById('llm-max-characters').value = _settings.llm_max_characters ?? 60;
  toggleCharacterDetection(detectionMode);
  toggleLLMProvider(llmProvider);

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
  const coal = String(_settings.tts_coalesce_chars ?? 0);
  const coalSelect = document.getElementById('tts-coalesce-chars');
  if (coalSelect) {
    coalSelect.value = '0';
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
  document.getElementById('audio-mastering').checked =
    _settings.audio_mastering !== false;
  const anchor = document.getElementById('voice-design-anchor');
  if (anchor) anchor.checked = _settings.voice_design_anchor !== false;
  const setChecked = (id, value) => { const el = document.getElementById(id); if (el) el.checked = value; };
  setChecked('trim-segment-silence', _settings.trim_segment_silence !== false);
  setChecked('export-room-tone', Boolean(_settings.export_room_tone));
  setChecked('asr-keep-loaded', Boolean(_settings.asr_keep_loaded));
  const setNumber = (id, value) => { const el = document.getElementById(id); if (el) el.value = value; };
  setNumber('qa-cer-warn', Math.round((_settings.qa_cer_warn ?? 0.08) * 100));
  setNumber('qa-cer-fail', Math.round((_settings.qa_cer_fail ?? 0.15) * 100));
  setNumber('qa-max-takes', _settings.qa_max_takes ?? 3);
  setNumber('asr-model', _settings.asr_model || '');
  const asrBackend = document.getElementById('asr-backend');
  if (asrBackend) asrBackend.value = _settings.asr_backend || 'auto';
  const onnxDevice = document.getElementById('onnx-device');
  if (onnxDevice) onnxDevice.value = _settings.onnx_device || 'auto';
  setNumber('narrator-credit', _settings.narrator_credit || '');
  setNumber('export-intro-template', _settings.export_intro_template || '');
  setNumber('export-outro-template', _settings.export_outro_template || '');
  setNumber('abs-url', _settings.abs_url || '');
  setNumber('abs-api-token', _settings.abs_api_token || '');
  setNumber('api-token', _settings.api_token || '');
  if (_settings.abs_library_id) {
    const select = document.getElementById('abs-library');
    if (select && ![...select.options].some(o => o.value === _settings.abs_library_id)) {
      select.add(new Option(`Mentett könyvtár (${_settings.abs_library_id})`, _settings.abs_library_id));
    }
    if (select) select.value = _settings.abs_library_id;
  }

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
  // Apply immediately
  Auris.applyTheme(theme);
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

function toggleCharacterDetection(mode) {
  document.getElementById('llm-character-settings')
    ?.classList.toggle('hidden', mode !== 'llm');
  document.getElementById('legacy-character-settings')
    ?.classList.toggle('hidden', mode !== 'legacy');
}

function toggleLLMProvider(provider) {
  document.getElementById('local-llm-settings')
    ?.classList.toggle('hidden', provider !== 'local');
  document.getElementById('openai-llm-settings')
    ?.classList.toggle('hidden', provider !== 'openai');
}

function llmConnectionPayload(provider) {
  if (provider === 'openai') {
    return {
      provider,
      api_key: document.getElementById('openai-api-key').value,
      model: document.getElementById('openai-model').value,
    };
  }
  return {
    provider: 'local',
    base_url: document.getElementById('llm-base-url').value.trim(),
    api_key: document.getElementById('llm-api-key').value,
    model: document.getElementById('llm-model').value,
  };
}

function isOpenAITextModel(model) {
  const id = String(model || '').toLowerCase();
  if (!OPENAI_TEXT_MODEL_PREFIXES.some(prefix => id.startsWith(prefix))) {
    return false;
  }
  return ![
    'audio', 'realtime', 'transcribe', 'tts', 'image', 'search-preview'
  ].some(fragment => id.includes(fragment));
}

async function loadLLMModels(provider) {
  const hint = document.getElementById('llm-test-hint');
  const select = document.getElementById(
    provider === 'openai' ? 'openai-model' : 'llm-model'
  );
  const previous = select.value;
  hint.textContent = 'Modellek listázása…';
  hint.className = 'status-hint status-warn';
  try {
    const response = await fetch('/api/settings/llm-test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(llmConnectionPayload(provider)),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    let models = [...new Set(data.models)].sort((a, b) => a.localeCompare(b));
    if (provider === 'openai') {
      models = models.filter(isOpenAITextModel);
    }
    select.replaceChildren(new Option('Válassz modellt…', ''));
    models.forEach(model => select.add(new Option(model, model)));
    if (previous && models.includes(previous)) {
      select.value = previous;
    } else if (provider === 'openai') {
      const preferred = [
        'gpt-5.6-luna', 'gpt-5.4-mini', 'gpt-5-mini', 'gpt-4.1-mini',
        'gpt-4o-mini'
      ].find(model => models.includes(model));
      if (preferred) select.value = preferred;
    }
    markSettingsDirty();
    hint.textContent = `Connected — ${models.length} compatible model(s) loaded.`;
    hint.className = 'status-hint status-ok';
  } catch (error) {
    ensureModelOption(select, previous);
    hint.textContent = `Kapcsolódási hiba: ${error.message}`;
    hint.className = 'status-hint status-error';
  }
}

async function testLLMConnection() {
  const hint = document.getElementById('llm-test-hint');
  const provider = document.getElementById('llm-provider').value;
  hint.textContent = 'Connecting…';
  hint.className = 'status-hint status-warn';
  try {
    const r = await fetch('/api/settings/llm-test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(llmConnectionPayload(provider)),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || `HTTP ${r.status}`);
    const selected = provider === 'openai'
      ? document.getElementById('openai-model').value
      : document.getElementById('llm-model').value;
    hint.textContent = d.selected_available
      ? `Connected — “${selected}” is available.`
      : `Connected — ${d.models.length} model(s), but the selected model was not listed.`;
    hint.className = d.selected_available
      ? 'status-hint status-ok' : 'status-hint status-warn';
  } catch (error) {
    hint.textContent = `Kapcsolódási hiba: ${error.message}`;
    hint.className = 'status-hint status-error';
  }
}

const ENGINE_CAPABILITIES = {
  omnivoice: {clone: true, design: true, speed: true, device: 'GPU vagy CPU', license: 'kód Apache-2.0, súlyok CC-BY-NC'},
  higgs: {clone: true, design: false, speed: true, device: 'GPU', license: 'Boson kutatási licenc'},
  moss_tts: {clone: true, design: false, speed: false, device: 'GPU, ~14 GB VRAM', license: 'Apache-2.0'},
  moss_nano: {clone: true, design: false, speed: false, device: 'CPU', license: 'Apache-2.0'},
  supertonic: {clone: false, design: false, speed: true, device: 'CPU vagy GPU (DirectML)', license: 'OpenRAIL-M'},
  piper: {clone: false, design: false, speed: true, device: 'CPU', license: 'GPL-3.0 (piper-tts)'},
};

function toggleEngineSettings(engine) {
  document.querySelectorAll('.engine-settings').forEach(el => {
    const owner = [...el.classList].find(name => name.endsWith('-settings') && name !== 'engine-settings');
    el.classList.toggle('hidden', owner !== `${engine}-settings`);
  });
  const caps = ENGINE_CAPABILITIES[engine] || {};
  const box = document.getElementById('engine-capabilities');
  if (box) {
    const chip = (ok, label) =>
      `<span class="cap-chip ${ok ? 'cap-yes' : 'cap-no'}">${ok ? '✓' : '✕'} ${label}</span>`;
    box.innerHTML = [
      chip(caps.clone, 'hangklónozás'),
      chip(caps.design, 'hangleírás (voice design)'),
      chip(caps.speed, 'tempóállítás'),
      `<span class="cap-chip">${esc(caps.device || '')}</span>`,
      `<span class="cap-chip">${esc(caps.license || '')}</span>`,
    ].join('');
  }
}

async function installEngineRuntime(engine) {
  const hint = document.getElementById('engine-install-hint');
  if (hint) { hint.textContent = 'Telepítés…'; hint.className = 'status-hint status-warn'; }
  try {
    const response = await fetch('/api/settings/engine-install', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({engine}),
    });
    const data = await response.json();
    if (hint) {
      hint.textContent = data.message || (data.ok ? 'Telepítve.' : 'A telepítés nem sikerült.');
      hint.className = 'status-hint ' + (data.ok ? 'status-ok' : 'status-error');
    }
  } catch (error) {
    if (hint) { hint.textContent = error.message; hint.className = 'status-hint status-error'; }
  }
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
  hint.textContent = 'Ellenőrzés…';
  const r = await fetch('/api/settings/check-model-path', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ path }),
  });
  const d = await r.json();
  if (!d.exists) {
    hint.textContent = 'A megadott mappa nem létezik.';
    hint.className = 'status-hint status-error';
  } else if (!d.has_config) {
    hint.textContent = 'A mappa létezik, de nincs benne config.json – ez nem modellmappa.';
    hint.className = 'status-hint status-warn';
  } else {
    hint.textContent = 'Érvényes modellmappa.';
    hint.className = 'status-hint status-ok';
  }
}

async function checkHiggsPath() {
  const path = document.getElementById('higgs-model-path').value.trim();
  const hint = document.getElementById('higgs-path-status');
  hint.textContent = 'Ellenőrzés…';
  const r = await fetch('/api/settings/check-model-path', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ path }),
  });
  const d = await r.json();
  if (!d.exists) {
    hint.textContent = 'A megadott mappa nem létezik.';
    hint.className = 'status-hint status-error';
  } else if (!d.has_config) {
    hint.textContent = 'A mappa létezik, de nincs benne config.json – ez nem modellmappa.';
    hint.className = 'status-hint status-warn';
  } else {
    hint.textContent = 'Érvényes modellmappa.';
    hint.className = 'status-hint status-ok';
  }
}

// ── HuggingFace download ──────────────────────────────────────────────────────

async function startDownload() {
  const repo = document.getElementById('model-repo').value.trim();
  const dest = document.getElementById('dl-dest').value.trim();
  const hfep = document.getElementById('hf-endpoint').value.trim();
  if (!dest) { Auris.toast('Add meg, hova töltődjön le a modell.', 'err'); return; }

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
  hint.textContent  = 'Újratöltés…';
  hint.className    = 'status-hint status-warn';
  const response = await fetch('/api/settings/tts-reload', { method: 'POST' });
  if (!response.ok) throw new Error('A beszédmotor nem tölthető újra. Előbb állítsd le a futó feladatokat.');
  hint.textContent  = 'A modell betöltése folyamatban…';
  hint.className    = 'status-hint status-ok';
  // Engine state arrives as server events; a slow check covers missed ones.
  let finished = false;
  let off = null;
  const started = Date.now();
  const consider = async (st) => {
    if (finished) return;
    if (st.state === 'ready') {
      finished = true;
      hint.textContent = 'A beszédmotor készen áll.';
      // The event carries no acceleration details, so read the full status once.
      try { refreshAccelStatus(await fetch('/api/tts/status').then(r => r.json())); } catch (_) {}
    } else if (st.state === 'error') {
      finished = true;
      hint.textContent = 'Betöltési hiba: ' + (st.message || 'ismeretlen hiba');
      hint.className = 'status-hint status-error';
    } else if (Date.now() - started > 30 * 60 * 1000) {
      finished = true;
      hint.textContent = 'Még töltődik; ellenőrizd a felső állapotjelzést vagy a szervernaplót.';
      hint.className = 'status-hint status-warn';
    }
    if (finished) { clearInterval(timer); if (off) off(); }
  };
  off = window.Auris?.onEvent?.('engine', consider) || null;
  const timer = setInterval(async () => {
    try { consider(await fetch('/api/tts/status').then(r => r.json())); } catch (_) {}
  }, off ? 10000 : 2000);
}

async function refreshAccelStatus(st) {
  const el = document.getElementById('tts-accel-status');
  if (!el) return;
  try {
    if (!st) st = await fetch('/api/tts/status').then(r => r.json());
    const a = st.accel || {};
    const probe = a.probe || {};
    const backends = { cuda: 'NVIDIA CUDA', rocm: 'AMD ROCm', mps: 'Apple Metal (MPS)', cpu: 'CPU' };
    const modes = { off: 'Alap PyTorch', eager: 'Optimalizált PyTorch', cuda_graph: 'CUDA Graph',
      triton: 'Triton', hybrid: 'Triton + CUDA Graph', transformers: 'Higgs Transformers' };
    const parts = [
      `Beszédmotor: ${st.engine || 'omnivoice'}`,
      st.state === 'ready' ? `Aktív: ${modes[a.effective] || a.effective || 'Alap PyTorch'}` : 'A modell nincs betöltve',
      backends[probe.backend] || backends[a.device] || '',
      probe.device_name || '',
      a.dtype || '',
      a.message || '',
      probe.platform || '',
    ].filter(Boolean);
    el.textContent = parts.join(' · ');
    const row = document.getElementById('triton-install-row');
    if (row) row.classList.toggle('hidden', !(probe.backend === 'cuda' && !(probe.triton && probe.omnivoice_triton)));
  } catch (_) {
    el.textContent = '';
  }
}

document.getElementById('triton-install-btn')?.addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const hint = document.getElementById('triton-install-hint');
  button.disabled = true;
  hint.className = 'status-hint status-warn';
  hint.textContent = 'Telepítés… (egy-két perc)';
  try {
    const response = await fetch('/api/settings/triton-install', { method: 'POST' });
    const data = await response.json();
    hint.className = `status-hint ${data.ok ? 'status-ok' : 'status-error'}`;
    hint.textContent = data.message || (data.ok ? 'Telepítve.' : 'A telepítés nem sikerült.');
    if (data.ok) document.getElementById('tts-accel').value = 'hybrid';
    if (data.ok) markSettingsDirty();
  } catch (error) {
    hint.className = 'status-hint status-error';
    hint.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

// ── spaCy ─────────────────────────────────────────────────────────────────────

async function checkSpacy() {
  const block      = document.getElementById('spacy-status-block');
  const installSec = document.getElementById('spacy-install-section');
  const d = await fetch('/api/settings/spacy-status').then(r => r.json());
  const huBtn = document.getElementById('spacy-hu-install-btn');
  const enBtn = document.getElementById('spacy-install-btn');

  if (!d.installed) {
    block.innerHTML = '<span class="status-error">A spaCy nincs telepítve.</span> Futtasd: <code>reader\.venv\Scripts\python.exe -m pip install spacy</code>, majd indítsd újra az Aurist.';
    installSec.classList.add('hidden');
  } else {
    const hu = d.hu_model_installed
      ? `<span class="status-ok">Magyar: ${esc(d.hu_model)} kész.</span>`
      : '<span class="status-warn">Magyar: a HuSpaCy modell hiányzik (kb. 130 MB); nélküle csak a párbeszéd-igék alapján ismeri fel a neveket.</span>';
    const en = d.model_installed
      ? '<span class="status-ok">Angol: en_core_web_sm kész.</span>'
      : '<span class="muted">Angol: en_core_web_sm nincs telepítve (csak angol könyvekhez kell).</span>';
    block.innerHTML = `${hu}<br>${en}`;
    installSec.classList.toggle('hidden', d.hu_model_installed && d.model_installed);
    if (huBtn) huBtn.classList.toggle('hidden', !!d.hu_model_installed);
    if (enBtn) enBtn.classList.toggle('hidden', !!d.model_installed);
  }

  if (d.error) block.innerHTML += `<br><span class="muted" style="font-size:.8rem">${esc(d.error)}</span>`;
}

async function installSpacy(language = 'hu') {
  const btn  = document.getElementById(language === 'hu' ? 'spacy-hu-install-btn' : 'spacy-install-btn');
  const hint = document.getElementById('spacy-install-hint');
  btn.disabled     = true;
  hint.textContent = 'Telepítés… ez egy-két percig is tarthat.';
  hint.className   = 'status-hint status-warn';

  const r = await fetch('/api/settings/spacy-install', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({language}),
  });
  const d = await r.json();

  if (d.ok) {
    hint.textContent = 'Sikeresen telepítve.';
    hint.className   = 'status-hint status-ok';
    checkSpacy();
  } else {
    hint.textContent = d.message || 'A telepítés nem sikerült.';
    hint.className   = 'status-hint status-error';
  }
  btn.disabled = false;
}

// ── Save ──────────────────────────────────────────────────────────────────────

async function saveSettingsValues() {
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
    character_detection_mode: document.getElementById('character-detection-mode').value,
    llm_provider:      document.getElementById('llm-provider').value,
    llm_base_url:      document.getElementById('llm-base-url').value.trim(),
    llm_model:         document.getElementById('llm-model').value,
    llm_api_key:       document.getElementById('llm-api-key').value,
    openai_model:      document.getElementById('openai-model').value,
    openai_api_key:    document.getElementById('openai-api-key').value,
    llm_timeout_sec:   parseInt(document.getElementById('llm-timeout-sec').value, 10) || 600,
    llm_max_characters: parseInt(document.getElementById('llm-max-characters').value, 10) || 60,
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
    audio_mastering:   document.getElementById('audio-mastering').checked,
    voice_design_anchor: document.getElementById('voice-design-anchor')?.checked !== false,
    trim_segment_silence: document.getElementById('trim-segment-silence')?.checked !== false,
    export_room_tone: Boolean(document.getElementById('export-room-tone')?.checked),
    asr_keep_loaded: Boolean(document.getElementById('asr-keep-loaded')?.checked),
    qa_cer_warn: (parseFloat(document.getElementById('qa-cer-warn')?.value || '8') || 0) / 100,
    qa_cer_fail: (parseFloat(document.getElementById('qa-cer-fail')?.value || '15') || 15) / 100,
    qa_max_takes: parseInt(document.getElementById('qa-max-takes')?.value || '3', 10),
    asr_model: (document.getElementById('asr-model')?.value || '').trim(),
    asr_backend: document.getElementById('asr-backend')?.value || 'auto',
    onnx_device: document.getElementById('onnx-device')?.value || 'auto',
    narrator_credit: (document.getElementById('narrator-credit')?.value || '').trim(),
    export_intro_template: document.getElementById('export-intro-template')?.value || '',
    export_outro_template: document.getElementById('export-outro-template')?.value || '',
    abs_url: (document.getElementById('abs-url')?.value || '').trim(),
    abs_api_token: document.getElementById('abs-api-token')?.value || '',
    api_token: document.getElementById('api-token')?.value || '',
    abs_library_id: document.getElementById('abs-library')?.value || '',
    abs_folder_id: document.getElementById('abs-library')?.selectedOptions?.[0]?.dataset.folder || '',
    piper_voice:      document.getElementById('piper-voice')?.value || 'anna',
    supertonic_voice: document.getElementById('supertonic-voice')?.value || 'F1',
    supertonic_steps: parseInt(document.getElementById('supertonic-steps')?.value || '10', 10),
    moss_seed:        parseInt(document.getElementById('moss-seed')?.value || '1234', 10),
    moss_temperature: parseFloat(document.getElementById('moss-temperature')?.value || '1.7'),
    moss_top_p:       parseFloat(document.getElementById('moss-top-p')?.value || '0.8'),
    moss_top_k:       parseInt(document.getElementById('moss-top-k')?.value || '25', 10),
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
    hint.textContent = 'Beállítások mentve.';
    hint.className   = 'status-hint status-ok';
    localStorage.setItem('theme',      payload.theme);
    localStorage.setItem('fontFamily', payload.font_family);
    localStorage.setItem('fontSize',   payload.font_size);
    localStorage.setItem('lineHeight', payload.line_height);
    setSettingsDirty(false);
    return true;
  } else {
    hint.textContent = d.error || 'A mentés nem sikerült.';
    hint.className   = 'status-hint status-error';
    return false;
  }
}

async function saveSettings(apply = false) {
  const hint = document.getElementById('save-hint');
  try {
    if (!_settingsReady) throw new Error('Várd meg a beállítások betöltését.');
    if (await saveSettingsValues() && apply) {
      await reloadTTS();
      hint.textContent = 'Mentve. A beszédmotor újratöltése elindult; állapotát felül követheted.';
    }
  } catch (error) {
    hint.textContent = error.message || 'A szerver nem érhető el. Próbáld újra.';
    hint.className = 'status-hint status-error';
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return Auris.esc(s || '');
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.querySelector('.settings-page').addEventListener('input', markSettingsDirty);
document.querySelector('.settings-page').addEventListener('change', markSettingsDirty);
const initialSettingsCategory = location.hash.slice(1);
showSettingsCategory(
  document.querySelector(`[data-settings-category="${initialSettingsCategory}"]`)
    ? initialSettingsCategory : 'speech',
  false
);
// First visit: open the quick setup instead of the engine details.
if (!initialSettingsCategory && document.querySelector('[data-settings-category="setup"]')) {
  fetch('/api/setup/status').then(r => r.json()).then(status => {
    if (!status.completed && !location.hash) showSettingsCategory('setup', false);
  }).catch(() => {});
}
loadSettings().catch(error => {
  document.getElementById('save-hint').textContent = 'A beállítások nem tölthetők be. Frissítsd az oldalt. ' + error.message;
});


async function loadAbsLibraries() {
  const hint = document.getElementById('abs-hint');
  const select = document.getElementById('abs-library');
  hint.textContent = 'Kapcsolódás…';
  hint.className = 'status-hint status-warn';
  try {
    const response = await fetch('/api/settings/abs-libraries', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url: document.getElementById('abs-url').value.trim(),
        token: document.getElementById('abs-api-token').value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'A kapcsolódás nem sikerült.');
    const current = select.value;
    select.replaceChildren(new Option('– válassz könyvtárat –', ''));
    (data.libraries || []).forEach(library => {
      const option = new Option(library.name, library.id);
      option.dataset.folder = library.folders?.[0]?.id || '';
      select.add(option);
    });
    if (current) select.value = current;
    hint.textContent = `${(data.libraries || []).length} könyvtár elérhető.`;
    hint.className = 'status-hint status-ok';
  } catch (error) {
    hint.textContent = error.message;
    hint.className = 'status-hint status-error';
  }
}
