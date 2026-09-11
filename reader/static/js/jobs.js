const jobLabels = {
  pending: "Várakozik",
  queued: "Várakozik",
  running: "Folyamatban",
  complete: "Elkészült",
  completed: "Elkészült",
  failed: "Hiba",
  interrupted: "Megszakadt",
  cancelled: "Leállítva",
  cancelling: "Leállítás folyamatban",
};
function escapeJob(v) {
  return String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
function safeJobLink(url) {
  try {
    const u = new URL(url, location.origin);
    return u.origin === location.origin && u.pathname.startsWith("/api/")
      ? u.href
      : null;
  } catch {
    return null;
  }
}
async function loadJobs() {
  try {
    const r = await fetch("/api/jobs");
    if (!r.ok) throw new Error("A feladatlista nem érhető el.");
    const data = await r.json();
    const jobs = Array.isArray(data) ? data : data.jobs || [];
    const focused = document.activeElement;
    const restoreFocus = focused?.matches('#jobs-list [data-job]')
      ? {id: focused.dataset.job, action: focused.dataset.action} : null;
    document.getElementById("jobs-list").innerHTML = jobs.length
      ? jobs
          .map((j) => {
            const state = j.state || j.status,
              id = j.id || j.job_id,
              pct = j.total
                ? Math.min(100, Math.round(((j.done || 0) / j.total) * 100))
                : 0;
            const result = j.result || {},
              links = Object.entries(result).filter(
                ([key, value]) =>
                  key.includes("download") &&
                  typeof value === "string" &&
                  safeJobLink(value),
              );
            const kind =
              {
                export: "Export",
                export_chapter: "Fejezetexport",
                export_book: "Könyvexport",
                generate_chapter: "Fejezethang",
                reanalyze: "Szereplők újraelemzése",
                initial_analysis: "Szereplőelemzés",
                chapter_generation: "Fejezethang",
                chapter: "Fejezethang",
                analysis: "Szereplőelemzés",
                reanalysis: "Szereplőelemzés",
              }[j.kind || j.type] || "Feladat";
            return `<article class="job-row" id="job-${escapeJob(id)}"><h2>${escapeJob(j.book_title || j.title || result.book_title || kind)} <small>· ${escapeJob(jobLabels[state] || state)}</small></h2><p>${escapeJob(j.message || kind)}</p>${j.total ? `<progress value="${pct}" max="100" aria-label="Készültség"></progress><span>${pct}% · ${j.done || 0}/${j.total}</span>` : ""}${j.error ? `<p class="status-error">${escapeJob(j.error)}</p>` : ""}${result.mastering_warning ? `<p class="status-warn">A hangerő-kiegyenlítés kimaradt: ${escapeJob(result.mastering_warning)}</p>` : ""}<div class="job-results">${links.map(([key, url]) => `<a class="btn btn-primary" href="${escapeJob(safeJobLink(url))}">${key.includes("subtitle") ? "Felirat letöltése" : key.includes("zip") ? "Csomag letöltése" : key.includes("audio") ? "Hang letöltése" : "Export letöltése"}</a>`).join("")}${["pending", "queued", "running"].includes(state) ? `<button class="btn btn-ghost" data-job="${escapeJob(id)}" data-action="cancel">Leállítás</button>` : ""}${["failed", "interrupted", "cancelled"].includes(state) ? `<button class="btn btn-primary" data-job="${escapeJob(id)}" data-action="resume">Folytatás / újrapróbálás</button>` : ""}</div></article>`;
          })
          .join("")
      : '<div class="experience-card"><h2>Még nincs feladat</h2><p>Nyiss meg egy könyvet, és indíts fejezethangot vagy exportot.</p><a href="/" class="btn btn-primary">Könyvtár</a></div>';
    document.getElementById("jobs-message").textContent = "";
    if (restoreFocus) {
      document.querySelector(`#jobs-list [data-job="${CSS.escape(restoreFocus.id)}"][data-action="${CSS.escape(restoreFocus.action)}"]`)?.focus({preventScroll:true});
    }
  } catch (e) {
    document.getElementById("jobs-message").textContent = e.message;
  }
}
document.getElementById("jobs-list").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-job]");
  if (!button) return;
  button.disabled = true;
  try {
    const r = await fetch(
      `/api/jobs/${encodeURIComponent(button.dataset.job)}/${button.dataset.action}`,
      { method: "POST" },
    );
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "A művelet nem sikerült.");
    await loadJobs();
  } catch (error) {
    document.getElementById("jobs-message").textContent = error.message;
    button.disabled = false;
  }
});
loadJobs();
setInterval(() => {
  if (!document.hidden) loadJobs();
}, 3000);
