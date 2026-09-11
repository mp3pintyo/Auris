const sx = (id) => document.getElementById(id);
function sxEscape(v) {
  return String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
async function sxApi(url, data, method = "POST") {
  const r = await fetch(
    url,
    data === undefined
      ? undefined
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "A művelet nem sikerült.");
  return d;
}
async function loadSetup() {
  try {
    const d = await sxApi("/api/setup/status");
    sx("setup-hardware").textContent =
      `Gép: ${d.device}${d.vram_gb ? ` · ${d.vram_gb} GB videomemória` : ""}. FFmpeg: ${d.ffmpeg ? "elérhető" : "hiányzik — MP3/M4B exporthoz szükséges"}.`;
    sx("setup-profile").value = d.profile || "balanced";
  } catch (e) {
    sx("setup-message").textContent = e.message;
  }
}
async function applySetupProfile(completed) {
  try {
    await sxApi("/api/setup/profile", {
      profile: sx("setup-profile").value,
      completed,
    });
    await loadSettings();
    sx("setup-message").textContent = completed
      ? "Az első beállítás kész. A könyvtárból megnyithatod az első könyvet."
      : "Minőségprofil alkalmazva. A változás az új generálásokra érvényes.";
  } catch (e) {
    sx("setup-message").textContent = e.message;
  }
}
async function previewSetupVoice() {
  const button = sx("setup-preview");
  button.disabled = true;
  sx("setup-message").textContent = "Próbahang készül…";
  try {
    const d = await sxApi("/api/setup/preview", {});
    sx("setup-audio").src = d.audio_url;
    sx("setup-audio").classList.remove("hidden");
    await sx("setup-audio").play();
    sx("setup-message").textContent =
      "Magyar próbahang. Hallgasd meg, mielőtt hosszabb szöveget generálsz.";
  } catch (e) {
    sx("setup-message").textContent = e.message;
  } finally {
    button.disabled = false;
  }
}
async function loadSetupEngine() {
  sx("setup-message").textContent = "A beszédmotor betöltése indul…";
  try {
    await reloadTTS();
    sx("setup-message").textContent =
      "A betöltés állapotát a felső állapotjelzőn követheted. Ha kész, indíts magyar próbahangot.";
  } catch (error) {
    sx("setup-message").textContent = error.message;
  }
}
async function loadDictionary() {
  try {
    const id = sx("dictionary-book").value;
    const rules = await sxApi(
      "/api/pronunciation" + (id ? "?book_id=" + id : ""),
    );
    sx("dictionary-list").innerHTML = rules.length
      ? rules
          .map(
            (r) =>
              `<div class="dictionary-row"><span><strong>${sxEscape(r.source)}</strong> → ${sxEscape(r.replacement)} <small>${r.book_id ? "Könyv saját szabálya" : "Minden könyv"}</small></span><button class="btn btn-ghost" data-delete-rule="${r.id}">Törlés</button></div>`,
          )
          .join("")
      : "<p>Még nincs kiejtési szabály.</p>";
  } catch (e) {
    sx("dictionary-message").textContent = e.message;
  }
}
async function savePronunciation() {
  try {
    await sxApi("/api/pronunciation", {
      book_id: sx("dictionary-book").value || null,
      source: sx("dictionary-source").value,
      replacement: sx("dictionary-replacement").value,
    });
    sx("dictionary-message").textContent =
      "Mentve. A szabály törlésével visszaállíthatod az eredeti kiejtést.";
    await loadDictionary();
  } catch (e) {
    sx("dictionary-message").textContent = e.message;
  }
}
sx("dictionary-list").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-delete-rule]");
  if (!button) return;
  try {
    await sxApi(
      "/api/pronunciation/" + button.dataset.deleteRule,
      {},
      "DELETE",
    );
    await loadDictionary();
    sx("dictionary-message").textContent = "Szabály törölve.";
  } catch (error) {
    sx("dictionary-message").textContent = error.message;
  }
});
sx("dictionary-book").addEventListener("change", loadDictionary);
async function previewPronunciation() {
  try {
    const d = await sxApi("/api/pronunciation/preview", {
      book_id: sx("dictionary-book").value || null,
      text: sx("dictionary-preview-input").value,
    });
    sx("dictionary-preview-output").textContent = d.spoken;
  } catch (e) {
    sx("dictionary-preview-output").textContent = e.message;
  }
}
function sizeText(bytes) {
  return bytes > 1024 ** 3
    ? (bytes / 1024 ** 3).toFixed(2) + " GB"
    : (bytes / 1024 ** 2).toFixed(1) + " MB";
}
async function loadStorage() {
  try {
    const d = await sxApi("/api/storage");
    sx("storage-areas").innerHTML =
      d.areas
        .map(
          (a) =>
            `<div class="storage-row"><span>${sxEscape(a.name)} · ${a.files} fájl</span><strong>${sizeText(a.bytes)}</strong></div>`,
        )
        .join("") + `<p>Szabad lemezterület: ${sizeText(d.free_bytes)}</p>`;
    const cache = d.audio_cache || {};
    sx("audio-cache-summary").textContent =
      `${cache.total_files || 0} WAV, ${sizeText(cache.total_bytes || 0)}; ` +
      `${cache.orphan_files || 0} már nem használt fájl (${sizeText(cache.orphan_bytes || 0)}).`;
  } catch (e) {
    sx("storage-message").textContent = e.message;
  }
}
async function cleanupAudioCache() {
  const button = sx("audio-cache-cleanup");
  button.disabled = true;
  sx("storage-message").textContent = "A nem használt hangok törlése…";
  try {
    const result = await sxApi("/api/storage/audio-cache/cleanup", {});
    sx("storage-message").textContent =
      `${result.removed_files} régi hangfájl törölve (${sizeText(result.removed_bytes)}).`;
    await loadStorage();
  } catch (error) {
    sx("storage-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
async function downloadBackup() {
  sx("backup-btn").disabled = true;
  sx("storage-message").textContent = "A mentés készül…";
  try {
    const r = await fetch("/api/backup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ include_audio: sx("backup-audio").checked }),
    });
    if (!r.ok) {
      const d = await r.json();
      throw new Error(d.error);
    }
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "auris-konyvtar.zip";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    sx("storage-message").textContent =
      "A mentés elkészült, a letöltés elindult.";
  } catch (e) {
    sx("storage-message").textContent = e.message;
  } finally {
    sx("backup-btn").disabled = false;
  }
}
async function restoreBackup() {
  const file = sx("restore-file").files[0];
  if (!file || sx("restore-confirm").value !== "VISSZAÁLLÍTÁS") {
    sx("storage-message").textContent =
      "Válassz mentést, majd írd be a megerősítő szöveget.";
    return;
  }
  sx("restore-btn").disabled = true;
  sx("storage-message").textContent = "A mentés ellenőrzése és visszaállítása…";
  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("confirm", sx("restore-confirm").value);
    const r = await fetch("/api/backup/restore", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    sx("storage-message").textContent =
      `${d.books} könyv visszaállítva. A korábbi könyvtár mentése: ${d.recovery_path}${d.warning ? " · " + d.warning : ""}`;
    await loadStorage();
  } catch (e) {
    sx("storage-message").textContent = e.message;
  } finally {
    sx("restore-btn").disabled = false;
  }
}
sxApi("/api/books")
  .then((books) => {
    for (const b of books) sx("dictionary-book").add(new Option(b.title, b.id));
    loadDictionary();
  })
  .catch((e) => (sx("dictionary-message").textContent = e.message));
loadSetup();
loadStorage();

let backupScheduleLoaded = false;
async function loadBackupSchedule() {
  try {
    const state = await sxApi('/api/backup/schedule');
    if (!backupScheduleLoaded) {
      sx('backup-frequency').value = state.frequency;
      sx('backup-keep').value = state.keep;
      backupScheduleLoaded = true;
    }
    const date = value => value ? new Date(value * 1000).toLocaleString('hu-HU') : '—';
    sx('backup-schedule-status').textContent = `${state.running ? 'Mentés folyamatban. ' : ''}Utolsó sikeres mentés: ${date(state.last_success)} · Következő: ${date(state.next_due)} · Mappa: ${state.directory}${state.last_error ? ' · Legutóbbi hiba (újrapróbálás 5 perc múlva): ' + state.last_error : ''}`;
    sx('backup-run-now').disabled = state.running;
    sx('backup-schedule-files').innerHTML = state.files.map(f => `<p><a href="${sxEscape(f.download)}">${sxEscape(f.name)}</a> · ${sizeText(f.bytes)}</p>`).join('');
  } catch (error) { sx('backup-schedule-status').textContent = error.message; }
}
async function saveBackupSchedule() {
  try {
    await sxApi('/api/backup/schedule', {frequency: sx('backup-frequency').value, keep: Number(sx('backup-keep').value)}, 'PATCH');
    sx('backup-schedule-message').textContent = 'Ütemezés mentve.';
    await loadBackupSchedule();
  } catch (error) { sx('backup-schedule-message').textContent = error.message; }
}
async function runScheduledBackup() {
  try {
    sx('backup-run-now').disabled = true;
    await sxApi('/api/backup/schedule/run', {});
    sx('backup-schedule-message').textContent = 'Mentési feladat elindítva.';
    await loadBackupSchedule();
  } catch (error) { sx('backup-schedule-message').textContent = error.message; sx('backup-run-now').disabled = false; }
}
loadBackupSchedule();
setInterval(loadBackupSchedule, 5000);
