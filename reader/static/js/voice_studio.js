const studioWindow = typeof window === "undefined" ? {} : window;
const studioDocument = typeof document === "undefined" ? null : document;
const BOOK_ID = studioWindow.BOOK_ID;
let narratorInstruct = studioWindow.NARRATOR_INSTRUCT || "";
const DEFAULT_NARRATOR_INSTRUCT = "male, elderly, low pitch, british accent";
const CURRENT_CHAPTER_ID = studioWindow.CURRENT_CHAPTER_ID !== null
  && Number.isInteger(Number(studioWindow.CURRENT_CHAPTER_ID))
  ? Number(studioWindow.CURRENT_CHAPTER_ID)
  : null;
const HUNGARIAN_PREVIEW_TEXT =
  "Az árvíztűrő tükörfúrógép próbája tisztán és természetesen szól magyarul.";

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

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
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
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
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
  const previous = element.style.color;
  element.style.color = "#4caf80";
  setTimeout(() => { element.style.color = previous; }, 1500);
}

function showError(prefix, error) {
  alert(`${prefix}: ${error.message || error}`);
}

function updateInstructPreview(charId) {
  const originalInstruct = loadedCharacters.find(
    (character) => Number(character.id) === Number(charId),
  )?.instruct || "";
  const instruct = buildInstruct(
    document.getElementById(`g-${charId}`)?.value || "female",
    document.getElementById(`a-${charId}`)?.value || "young adult",
    document.getElementById(`p-${charId}`)?.value || "moderate pitch",
    document.getElementById(`ac-${charId}`)?.value || "",
    originalInstruct,
  );
  const element = document.getElementById(`ins-${charId}`);
  if (element) element.textContent = instruct;
  return instruct;
}

function getNarratorInstruct() {
  return buildInstruct(
    document.getElementById("narrator-gender")?.value || "male",
    document.getElementById("narrator-age")?.value || "elderly",
    document.getElementById("narrator-pitch")?.value || "low pitch",
    document.getElementById("narrator-accent")?.value || "",
    narratorInstruct,
  );
}

function updateNarratorPreview() {
  const instruct = getNarratorInstruct();
  const element = document.getElementById("narrator-instruct-preview");
  if (element) element.textContent = instruct;
  return instruct;
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

function profileOptions() {
  return `<option value="">Válassz mentett hangot…</option>${voiceProfiles.map((profile) => (
    `<option value="${profile.id}">${esc(profile.name)}</option>`
  )).join("")}`;
}

function populateProfileSelects(selectedId = null) {
  document.querySelectorAll(".voice-profile-select").forEach((select) => {
    const previous = selectedId || Number(select.value) || null;
    select.innerHTML = profileOptions();
    if (previous) select.value = String(previous);
  });
}

async function loadProfiles(selectedId = null) {
  voiceProfiles = await requestJson("/api/voice-profiles");
  populateProfileSelects(selectedId);
}

function profileControls(charId, ownerName) {
  const suffix = charId === null ? "narrator" : String(charId);
  const argument = charId === null ? "null" : String(charId);
  return `<section class="profile-controls" aria-label="${esc(ownerName)} mentett hangprofilja">
    <label for="profile-${suffix}">Mentett hangprofil</label>
    <div class="profile-apply-row">
      <select id="profile-${suffix}" class="vc-select voice-profile-select" aria-label="Mentett hangprofil ${esc(ownerName)} számára">${profileOptions()}</select>
      <button type="button" class="btn btn-sm btn-primary" onclick="applySelectedProfile(${argument})">Alkalmazás</button>
      <button type="button" class="btn btn-sm btn-ghost" onclick="deleteSelectedProfile(${argument})">Törlés</button>
    </div>
    <div class="profile-save-row">
      <label class="sr-only" for="profile-name-${suffix}">Új hangprofil neve</label>
      <input id="profile-name-${suffix}" maxlength="100" placeholder="Új hangprofil neve">
      <button type="button" class="btn btn-sm btn-ghost" onclick="saveCurrentAsProfile(${argument})">Jelenlegi hang mentése</button>
    </div>
  </section>`;
}

function renderCharacters(characters, filterActive) {
  const query = document.getElementById("character-search")?.value || "";
  const visible = filterCharacters(characters, query);
  const count = document.getElementById("char-count");
  if (count) {
    count.textContent = query.trim()
      ? `(${visible.length}/${characters.length})`
      : filterActive ? `(${characters.length} ebben a fejezetben)` : `(${characters.length})`;
  }
  const list = document.getElementById("char-list");
  if (!list) return;
  if (!visible.length) {
    list.innerHTML = `<div class="voice-empty">${query.trim() ? "Nincs ilyen nevű szereplő." : "Nem található szereplő."}</div>`;
    return;
  }

  list.innerHTML = visible.map((character) => {
    const voice = parseInstruct(character.instruct);
    const initial = String(character.name || "?").charAt(0).toUpperCase();
    const gender = optionLabel(character.gender || voice.gender);
    return `<details class="character-card voice-character" id="card-${character.id}">
      <summary class="character-summary">
        <span class="char-avatar" style="background:${esc(character.color_hex || "#d8b4fe")};color:#1a1a2e">${esc(initial)}</span>
        <span class="character-summary-text"><strong>${esc(character.name)}</strong><span>${esc(gender)} · ${Number(character.frequency) || 0} megszólalás</span></span>
        <span class="summary-action" aria-hidden="true">Beállítások</span>
      </summary>
      <div class="char-details voice-character-body">
        ${profileControls(character.id, character.name)}
        <div class="clone-section clone-prominent">
          <div id="ref-status-${character.id}" class="reference-status${character.ref_audio_path ? "" : " hidden"}">
            <span class="reference-status-label">Aktív referencia:</span>
            <span id="ref-name-${character.id}">${esc(character.ref_audio_name || "Korábban feltöltött WAV")}</span>
          </div>
          <label for="ref-text-${character.id}">Referenciahang pontos átirata</label>
          <textarea id="ref-text-${character.id}" class="reference-text" rows="3" placeholder="Pontosan azt írd ide, ami a hangfelvételen elhangzik.">${esc(character.ref_text)}</textarea>
          <div class="reference-actions">
            <label class="btn btn-sm btn-ghost file-picker"><span>Átirat betöltése TXT-ből</span><input type="file" accept=".txt,text/plain" onchange="loadRefText(event, ${character.id})"></label>
            <label class="btn btn-sm btn-primary file-picker"><span>Referencia WAV kiválasztása</span><input type="file" accept=".wav,audio/wav" onchange="uploadRef(event, ${character.id})"></label>
            <button id="remove-ref-${character.id}" class="btn btn-sm btn-ghost" type="button" onclick="removeRef(${character.id})"${character.ref_audio_path ? "" : " disabled"}>Referencia törlése</button>
          </div>
          <p class="studio-note">Tiszta, egyetlen beszélőt tartalmazó, 3–10 másodperces magyar felvétel ajánlott.</p>
        </div>
        <details class="technical-panel">
          <summary>Hang finomhangolása</summary>
          <div class="voice-controls">
            ${buildSelect(GENDERS, voice.gender, `g-${character.id}`, `${character.name} hang neme`)}
            ${buildSelect(AGES, voice.age, `a-${character.id}`, `${character.name} életkora`)}
            ${buildSelect(PITCHES, voice.pitch, `p-${character.id}`, `${character.name} hangmagassága`)}
            ${buildSelect(ACCENTS, voice.accent, `ac-${character.id}`, `${character.name} akcentusa`)}
          </div>
          <div class="char-card-footer">
            <span class="instruct-preview" id="ins-${character.id}">${esc(character.instruct)}</span>
            <button class="btn btn-sm btn-ghost" type="button" onclick="previewChar(${character.id})">▶ Magyar próba</button>
            <button class="btn btn-sm btn-ghost" type="button" onclick="downloadChar(${character.id})">↓ Próba mentése</button>
            <button class="btn btn-sm btn-primary" type="button" onclick="saveChar(${character.id})">Mentés</button>
          </div>
        </details>
      </div>
    </details>`;
  }).join("");

  visible.forEach((character) => {
    ["g", "a", "p", "ac"].forEach((prefix) => {
      document.getElementById(`${prefix}-${character.id}`)?.addEventListener(
        "change", () => updateInstructPreview(character.id),
      );
    });
    updateInstructPreview(character.id);
  });
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
      if (active) setTimeout(loadCharacters, 1500);
      return;
    }
    renderCharacters(loadedCharacters, filterActive);
  } catch (error) {
    const list = document.getElementById("char-list");
    if (list) list.innerHTML = `<div class="voice-empty status-error">${esc(error.message)}</div>`;
  }
}

async function saveChar(charId) {
  try {
    const instruct = updateInstructPreview(charId);
    const gender = document.getElementById(`g-${charId}`)?.value || "female";
    const refText = document.getElementById(`ref-text-${charId}`)?.value.trim() || "";
    await requestJson(`/api/books/${BOOK_ID}/characters/${charId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruct, gender, ref_text: refText }),
    });
    const character = loadedCharacters.find(
      (item) => Number(item.id) === Number(charId),
    );
    if (character) {
      character.instruct = instruct;
      character.gender = gender;
    }
    flashSaved(document.getElementById(`ins-${charId}`));
    return true;
  } catch (error) {
    showError("A mentés sikertelen", error);
    return false;
  }
}

async function saveNarrator() {
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
    flashSaved(document.getElementById("narrator-instruct-preview"));
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
      saveCurrent: () => charId === null ? saveNarrator() : saveChar(charId),
    });
    if (input) input.value = "";
    await loadProfiles(profile.id);
    alert("A hangprofil mentve.");
  } catch (error) {
    showError("A hangprofil mentése sikertelen", error);
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

async function applySelectedProfile(charId) {
  const suffix = charId === null ? "narrator" : String(charId);
  const profileId = Number(document.getElementById(`profile-${suffix}`)?.value);
  if (!profileId) {
    alert("Előbb válassz mentett hangprofilt.");
    return;
  }
  try {
    await requestJson(`/api/voice-profiles/${profileId}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(targetPayload(BOOK_ID, charId)),
    });
    if (charId === null) await refreshNarrator();
    else await loadCharacters();
    alert("A hangprofil alkalmazva. Az érintett hangok újragenerálódnak.");
  } catch (error) {
    showError("A hangprofil alkalmazása sikertelen", error);
  }
}

async function deleteSelectedProfile(charId) {
  const suffix = charId === null ? "narrator" : String(charId);
  const profileId = Number(document.getElementById(`profile-${suffix}`)?.value);
  if (!profileId) {
    alert("Előbb válassz törlendő hangprofilt.");
    return;
  }
  if (!confirm("Biztosan törlöd ezt a mentett hangprofilt?")) return;
  try {
    await requestJson(`/api/voice-profiles/${profileId}`, { method: "DELETE" });
    await loadProfiles();
  } catch (error) {
    showError("A hangprofil törlése sikertelen", error);
  }
}

async function previewChar(charId) {
  try {
    const payload = previewPayload(
      updateInstructPreview(charId),
      document.getElementById(`ref-text-${charId}`)?.value.trim() || "",
      currentPreviewText(),
    );
    const data = await requestJson(`/api/books/${BOOK_ID}/characters/${charId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    previewAudio.src = `${data.audio_url}?t=${Date.now()}`;
    await previewAudio.play();
  } catch (error) {
    showError("A próbahang sikertelen", error);
  }
}

function exportSelectedProfile() {
  const profileId = Number(document.getElementById("profile-narrator")?.value);
  if (!profileId) {
    alert("Előbb válassz egy mentett hangprofilt.");
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
    alert(`A(z) „${imported.name}” hangprofil importálva.`);
  } catch (error) {
    showError("A hangprofil importálása sikertelen", error);
  } finally {
    event.target.value = "";
  }
}

async function downloadChar(charId) {
  try {
    const payload = previewPayload(
      updateInstructPreview(charId),
      document.getElementById(`ref-text-${charId}`)?.value.trim() || "",
      currentPreviewText(),
    );
    const data = await requestJson(`/api/books/${BOOK_ID}/characters/${charId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const name = loadedCharacters.find((item) => Number(item.id) === Number(charId))?.name
      || `szereplo-${charId}`;
    downloadAudio(data.audio_url, `${name}-proba`);
  } catch (error) {
    showError("A próbahang mentése sikertelen", error);
  }
}

async function previewNarrator() {
  try {
    const payload = previewPayload(
      updateNarratorPreview(),
      document.getElementById("narrator-ref-text")?.value.trim() || "",
      currentPreviewText(),
    );
    const data = await requestJson(`/api/books/${BOOK_ID}/characters/narrator/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    previewAudio.src = `${data.audio_url}?t=${Date.now()}`;
    await previewAudio.play();
  } catch (error) {
    showError("A próbahang sikertelen", error);
  }
}

async function downloadNarrator() {
  try {
    const payload = previewPayload(
      updateNarratorPreview(),
      document.getElementById("narrator-ref-text")?.value.trim() || "",
      currentPreviewText(),
    );
    const data = await requestJson(`/api/books/${BOOK_ID}/characters/narrator/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    downloadAudio(data.audio_url, "narrator-proba");
  } catch (error) {
    showError("A próbahang mentése sikertelen", error);
  }
}

async function loadTextFileIntoField(event, fieldId) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const field = document.getElementById(fieldId);
    if (field) field.value = (await file.text()).replace(/^\uFEFF/, "").trim();
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

async function uploadRef(event, charId) {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("ref_text", document.getElementById(`ref-text-${charId}`)?.value.trim() || "");
  try {
    const data = await requestJson(`/api/characters/${charId}/ref-audio`, { method: "POST", body: form });
    document.getElementById(`ref-name-${charId}`).textContent = data.ref_audio_name;
    document.getElementById(`ref-status-${charId}`).classList.remove("hidden");
    document.getElementById(`remove-ref-${charId}`).disabled = false;
    alert("A referenciahang és az átirat mentve.");
  } catch (error) {
    showError("A feltöltés sikertelen", error);
  } finally {
    event.target.value = "";
  }
}

async function removeRef(charId) {
  try {
    await requestJson(`/api/characters/${charId}/ref-audio`, { method: "DELETE" });
    document.getElementById(`ref-status-${charId}`).classList.add("hidden");
    document.getElementById(`remove-ref-${charId}`).disabled = true;
    document.getElementById(`ref-text-${charId}`).value = "";
  } catch (error) {
    showError("A referencia törlése sikertelen", error);
  }
}

async function uploadNarratorRef(event) {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("ref_text", document.getElementById("narrator-ref-text")?.value.trim() || "");
  try {
    const data = await requestJson(`/api/books/${BOOK_ID}/narrator-ref-audio`, { method: "POST", body: form });
    narratorHasRefAudio = true;
    narratorRefAudioName = data.ref_audio_name;
    syncNarratorRefUI();
    alert("A narrátor referenciahangja mentve.");
  } catch (error) {
    showError("A feltöltés sikertelen", error);
  } finally {
    event.target.value = "";
  }
}

async function removeNarratorRef() {
  try {
    await requestJson(`/api/books/${BOOK_ID}/narrator-ref-audio`, { method: "DELETE" });
    narratorHasRefAudio = false;
    narratorRefAudioName = "Korábban feltöltött WAV";
    const refText = document.getElementById("narrator-ref-text");
    if (refText) refText.value = "";
    syncNarratorRefUI();
  } catch (error) {
    showError("A referencia törlése sikertelen", error);
  }
}

function initializeVoiceStudio() {
  initNarratorControls();
  document.getElementById("narrator-preview-btn")?.addEventListener("click", previewNarrator);
  document.getElementById("narrator-download-btn")?.addEventListener("click", downloadNarrator);
  document.getElementById("chapter-character-filter")?.addEventListener("change", loadCharacters);
  document.getElementById("character-search")?.addEventListener("input", () => {
    const active = Boolean(document.getElementById("chapter-character-filter")?.checked && CURRENT_CHAPTER_ID);
    renderCharacters(loadedCharacters, active);
  });
  loadProfiles().then(loadCharacters).catch((error) => showError("A hangprofilok betöltése sikertelen", error));
}

if (studioDocument) {
  Object.assign(studioWindow, {
    applySelectedProfile,
    deleteSelectedProfile,
    downloadChar,
    exportSelectedProfile,
    importVoiceProfile,
    loadNarratorRefText,
    loadRefText,
    previewChar,
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
    buildInstruct,
    filterCharacters,
    optionLabel,
    parseInstruct,
    previewPayload,
    saveVoiceProfile,
    targetPayload,
  };
}
