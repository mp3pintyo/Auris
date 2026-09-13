/* Optional chapter editing. Reading remains the default experience. */
(() => {
  const dialog = document.createElement('dialog');
  dialog.id = 'text-editor';
  dialog.setAttribute('aria-labelledby', 'text-editor-title');
  dialog.innerHTML = `<form method="dialog" class="text-editor-shell">
    <header><h2 id="text-editor-title">Szöveg szerkesztése</h2><button type="button" data-action="close" class="btn btn-ghost" aria-label="Szerkesztő bezárása">×</button></header>
    <div class="text-editor-body"><p>A címek és bekezdések a felolvasás ritmusát is meghatározzák. A mentés után az érintett hangrészek újra készülnek.</p>
    <label>Fejezet neve<input id="editor-chapter-title" maxlength="500"></label>
    <details><summary>Keresés és csere</summary><div class="editor-find"><label>Keresett szöveg<input id="editor-find"></label><label>Csere erre<input id="editor-replace"></label><button type="button" class="btn btn-ghost" data-action="replace">Összes cseréje</button></div><p>A csere kis- és nagybetűérzékeny, a szövegblokkokban történik.</p></details>
    <div id="editor-blocks"></div><button type="button" class="btn btn-ghost" data-action="add">+ Bekezdés hozzáadása</button>
    </div><footer><div id="editor-status" role="status" aria-live="polite"></div><div class="editor-actions"><button type="button" class="btn btn-ghost" data-action="restore">Előző változat visszaállítása</button><button type="button" class="btn btn-ghost" data-action="close">Elvetés / bezárás</button><button type="button" class="btn btn-primary" data-action="save">Mentés</button></div></footer>
  </form>`;
  document.body.append(dialog);
  const $ = selector => dialog.querySelector(selector);
  let chapterId, revision, original = '', busy = false, loaded = false, canRestore = false, speedSupported = true;
  const preview = new Audio();
  let previewRequest = 0;
  const status = message => { $('#editor-status').textContent = message; };
  const endpoint = () => `/api/books/${BOOK_ID}/chapters/${chapterId}/editor`;
  async function request(url, method = 'GET', body) {
    const response = await fetch(url, {method, headers: {'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.message || `Sikertelen kérés (${response.status}).`);
    return data;
  }
  function blockData(card) {
    const speed = card.querySelector('[data-field="speed"]').value;
    const pause = card.querySelector('[data-field="pause_ms"]').value;
    return {text: card.querySelector('textarea').value, kind: card.querySelector('[data-field="kind"]').value,
      speed: speed === '' ? null : Number(speed), pause_ms: pause === '' ? null : Number(pause)};
  }
  function payload() { return {title: $('#editor-chapter-title').value, blocks: [...dialog.querySelectorAll('.editor-block')].map(blockData)}; }
  const dirty = () => original !== JSON.stringify(payload());
  function addBlock(block = {text: '', kind: 'paragraph'}, after = null) {
    const card = document.createElement('section');
    card.className = 'editor-block';
    card.innerHTML = `<div class="editor-block-tools"><label>Szövegtípus<select data-field="kind"><option value="paragraph">Bekezdés</option><option value="heading">Cím</option><option value="subheading">Alcím</option></select></label><button type="button" class="btn btn-ghost" data-action="split" title="A kurzor helyén új bekezdést kezd">Kettébontás</button><button type="button" class="btn btn-ghost" data-action="delete">Törlés</button></div><label>Szöveg<textarea rows="4" spellcheck="true" lang="hu"></textarea></label><details><summary>Felolvasás finomhangolása</summary><div class="editor-tuning"><label>Tempó (0,5–2×)<input type="number" min="0.5" max="2" step="0.05" placeholder="Alapértelmezett" data-field="speed"></label><label>Szünet utána (ms)<input type="number" min="0" max="5000" step="50" placeholder="Automatikus" data-field="pause_ms"></label><button type="button" class="btn btn-ghost" data-action="preview">Előnézet narrátorhanggal</button><button type="button" class="btn btn-ghost" data-action="stop-preview">Leállítás</button></div><small>Üres mező: automatikus érték. A szünet a teljes blokk után következik. Az előnézet narrátorhanggal, a záró szünettel együtt készül; legfeljebb 1500 karakteres blokkhoz érhető el.</small></details>`;
    card.querySelector('textarea').value = block.text;
    card.querySelector('[data-field="kind"]').value = block.kind;
    card.querySelector('[data-field="speed"]').value = block.speed ?? '';
    card.querySelector('[data-field="speed"]').disabled = !speedSupported;
    if (!speedSupported) {
      const help = document.createElement('p');
      help.textContent = 'A Higgs nyers módja nem alkalmaz tempóvezérlést. Ehhez válts kifejező módra vagy OmniVoice-ra a Beállításokban.';
      card.querySelector('details').append(help);
    }
    card.querySelector('[data-field="pause_ms"]').value = block.pause_ms ?? '';
    if (after) after.after(card); else $('#editor-blocks').append(card);
    return card;
  }
  function populate(data) {
    loaded = true;
    speedSupported = data.speed_supported !== false;
    revision = data.revision;
    $('#editor-chapter-title').value = data.title;
    $('#editor-blocks').replaceChildren();
    data.blocks.forEach(block => addBlock(block));
    canRestore = Boolean(data.can_restore);
    $('[data-action="restore"]').disabled = !canRestore;
    original = JSON.stringify(payload());
  }
  function close() {
    if (busy) return;
    if (dirty() && !window.confirm('Elveted a nem mentett módosításokat?')) return;
    previewRequest++;
    preview.pause();
    dialog.close();
    document.getElementById('text-editor-open').focus();
  }
  async function refreshReader() {
    const progress = await request(`/api/books/${BOOK_ID}/progress`);
    const position = Number(progress.chapter_id) === chapterId ? Number(progress.position) || 0 : currentSegIdx;
    const data = await request(`/api/books/${BOOK_ID}/chapters`);
    chapters = data;
    document.querySelectorAll('.toc-item').forEach(item => {
      if (Number(item.dataset.id) === chapterId) {
        const title = item.querySelector('.toc-item-title');
        if (title) title.textContent = data.find(ch => ch.id === chapterId)?.title || '';
      }
    });
    await openChapter(chapterId, {resumePosition: position, persistCurrent: false});
  }
  document.getElementById('text-editor-open').addEventListener('click', async () => {
    if (!currentChapterId) return;
    chapterId = currentChapterId;
    stopPlayback();
    loaded = false;
    busy = true;
    $('.text-editor-body').inert = true;
    $('#editor-blocks').replaceChildren();
    $('#editor-chapter-title').value = '';
    original = JSON.stringify(payload());
    dialog.showModal(); status('Betöltés…');
    try { populate(await request(endpoint())); status(''); } catch (error) { status(error.message); }
    finally { busy = false; $('.text-editor-body').inert = false; }
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('click', async event => {
    if (event.target === dialog) { close(); return; }
    const button = event.target.closest('[data-action]');
    if (!button || busy) return;
    const action = button.dataset.action;
    const card = button.closest('.editor-block');
    if (action === 'close') return close();
    if (!loaded) { status('A fejezet nem töltődött be. Zárd be, majd nyisd meg újra a szerkesztőt.'); return; }
    if (action === 'stop-preview') { previewRequest++; preview.pause(); return; }
    if (action === 'add') { addBlock().querySelector('textarea').focus(); return; }
    if (action === 'delete') {
      if (!card.querySelector('textarea').value.trim() || window.confirm('Törlöd ezt a szövegblokkot?')) card.remove();
      return;
    }
    if (action === 'split') {
      const textarea = card.querySelector('textarea');
      const cursor = textarea.selectionStart;
      if (!cursor || cursor === textarea.value.length) { status('A kettébontáshoz helyezd a kurzort a szöveg belsejébe.'); textarea.focus(); return; }
      const next = {...blockData(card), text: textarea.value.slice(cursor).trimStart(), kind: 'paragraph'};
      textarea.value = textarea.value.slice(0, cursor).trimEnd();
      card.querySelector('[data-field="pause_ms"]').value = '';
      addBlock(next, card).querySelector('textarea').focus(); return;
    }
    if (action === 'replace') {
      const find = $('#editor-find').value; if (!find) { status('Adj meg keresett szöveget.'); return; }
      let count = 0;
      dialog.querySelectorAll('textarea').forEach(input => { const parts = input.value.split(find); count += parts.length - 1; input.value = parts.join($('#editor-replace').value); });
      status(`${count} találat cserélve. A változtatásokat még menteni kell.`); return;
    }
    if (!dialog.querySelector('form').reportValidity()) return;
    if (action === 'preview') {
      const block = blockData(card);
      if (!block.text.trim()) { status('Az előnézethez adj meg szöveget.'); return; }
      if (block.text.length > 1500) { status('Az előnézet legfeljebb 1500 karakteres blokkhoz érhető el. Bontsd kisebb részekre a blokkot a Kettébontás gombbal.'); return; }
      const token = ++previewRequest;
      preview.pause(); button.disabled = true; status('Hangelőnézet készül…');
      try {
        const result = await request(endpoint() + '/preview', 'POST', {block});
        if (token !== previewRequest || !dialog.open) return;
        preview.src = result.audio_url; await preview.play(); status('Előnézet lejátszása.');
      } catch (error) { status(error.message); } finally { button.disabled = false; }
      return;
    }
    if (action !== 'save' && action !== 'restore') return;
    if (action === 'restore' && !window.confirm('Visszaállítod az előző mentett változatot? A jelenlegi módosítások elvesznek.')) return;
    if (action === 'save' && (!payload().title.trim() || !payload().blocks.length || payload().blocks.some(block => !block.text.trim()))) { status('Adj meg fejezetnevet és legalább egy nem üres szövegblokkot.'); return; }
    busy = true; $('.text-editor-body').inert = true; button.disabled = true; previewRequest++; preview.pause(); status('Mentés…');
    try {
      const saved = await request(endpoint() + (action === 'restore' ? '/restore' : ''), action === 'restore' ? 'POST' : 'PUT', {...(action === 'save' ? payload() : {}), revision});
      populate(await request(endpoint()));
      await refreshReader();
      const notice = saved.annotations_removed > 0 ? ` ${saved.annotations_removed} beszélő-hozzárendelést a szövegváltozás miatt töröltünk. Ellenőrizd ezeket a Beszélők javítása eszközzel.` : '';
      status((action === 'restore' ? 'Az előző változat visszaállítva.' : 'Elmentve. A friss szöveg már az olvasóban is elérhető.') + notice);
    } catch (error) { status(error.message); } finally { busy = false; $('.text-editor-body').inert = false; button.disabled = action === 'restore' && !canRestore; }
  });
  // Prevent reader shortcuts (including Escape) while the native modal owns focus.
  dialog.addEventListener('keydown', event => { event.stopPropagation(); });
  window.addEventListener('beforeunload', event => {
    if (dialog.open && (busy || dirty())) { event.preventDefault(); event.returnValue = ''; }
  });
})();
