const BOOK_ID = window.BOOK_ID;
const NARRATOR_INSTRUCT = window.NARRATOR_INSTRUCT || "";
const DEFAULT_NARRATOR_INSTRUCT = "male, elderly, low pitch, british accent";
let singleNarratorMode = Boolean(window.SINGLE_NARRATOR_MODE);
let narratorHasRefAudio = Boolean(window.NARRATOR_HAS_REF_AUDIO);
let narratorRefAudioName = window.NARRATOR_REF_AUDIO_NAME || "Previously uploaded WAV";
const previewAudio = document.getElementById("preview-audio");

const GENDERS = ["male", "female"];
const AGES = ["child", "teenager", "young adult", "middle-aged", "elderly"];
const PITCHES = ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"];
const ACCENTS = [
  "american accent",
  "british accent",
  "australian accent",
  "canadian accent",
  "indian accent",
  "chinese accent",
  "korean accent",
  "japanese accent",
];

function buildSelect(options, selected, id) {
  return `<select class="vc-select" id="${id}">
    ${options
      .map((option) => `<option value="${option}"${option === selected ? " selected" : ""}>${option}</option>`)
      .join("")}
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
    accent: ACCENTS.find((accent) => parts.includes(accent)) || "american accent",
  };
}

function buildInstruct(gender, age, pitch, accent) {
  return [gender, age, pitch, accent].join(", ");
}

function esc(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function flashSaved(el) {
  if (!el) return;
  const prev = el.style.color;
  el.style.color = "#4caf80";
  setTimeout(() => {
    el.style.color = prev;
  }, 1500);
}

function updateInstructPreview(charId) {
  const instruct = buildInstruct(
    document.getElementById(`g-${charId}`)?.value || "female",
    document.getElementById(`a-${charId}`)?.value || "young adult",
    document.getElementById(`p-${charId}`)?.value || "moderate pitch",
    document.getElementById(`ac-${charId}`)?.value || "american accent"
  );
  const el = document.getElementById(`ins-${charId}`);
  if (el) el.textContent = instruct;
  return instruct;
}

function getNarratorInstruct() {
  return buildInstruct(
    document.getElementById("narrator-gender")?.value || "male",
    document.getElementById("narrator-age")?.value || "elderly",
    document.getElementById("narrator-pitch")?.value || "low pitch",
    document.getElementById("narrator-accent")?.value || "british accent"
  );
}

function updateNarratorPreview() {
  const instruct = getNarratorInstruct();
  const el = document.getElementById("narrator-instruct-preview");
  if (el) el.textContent = instruct;
  return instruct;
}

function syncNarratorRefUI() {
  const status = document.getElementById("narrator-ref-status");
  const name = document.getElementById("narrator-ref-name");
  const removeBtn = document.getElementById("remove-narrator-ref-btn");
  if (status) status.classList.toggle("hidden", !narratorHasRefAudio);
  if (name) name.textContent = narratorRefAudioName;
  if (removeBtn) {
    removeBtn.disabled = !narratorHasRefAudio;
    removeBtn.title = narratorHasRefAudio ? "" : "No cloned narrator voice is active.";
  }
}

function syncSingleNarratorUI() {
  const toggle = document.getElementById("single-narrator-mode");
  if (toggle) toggle.checked = singleNarratorMode;

  const note = document.getElementById("character-voice-note");
  if (!note) return;

  if (singleNarratorMode) {
    note.textContent =
      "Single narrator mode is on. Character voices can still be edited here, but playback and export will use the narrator voice for every line.";
    note.classList.remove("hidden");
  } else {
    note.textContent = "";
    note.classList.add("hidden");
  }
}

function initNarratorControls() {
  const parsed = parseInstruct(NARRATOR_INSTRUCT || DEFAULT_NARRATOR_INSTRUCT);
  const pairs = [
    ["narrator-gender", parsed.gender],
    ["narrator-age", parsed.age],
    ["narrator-pitch", parsed.pitch],
    ["narrator-accent", parsed.accent],
  ];

  pairs.forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = value;
    el.addEventListener("change", updateNarratorPreview);
  });

  const toggle = document.getElementById("single-narrator-mode");
  if (toggle) {
    toggle.checked = singleNarratorMode;
    toggle.addEventListener("change", () => {
      singleNarratorMode = toggle.checked;
      syncSingleNarratorUI();
    });
  }

  updateNarratorPreview();
  syncSingleNarratorUI();
  syncNarratorRefUI();
}

async function loadCharacters() {
  const chars = await fetch(`/api/books/${BOOK_ID}/characters`).then((r) => r.json());
  const list = document.getElementById("char-list");
  document.getElementById("char-count").textContent = `(${chars.length} detected)`;

  if (!chars.length) {
    list.innerHTML =
      '<div class="muted" style="padding:16px">No characters detected yet. Characters are detected in the background after import. Please wait or refresh.</div>';
    return;
  }

  list.innerHTML = chars
    .map((ch) => {
      const v = parseInstruct(ch.instruct);
      const avatarStyle = `background:${ch.color_hex};color:#1a1a2e`;
      const initial = ch.name.charAt(0).toUpperCase();
      const genderBadge = `<span class="char-gender gender-${ch.gender}">${ch.gender}</span>`;
      return `
      <div class="character-card" id="card-${ch.id}">
        <div class="char-avatar" style="${avatarStyle}">${initial}</div>
        <div class="char-details">
          <span class="char-name">${esc(ch.name)} ${genderBadge} <span class="char-freq">x ${ch.frequency}</span></span>
          <div class="voice-controls">
            ${buildSelect(GENDERS, v.gender, `g-${ch.id}`)}
            ${buildSelect(AGES, v.age, `a-${ch.id}`)}
            ${buildSelect(PITCHES, v.pitch, `p-${ch.id}`)}
            ${buildSelect(ACCENTS, v.accent, `ac-${ch.id}`)}
          </div>
          <div class="char-card-footer">
            <span class="instruct-preview" id="ins-${ch.id}">${esc(ch.instruct)}</span>
            <button class="btn btn-sm btn-ghost preview-btn" onclick="previewChar(${ch.id})">&#9654; Preview</button>
            <button class="btn btn-sm btn-primary" onclick="saveChar(${ch.id})">Save</button>
          </div>
          <div class="clone-section">
            <div id="ref-status-${ch.id}" class="reference-status${ch.ref_audio_path ? "" : " hidden"}">
              <span class="reference-status-label">Active reference:</span>
              <span id="ref-name-${ch.id}">${esc(ch.ref_audio_name || "Previously uploaded WAV")}</span>
            </div>
            <label for="ref-text-${ch.id}">Reference audio transcript</label>
            <textarea id="ref-text-${ch.id}" class="reference-text" rows="3" placeholder="Type exactly what is spoken in the reference audio.">${esc(ch.ref_text)}</textarea>
            <div class="reference-actions">
              <label class="btn btn-sm btn-ghost file-picker">
                <span>Load transcript TXT</span>
                <input type="file" accept=".txt,text/plain" onchange="loadRefText(event, ${ch.id})">
              </label>
            </div>
            <div class="studio-note">A matching transcript gives OmniVoice the best cloning quality. The TXT content is loaded into this field; save it or upload the audio to persist it. Empty uses Whisper auto-transcription.</div>
            <div class="reference-actions">
              <label class="btn btn-sm btn-ghost file-picker">
                <span>Choose reference WAV</span>
                <input type="file" accept=".wav,audio/wav" onchange="uploadRef(event, ${ch.id})">
              </label>
              <button id="remove-ref-${ch.id}" class="btn btn-sm btn-ghost" type="button" onclick="removeRef(${ch.id})"${ch.ref_audio_path ? "" : " disabled"}>Remove reference</button>
            </div>
            <div class="studio-note">Best results: a clean, single-speaker, 3–10 second clip in the target language.</div>
          </div>
        </div>
      </div>`;
    })
    .join("");

  chars.forEach((ch) => {
    ["g", "a", "p", "ac"].forEach((prefix) => {
      const el = document.getElementById(`${prefix}-${ch.id}`);
      if (el) {
        el.addEventListener("change", () => updateInstructPreview(ch.id));
      }
    });
    updateInstructPreview(ch.id);
  });
}

async function saveChar(charId) {
  const instruct = updateInstructPreview(charId);
  const gender = document.getElementById(`g-${charId}`)?.value || "female";
  const refText = document.getElementById(`ref-text-${charId}`)?.value.trim() || "";

  const r = await fetch(`/api/books/${BOOK_ID}/characters/${charId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruct, gender, ref_text: refText }),
  });
  const d = await r.json();
  if (d.ok) {
    flashSaved(document.getElementById(`ins-${charId}`));
  } else if (d.error) {
    alert(`Save failed: ${d.error}`);
  }
}

async function previewChar(charId) {
  const instruct = updateInstructPreview(charId);
  const refText = document.getElementById(`ref-text-${charId}`)?.value.trim() || "";
  const r = await fetch(`/api/books/${BOOK_ID}/characters/${charId}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruct, ref_text: refText }),
  });
  const d = await r.json();
  if (d.error) {
    alert(`Preview failed: ${d.error}`);
    return;
  }
  previewAudio.src = `${d.audio_url}?t=${Date.now()}`;
  await previewAudio.play();
}

async function uploadRef(event, charId) {
  const file = event.target.files[0];
  if (!file) return;

  const fd = new FormData();
  fd.append("file", file);
  fd.append("ref_text", document.getElementById(`ref-text-${charId}`)?.value.trim() || "");

  const r = await fetch(`/api/characters/${charId}/ref-audio`, {
    method: "POST",
    body: fd,
  });
  const d = await r.json();
  if (d.ok) {
    document.getElementById(`ref-name-${charId}`).textContent = d.ref_audio_name;
    document.getElementById(`ref-status-${charId}`).classList.remove("hidden");
    document.getElementById(`remove-ref-${charId}`).disabled = false;
    alert("Reference audio and transcript saved for cloning.");
  } else if (d.error) {
    alert(`Upload failed: ${d.error}`);
  }
  event.target.value = "";
}

async function loadTextFileIntoField(event, fieldId) {
  const file = event.target.files[0];
  if (!file) return;

  try {
    const text = await file.text();
    const field = document.getElementById(fieldId);
    if (field) field.value = text.replace(/^\uFEFF/, "").trim();
  } catch (error) {
    alert(`Could not read the TXT file: ${error.message || error}`);
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

async function removeRef(charId) {
  const r = await fetch(`/api/characters/${charId}/ref-audio`, { method: "DELETE" });
  const d = await r.json();
  if (d.ok) {
    document.getElementById(`ref-status-${charId}`).classList.add("hidden");
    document.getElementById(`remove-ref-${charId}`).disabled = true;
    document.getElementById(`ref-text-${charId}`).value = "";
  } else if (d.error) {
    alert(`Remove failed: ${d.error}`);
  }
}

async function uploadNarratorRef(event) {
  const file = event.target.files[0];
  if (!file) return;

  const fd = new FormData();
  fd.append("file", file);
  fd.append("ref_text", document.getElementById("narrator-ref-text")?.value.trim() || "");

  const r = await fetch(`/api/books/${BOOK_ID}/narrator-ref-audio`, {
    method: "POST",
    body: fd,
  });
  const d = await r.json();
  if (d.ok) {
    narratorHasRefAudio = true;
    narratorRefAudioName = d.ref_audio_name;
    syncNarratorRefUI();
    alert("Narrator reference audio saved. Existing audio will be regenerated with the cloned voice.");
  } else if (d.error) {
    alert(`Upload failed: ${d.error}`);
  }
  event.target.value = "";
}

async function removeNarratorRef() {
  const r = await fetch(`/api/books/${BOOK_ID}/narrator-ref-audio`, {
    method: "DELETE",
  });
  const d = await r.json();
  if (d.ok) {
    narratorHasRefAudio = false;
    narratorRefAudioName = "Previously uploaded WAV";
    const refText = document.getElementById("narrator-ref-text");
    if (refText) refText.value = "";
    syncNarratorRefUI();
    alert("Cloned narrator voice removed. Preview, playback, and export will use the narrator settings again.");
  } else if (d.error) {
    alert(`Remove failed: ${d.error}`);
  }
}

async function saveNarrator() {
  const instruct = updateNarratorPreview();
  const refText = document.getElementById("narrator-ref-text")?.value.trim() || "";
  const r = await fetch(`/api/books/${BOOK_ID}/narrator`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruct, single_narrator_mode: singleNarratorMode, ref_text: refText }),
  });
  const d = await r.json();
  if (d.ok) {
    singleNarratorMode = Boolean(d.single_narrator_mode);
    syncSingleNarratorUI();
    flashSaved(document.getElementById("narrator-instruct-preview"));
  } else if (d.error) {
    alert(`Save failed: ${d.error}`);
  }
}

async function previewNarrator() {
  const instruct = updateNarratorPreview();
  const refText = document.getElementById("narrator-ref-text")?.value.trim() || "";
  const r = await fetch(`/api/books/${BOOK_ID}/characters/narrator/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruct, ref_text: refText }),
  });
  const d = await r.json();
  if (d.error) {
    alert(`Preview failed: ${d.error}`);
    return;
  }
  previewAudio.src = `${d.audio_url}?t=${Date.now()}`;
  await previewAudio.play();
}

document.querySelector('.preview-btn[data-char-id="narrator"]').onclick = previewNarrator;

initNarratorControls();
loadCharacters();

window.saveChar = saveChar;
window.previewChar = previewChar;
window.uploadRef = uploadRef;
window.removeRef = removeRef;
window.uploadNarratorRef = uploadNarratorRef;
window.removeNarratorRef = removeNarratorRef;
window.saveNarrator = saveNarrator;
window.loadRefText = loadRefText;
window.loadNarratorRefText = loadNarratorRefText;
