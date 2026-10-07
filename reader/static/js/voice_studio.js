const studioWindow = typeof window === "undefined" ? {} : window;
const studioDocument = typeof document === "undefined" ? null : document;
const BOOK_ID = studioWindow.BOOK_ID;
let narratorInstruct = studioWindow.NARRATOR_INSTRUCT || "";
const DEFAULT_NARRATOR_INSTRUCT = "male, middle-aged, low pitch";
const CURRENT_CHAPTER_ID = studioWindow.CURRENT_CHAPTER_ID !== null
  && Number.isInteger(Number(studioWindow.CURRENT_CHAPTER_ID))
  ? Number(studioWindow.CURRENT_CHAPTER_ID)
  : null;
const HUNGARIAN_PREVIEW_TEXT =
  "Az árvíztűrő tükörfúrógép próbája tisztán és természetesen szól magyarul.";
const MAX_RECORDING_SECONDS = 30;
const RECORDING_SAMPLE_RATE = 24000;
const MAX_COMPARE_PROFILES = 3;

let singleNarratorMode = Boolean(studioWindow.SINGLE_NARRATOR_MODE);
let narratorHasRefAudio = Boolean(studioWindow.NARRATOR_HAS_REF_AUDIO);
let narratorRefAudioName = studioWindow.NARRATOR_REF_AUDIO_NAME || "Korábban feltöltött WAV";
let voiceProfiles = [];
let loadedCharacters = [];
const previewAudio = studioDocument?.getElementById("preview-audio") || null;

const GENDERS = ["female", "male"];
const AGES = ["child", "teenager", "young adult", "middle-aged", "elderly"];
const PITCHES = ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"];
const ACCENTS = [
  "",
  "american accent",
  "british accent",
  "australian accent",
  "canadian accent",
  "indian accent",
  "chinese accent",
  "korean accent",
  "japanese accent",
];
const OPTION_LABELS = {
  "": "Semleges / nincs akcentus",
  female: "Női",
  male: "Férfi",
  child: "Gyermek",
  teenager: "Tinédzser",
  "young adult": "Fiatal felnőtt",
  "middle-aged": "Középkorú",
  elderly: "Idős",
  "very low pitch": "Nagyon mély hang",
  "low pitch": "Mély hang",
  "moderate pitch": "Közepes hangmagasság",
  "high pitch": "Magas hang",
  "very high pitch": "Nagyon magas hang",
  "american accent": "Amerikai akcentus",
  "british accent": "Brit akcentus",
  "australian accent": "Ausztrál akcentus",
  "canadian accent": "Kanadai akcentus",
  "indian accent": "Indiai akcentus",
  "chinese accent": "Kínai akcentus",
  "korean accent": "Koreai akcentus",
  "japanese accent": "Japán akcentus",
};

function optionLabel(value) {
  return OPTION_LABELS[value] || value;
}

// Shared escaper from common.js (required directly under Node tests).
const sharedEsc = studioWindow.Auris?.esc || require("./common.js").esc;
function esc(value) {
  return sharedEsc(value);
}

function icon(name) {
  return studioWindow.Auris?.icon ? studioWindow.Auris.icon(name) : "";
}

function buildSelect(options, selected, id, label) {
  return `<select class="vc-select" id="${esc(id)}" aria-label="${esc(label)}">
    ${options.map((option) => (
      `<option value="${esc(option)}"${option === selected ? " selected" : ""}>${esc(optionLabel(option))}</option>`
    )).join("")}
  </select>`;
}

function parseInstruct(instruct) {
  const parts = String(instruct || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return {
    gender: parts.find((part) => GENDERS.includes(part)) || "female",
    age: AGES.find((age) => parts.includes(age)) || "young adult",
    pitch: PITCHES.find((pitch) => parts.includes(pitch)) || "moderate pitch",
    accent: ACCENTS.find((accent) => accent && parts.includes(accent)) || "",
  };
}

function buildInstruct(gender, age, pitch, accent, originalInstruct = "") {
  const selected = { gender, age, pitch, accent };
  const original = String(originalInstruct || "");
  if (original) {
    const parsed = parseInstruct(original);
    const controlsUnchanged = Object.keys(selected).every(
      (key) => selected[key] === parsed[key],
    );
    if (controlsUnchanged) return original;
  }

  const knownParts = new Set([...GENDERS, ...AGES, ...PITCHES, ...ACCENTS]);
  const extraParts = original
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part && !knownParts.has(part.toLowerCase()));
  return [gender, age, pitch, accent, ...extraParts].filter(Boolean).join(", ");
}

// Preset voices of engines that cannot clone or design a voice. The choice
// is stored in the voice description as a "voice:<name>" token.
const PRESET_VOICES = {
  piper: [["anna", "Anna (női)"], ["berta", "Berta (női)"], ["imre", "Imre (férfi)"]],
  supertonic: [
    ["F1", "F1 (női)"], ["F2", "F2 (női)"], ["F3", "F3 (női)"], ["F4", "F4 (női)"], ["F5", "F5 (női)"],
    ["M1", "M1 (férfi)"], ["M2", "M2 (férfi)"], ["M3", "M3 (férfi)"], ["M4", "M4 (férfi)"], ["M5", "M5 (férfi)"],
  ],
};
const ENGINE_LABELS = {
  omnivoice: "OmniVoice", higgs: "Higgs TTS 3", moss_tts: "MOSS-TTS 1.5",
  moss_nano: "MOSS-TTS-Nano", supertonic: "Supertonic 3", piper: "Piper",
};
let activeEngine = { engine: "omnivoice", capabilities: { voice_clone: true, voice_design: true } };

function presetVoiceOf(instruct) {
  const match = String(instruct || "").match(/(?:^|,)\s*voice:\s*([\w-]+)/i);
  return match ? match[1] : "";
}

function withPresetVoice(instruct, voice) {
  const parts = String(instruct || "")
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part && !/^voice:/i.test(part));
  if (voice) parts.push(`voice:${voice}`);
  return parts.join(", ");
}

// ── Pure helpers (unit tested) ──────────────────────────────────────────────

/** Hungarian, human-readable summary of an English voice description. */
function summarizeInstruct(instruct) {
  const raw = String(instruct || "").trim();
  if (!raw) return "Automatikus hang (nincs leírás)";
  const parts = raw.split(",").map((part) => part.trim()).filter(Boolean);
  const lower = parts.map((part) => part.toLowerCase());
  const known = new Set([...GENDERS, ...AGES, ...PITCHES, ...ACCENTS.filter(Boolean)]);
  const out = [];
  const gender = GENDERS.find((item) => lower.includes(item));
  if (gender) out.push(optionLabel(gender));
  const age = AGES.find((item) => lower.includes(item));
  if (age) out.push(optionLabel(age).toLocaleLowerCase("hu"));
  const pitch = PITCHES.find((item) => lower.includes(item));
  if (pitch) out.push(optionLabel(pitch).toLocaleLowerCase("hu"));
  const accent = ACCENTS.find((item) => item && lower.includes(item));
  if (accent) out.push(optionLabel(accent).toLocaleLowerCase("hu"));
  const preset = presetVoiceOf(raw);
  if (preset) {
    const all = Object.values(PRESET_VOICES).flat();
    const found = all.find(([value]) => value.toLowerCase() === preset.toLowerCase());
    const name = found ? found[1].replace(/\s*\(.*\)$/, "") : preset;
    out.push(`beépített hang: ${name}`);
  }
  const extras = lower.filter((part) => !known.has(part) && !/^voice:/.test(part));
  if (!out.length) return "Egyedi hangleírás";
  if (extras.length) out.push("egyedi kiegészítéssel");
  const text = out.join(" · ");
  return text.charAt(0).toLocaleUpperCase("hu") + text.slice(1);
}

/**
 * Where a character's voice comes from: a saved profile, an uploaded
 * reference recording, or the automatic (description based) voice.
 */
function voiceSourceOf(character, profiles = []) {
  const ref = character?.ref_audio_path || "";
  const instruct = String(character?.instruct || "").trim();
  const profile = (profiles || []).find((item) => {
    const profileRef = item.ref_audio_path || "";
    if (ref && profileRef) {
      if (character.match_by_name) {
        return item.ref_audio_name === character.ref_audio_name
          && String(item.instruct || "").trim() === instruct;
      }
      return profileRef === ref;
    }
    if (!ref && !profileRef) return Boolean(instruct) && String(item.instruct || "").trim() === instruct;
    return false;
  });
  if (profile) return { kind: "profile", label: `Profil: ${profile.name}`, profile };
  if (ref) return { kind: "reference", label: "Saját referenciahang" };
  return { kind: "auto", label: "Automatikus hang" };
}

function sortCharacters(characters, mode = "lines") {
  const list = [...(characters || [])];
  const byName = (a, b) => String(a.name || "").localeCompare(String(b.name || ""), "hu", { sensitivity: "base" });
  if (mode === "name") return list.sort(byName);
  return list.sort((a, b) => ((Number(b.line_count ?? b.frequency) || 0) - (Number(a.line_count ?? a.frequency) || 0)) || byName(a, b));
}

/** Toggle an id in a selection while keeping at most `max` items. */
function toggleLimited(selection, id, max) {
  const list = [...selection];
  const index = list.indexOf(id);
  if (index >= 0) {
    list.splice(index, 1);
    return list;
  }
  if (list.length >= max) return list;
  list.push(id);
  return list;
}

function formatSeconds(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function formatDecimalSeconds(seconds) {
  return `${(Math.round((Number(seconds) || 0) * 10) / 10).toFixed(1).replace(".", ",")} s`;
}

/** Average the channels of a decoded buffer into a single mono track. */
function mixToMono(channels) {
  if (!channels || !channels.length) return new Float32Array(0);
  if (channels.length === 1) return Float32Array.from(channels[0]);
  const length = Math.min(...channels.map((channel) => channel.length));
  const mono = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    let sum = 0;
    for (const channel of channels) sum += channel[i];
    mono[i] = sum / channels.length;
  }
  return mono;
}

function trimSamples(samples, sampleRate, startSec, endSec) {
  const start = Math.max(0, Math.floor((Number(startSec) || 0) * sampleRate));
  const endRaw = endSec === undefined || endSec === null ? samples.length : Math.ceil(Number(endSec) * sampleRate);
  const end = Math.min(samples.length, Math.max(start, endRaw));
  return samples.slice(start, end);
}

/**
 * Suggest trim points that cut leading and trailing silence. The threshold is
 * relative to the loudest 20 ms window so quiet microphones still work.
 */
function detectSilenceBounds(samples, sampleRate, { padding = 0.15, windowMs = 20, ratio = 0.08, floor = 0.004 } = {}) {
  const duration = samples.length / sampleRate;
  const size = Math.max(1, Math.round((sampleRate * windowMs) / 1000));
  const levels = [];
  for (let offset = 0; offset < samples.length; offset += size) {
    let sum = 0;
    const end = Math.min(samples.length, offset + size);
    for (let i = offset; i < end; i += 1) sum += samples[i] * samples[i];
    levels.push(Math.sqrt(sum / Math.max(1, end - offset)));
  }
  const peak = Math.max(0, ...levels);
  const threshold = Math.max(floor, peak * ratio);
  const first = levels.findIndex((level) => level >= threshold);
  if (!peak || first < 0) return { start: 0, end: duration };
  let last = levels.length - 1;
  while (last > first && levels[last] < threshold) last -= 1;
  const start = Math.max(0, (first * size) / sampleRate - padding);
  const end = Math.min(duration, ((last + 1) * size) / sampleRate + padding);
  return { start: Math.round(start * 100) / 100, end: Math.round(end * 100) / 100 };
}

/** Encode mono float samples as a 16-bit PCM WAV file. */
function encodeWav(samples, sampleRate) {
  const bytesPerSample = 2;
  const dataLength = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataLength);
  const view = new DataView(buffer);
  const writeText = (offset, text) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + dataLength, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, dataLength, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, Number(samples[i]) || 0));
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

function previewSignature(endpoint, payload, version = 0) {
  return JSON.stringify([endpoint, payload, version]);
}

function micErrorMessage(error) {
  const name = error?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return "A mikrofon használata nincs engedélyezve. Engedélyezd a böngésző címsorában (a lakat ikonnál), majd próbáld újra.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
    return "Nem található mikrofon. Csatlakoztass egyet, majd próbáld újra.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "A mikrofont most egy másik alkalmazás használja. Zárd be, majd próbáld újra.";
  }
  if (name === "Unsupported") {
    return "Ez a böngésző nem tud hangot felvenni. A felvételhez biztonságos kapcsolat (localhost vagy HTTPS) szükséges.";
  }
  return `A felvétel nem indult el: ${error?.message || error}`;
}

// ── Generic UI helpers ──────────────────────────────────────────────────────

function notify(message, kind = "") {
  if (studioWindow.Auris?.toast) studioWindow.Auris.toast(message, kind);
  announce(message);
}

function announce(message) {
  const live = studioDocument?.getElementById("studio-live");
  if (!live) return;
  live.textContent = "";
  setTimeout(() => { live.textContent = message; }, 30);
}

function showError(prefix, error) {
  notify(`${prefix}: ${error?.message || error}`, "err");
}

/** Show a spinner while a task runs; the button stays focusable. */
async function withBusy(button, busyLabel, task) {
  if (!button) return task();
  if (button.dataset.busy === "1") return undefined;
  const original = button.innerHTML;
  button.dataset.busy = "1";
  button.classList.add("is-busy");
  button.setAttribute("aria-disabled", "true");
  button.setAttribute("aria-busy", "true");
  button.innerHTML = `<span class="vs-spinner" aria-hidden="true"></span><span>${esc(busyLabel)}</span>`;
  try {
    return await task();
  } finally {
    button.innerHTML = original;
    delete button.dataset.busy;
    button.classList.remove("is-busy");
    button.removeAttribute("aria-disabled");
    button.removeAttribute("aria-busy");
  }
}

/** Accessible replacement for window.confirm() built on <dialog>. */
function confirmAction(message, { confirmLabel = "Megerősítés", danger = false } = {}) {
  const dialog = studioDocument?.getElementById("vs-confirm");
  if (!dialog || typeof dialog.showModal !== "function") return Promise.resolve(false);
  const opener = studioDocument.activeElement;
  dialog.querySelector("#vs-confirm-message").textContent = message;
  const ok = dialog.querySelector("[data-confirm=ok]");
  ok.textContent = confirmLabel;
  ok.classList.toggle("btn-danger", danger);
  return new Promise((resolve) => {
    const finish = () => {
      dialog.removeEventListener("close", finish);
      resolve(dialog.returnValue === "ok");
      if (opener && opener.isConnected) opener.focus();
    };
    dialog.returnValue = "";
    dialog.addEventListener("close", finish);
    dialog.showModal();
    dialog.querySelector("[data-confirm=cancel]")?.focus();
  });
}

function downloadAudio(audioUrl, name) {
  const link = document.createElement("a");
  const separator = audioUrl.includes("?") ? "&" : "?";
  link.href = `${audioUrl}${separator}download=${encodeURIComponent(name)}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.error) {
    throw new Error(data.error?.message || data.error || `HTTP ${response.status}`);
  }
  return data;
}

function postJson(url, payload) {
  return requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function saveVoiceProfile({ bookId, charId, name, saveCurrent, request = requestJson }) {
  const trimmedName = String(name || "").trim();
  if (!trimmedName) throw new Error("Adj nevet a hangprofilnak.");
  const saved = await saveCurrent();
  if (!saved) throw new Error("A jelenlegi hangbeállításokat nem sikerült menteni.");
  return request("/api/voice-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: trimmedName, ...targetPayload(bookId, charId) }),
  });
}

function flashSaved(element) {
  if (!element) return;
  element.classList.add("is-saved");
  setTimeout(() => element.classList.remove("is-saved"), 1500);
}

// ── Inline preview player (one shared <audio>, many visible controls) ───────

const playerSources = new Map(); // key -> { url, downloadName }
let activePlayerKey = null;

function miniPlayerHtml(key, label) {
  const source = playerSources.get(key);
  return `<div class="mini-player" data-player="${esc(key)}" role="group" aria-label="${esc(label)}"${source ? "" : " hidden"}>
    <button type="button" class="mini-player-btn" data-player-action="toggle" aria-label="Lejátszás">${icon("play")}</button>
    <button type="button" class="mini-player-btn" data-player-action="stop" aria-label="Leállítás">${icon("stop")}</button>
    <input type="range" class="mini-player-seek" data-player-action="seek" min="0" max="1000" step="1" value="0" aria-label="${esc(label)}: lejátszási pozíció">
    <span class="mini-player-time" aria-hidden="true">0:00 / 0:00</span>
    <button type="button" class="btn btn-sm btn-ghost mini-player-download" data-player-action="download"${source?.downloadName ? "" : " hidden"}>${icon("download")}<span>Próba mentése</span></button>
  </div>`;
}

function mountPlayers(scope = studioDocument) {
  scope?.querySelectorAll("[data-player-slot]").forEach((slot) => {
    slot.outerHTML = miniPlayerHtml(slot.dataset.playerSlot, slot.dataset.playerLabel || "Próbahang");
  });
}

function playerElements(key) {
  return [...(studioDocument?.querySelectorAll("[data-player]") || [])]
    .filter((element) => element.dataset.player === key);
}

function loadIntoPlayer(key, url, { downloadName = null, autoplay = true } = {}) {
  const previous = playerSources.get(key);
  if (previous?.url?.startsWith("blob:") && previous.url !== url) URL.revokeObjectURL(previous.url);
  playerSources.set(key, { url, downloadName });
  playerElements(key).forEach((element) => {
    element.hidden = false;
    const download = element.querySelector("[data-player-action=download]");
    if (download) download.hidden = !downloadName;
  });
  if (activePlayerKey === key && previewAudio) {
    previewAudio.pause();
    previewAudio.removeAttribute("src");
    previewAudio.dataset.src = "";
  }
  syncPlayerUI();
  if (autoplay) return playKey(key);
  return Promise.resolve();
}

function clearPlayer(key) {
  if (activePlayerKey === key) stopPlayer();
  const source = playerSources.get(key);
  if (source?.url?.startsWith("blob:")) URL.revokeObjectURL(source.url);
  playerSources.delete(key);
  playerElements(key).forEach((element) => { element.hidden = true; });
}

async function playKey(key) {
  const source = playerSources.get(key);
  if (!source || !previewAudio) return;
  if (activePlayerKey !== key || previewAudio.dataset.src !== source.url) {
    previewAudio.pause();
    previewAudio.src = source.url;
    previewAudio.dataset.src = source.url;
    activePlayerKey = key;
  }
  try {
    await previewAudio.play();
  } catch (error) {
    if (error?.name !== "AbortError") notify(`A lejátszás nem indult el: ${error.message || error}`, "err");
  }
  syncPlayerUI();
}

function togglePlayer(key) {
  if (activePlayerKey === key && previewAudio && !previewAudio.paused) previewAudio.pause();
  else playKey(key);
}

function stopPlayer() {
  if (!previewAudio) return;
  previewAudio.pause();
  if (previewAudio.dataset.src) previewAudio.currentTime = 0;
  syncPlayerUI();
}

function seekPlayer(key, fraction) {
  if (activePlayerKey !== key || !previewAudio?.duration) return;
  previewAudio.currentTime = previewAudio.duration * fraction;
}

function syncPlayerUI() {
  if (!studioDocument) return;
  studioDocument.querySelectorAll("[data-player]").forEach((element) => {
    const active = element.dataset.player === activePlayerKey && previewAudio;
    const playing = Boolean(active && !previewAudio.paused && !previewAudio.ended);
    const toggle = element.querySelector("[data-player-action=toggle]");
    if (toggle && toggle.dataset.state !== (playing ? "pause" : "play")) {
      toggle.dataset.state = playing ? "pause" : "play";
      toggle.innerHTML = icon(playing ? "pause" : "play");
      toggle.setAttribute("aria-label", playing ? "Szünet" : "Lejátszás");
    }
    element.classList.toggle("is-playing", playing);
    const duration = active && Number.isFinite(previewAudio.duration) ? previewAudio.duration : 0;
    const current = active ? previewAudio.currentTime : 0;
    const seek = element.querySelector(".mini-player-seek");
    if (seek && studioDocument.activeElement !== seek) {
      seek.value = duration ? String(Math.round((current / duration) * 1000)) : "0";
    }
    if (seek) seek.setAttribute("aria-valuetext", `${formatSeconds(current)} / ${formatSeconds(duration)}`);
    const time = element.querySelector(".mini-player-time");
    if (time) time.textContent = `${formatSeconds(current)} / ${formatSeconds(duration)}`;
  });
}

function downloadPreview(key) {
  const source = playerSources.get(key);
  if (!source?.downloadName) return;
  downloadAudio(source.url, source.downloadName);
}

function initPlayer() {
  if (!previewAudio) return;
  ["play", "pause", "ended", "timeupdate", "loadedmetadata", "emptied"].forEach((type) => {
    previewAudio.addEventListener(type, syncPlayerUI);
  });
  previewAudio.addEventListener("error", () => {
    if (!previewAudio.dataset.src) return;
    notify("A hang nem tölthető be. Lehet, hogy a fájl már nem érhető el.", "err");
  });
  studioDocument.addEventListener("click", (event) => {
    const button = event.target.closest("[data-player-action]");
    if (!button || button.tagName === "INPUT") return;
    const key = button.closest("[data-player]")?.dataset.player;
    if (!key) return;
    const action = button.dataset.playerAction;
    if (action === "toggle") togglePlayer(key);
    else if (action === "stop") { if (activePlayerKey === key) stopPlayer(); }
    else if (action === "download") downloadPreview(key);
  });
  studioDocument.addEventListener("input", (event) => {
    const seek = event.target.closest?.(".mini-player-seek");
    if (!seek) return;
    const key = seek.closest("[data-player]")?.dataset.player;
    seekPlayer(key, Number(seek.value) / 1000);
  });
}

// ── Voice previews (cached, so "Próba mentése" reuses the generated audio) ──

const previewCache = new Map(); // signature -> audio_url
const refVersions = {}; // ref key -> counter, bumped when the reference changes

function refVersion(refKey) {
  return refVersions[refKey] || 0;
}

function bumpRefVersion(refKey) {
  refVersions[refKey] = refVersion(refKey) + 1;
}

async function generatePreview({ endpoint, payload, version = 0 }) {
  const signature = previewSignature(endpoint, payload, version);
  if (previewCache.has(signature)) return previewCache.get(signature);
  const data = await postJson(endpoint, payload);
  previewCache.set(signature, data.audio_url);
  return data.audio_url;
}

async function runPreview({ key, button, endpoint, payload, version, downloadName, autoplay = true, errorPrefix = "A próbahang sikertelen" }) {
  const cachedUrl = previewCache.get(previewSignature(endpoint, payload, version));
  if (cachedUrl) {
    await loadIntoPlayer(key, cachedUrl, { downloadName, autoplay });
    return cachedUrl;
  }
  try {
    return await withBusy(button, "Készül…", async () => {
      announce("A próbahang készül…");
      const url = await generatePreview({ endpoint, payload, version });
      await loadIntoPlayer(key, url, { downloadName, autoplay });
      announce("A próbahang elkészült.");
      return url;
    });
  } catch (error) {
    showError(errorPrefix, error);
    return null;
  }
}

function characterById(charId) {
  return loadedCharacters.find((item) => Number(item.id) === Number(charId));
}

function charPreviewRequest(charId) {
  const character = characterById(charId);
  return {
    endpoint: `/api/books/${BOOK_ID}/characters/${charId}/preview`,
    payload: previewPayload(
      updateInstructPreview(charId),
      document.getElementById(`ref-text-${charId}`)?.value.trim() || "",
      currentPreviewText(),
    ),
    version: `${character?.ref_audio_path || ""}#${refVersion(String(charId))}`,
    downloadName: `${character?.name || `szereplo-${charId}`}-proba`,
  };
}

function narratorPreviewRequest(text = currentPreviewText()) {
  return {
    endpoint: `/api/books/${BOOK_ID}/characters/narrator/preview`,
    payload: previewPayload(
      updateNarratorPreview(),
      document.getElementById("narrator-ref-text")?.value.trim() || "",
      text,
    ),
    version: `${narratorHasRefAudio ? narratorRefAudioName : ""}#${refVersion("narrator")}`,
    downloadName: "narrator-proba",
  };
}

function eventButton(maybeButton) {
  return maybeButton && maybeButton.nodeType === 1 ? maybeButton : null;
}

async function previewChar(charId, button = null) {
  return runPreview({
    key: `char-${charId}`,
    button: eventButton(button) || document.querySelector(`#card-${charId} [data-action=preview]`),
    ...charPreviewRequest(charId),
  });
}

async function previewNarrator(button = null, key = "narrator") {
  const target = eventButton(button?.currentTarget || button) || document.getElementById("narrator-preview-btn");
  return runPreview({ key, button: target, ...narratorPreviewRequest() });
}

async function downloadCached(key, request, button) {
  const url = await runPreview({ key, button, autoplay: false, errorPrefix: "A próbahang mentése sikertelen", ...request });
  if (url) downloadAudio(url, request.downloadName);
}

function downloadChar(charId, button = null) {
  return downloadCached(`char-${charId}`, charPreviewRequest(charId), eventButton(button));
}

function downloadNarrator(button = null) {
  return downloadCached("narrator", narratorPreviewRequest(), eventButton(button?.currentTarget || button));
}

// ── Engine capabilities ─────────────────────────────────────────────────────

function presetSelect(id, instruct, label) {
  const presets = PRESET_VOICES[activeEngine.engine];
  if (!presets) return "";
  const current = presetVoiceOf(instruct);
  return `<label class="preset-voice-label">Beépített hang (${esc(ENGINE_LABELS[activeEngine.engine] || "")})
    <select class="vc-select" id="${esc(id)}" aria-label="${esc(label)}">
      <option value="">Automatikus (a leírt nem alapján)</option>
      ${presets.map(([value, text]) => `<option value="${esc(value)}"${value.toLowerCase() === current.toLowerCase() ? " selected" : ""}>${esc(text)}</option>`).join("")}
    </select></label>`;
}

async function applyEngineCapabilities() {
  try {
    const status = await requestJson("/api/tts/status");
    activeEngine = {
      engine: status.engine || "omnivoice",
      capabilities: status.capabilities || {},
    };
  } catch (_) {
    return;
  }
  const caps = activeEngine.capabilities;
  const body = studioDocument.body;
  body.classList.toggle("engine-no-clone", caps.voice_clone === false);
  body.classList.toggle("engine-no-design", caps.voice_design === false);
  let note = studioDocument.getElementById("engine-voice-note");
  if (!note) {
    note = studioDocument.createElement("p");
    note.id = "engine-voice-note";
    note.className = "engine-voice-note";
    studioDocument.querySelector(".studio-header")?.after(note);
  }
  const name = ENGINE_LABELS[activeEngine.engine] || activeEngine.engine;
  if (caps.voice_clone === false) {
    note.textContent = `A kiválasztott beszédmotor (${name}) nem támogat hangklónozást: beépített hangokkal dolgozik, a feltöltött referenciahangot figyelmen kívül hagyja. A hangot a „Beépített hang” mezőben vagy a nem kiválasztásával adhatod meg.`;
  } else if (caps.voice_design === false) {
    note.textContent = `A kiválasztott beszédmotor (${name}) hangklónozással dolgozik: saját hanghoz tölts fel vagy vegyél fel referenciahangot. Referencia nélkül automatikus magyar mintahangot használ; a leírt életkor és hangmagasság nem hat.`;
  } else {
    note.textContent = "";
  }
  note.classList.toggle("hidden", !note.textContent);
  const narratorPreset = presetSelect("narrator-preset-voice", narratorInstruct, "Narrátor beépített hangja");
  const narratorControls = studioDocument.getElementById("narrator-accent")?.closest(".voice-controls");
  studioDocument.getElementById("narrator-preset-wrap")?.remove();
  if (narratorPreset && narratorControls) {
    const wrap = studioDocument.createElement("div");
    wrap.id = "narrator-preset-wrap";
    wrap.className = "preset-voice-wrap";
    wrap.innerHTML = narratorPreset;
    narratorControls.after(wrap);
    studioDocument.getElementById("narrator-preset-voice")?.addEventListener("change", updateNarratorPreview);
    updateNarratorPreview();
  }
}

function filterCharacters(characters, query) {
  const needle = String(query || "").trim().toLocaleLowerCase("hu");
  if (!needle) return characters;
  return characters.filter((character) => (
    String(character.name || "").toLocaleLowerCase("hu").includes(needle)
  ));
}

function targetPayload(bookId, charId) {
  const payload = { book_id: bookId };
  if (charId !== null && charId !== undefined) payload.char_id = charId;
  return payload;
}

function previewPayload(instruct, refText, text = HUNGARIAN_PREVIEW_TEXT) {
  return {
    instruct,
    ref_text: refText,
    text: String(text || "").trim() || HUNGARIAN_PREVIEW_TEXT,
  };
}

function currentPreviewText() {
  return document.getElementById("voice-preview-text")?.value || HUNGARIAN_PREVIEW_TEXT;
}

// ── Voice description controls ──────────────────────────────────────────────

function updateInstructPreview(charId) {
  const originalInstruct = characterById(charId)?.instruct || "";
  // The card may be filtered out of view: fall back to the stored voice.
  if (!document.getElementById(`g-${charId}`)) return originalInstruct;
  const instruct = buildInstruct(
    document.getElementById(`g-${charId}`)?.value || "female",
    document.getElementById(`a-${charId}`)?.value || "young adult",
    document.getElementById(`p-${charId}`)?.value || "moderate pitch",
    document.getElementById(`ac-${charId}`)?.value || "",
    originalInstruct,
  );
  const preset = document.getElementById(`pv-${charId}`);
  const final = preset ? withPresetVoice(instruct, preset.value) : instruct;
  const element = document.getElementById(`ins-${charId}`);
  if (element) element.textContent = final;
  const summary = document.getElementById(`sum-${charId}`);
  if (summary) summary.textContent = summarizeInstruct(final);
  return final;
}

function getNarratorInstruct() {
  const instruct = buildInstruct(
    document.getElementById("narrator-gender")?.value || "male",
    document.getElementById("narrator-age")?.value || "middle-aged",
    document.getElementById("narrator-pitch")?.value || "low pitch",
    document.getElementById("narrator-accent")?.value || "",
    narratorInstruct,
  );
  const preset = document.getElementById("narrator-preset-voice");
  return preset ? withPresetVoice(instruct, preset.value) : instruct;
}

function updateNarratorPreview() {
  const instruct = getNarratorInstruct();
  const element = document.getElementById("narrator-instruct-preview");
  if (element) element.textContent = instruct;
  const summary = document.getElementById("narrator-voice-summary");
  if (summary) summary.textContent = summarizeInstruct(instruct);
  return instruct;
}

function narratorPseudoCharacter() {
  return {
    instruct: narratorInstruct || DEFAULT_NARRATOR_INSTRUCT,
    ref_audio_path: narratorHasRefAudio ? "narrator" : null,
    ref_audio_name: narratorHasRefAudio ? narratorRefAudioName : null,
    match_by_name: true,
  };
}

function sourceBadgeHtml(source) {
  const iconName = source.kind === "profile" ? "users" : source.kind === "reference" ? "mic" : "wave";
  return `<span class="voice-source-badge is-${source.kind}">${icon(iconName)}<span>${esc(source.label)}</span></span>`;
}

function syncNarratorBadge() {
  const badge = document.getElementById("narrator-source-badge");
  if (badge) badge.innerHTML = sourceBadgeHtml(voiceSourceOf(narratorPseudoCharacter(), voiceProfiles));
}

function syncNarratorRefUI() {
  document.getElementById("narrator-ref-status")?.classList.toggle("hidden", !narratorHasRefAudio);
  const name = document.getElementById("narrator-ref-name");
  if (name) name.textContent = narratorRefAudioName;
  const remove = document.getElementById("remove-narrator-ref-btn");
  if (remove) {
    remove.disabled = !narratorHasRefAudio;
    remove.title = narratorHasRefAudio ? "" : "Nincs aktív narrátori referenciahang.";
  }
  if (!narratorHasRefAudio) {
    clearPlayer("ref-narrator");
    resetReferenceCheck("narrator");
  }
  const check = document.getElementById("check-ref-narrator");
  if (check) check.disabled = !narratorHasRefAudio;
  syncNarratorBadge();
}

function syncSingleNarratorUI() {
  const toggle = document.getElementById("single-narrator-mode");
  if (toggle) toggle.checked = singleNarratorMode;
  const note = document.getElementById("character-voice-note");
  if (!note) return;
  note.textContent = singleNarratorMode
    ? "Az egy narrátoros mód aktív. A szereplők hangjai szerkeszthetők, de a lejátszás és az export a narrátor hangját használja."
    : "";
  note.classList.toggle("hidden", !singleNarratorMode);
}

function setNarratorControls(instruct) {
  const parsed = parseInstruct(instruct || DEFAULT_NARRATOR_INSTRUCT);
  [
    ["narrator-gender", parsed.gender],
    ["narrator-age", parsed.age],
    ["narrator-pitch", parsed.pitch],
    ["narrator-accent", parsed.accent],
  ].forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.value = value;
  });
  const preset = document.getElementById("narrator-preset-voice");
  if (preset) preset.value = presetVoiceOf(instruct) || "";
  updateNarratorPreview();
}

function initNarratorControls() {
  setNarratorControls(narratorInstruct || DEFAULT_NARRATOR_INSTRUCT);
  ["narrator-gender", "narrator-age", "narrator-pitch", "narrator-accent"]
    .forEach((id) => document.getElementById(id)?.addEventListener("change", updateNarratorPreview));
  const toggle = document.getElementById("single-narrator-mode");
  if (toggle) {
    toggle.checked = singleNarratorMode;
    toggle.addEventListener("change", () => {
      singleNarratorMode = toggle.checked;
      syncSingleNarratorUI();
    });
  }
  syncSingleNarratorUI();
  syncNarratorRefUI();
}

// ── Profiles ────────────────────────────────────────────────────────────────

function profileOptions() {
  return `<option value="">Válassz mentett hangot…</option>${voiceProfiles.map((profile) => (
    `<option value="${profile.id}">${esc(profile.name)}</option>`
  )).join("")}`;
}

function populateProfileSelects(selectedId = null) {
  document.querySelectorAll(".voice-profile-select").forEach((select) => {
    const previous = selectedId || Number(select.value) || null;
    select.innerHTML = profileOptions();
    if (previous && voiceProfiles.some((profile) => Number(profile.id) === Number(previous))) {
      select.value = String(previous);
    }
  });
  syncBulkBar();
}

async function loadProfiles(selectedId = null) {
  voiceProfiles = await requestJson("/api/voice-profiles");
  populateProfileSelects(selectedId);
  refreshAllSourceBadges();
}

function profileControls(charId, ownerName) {
  const suffix = charId === null ? "narrator" : String(charId);
  return `<section class="profile-controls" aria-label="${esc(ownerName)} mentett hangprofilja">
    <label for="profile-${suffix}">Mentett hangprofil</label>
    <div class="profile-apply-row">
      <select id="profile-${suffix}" class="vc-select voice-profile-select" aria-label="Mentett hangprofil ${esc(ownerName)} számára">${profileOptions()}</select>
      <button type="button" class="btn btn-sm btn-primary" data-action="apply-profile">Alkalmazás</button>
      <button type="button" class="btn btn-sm btn-ghost" data-action="delete-profile">Törlés</button>
      <button type="button" class="btn btn-sm btn-ghost" data-action="compare">${icon("users")}<span>Összehasonlítás</span></button>
    </div>
    <div class="profile-save-row">
      <label class="sr-only" for="profile-name-${suffix}">Új hangprofil neve</label>
      <input id="profile-name-${suffix}" maxlength="100" placeholder="Új hangprofil neve">
      <button type="button" class="btn btn-sm btn-ghost" data-action="save-profile">Jelenlegi hang mentése</button>
    </div>
  </section>`;
}

// ── Reference audio section (upload, playback, microphone recording) ───────

function referenceSectionHtml(character) {
  const id = character.id;
  const hasRef = Boolean(character.ref_audio_path);
  return `<section class="clone-section clone-prominent" aria-labelledby="ref-title-${id}">
    <h4 id="ref-title-${id}">Referenciahang</h4>
    <div id="ref-status-${id}" class="reference-status${hasRef ? "" : " hidden"}">
      <span class="reference-status-label">Aktív referencia:</span>
      <span id="ref-name-${id}" class="reference-name">${esc(character.ref_audio_name || "Korábban feltöltött WAV")}</span>
      <button type="button" class="btn btn-sm btn-ghost ref-play-btn" data-action="play-ref">${icon("play")}<span>Referencia meghallgatása</span></button>
    </div>
    ${miniPlayerHtml(`ref-${id}`, `${character.name} referenciahangja`)}
    <label for="ref-text-${id}">Referenciahang pontos átirata</label>
    <textarea id="ref-text-${id}" class="reference-text" rows="3" placeholder="Pontosan azt írd ide, ami a hangfelvételen elhangzik.">${esc(character.ref_text)}</textarea>
    <div class="reference-actions">
      <label class="btn btn-sm btn-ghost file-picker"><span>Átirat betöltése TXT-ből</span><input type="file" accept=".txt,text/plain" data-file-action="ref-text"></label>
      <label class="btn btn-sm btn-primary file-picker"><span>Referenciahang kiválasztása</span><input type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.opus,.m4a" data-file-action="ref-audio"></label>
      <button type="button" class="btn btn-sm btn-ghost" data-action="record" aria-expanded="false" aria-controls="rec-${id}">${icon("mic")}<span>Felvétel mikrofonnal</span></button>
      <button id="check-ref-${id}" class="btn btn-sm btn-ghost" type="button" data-action="check-ref"${hasRef ? "" : " disabled"}>Referencia ellenőrzése</button>
      <button id="remove-ref-${id}" class="btn btn-sm btn-ghost" type="button" data-action="remove-ref"${hasRef ? "" : " disabled"}>Referencia törlése</button>
    </div>
    <div id="ref-check-${id}" class="reference-check" role="status" aria-live="polite" hidden></div>
    <div class="recorder" id="rec-${id}" hidden></div>
    <label class="reference-clean"><input type="checkbox" id="ref-clean-${id}" checked> Zajszűrés, csendvágás és hangerő-kiegyenlítés feltöltéskor</label>
    <p class="studio-note">${REFERENCE_NOTE}</p>
  </section>`;
}

const REFERENCE_NOTE = "Tiszta, egyetlen beszélős, 6–15 másodperces felvétel ajánlott, az elején és a végén rövid csenddel. Feltöltés után az Auris ellenőrzi, és üres átiratnál kitölti.";
const referenceChecks = new Map(); // ref key -> last check report

function refEndpoint(refKey) {
  return refKey === "narrator"
    ? `/api/books/${BOOK_ID}/narrator-ref-audio`
    : `/api/characters/${refKey}/ref-audio`;
}

function refTextField(refKey) {
  return document.getElementById(refKey === "narrator" ? "narrator-ref-text" : `ref-text-${refKey}`);
}

async function playReference(refKey, button) {
  const key = `ref-${refKey}`;
  const url = `${refEndpoint(refKey)}?v=${refVersion(refKey)}`;
  try {
    await withBusy(button, "Betöltés…", async () => {
      const response = await fetch(url, { method: "HEAD" });
      if (!response.ok) throw new Error("Nincs feltöltött referenciahang.");
      await loadIntoPlayer(key, url);
    });
  } catch (error) {
    showError("A referencia nem játszható le", error);
  }
}

function applyUploadedReference(refKey, data) {
  bumpRefVersion(refKey);
  clearPlayer(`ref-${refKey}`);
  if (refKey === "narrator") {
    narratorHasRefAudio = true;
    narratorRefAudioName = data.ref_audio_name;
    syncNarratorRefUI();
    return;
  }
  const character = characterById(refKey);
  if (character) {
    character.ref_audio_path = `uploaded:${refVersion(refKey)}`;
    character.ref_audio_name = data.ref_audio_name;
    character.ref_text = data.ref_text;
  }
  const name = document.getElementById(`ref-name-${refKey}`);
  if (name) name.textContent = data.ref_audio_name;
  document.getElementById(`ref-status-${refKey}`)?.classList.remove("hidden");
  const remove = document.getElementById(`remove-ref-${refKey}`);
  if (remove) remove.disabled = false;
  const check = document.getElementById(`check-ref-${refKey}`);
  if (check) check.disabled = false;
  refreshCardSource(refKey);
}

async function uploadReferenceFile(refKey, file) {
  const form = new FormData();
  form.append("file", file);
  form.append("ref_text", refTextField(refKey)?.value.trim() || "");
  const clean = studioDocument?.getElementById(`ref-clean-${refKey}`);
  form.append("clean", !clean || clean.checked ? "1" : "0");
  const data = await requestJson(refEndpoint(refKey), { method: "POST", body: form });
  applyUploadedReference(refKey, data);
  checkReference(refKey);
  return data;
}

// ── Reference check: length, cut-off edges, transcript, shorter stretches ──

function resetReferenceCheck(refKey) {
  referenceChecks.delete(refKey);
  const panel = refCheckPanel(refKey);
  if (panel) { panel.hidden = true; panel.innerHTML = ""; }
  const check = document.getElementById(`check-ref-${refKey}`);
  if (check) check.disabled = true;
}

function refCheckPanel(refKey) {
  return document.getElementById(`ref-check-${refKey}`);
}

function setReferenceText(refKey, text) {
  const field = refTextField(refKey);
  if (field) field.value = text;
  const character = refKey === "narrator" ? null : characterById(refKey);
  if (character) character.ref_text = text;
}

function decimalSeconds(value) {
  return Number(value).toFixed(1).replace(".", ",");
}

async function checkReference(refKey, button = null) {
  const panel = refCheckPanel(refKey);
  if (panel) {
    panel.hidden = false;
    panel.className = "reference-check is-busy";
    panel.innerHTML = `<p class="reference-check-title"><span class="vs-spinner" aria-hidden="true"></span>A referencia ellenőrzése… Az első alkalommal a beszédfelismerő betöltése fél percig is eltarthat.</p>`;
  }
  try {
    const report = await withBusy(button, "Ellenőrzés…", () => postJson(`${refEndpoint(refKey)}/check`, {}));
    referenceChecks.set(refKey, report);
    if (report.ref_text_saved) setReferenceText(refKey, report.ref_text);
    renderReferenceCheck(refKey, report);
    return report;
  } catch (error) {
    if (panel) {
      panel.className = "reference-check is-error";
      panel.innerHTML = `<p class="reference-check-title">Az ellenőrzés nem sikerült: ${esc(error.message || error)}</p>`;
    }
    return null;
  }
}

function renderReferenceCheck(refKey, report) {
  const panel = refCheckPanel(refKey);
  if (!panel) return;
  const levels = report.issues.map((issue) => issue.level);
  const state = levels.includes("error") ? "error" : levels.length ? "warn" : "ok";
  const title = {
    ok: `A referencia rendben (${decimalSeconds(report.duration)} s).`,
    warn: `A referencia használható, de érdemes javítani (${decimalSeconds(report.duration)} s).`,
    error: `A referencia így rontja a klónt (${decimalSeconds(report.duration)} s).`,
  }[state];
  const issues = report.issues.map((issue) =>
    `<li class="is-${esc(issue.level)}">${esc(issue.message)}</li>`).join("");
  const saved = report.ref_text_saved
    ? `<p class="studio-note">Az átiratot a beszédfelismerő töltötte ki. Hallgasd meg a felvételt, és javítsd az elírásokat, majd mentsd a hangot.</p>`
    : "";
  const scores = new Map((report.audition?.results || []).map((row) => [row.index, row]));
  const cuts = (report.candidates || []).map((cand, index) => {
    const score = scores.get(index);
    const scoreHtml = score
      ? `<span class="reference-cut-score">${score.recommended ? `<span class="reference-cut-badge">Ajánlott</span>` : ""}Hasonlóság ${score.similarity.toFixed(3).replace(".", ",")} · szóhiba ${decimalSeconds(score.wer * 100)} %</span>`
      : "";
    return `<li class="reference-cut${score?.recommended ? " is-recommended" : ""}">
      <span class="reference-cut-time">${decimalSeconds(cand.start)}–${decimalSeconds(cand.end)} s · ${decimalSeconds(cand.duration)} s</span>${scoreHtml}
      <span class="reference-cut-text">${esc(cand.text)}</span>
      <span class="reference-cut-actions">
        <button type="button" class="btn btn-sm btn-ghost" data-action="ref-span-play" data-index="${index}">${icon("play")}<span>Meghallgatás</span></button>
        <button type="button" class="btn btn-sm btn-primary" data-action="ref-span-use" data-index="${index}">Ezt használom</button>
      </span>
    </li>`;
  }).join("");
  const auditionNote = report.audition
    ? `<p class="studio-note">Mindegyik szakasz ${report.audition.sentences} próbamondatot olvasott fel ${report.audition.takes} változatban; a hasonlóság a teljes felvételhez mért hangazonosság, a szóhibát a beszédfelismerő hallja.</p>`
    : `<button type="button" class="btn btn-sm btn-ghost reference-audition-btn" data-action="ref-audition">Legjobb szakasz keresése próbagenerálással (kb. 1 perc)</button>`;
  const cutBlock = cuts
    ? `<p class="reference-check-subtitle">Mondathatáron vágott, rövidebb szakaszok ebből a felvételből:</p>${auditionNote}<ul class="reference-cuts">${cuts}</ul>`
    : "";
  panel.className = `reference-check is-${state}`;
  panel.hidden = false;
  panel.innerHTML = `<p class="reference-check-title">${esc(title)}</p>${issues ? `<ul class="reference-issues">${issues}</ul>` : ""}${saved}${cutBlock}`;
}

let spanAudio = null;

function playReferenceSpan(refKey, index) {
  const cand = referenceChecks.get(refKey)?.candidates?.[index];
  if (!cand) return;
  if (spanAudio) spanAudio.pause();
  spanAudio = new Audio(`${refEndpoint(refKey)}?v=${refVersion(refKey)}#t=${cand.start},${cand.end}`);
  spanAudio.play().catch((error) => showError("A szakasz nem játszható le", error));
}

async function useReferenceSpan(refKey, index, button) {
  const cand = referenceChecks.get(refKey)?.candidates?.[index];
  if (!cand) return;
  try {
    const data = await withBusy(button, "Vágás…", () => postJson(`${refEndpoint(refKey)}/trim`, cand));
    if (spanAudio) spanAudio.pause();
    applyUploadedReference(refKey, data);
    setReferenceText(refKey, data.ref_text);
    notify(`A referencia a kiválasztott ${decimalSeconds(data.duration)} másodperces szakasz lett.`, "ok");
    checkReference(refKey);
  } catch (error) {
    showError("A vágás nem sikerült", error);
  }
}

async function auditionReference(refKey, button) {
  const report = referenceChecks.get(refKey);
  if (!report?.candidates?.length) return;
  try {
    const result = await withBusy(button, "Próbagenerálás…", () =>
      postJson(`${refEndpoint(refKey)}/audition`, { candidates: report.candidates }));
    report.audition = result;
    renderReferenceCheck(refKey, report);
    const best = result.results.find((row) => row.recommended);
    if (best) notify(`Ajánlott szakasz: ${decimalSeconds(best.start)}–${decimalSeconds(best.end)} s.`, "ok");
  } catch (error) {
    showError("A próbagenerálás nem sikerült", error);
  }
}

function handleReferenceCheckAction(refKey, button) {
  const action = button.dataset.action;
  if (action === "check-ref") checkReference(refKey, button);
  else if (action === "ref-audition") auditionReference(refKey, button);
  else if (action === "ref-span-play") playReferenceSpan(refKey, Number(button.dataset.index));
  else if (action === "ref-span-use") useReferenceSpan(refKey, Number(button.dataset.index), button);
  else return false;
  return true;
}

async function uploadRef(event, charId) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    await uploadReferenceFile(String(charId), file);
    notify("A referenciahang és az átirat mentve.", "ok");
  } catch (error) {
    showError("A feltöltés sikertelen", error);
  } finally {
    event.target.value = "";
  }
}

async function uploadNarratorRef(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    await uploadReferenceFile("narrator", file);
    notify("A narrátor referenciahangja mentve.", "ok");
  } catch (error) {
    showError("A feltöltés sikertelen", error);
  } finally {
    event.target.value = "";
  }
}

async function removeRef(charId) {
  const ok = await confirmAction("Biztosan törlöd ezt a referenciahangot és az átiratát?", { confirmLabel: "Törlés", danger: true });
  if (!ok) return;
  try {
    await requestJson(`/api/characters/${charId}/ref-audio`, { method: "DELETE" });
    bumpRefVersion(String(charId));
    clearPlayer(`ref-${charId}`);
    document.getElementById(`ref-status-${charId}`)?.classList.add("hidden");
    const remove = document.getElementById(`remove-ref-${charId}`);
    if (remove) remove.disabled = true;
    resetReferenceCheck(String(charId));
    const text = document.getElementById(`ref-text-${charId}`);
    if (text) text.value = "";
    const character = characterById(charId);
    if (character) {
      character.ref_audio_path = null;
      character.ref_audio_name = null;
      character.ref_text = null;
    }
    refreshCardSource(charId);
    notify("A referenciahang törölve.", "ok");
  } catch (error) {
    showError("A referencia törlése sikertelen", error);
  }
}

async function removeNarratorRef() {
  const ok = await confirmAction("Biztosan törlöd a narrátor referenciahangját és az átiratát?", { confirmLabel: "Törlés", danger: true });
  if (!ok) return;
  try {
    await requestJson(`/api/books/${BOOK_ID}/narrator-ref-audio`, { method: "DELETE" });
    bumpRefVersion("narrator");
    narratorHasRefAudio = false;
    narratorRefAudioName = "Korábban feltöltött WAV";
    const refText = document.getElementById("narrator-ref-text");
    if (refText) refText.value = "";
    syncNarratorRefUI();
    notify("A narrátor referenciahangja törölve.", "ok");
  } catch (error) {
    showError("A referencia törlése sikertelen", error);
  }
}

async function loadTextFileIntoField(event, fieldId) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const field = document.getElementById(fieldId);
    if (field) field.value = (await file.text()).replace(/^﻿/, "").trim();
    notify("Az átirat betöltve.", "ok");
  } catch (error) {
    showError("A TXT fájl nem olvasható", error);
  } finally {
    event.target.value = "";
  }
}

function loadRefText(event, charId) {
  return loadTextFileIntoField(event, `ref-text-${charId}`);
}

function loadNarratorRefText(event) {
  return loadTextFileIntoField(event, "narrator-ref-text");
}

// Microphone recorder ------------------------------------------------------

const recorders = new Map(); // ref key -> state

function recorderPanel(refKey) {
  return document.getElementById(refKey === "narrator" ? "rec-narrator" : `rec-${refKey}`);
}

function recorderHtml(refKey) {
  return `<div class="recorder-head">
      <h5 class="recorder-title">Felvétel mikrofonnal</h5>
      <button type="button" class="btn btn-sm btn-ghost" data-rec-action="close">Bezárás</button>
    </div>
    <p class="studio-note">Olvasd fel hangosan az átirat mezőbe írt szöveget csendes helyen, egyenletes hangerővel. A felvétel legfeljebb ${MAX_RECORDING_SECONDS} másodperc.</p>
    <div class="recorder-controls">
      <button type="button" class="btn btn-sm btn-ghost" data-rec-action="insert-sample">Próbaszöveg beillesztése az átiratba</button>
      <button type="button" class="btn btn-sm btn-primary" data-rec-action="start">${icon("mic")}<span>Felvétel indítása</span></button>
      <button type="button" class="btn btn-sm btn-ghost" data-rec-action="stop" hidden>${icon("stop")}<span>Leállítás</span></button>
      <span class="recorder-timer" aria-hidden="true">0:00 / ${formatSeconds(MAX_RECORDING_SECONDS)}</span>
    </div>
    <div class="recorder-meter" aria-hidden="true"><span></span></div>
    <p class="recorder-status" role="status" aria-live="polite"></p>
    <div class="recorder-review" hidden>
      ${miniPlayerHtml(`rec-${refKey}`, "Levágott felvétel")}
      <div class="trim-row">
        <label class="trim-label">Kezdet <output data-trim-out="start">0,0 s</output>
          <input type="range" data-trim="start" min="0" max="1" step="0.05" value="0">
        </label>
        <label class="trim-label">Vég <output data-trim-out="end">0,0 s</output>
          <input type="range" data-trim="end" min="0" max="1" step="0.05" value="1">
        </label>
      </div>
      <p class="trim-info"></p>
      <div class="recorder-actions">
        <button type="button" class="btn btn-sm btn-primary" data-rec-action="upload">${icon("check")}<span>Feltöltés referenciaként</span></button>
        <button type="button" class="btn btn-sm btn-ghost" data-rec-action="discard">Elvetés</button>
      </div>
    </div>`;
}

function setRecorderStatus(refKey, message, kind = "") {
  const status = recorderPanel(refKey)?.querySelector(".recorder-status");
  if (!status) return;
  status.textContent = message;
  status.className = `recorder-status${kind ? ` is-${kind}` : ""}`;
}

function toggleRecorder(refKey, button) {
  const panel = recorderPanel(refKey);
  if (!panel) return;
  if (!panel.hidden) {
    closeRecorder(refKey);
    return;
  }
  panel.innerHTML = recorderHtml(refKey);
  panel.hidden = false;
  button?.setAttribute("aria-expanded", "true");
  if (!refTextField(refKey)?.value.trim()) {
    setRecorderStatus(refKey, "Tipp: előbb írd be az átiratba, amit felolvasol – vagy illeszd be a próbaszöveget.");
  }
  panel.querySelector("[data-rec-action=start]")?.focus();
}

function closeRecorder(refKey) {
  const state = recorders.get(refKey);
  if (state?.mediaRecorder?.state === "recording") {
    state.cancelled = true;
    state.mediaRecorder.stop();
  }
  cleanupRecorderStream(state);
  recorders.delete(refKey);
  clearPlayer(`rec-${refKey}`);
  const panel = recorderPanel(refKey);
  if (panel) {
    panel.hidden = true;
    panel.innerHTML = "";
  }
  const opener = refKey === "narrator"
    ? document.getElementById("narrator-record-btn")
    : document.querySelector(`#card-${refKey} [data-action=record]`);
  opener?.setAttribute("aria-expanded", "false");
  opener?.focus();
}

function cleanupRecorderStream(state) {
  if (!state) return;
  clearInterval(state.timer);
  clearTimeout(state.limitTimer);
  if (state.meterFrame) cancelAnimationFrame(state.meterFrame);
  state.stream?.getTracks().forEach((track) => track.stop());
  state.stream = null;
  state.meterContext?.close().catch(() => {});
  state.meterContext = null;
}

function startMeter(state, panel) {
  const Context = studioWindow.AudioContext || studioWindow.webkitAudioContext;
  const bar = panel.querySelector(".recorder-meter span");
  if (!Context || !bar) return;
  try {
    state.meterContext = new Context();
    const analyser = state.meterContext.createAnalyser();
    analyser.fftSize = 512;
    state.meterContext.createMediaStreamSource(state.stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const value of data) peak = Math.max(peak, Math.abs(value - 128) / 128);
      bar.style.width = `${Math.min(100, Math.round(peak * 140))}%`;
      state.meterFrame = requestAnimationFrame(tick);
    };
    tick();
  } catch (_) {
    // The level meter is optional.
  }
}

async function startRecording(refKey) {
  const panel = recorderPanel(refKey);
  if (!panel) return;
  const media = studioWindow.navigator?.mediaDevices;
  if (!media?.getUserMedia || typeof studioWindow.MediaRecorder === "undefined") {
    const message = micErrorMessage({ name: "Unsupported" });
    setRecorderStatus(refKey, message, "error");
    notify(message, "err");
    return;
  }
  const previous = recorders.get(refKey);
  cleanupRecorderStream(previous);
  clearPlayer(`rec-${refKey}`);
  panel.querySelector(".recorder-review").hidden = true;
  setRecorderStatus(refKey, "Mikrofon engedélyezése…");
  let stream;
  try {
    stream = await media.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: true },
    });
  } catch (error) {
    const message = micErrorMessage(error);
    setRecorderStatus(refKey, message, "error");
    notify(message, "err");
    return;
  }
  const state = { stream, chunks: [], startedAt: Date.now(), cancelled: false };
  recorders.set(refKey, state);
  try {
    state.mediaRecorder = new studioWindow.MediaRecorder(stream);
  } catch (error) {
    cleanupRecorderStream(state);
    setRecorderStatus(refKey, micErrorMessage(error), "error");
    return;
  }
  state.mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data?.size) state.chunks.push(event.data);
  });
  state.mediaRecorder.addEventListener("stop", () => finishRecording(refKey, state));
  state.mediaRecorder.start();
  startMeter(state, panel);
  const timerEl = panel.querySelector(".recorder-timer");
  state.timer = setInterval(() => {
    const elapsed = (Date.now() - state.startedAt) / 1000;
    if (timerEl) timerEl.textContent = `${formatSeconds(elapsed)} / ${formatSeconds(MAX_RECORDING_SECONDS)}`;
  }, 250);
  state.limitTimer = setTimeout(() => {
    if (state.mediaRecorder?.state === "recording") {
      setRecorderStatus(refKey, `Elérted a ${MAX_RECORDING_SECONDS} másodperces határt, a felvétel leállt.`);
      state.mediaRecorder.stop();
    }
  }, MAX_RECORDING_SECONDS * 1000);
  panel.querySelector("[data-rec-action=start]").hidden = true;
  const stop = panel.querySelector("[data-rec-action=stop]");
  stop.hidden = false;
  stop.focus();
  panel.classList.add("is-recording");
  setRecorderStatus(refKey, "Felvétel folyamatban… Kattints a Leállítás gombra, ha befejezted.");
}

function stopRecording(refKey) {
  const state = recorders.get(refKey);
  if (state?.mediaRecorder?.state === "recording") state.mediaRecorder.stop();
}

async function decodeRecording(blob) {
  const Context = studioWindow.AudioContext || studioWindow.webkitAudioContext;
  if (!Context) throw new Error("A böngésző nem tudja feldolgozni a felvételt.");
  let context;
  try {
    context = new Context({ sampleRate: RECORDING_SAMPLE_RATE });
  } catch (_) {
    context = new Context();
  }
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const channels = [];
    for (let i = 0; i < decoded.numberOfChannels; i += 1) channels.push(decoded.getChannelData(i));
    const mono = mixToMono(channels);
    const limit = decoded.sampleRate * MAX_RECORDING_SECONDS;
    return { samples: mono.length > limit ? mono.slice(0, limit) : mono, sampleRate: decoded.sampleRate };
  } finally {
    context.close().catch(() => {});
  }
}

async function finishRecording(refKey, state) {
  cleanupRecorderStream(state);
  const panel = recorderPanel(refKey);
  if (state.cancelled || !panel || recorders.get(refKey) !== state) return;
  panel.classList.remove("is-recording");
  panel.querySelector("[data-rec-action=stop]").hidden = true;
  const start = panel.querySelector("[data-rec-action=start]");
  start.hidden = false;
  start.querySelector("span:last-child").textContent = "Új felvétel";
  const meter = panel.querySelector(".recorder-meter span");
  if (meter) meter.style.width = "0";
  setRecorderStatus(refKey, "A felvétel feldolgozása…");
  try {
    const blob = new Blob(state.chunks, { type: state.mediaRecorder.mimeType || "audio/webm" });
    const { samples, sampleRate } = await decodeRecording(blob);
    if (!samples.length) throw new Error("A felvétel üres.");
    state.samples = samples;
    state.sampleRate = sampleRate;
    const duration = samples.length / sampleRate;
    const bounds = detectSilenceBounds(samples, sampleRate);
    ["start", "end"].forEach((edge) => {
      const input = panel.querySelector(`[data-trim=${edge}]`);
      input.max = String(Math.round(duration * 100) / 100);
      input.value = String(bounds[edge]);
      input.setAttribute("aria-label", edge === "start" ? "Felvétel kezdete (levágás)" : "Felvétel vége (levágás)");
    });
    panel.querySelector(".recorder-review").hidden = false;
    updateTrim(refKey, { autoplay: false });
    setRecorderStatus(refKey, `Kész: ${formatDecimalSeconds(duration)} felvétel. A csendes elejét és végét automatikusan levágtuk – a csúszkákkal módosíthatod.`, "ok");
    panel.querySelector("[data-player-action=toggle]")?.focus();
  } catch (error) {
    setRecorderStatus(refKey, `A felvétel nem dolgozható fel: ${error.message || error}`, "error");
  }
}

function trimmedRecording(refKey) {
  const state = recorders.get(refKey);
  const panel = recorderPanel(refKey);
  if (!state?.samples || !panel) return null;
  const start = Number(panel.querySelector("[data-trim=start]").value);
  const end = Number(panel.querySelector("[data-trim=end]").value);
  return { samples: trimSamples(state.samples, state.sampleRate, start, end), sampleRate: state.sampleRate, start, end };
}

function updateTrimLabels(refKey, changed) {
  const panel = recorderPanel(refKey);
  if (!panel) return null;
  const startInput = panel.querySelector("[data-trim=start]");
  const endInput = panel.querySelector("[data-trim=end]");
  const minimumGap = 0.5;
  if (Number(endInput.value) - Number(startInput.value) < minimumGap) {
    if (changed === "start") startInput.value = String(Math.max(0, Number(endInput.value) - minimumGap));
    else endInput.value = String(Math.min(Number(endInput.max), Number(startInput.value) + minimumGap));
  }
  panel.querySelector("[data-trim-out=start]").textContent = formatDecimalSeconds(startInput.value);
  panel.querySelector("[data-trim-out=end]").textContent = formatDecimalSeconds(endInput.value);
  startInput.setAttribute("aria-valuetext", formatDecimalSeconds(startInput.value));
  endInput.setAttribute("aria-valuetext", formatDecimalSeconds(endInput.value));
  const length = Number(endInput.value) - Number(startInput.value);
  const info = panel.querySelector(".trim-info");
  info.textContent = `Feltöltendő hossz: ${formatDecimalSeconds(length)}${length < 3 ? " – legalább 3 másodperc ajánlott." : length > 12 ? " – 3–10 másodperc az ideális." : ""}`;
  info.classList.toggle("is-warning", length < 3 || length > 12);
  return length;
}

function updateTrim(refKey, { autoplay = false, changed = "end" } = {}) {
  updateTrimLabels(refKey, changed);
  const trimmed = trimmedRecording(refKey);
  if (!trimmed) return;
  const blob = new Blob([encodeWav(trimmed.samples, trimmed.sampleRate)], { type: "audio/wav" });
  loadIntoPlayer(`rec-${refKey}`, URL.createObjectURL(blob), { autoplay });
}

async function uploadRecording(refKey, button) {
  const trimmed = trimmedRecording(refKey);
  if (!trimmed?.samples.length) {
    notify("Nincs feltölthető felvétel.", "err");
    return;
  }
  if (!refTextField(refKey)?.value.trim()) {
    const ok = await confirmAction("Az átirat üres. Feltöltés után a beszédfelismerő kitölti, de a saját, pontos átirat megbízhatóbb. Feltöltöd átirat nélkül?", { confirmLabel: "Feltöltés átirat nélkül" });
    if (!ok) {
      refTextField(refKey)?.focus();
      return;
    }
  }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const file = new File([encodeWav(trimmed.samples, trimmed.sampleRate)], `mikrofon-felvetel-${stamp}.wav`, { type: "audio/wav" });
  try {
    await withBusy(button, "Feltöltés…", () => uploadReferenceFile(refKey, file));
    notify("A felvett referenciahang és az átirat mentve.", "ok");
    closeRecorder(refKey);
  } catch (error) {
    showError("A feltöltés sikertelen", error);
  }
}

function initRecorderEvents(root) {
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-rec-action]");
    if (!button) return;
    const panel = button.closest(".recorder");
    const refKey = panel?.dataset.ref;
    if (!refKey) return;
    const action = button.dataset.recAction;
    if (action === "start") startRecording(refKey);
    else if (action === "stop") stopRecording(refKey);
    else if (action === "close") closeRecorder(refKey);
    else if (action === "discard") {
      clearPlayer(`rec-${refKey}`);
      recorders.delete(refKey);
      panel.querySelector(".recorder-review").hidden = true;
      setRecorderStatus(refKey, "A felvételt elvetettük.");
      panel.querySelector("[data-rec-action=start]")?.focus();
    } else if (action === "upload") uploadRecording(refKey, button);
    else if (action === "insert-sample") {
      const field = refTextField(refKey);
      if (field) {
        field.value = currentPreviewText().trim();
        setRecorderStatus(refKey, "A próbaszöveg bekerült az átiratba. Most olvasd fel pontosan ezt.");
      }
    }
  });
  root.addEventListener("input", (event) => {
    const input = event.target.closest?.("[data-trim]");
    if (!input) return;
    updateTrimLabels(input.closest(".recorder").dataset.ref, input.dataset.trim);
  });
  root.addEventListener("change", (event) => {
    const input = event.target.closest?.("[data-trim]");
    if (!input) return;
    updateTrim(input.closest(".recorder").dataset.ref, { autoplay: true, changed: input.dataset.trim });
  });
}

// ── Character list ──────────────────────────────────────────────────────────

const selectedCharacters = new Set();
const expandedCards = new Set();
let characterSort = "lines";
let lastFilterActive = false;

function characterCardHtml(character) {
  const id = character.id;
  const voice = parseInstruct(character.instruct);
  const initial = String(character.name || "?").charAt(0).toUpperCase();
  const lines = Number(character.line_count ?? character.frequency) || 0;
  const expanded = expandedCards.has(Number(id));
  const source = voiceSourceOf(character, voiceProfiles);
  return `<article class="character-card voice-character${expanded ? " is-open" : ""}" id="card-${id}" data-char="${id}" aria-labelledby="char-name-${id}">
    <div class="voice-character-head">
      <label class="char-select">
        <input type="checkbox" data-select-char="${id}"${selectedCharacters.has(Number(id)) ? " checked" : ""}>
        <span class="sr-only">${esc(character.name)} kijelölése</span>
      </label>
      <span class="char-avatar" style="background:${esc(character.color_hex || "#d8b4fe")};color:#1a1a2e" aria-hidden="true">${esc(initial)}</span>
      <div class="character-summary-text">
        <h3 class="char-title" id="char-name-${id}">${esc(character.name)}</h3>
        <p class="voice-summary" id="sum-${id}">${esc(summarizeInstruct(character.instruct))}</p>
        <p class="char-meta">
          <span id="src-${id}">${sourceBadgeHtml(source)}</span>
          <span class="line-count"><strong class="num">${lines}</strong> megszólalás</span>
        </p>
      </div>
      <div class="voice-character-actions">
        <button type="button" class="btn btn-sm btn-primary" data-action="preview">${icon("play")}<span>Meghallgatás</span></button>
        <button type="button" class="btn btn-sm btn-ghost settings-toggle" data-action="toggle" aria-expanded="${expanded}" aria-controls="body-${id}">
          <span>Beállítások</span><span class="toggle-caret" aria-hidden="true">▾</span>
        </button>
      </div>
    </div>
    ${miniPlayerHtml(`char-${id}`, `${character.name} próbahangja`)}
    <div class="char-details voice-character-body" id="body-${id}"${expanded ? "" : " hidden"}>
      ${profileControls(id, character.name)}
      ${referenceSectionHtml(character)}
      <details class="technical-panel">
        <summary>Hang finomhangolása</summary>
        ${presetSelect(`pv-${id}`, character.instruct, `${character.name} beépített hangja`)}
        <div class="voice-controls">
          ${buildSelect(GENDERS, voice.gender, `g-${id}`, `${character.name} hang neme`)}
          ${buildSelect(AGES, voice.age, `a-${id}`, `${character.name} életkora`)}
          ${buildSelect(PITCHES, voice.pitch, `p-${id}`, `${character.name} hangmagassága`)}
          ${buildSelect(ACCENTS, voice.accent, `ac-${id}`, `${character.name} akcentusa`)}
        </div>
        <details class="tech-disclosure">
          <summary>Technikai leírás</summary>
          <code class="instruct-preview" id="ins-${id}">${esc(character.instruct)}</code>
        </details>
        <div class="char-card-footer">
          <button class="btn btn-sm btn-ghost" type="button" data-action="download">${icon("download")}<span>Próba mentése</span></button>
          <button class="btn btn-sm btn-primary" type="button" data-action="save">Mentés</button>
        </div>
      </details>
    </div>
  </article>`;
}

function renderCharacters(characters, filterActive = lastFilterActive) {
  lastFilterActive = filterActive;
  const query = document.getElementById("character-search")?.value || "";
  const visible = sortCharacters(filterCharacters(characters, query), characterSort);
  const count = document.getElementById("char-count");
  if (count) {
    count.textContent = query.trim()
      ? `(${visible.length}/${characters.length})`
      : filterActive ? `(${characters.length} ebben a fejezetben)` : `(${characters.length})`;
  }
  renderSourceSummary(characters);
  const list = document.getElementById("char-list");
  if (!list) return;
  if (!visible.length) {
    list.innerHTML = `<div class="voice-empty">${query.trim() ? "Nincs ilyen nevű szereplő." : "Nem található szereplő."}</div>`;
    syncBulkBar();
    return;
  }

  list.innerHTML = visible.map(characterCardHtml).join("");
  list.querySelectorAll(".recorder").forEach((panel) => { panel.dataset.ref = panel.closest("[data-char]").dataset.char; });

  visible.forEach((character) => {
    ["g", "a", "p", "ac", "pv"].forEach((prefix) => {
      document.getElementById(`${prefix}-${character.id}`)?.addEventListener(
        "change", () => updateInstructPreview(character.id),
      );
    });
    updateInstructPreview(character.id);
  });
  syncPlayerUI();
  syncBulkBar();
}

function renderSourceSummary(characters) {
  const element = document.getElementById("voice-source-summary");
  if (!element) return;
  const counts = { auto: 0, reference: 0, profile: 0 };
  characters.forEach((character) => { counts[voiceSourceOf(character, voiceProfiles).kind] += 1; });
  element.textContent = characters.length
    ? `Automatikus hang: ${counts.auto} · Saját referencia: ${counts.reference} · Mentett profil: ${counts.profile}`
    : "";
}

function refreshCardSource(charId) {
  const character = characterById(charId);
  const badge = document.getElementById(`src-${charId}`);
  if (character && badge) badge.innerHTML = sourceBadgeHtml(voiceSourceOf(character, voiceProfiles));
  renderSourceSummary(loadedCharacters);
}

function refreshAllSourceBadges() {
  loadedCharacters.forEach((character) => {
    const badge = document.getElementById(`src-${character.id}`);
    if (badge) badge.innerHTML = sourceBadgeHtml(voiceSourceOf(character, voiceProfiles));
  });
  renderSourceSummary(loadedCharacters);
  syncNarratorBadge();
}

function toggleCard(charId, button) {
  const body = document.getElementById(`body-${charId}`);
  if (!body) return;
  const open = body.hidden;
  body.hidden = !open;
  button?.setAttribute("aria-expanded", String(open));
  document.getElementById(`card-${charId}`)?.classList.toggle("is-open", open);
  if (open) expandedCards.add(Number(charId));
  else expandedCards.delete(Number(charId));
}

function visibleCharacterIds() {
  return [...document.querySelectorAll("#char-list [data-select-char]")].map((input) => Number(input.dataset.selectChar));
}

function syncBulkBar() {
  const count = document.getElementById("bulk-count");
  const apply = document.getElementById("bulk-apply");
  const profile = document.getElementById("bulk-profile");
  const selectAll = document.getElementById("select-all-characters");
  const known = new Set(loadedCharacters.map((character) => Number(character.id)));
  [...selectedCharacters].forEach((id) => { if (!known.has(id)) selectedCharacters.delete(id); });
  const n = selectedCharacters.size;
  if (count) count.textContent = n ? `${n} szereplő kijelölve` : "Nincs kijelölt szereplő";
  if (apply) apply.disabled = !n || !Number(profile?.value);
  document.getElementById("bulk-bar")?.classList.toggle("has-selection", n > 0);
  if (selectAll) {
    const ids = visibleCharacterIds();
    const selectedVisible = ids.filter((id) => selectedCharacters.has(id)).length;
    selectAll.checked = Boolean(ids.length) && selectedVisible === ids.length;
    selectAll.indeterminate = selectedVisible > 0 && selectedVisible < ids.length;
  }
}

async function bulkApplyProfile(button) {
  const profileId = Number(document.getElementById("bulk-profile")?.value);
  const profile = voiceProfiles.find((item) => Number(item.id) === profileId);
  const ids = [...selectedCharacters];
  if (!profile || !ids.length) {
    notify("Jelölj ki szereplőket, és válassz egy mentett hangprofilt.", "err");
    return;
  }
  const ok = await confirmAction(
    `A(z) „${profile.name}” hangprofilt ${ids.length} szereplőre alkalmazod. Az érintett mondatok újragenerálódnak. Folytatod?`,
    { confirmLabel: "Alkalmazás" },
  );
  if (!ok) return;
  await withBusy(button, "Alkalmazás…", async () => {
    const failed = [];
    for (const id of ids) {
      try {
        await postJson(`/api/voice-profiles/${profileId}/apply`, targetPayload(BOOK_ID, id));
        bumpRefVersion(String(id));
      } catch (error) {
        failed.push(`${characterById(id)?.name || id}: ${error.message}`);
      }
    }
    selectedCharacters.clear();
    await loadCharacters();
    if (failed.length) notify(`Néhány szereplőnél nem sikerült: ${failed.join("; ")}`, "err");
    else notify(`A(z) „${profile.name}” profil ${ids.length} szereplőre alkalmazva.`, "ok");
  });
}

// Reload once the background character analysis finishes (server events),
// with a slow fallback check instead of a tight polling loop.
let analysisWatch = null;
function waitForCharacterAnalysis() {
  if (analysisWatch) return;
  const reload = () => {
    if (!analysisWatch) return;
    clearTimeout(analysisWatch.timer);
    if (analysisWatch.off) analysisWatch.off();
    analysisWatch = null;
    loadCharacters();
  };
  const off = studioWindow.Auris?.onEvent?.("jobs", (data) => {
    if ((data.finished || []).some((job) => job.book_id === BOOK_ID)) reload();
  }) || null;
  analysisWatch = { off, timer: setTimeout(reload, off ? 10000 : 1500) };
}

async function loadCharacters() {
  const chapterFilter = document.getElementById("chapter-character-filter");
  const filterActive = Boolean(chapterFilter?.checked && CURRENT_CHAPTER_ID);
  const query = filterActive ? `?chapter_id=${CURRENT_CHAPTER_ID}` : "";
  try {
    loadedCharacters = await requestJson(`/api/books/${BOOK_ID}/characters${query}`);
    if (!loadedCharacters.length) {
      const analysis = await requestJson(`/api/books/${BOOK_ID}/character-analysis`);
      const active = analysis.status === "queued" || analysis.status === "running";
      const list = document.getElementById("char-list");
      if (list) list.innerHTML = `<div class="voice-empty">${esc(analysis.message || "Nem található szereplő.")}</div>`;
      renderSourceSummary([]);
      syncBulkBar();
      if (active) waitForCharacterAnalysis();
      return;
    }
    renderCharacters(loadedCharacters, filterActive);
  } catch (error) {
    const list = document.getElementById("char-list");
    if (list) list.innerHTML = `<div class="voice-empty status-error">${esc(error.message)}</div>`;
  }
}

// ── Saving ──────────────────────────────────────────────────────────────────

async function saveChar(charId, { quiet = false } = {}) {
  try {
    const instruct = updateInstructPreview(charId);
    const gender = document.getElementById(`g-${charId}`)?.value || "female";
    const refText = document.getElementById(`ref-text-${charId}`)?.value.trim() || "";
    await requestJson(`/api/books/${BOOK_ID}/characters/${charId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruct, gender, ref_text: refText }),
    });
    const character = characterById(charId);
    if (character) {
      character.instruct = instruct;
      character.gender = gender;
      character.ref_text = refText;
    }
    refreshCardSource(charId);
    flashSaved(document.getElementById(`sum-${charId}`));
    if (!quiet) notify(`${character?.name || "A szereplő"} hangja mentve.`, "ok");
    return true;
  } catch (error) {
    showError("A mentés sikertelen", error);
    return false;
  }
}

async function saveNarrator({ quiet = false } = {}) {
  try {
    const instruct = updateNarratorPreview();
    const refText = document.getElementById("narrator-ref-text")?.value.trim() || "";
    const data = await requestJson(`/api/books/${BOOK_ID}/narrator`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruct, single_narrator_mode: singleNarratorMode, ref_text: refText }),
    });
    narratorInstruct = data.instruct || instruct;
    singleNarratorMode = Boolean(data.single_narrator_mode);
    syncSingleNarratorUI();
    syncNarratorBadge();
    flashSaved(document.getElementById("narrator-voice-summary"));
    if (!quiet) notify("A narrátor beállításai mentve.", "ok");
    return true;
  } catch (error) {
    showError("A narrátor mentése sikertelen", error);
    return false;
  }
}

async function saveCurrentAsProfile(charId) {
  const suffix = charId === null ? "narrator" : String(charId);
  const input = document.getElementById(`profile-name-${suffix}`);
  try {
    const profile = await saveVoiceProfile({
      bookId: BOOK_ID,
      charId,
      name: input?.value,
      saveCurrent: () => (charId === null ? saveNarrator({ quiet: true }) : saveChar(charId, { quiet: true })),
    });
    if (input) input.value = "";
    await loadProfiles(profile.id);
    notify(`A(z) „${profile.name}” hangprofil mentve.`, "ok");
  } catch (error) {
    showError("A hangprofil mentése sikertelen", error);
    if (!String(input?.value || "").trim()) input?.focus();
  }
}

async function refreshNarrator() {
  const data = await requestJson(`/api/books/${BOOK_ID}/narrator`);
  narratorInstruct = data.instruct || "";
  singleNarratorMode = Boolean(data.single_narrator_mode);
  narratorHasRefAudio = Boolean(data.ref_audio_name);
  narratorRefAudioName = data.ref_audio_name || "Korábban feltöltött WAV";
  const text = document.getElementById("narrator-ref-text");
  if (text) text.value = data.ref_text || "";
  setNarratorControls(narratorInstruct);
  syncSingleNarratorUI();
  syncNarratorRefUI();
}

async function applyProfileTo(profileId, charId) {
  await postJson(`/api/voice-profiles/${profileId}/apply`, targetPayload(BOOK_ID, charId));
  bumpRefVersion(charId === null ? "narrator" : String(charId));
  if (charId === null) await refreshNarrator();
  else await loadCharacters();
}

async function applySelectedProfile(charId) {
  const suffix = charId === null ? "narrator" : String(charId);
  const select = document.getElementById(`profile-${suffix}`);
  const profileId = Number(select?.value);
  if (!profileId) {
    notify("Előbb válassz mentett hangprofilt.", "err");
    select?.focus();
    return;
  }
  try {
    await applyProfileTo(profileId, charId);
    notify("A hangprofil alkalmazva. Az érintett hangok újragenerálódnak.", "ok");
  } catch (error) {
    showError("A hangprofil alkalmazása sikertelen", error);
  }
}

async function deleteSelectedProfile(charId) {
  const suffix = charId === null ? "narrator" : String(charId);
  const select = document.getElementById(`profile-${suffix}`);
  const profileId = Number(select?.value);
  if (!profileId) {
    notify("Előbb válassz törlendő hangprofilt.", "err");
    select?.focus();
    return;
  }
  const profile = voiceProfiles.find((item) => Number(item.id) === profileId);
  const ok = await confirmAction(
    `Biztosan törlöd a(z) „${profile?.name || "kijelölt"}” mentett hangprofilt? A már beállított hangokat nem érinti.`,
    { confirmLabel: "Profil törlése", danger: true },
  );
  if (!ok) return;
  try {
    await requestJson(`/api/voice-profiles/${profileId}`, { method: "DELETE" });
    await loadProfiles();
    notify("A hangprofil törölve.", "ok");
  } catch (error) {
    showError("A hangprofil törlése sikertelen", error);
  }
}

function exportSelectedProfile() {
  const select = document.getElementById("profile-narrator");
  const profileId = Number(select?.value);
  if (!profileId) {
    notify("Előbb válassz egy mentett hangprofilt.", "err");
    select?.focus();
    return;
  }
  window.location.href = `/api/voice-profiles/${profileId}/export`;
}

async function importVoiceProfile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const imported = await requestJson("/api/voice-profiles/import", {
      method: "POST",
      body: form,
    });
    await loadProfiles(imported.id);
    notify(`A(z) „${imported.name}” hangprofil importálva.`, "ok");
  } catch (error) {
    showError("A hangprofil importálása sikertelen", error);
  } finally {
    event.target.value = "";
  }
}

// ── Compare drawer ──────────────────────────────────────────────────────────

const compareState = { charId: null, profiles: [], includeCurrent: true, opener: null };

function compareTargetName() {
  return compareState.charId === null ? "Narrátor" : characterById(compareState.charId)?.name || "Szereplő";
}

function openCompare(charId, opener) {
  const dialog = document.getElementById("compare-drawer");
  if (!dialog || typeof dialog.showModal !== "function") return;
  compareState.charId = charId;
  compareState.opener = opener || null;
  compareState.includeCurrent = true;
  const preselected = Number(document.getElementById(`profile-${charId === null ? "narrator" : charId}`)?.value);
  compareState.profiles = preselected ? [preselected] : voiceProfiles.slice(0, Math.min(2, MAX_COMPARE_PROFILES)).map((p) => Number(p.id));
  document.getElementById("compare-target").textContent = `Kinek: ${compareTargetName()}. Minden hang ugyanazt a mondatot olvassa fel, így könnyű összevetni őket.`;
  document.getElementById("compare-text").value = currentPreviewText();
  renderCompareOptions();
  renderCompareGrid();
  dialog.showModal();
  document.getElementById("compare-close")?.focus();
}

function closeCompare() {
  document.getElementById("compare-drawer")?.close();
}

function renderCompareOptions() {
  const box = document.getElementById("compare-options");
  if (!box) return;
  const full = compareState.profiles.length >= MAX_COMPARE_PROFILES;
  const current = `<label class="compare-option"><input type="checkbox" data-compare-current${compareState.includeCurrent ? " checked" : ""}> <span>Jelenlegi hang (${esc(compareTargetName())})</span></label>`;
  const profiles = voiceProfiles.map((profile) => {
    const checked = compareState.profiles.includes(Number(profile.id));
    return `<label class="compare-option${!checked && full ? " is-disabled" : ""}"><input type="checkbox" data-compare-profile="${profile.id}"${checked ? " checked" : ""}${!checked && full ? " disabled" : ""}> <span>${esc(profile.name)}</span></label>`;
  }).join("");
  box.innerHTML = current + (profiles || `<p class="studio-note">Még nincs mentett hangprofil. A „Jelenlegi hang mentése” gombbal hozhatsz létre egyet.</p>`);
  const status = document.getElementById("compare-status");
  if (status) {
    status.textContent = `${compareState.profiles.length} / ${MAX_COMPARE_PROFILES} profil kiválasztva${full ? " – a maximumot elérted." : "."}`;
  }
}

function compareCandidates() {
  const list = [];
  if (compareState.includeCurrent) {
    const instruct = compareState.charId === null ? getNarratorInstruct() : updateInstructPreview(compareState.charId);
    list.push({ id: "current", name: "Jelenlegi hang", summary: summarizeInstruct(instruct), profile: null });
  }
  compareState.profiles.forEach((id) => {
    const profile = voiceProfiles.find((item) => Number(item.id) === id);
    if (profile) {
      list.push({
        id: String(profile.id),
        name: profile.name,
        summary: `${summarizeInstruct(profile.instruct)}${profile.ref_audio_path ? " · referenciahanggal" : ""}`,
        profile,
      });
    }
  });
  return list;
}

function renderCompareGrid() {
  const grid = document.getElementById("compare-grid");
  if (!grid) return;
  const candidates = compareCandidates();
  if (!candidates.length) {
    grid.innerHTML = `<p class="voice-empty">Válassz legalább egy hangot az összehasonlításhoz.</p>`;
    return;
  }
  grid.innerHTML = candidates.map((candidate) => `<article class="compare-card" data-compare-id="${esc(candidate.id)}" aria-labelledby="cmp-title-${esc(candidate.id)}">
      <h3 id="cmp-title-${esc(candidate.id)}">${esc(candidate.name)}</h3>
      <p class="voice-summary">${esc(candidate.summary)}</p>
      <button type="button" class="btn btn-sm btn-primary" data-compare-action="play">${icon("play")}<span>Lejátszás</span></button>
      ${miniPlayerHtml(`cmp-${candidate.id}`, `${candidate.name} próbahangja`)}
      ${candidate.profile
    ? `<button type="button" class="btn btn-sm btn-ghost" data-compare-action="choose">${icon("check")}<span>Ezt választom</span></button>`
    : `<p class="studio-note">Ez a most beállított hang.</p>`}
    </article>`).join("");
  syncPlayerUI();
}

function compareRequest(candidateId) {
  const text = document.getElementById("compare-text")?.value.trim() || currentPreviewText();
  if (candidateId === "current") {
    if (compareState.charId === null) return narratorPreviewRequest(text);
    const request = charPreviewRequest(compareState.charId);
    request.payload = { ...request.payload, text: previewPayload("", "", text).text };
    return request;
  }
  return {
    endpoint: `/api/voice-profiles/${candidateId}/preview`,
    payload: { text: previewPayload("", "", text).text },
    version: 0,
    downloadName: `profil-${candidateId}-proba`,
  };
}

async function chooseCompared(candidateId, button) {
  const profileId = Number(candidateId);
  const profile = voiceProfiles.find((item) => Number(item.id) === profileId);
  try {
    await withBusy(button, "Alkalmazás…", () => applyProfileTo(profileId, compareState.charId));
    closeCompare();
    notify(`A(z) „${profile?.name || "kiválasztott"}” hang beállítva: ${compareTargetName()}. Az érintett mondatok újragenerálódnak.`, "ok");
  } catch (error) {
    showError("A hangprofil alkalmazása sikertelen", error);
  }
}

function initCompare() {
  const dialog = document.getElementById("compare-drawer");
  if (!dialog) return;
  dialog.addEventListener("close", () => {
    stopPlayer();
    const charId = compareState.charId;
    const opener = compareState.opener?.isConnected
      ? compareState.opener
      : charId === null
        ? document.getElementById("narrator-compare-btn")
        : document.querySelector(`#card-${charId} [data-action=compare]`) || document.querySelector(`#card-${charId} [data-action=toggle]`);
    opener?.focus();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeCompare();
    const action = event.target.closest("[data-compare-action]");
    if (!action) return;
    const candidateId = action.closest("[data-compare-id]")?.dataset.compareId;
    if (action.dataset.compareAction === "play") {
      runPreview({ key: `cmp-${candidateId}`, button: action, ...compareRequest(candidateId) });
    } else if (action.dataset.compareAction === "choose") {
      chooseCompared(candidateId, action);
    }
  });
  dialog.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches("[data-compare-current]")) compareState.includeCurrent = input.checked;
    else if (input.matches("[data-compare-profile]")) {
      compareState.profiles = toggleLimited(compareState.profiles, Number(input.dataset.compareProfile), MAX_COMPARE_PROFILES);
    } else return;
    const focusKey = input.dataset.compareProfile || "current";
    renderCompareOptions();
    renderCompareGrid();
    const selector = focusKey === "current" ? "[data-compare-current]" : `[data-compare-profile="${focusKey}"]`;
    dialog.querySelector(selector)?.focus();
  });
  document.getElementById("compare-close")?.addEventListener("click", closeCompare);
}

// ── Event wiring ────────────────────────────────────────────────────────────

function initCharacterListEvents() {
  const list = document.getElementById("char-list");
  if (!list) return;
  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || button.getAttribute("aria-disabled") === "true") return;
    const card = button.closest("[data-char]");
    if (!card) return;
    const charId = Number(card.dataset.char);
    const action = button.dataset.action;
    if (action === "preview") previewChar(charId, button);
    else if (action === "toggle") toggleCard(charId, button);
    else if (action === "download") downloadChar(charId, button);
    else if (action === "save") withBusy(button, "Mentés…", () => saveChar(charId));
    else if (action === "apply-profile") withBusy(button, "Alkalmazás…", () => applySelectedProfile(charId));
    else if (action === "delete-profile") deleteSelectedProfile(charId);
    else if (action === "save-profile") withBusy(button, "Mentés…", () => saveCurrentAsProfile(charId));
    else if (action === "compare") openCompare(charId, button);
    else if (action === "play-ref") playReference(String(charId), button);
    else if (action === "record") toggleRecorder(String(charId), button);
    else if (action === "remove-ref") removeRef(charId);
    else handleReferenceCheckAction(String(charId), button);
  });
  list.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches("[data-select-char]")) {
      const id = Number(input.dataset.selectChar);
      if (input.checked) selectedCharacters.add(id);
      else selectedCharacters.delete(id);
      syncBulkBar();
      return;
    }
    const card = input.closest("[data-char]");
    if (!card) return;
    if (input.dataset.fileAction === "ref-text") loadRefText(event, card.dataset.char);
    else if (input.dataset.fileAction === "ref-audio") uploadRef(event, card.dataset.char);
  });
  initRecorderEvents(list);
}

function initNarratorEvents() {
  const narrator = document.getElementById("narrator-section");
  document.getElementById("narrator-preview-btn")?.addEventListener("click", (event) => previewNarrator(event.currentTarget, "narrator"));
  document.getElementById("sample-play-btn")?.addEventListener("click", (event) => previewNarrator(event.currentTarget, "sample"));
  document.getElementById("narrator-download-btn")?.addEventListener("click", (event) => downloadNarrator(event.currentTarget));
  document.getElementById("narrator-compare-btn")?.addEventListener("click", (event) => openCompare(null, event.currentTarget));
  document.getElementById("narrator-ref-play")?.addEventListener("click", (event) => playReference("narrator", event.currentTarget));
  document.getElementById("narrator-record-btn")?.addEventListener("click", (event) => toggleRecorder("narrator", event.currentTarget));
  document.getElementById("narrator-save-btn")?.addEventListener("click", (event) => withBusy(event.currentTarget, "Mentés…", () => saveNarrator()));
  narrator?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (button && narrator.querySelector("#narrator-reference-title")?.closest("section")?.contains(button)) {
      handleReferenceCheckAction("narrator", button);
    }
  });
  const recorder = document.getElementById("rec-narrator");
  if (recorder) recorder.dataset.ref = "narrator";
  if (narrator) initRecorderEvents(narrator);
}

function initToolbar() {
  const sort = document.getElementById("character-sort");
  try {
    const saved = localStorage.getItem("auris.voiceStudio.sort");
    if (saved === "name" || saved === "lines") characterSort = saved;
  } catch (_) { /* storage is optional */ }
  if (sort) {
    sort.value = characterSort;
    sort.addEventListener("change", () => {
      characterSort = sort.value === "name" ? "name" : "lines";
      try { localStorage.setItem("auris.voiceStudio.sort", characterSort); } catch (_) { /* optional */ }
      renderCharacters(loadedCharacters);
    });
  }
  document.getElementById("select-all-characters")?.addEventListener("change", (event) => {
    visibleCharacterIds().forEach((id) => {
      if (event.target.checked) selectedCharacters.add(id);
      else selectedCharacters.delete(id);
    });
    document.querySelectorAll("#char-list [data-select-char]").forEach((input) => {
      input.checked = selectedCharacters.has(Number(input.dataset.selectChar));
    });
    syncBulkBar();
  });
  document.getElementById("bulk-profile")?.addEventListener("change", syncBulkBar);
  document.getElementById("bulk-apply")?.addEventListener("click", (event) => bulkApplyProfile(event.currentTarget));
  document.getElementById("bulk-clear")?.addEventListener("click", () => {
    selectedCharacters.clear();
    document.querySelectorAll("#char-list [data-select-char]").forEach((input) => { input.checked = false; });
    syncBulkBar();
  });
}

function initializeVoiceStudio() {
  mountPlayers();
  initPlayer();
  initNarratorControls();
  initNarratorEvents();
  initCharacterListEvents();
  initCompare();
  initToolbar();
  document.getElementById("chapter-character-filter")?.addEventListener("change", loadCharacters);
  document.getElementById("character-search")?.addEventListener("input", () => {
    const active = Boolean(document.getElementById("chapter-character-filter")?.checked && CURRENT_CHAPTER_ID);
    renderCharacters(loadedCharacters, active);
  });
  applyEngineCapabilities()
    .then(() => loadProfiles())
    .then(loadCharacters)
    .catch((error) => showError("A hangprofilok betöltése sikertelen", error));
}

if (studioDocument) {
  Object.assign(studioWindow, {
    applySelectedProfile,
    deleteSelectedProfile,
    downloadChar,
    downloadNarrator,
    exportSelectedProfile,
    importVoiceProfile,
    loadNarratorRefText,
    loadRefText,
    loadCharacters,
    previewChar,
    previewNarrator,
    removeNarratorRef,
    removeRef,
    saveChar,
    saveCurrentAsProfile,
    saveNarrator,
    uploadNarratorRef,
    uploadRef,
  });
  initializeVoiceStudio();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    presetVoiceOf,
    withPresetVoice,
    buildInstruct,
    detectSilenceBounds,
    encodeWav,
    filterCharacters,
    formatSeconds,
    micErrorMessage,
    mixToMono,
    optionLabel,
    parseInstruct,
    previewPayload,
    previewSignature,
    saveVoiceProfile,
    sortCharacters,
    summarizeInstruct,
    targetPayload,
    toggleLimited,
    trimSamples,
    voiceSourceOf,
  };
}
