/* SubCal — Interface web v2 */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const S = {
  file: null,
  filename: '',
  blocks: [],           // blocks currently displayed (original or calibrated)
  originalBlocks: [],   // blocks before calibration (for compare)
  isCalibrated: false,
  rules: {},
  selectedIdx: 0,
  compareMode: false,
  filterModified: false,
  filterErrors: false,
  format: '16:9',
  presets: {},
  // History (undo/redo)
  history: [],          // array of {blocks, selectedIdx} snapshots
  historyIdx: -1,       // current position in history
  // Player
  playing: false,
  playerTime: 0,
  playerSpeed: 1,
  playerDuration: 0,
  playerLastTS: null,
  playerRAF: null,
  // Batch
  batchMode: false,
  batchFiles: [],
  batchFormat: '16:9',
};

// ── History (undo / redo) ──────────────────────────────────────────────────
function pushHistory() {
  // Truncate redo stack
  S.history = S.history.slice(0, S.historyIdx + 1);
  S.history.push({
    blocks: JSON.parse(JSON.stringify(S.blocks)),
    selectedIdx: S.selectedIdx,
  });
  // Keep at most 50 snapshots
  if (S.history.length > 50) S.history.shift();
  S.historyIdx = S.history.length - 1;
  updateUndoRedoBtns();
}

function undo() {
  if (S.historyIdx <= 0) return;
  S.historyIdx--;
  restoreSnapshot(S.history[S.historyIdx]);
}

function redo() {
  if (S.historyIdx >= S.history.length - 1) return;
  S.historyIdx++;
  restoreSnapshot(S.history[S.historyIdx]);
}

function restoreSnapshot(snap) {
  S.blocks = JSON.parse(JSON.stringify(snap.blocks));
  S.selectedIdx = snap.selectedIdx;
  recomputePlayerDuration();
  renderBlockList();
  selectBlock(S.selectedIdx);
  updateUndoRedoBtns();
}

function updateUndoRedoBtns() {
  $('btn-undo').disabled = S.historyIdx <= 0;
  $('btn-redo').disabled = S.historyIdx >= S.history.length - 1;
}

function recomputePlayerDuration() {
  S.playerDuration = S.blocks.length ? S.blocks[S.blocks.length - 1].end_ms : 0;
}

// ── DOM ────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const dropZone      = $('drop-zone');
const fileInput     = $('file-input');
const dropLabel     = $('drop-label');
const formatBtns    = $('format-btns');
const fpsBadge      = $('fps-badge');
const btnCalibrate  = $('btn-calibrate');
const reportBadge   = $('report-badge');
const sidebarActions = $('sidebar-actions');
const btnExport     = $('btn-export');
const btnCompare    = $('btn-compare');
const filterModified = $('filter-modified');
const filterErrors   = $('filter-errors');
const emptyState    = $('empty-state');
const blockListWrap = $('block-list-wrap');
const blockList     = $('block-list');
const editorFilename = $('editor-filename');
const blockCount    = $('block-count');
const calibratedBadge = $('calibrated-badge');
const batchPanel    = $('batch-panel');
const previewFrame  = $('preview-frame');
const previewSub    = $('preview-subtitle');
const previewBg     = $('preview-bg');
const playerTC      = $('player-tc');
const playerProgress = $('player-progress');
const playerCursor  = $('player-cursor');
const playerSpeedSel = $('player-speed');
const btnPlay       = $('btn-play');
const loading       = $('loading');
const loadingMsg    = $('loading-msg');

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  const res = await fetch('/api/presets');
  S.presets = await res.json();
  applyPresetToUI('16:9');
  setupListeners();
}

// ── Listeners ──────────────────────────────────────────────────────────────
function setupListeners() {
  // Drop zone
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault(); dropZone.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f && f.name.endsWith('.srt')) loadFile(f);
  });
  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) loadFile(fileInput.files[0]); });

  // Format buttons (left sidebar)
  formatBtns.querySelectorAll('.btn-format').forEach(btn => {
    btn.addEventListener('click', () => {
      formatBtns.querySelectorAll('.btn-format').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.format = btn.dataset.format;
      applyPresetToUI(S.format);
    });
  });

  // Config sliders
  [
    ['cfg-cpl', 'lbl-cpl', v => v],
    ['cfg-cps', 'lbl-cps', v => v],
    ['cfg-lines', 'lbl-lines', v => v],
    ['cfg-mindur', 'lbl-mindur', v => parseFloat(v).toFixed(1)],
    ['cfg-maxdur', 'lbl-maxdur', v => parseFloat(v).toFixed(1)],
    ['cfg-gap', 'lbl-gap', v => v],
  ].forEach(([id, lbl, fmt]) => {
    $(id).addEventListener('input', () => { $(lbl).textContent = fmt($(id).value); checkFPSBadge(); });
  });
  $('cfg-fps-src').addEventListener('change', checkFPSBadge);
  $('cfg-fps-tgt').addEventListener('change', checkFPSBadge);

  // Calibrate
  btnCalibrate.addEventListener('click', doCalibrate);

  // Sidebar actions
  btnExport.addEventListener('click', doExport);
  btnCompare.addEventListener('click', toggleCompare);
  filterModified.addEventListener('change', () => { S.filterModified = filterModified.checked; renderBlockList(); });
  filterErrors.addEventListener('change', () => { S.filterErrors = filterErrors.checked; renderBlockList(); });

  // Preview format
  document.querySelectorAll('.btn-format-preview').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-format-preview').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      previewFrame.dataset.ratio = btn.dataset.ratio;
      renderPreview();
    });
  });

  // Preview background
  $('preview-bg-input').addEventListener('change', e => {
    const f = e.target.files[0];
    if (!f) return;
    previewBg.src = URL.createObjectURL(f);
    previewBg.classList.remove('hidden');
  });

  // Undo / Redo — boutons
  $('btn-undo').addEventListener('click', undo);
  $('btn-redo').addEventListener('click', redo);

  // Undo / Redo — clavier ⌘Z / ⌘⇧Z ; ⌘F pour la recherche
  document.addEventListener('keydown', e => {
    const meta = e.metaKey || e.ctrlKey;
    if (!meta) return;
    if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    if ((e.key === 'z' && e.shiftKey) || e.key === 'y') { e.preventDefault(); redo(); }
    if (e.key === 'f') { e.preventDefault(); openSearchBar(); }
  });

  // Taille de police preview (slider)
  const fontSlider = $('cfg-font-size');
  fontSlider.addEventListener('input', () => {
    const px = fontSlider.value + 'px';
    $('lbl-font-size').textContent = px;
    previewFrame.style.setProperty('--preview-font-size', px);
  });

  // Largeur du panneau preview (slider)
  $('cfg-preview-width').addEventListener('input', () => {
    const px = $('cfg-preview-width').value + 'px';
    $('lbl-preview-width').textContent = px;
    document.documentElement.style.setProperty('--right-w', px);
  });

  // Recherche / Remplacement
  $('btn-search-toggle').addEventListener('click', openSearchBar);
  $('btn-search-close').addEventListener('click', () => $('search-bar').classList.add('hidden'));
  $('search-input').addEventListener('input', updateSearchCount);
  $('replace-input').addEventListener('keydown', e => { if (e.key === 'Enter') doReplaceAll(); });
  $('btn-replace-all').addEventListener('click', doReplaceAll);

  // Normalisation des chiffres
  $('btn-normalize').addEventListener('click', doNormalize);

  // Player
  btnPlay.addEventListener('click', togglePlay);
  playerSpeedSel.addEventListener('change', () => { S.playerSpeed = parseFloat(playerSpeedSel.value); });
  $('player-progress-wrap').addEventListener('click', e => {
    const rect = playerProgress.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    S.playerTime = Math.round(ratio * S.playerDuration);
    updatePlayerUI();
  });

  // Batch
  $('btn-batch-toggle').addEventListener('click', toggleBatch);
  const batchDrop = $('batch-drop-zone');
  const batchInput = $('batch-file-input');
  batchDrop.addEventListener('dragover', e => { e.preventDefault(); batchDrop.classList.add('dragover'); });
  batchDrop.addEventListener('dragleave', () => batchDrop.classList.remove('dragover'));
  batchDrop.addEventListener('drop', e => {
    e.preventDefault(); batchDrop.classList.remove('dragover');
    addBatchFiles(Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.srt')));
  });
  batchDrop.addEventListener('click', () => batchInput.click());
  batchInput.addEventListener('change', () => addBatchFiles(Array.from(batchInput.files)));
  document.querySelectorAll('#batch-format-btns .btn-format').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#batch-format-btns .btn-format').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.batchFormat = btn.dataset.format;
    });
  });
  $('btn-batch-calibrate').addEventListener('click', doBatchCalibrate);
}

// ── Preset & config ────────────────────────────────────────────────────────
function applyPresetToUI(fmt) {
  const p = S.presets[fmt];
  if (!p) return;
  $('cfg-cpl').value = p.max_cpl; $('lbl-cpl').textContent = p.max_cpl;
  $('cfg-cps').value = p.max_cps; $('lbl-cps').textContent = p.max_cps;
  $('cfg-lines').value = p.max_lines; $('lbl-lines').textContent = p.max_lines;
}

function checkFPSBadge() {
  const src = $('cfg-fps-src').value;
  const tgt = $('cfg-fps-tgt').value;
  if (src && tgt && src !== tgt) {
    fpsBadge.textContent = `FPS ${src} → ${tgt} (ratio ${(parseFloat(tgt)/parseFloat(src)).toFixed(5)})`;
    fpsBadge.classList.remove('hidden');
  } else {
    fpsBadge.classList.add('hidden');
  }
}

function getFormRules() {
  return {
    format: S.format,
    cpl: $('cfg-cpl').value,
    cps: $('cfg-cps').value,
    max_lines: $('cfg-lines').value,
    min_duration: $('cfg-mindur').value,
    max_duration: $('cfg-maxdur').value,
    min_gap: (parseFloat($('cfg-gap').value) / 1000).toFixed(3),
    source_fps: $('cfg-fps-src').value || null,
    target_fps: $('cfg-fps-tgt').value || null,
    semantic: $('cfg-semantic').checked,
  };
}

// ── Load file (parse only) ─────────────────────────────────────────────────
async function loadFile(f) {
  S.file = f;
  S.filename = f.name;
  S.isCalibrated = false;

  // Update drop zone
  dropZone.classList.add('has-file');
  dropLabel.innerHTML = `<strong>${f.name}</strong>`;

  // Update button
  btnCalibrate.disabled = false;
  btnCalibrate.textContent = 'Calibrer';

  loadingMsg.textContent = 'Chargement…';
  loading.classList.remove('hidden');

  const fd = new FormData();
  fd.append('file', f);

  try {
    const res = await fetch('/api/parse', { method: 'POST', body: fd });
    const data = await res.json();
    S.blocks = data.blocks;
    S.originalBlocks = [];

    S.playerDuration = S.blocks.length ? S.blocks[S.blocks.length - 1].end_ms : 0;
    S.playerTime = 0;
    stopPlayer();

    editorFilename.textContent = data.filename;
    blockCount.textContent = `${S.blocks.length} blocs`;
    calibratedBadge.classList.add('hidden');
    reportBadge.classList.add('hidden');
    sidebarActions.classList.add('hidden');
    btnPlay.disabled = false;

    showBlocks();
    renderBlockList();
    selectBlock(0);
  } catch (e) {
    alert('Erreur chargement : ' + e.message);
  } finally {
    loading.classList.add('hidden');
  }
}

// ── Calibrate ──────────────────────────────────────────────────────────────
async function doCalibrate() {
  if (!S.file) return;

  loadingMsg.textContent = 'Calibrage en cours…';
  loading.classList.remove('hidden');

  const rules = getFormRules();
  const fd = new FormData();
  fd.append('file', S.file);
  fd.append('format', rules.format);
  fd.append('cpl', rules.cpl);
  fd.append('cps', rules.cps);
  fd.append('max_lines', rules.max_lines);
  fd.append('min_duration', rules.min_duration);
  fd.append('max_duration', rules.max_duration);
  fd.append('min_gap', rules.min_gap);
  if (rules.source_fps) fd.append('source_fps', rules.source_fps);
  if (rules.target_fps) fd.append('target_fps', rules.target_fps);
  fd.append('semantic', rules.semantic ? 'true' : 'false');

  try {
    const res = await fetch('/api/calibrate', { method: 'POST', body: fd });
    if (!res.ok) { const e = await res.json(); alert('Erreur : ' + (e.detail || res.statusText)); return; }
    const data = await res.json();

    S.blocks = data.blocks;
    S.originalBlocks = data.original_blocks;
    S.rules = data.rules;
    S.isCalibrated = true;

    S.playerDuration = S.blocks.length ? S.blocks[S.blocks.length - 1].end_ms : 0;
    S.playerTime = 0;
    stopPlayer();

    blockCount.textContent = `${S.blocks.length} blocs`;
    calibratedBadge.classList.remove('hidden');
    reportBadge.textContent = data.report;
    reportBadge.classList.remove('hidden');
    sidebarActions.classList.remove('hidden');
    btnCalibrate.textContent = 'Recalibrer';

    pushHistory();
    renderBlockList();
    selectBlock(0);
  } catch (e) {
    alert('Erreur réseau : ' + e.message);
  } finally {
    loading.classList.add('hidden');
  }
}

// ── Panel visibility ───────────────────────────────────────────────────────
function showBlocks() {
  emptyState.classList.add('hidden');
  batchPanel.classList.add('hidden');
  blockListWrap.classList.remove('hidden');
}

function toggleBatch() {
  S.batchMode = !S.batchMode;
  $('btn-batch-toggle').textContent = S.batchMode ? 'Fichier unique' : 'Batch';
  if (S.batchMode) {
    emptyState.classList.add('hidden');
    blockListWrap.classList.add('hidden');
    batchPanel.classList.remove('hidden');
  } else {
    batchPanel.classList.add('hidden');
    if (S.blocks.length) {
      blockListWrap.classList.remove('hidden');
    } else {
      emptyState.classList.remove('hidden');
    }
  }
}

// ── Block list ─────────────────────────────────────────────────────────────
function renderBlockList() {
  blockList.innerHTML = '';
  const blocks = S.blocks.filter(b => {
    if (S.filterModified && !b.modified) return false;
    if (S.filterErrors && !blockHasError(b)) return false;
    return true;
  });

  blocks.forEach(block => {
    const realIdx = block.index - 1;
    const orig = S.originalBlocks.find(o => o.index === block.index);
    const origText = orig ? orig.lines.join('\n') : '';

    const item = document.createElement('div');
    item.className = 'block-item'
      + (block.modified ? ' modified' : '')
      + (blockHasError(block) ? ' has-error' : '')
      + (!S.isCalibrated ? ' original-only' : '')
      + (realIdx === S.selectedIdx ? ' active' : '');
    item.dataset.idx = realIdx;

    item.innerHTML = `
      <div class="block-index">${block.index}</div>
      <div class="block-content">
        <div class="block-timecodes">${block.start_tc} → ${block.end_tc} · ${block.duration_s.toFixed(2)}s</div>
        ${S.compareMode && orig ? `<div class="block-original">${escHtml(origText)}</div>` : ''}
        <div class="block-text-wrap" contenteditable="${S.isCalibrated}" spellcheck="false" data-idx="${realIdx}">${escHtml(block.lines.join('\n'))}</div>
        ${block.modified ? '<span class="badge-modified">modifié</span>' : ''}
        ${S.isCalibrated ? `<div class="block-actions">
          <button class="btn-block-action" data-action="split" data-idx="${realIdx}" title="Scinder ce bloc en deux">⟂ Scinder</button>
          ${realIdx > 0 ? `<button class="btn-block-action" data-action="merge" data-idx="${realIdx}" title="Fusionner avec le bloc précédent">↑ Fusionner</button>` : ''}
        </div>` : ''}
      </div>
      <div class="block-metrics">
        ${S.isCalibrated ? renderMetrics(block) : ''}
      </div>`;

    // Click to select
    item.addEventListener('click', e => {
      const action = e.target.dataset.action;
      if (action === 'split') { splitBlock(parseInt(e.target.dataset.idx)); return; }
      if (action === 'merge') { mergeBlock(parseInt(e.target.dataset.idx)); return; }
      if (e.target.classList.contains('block-text-wrap')) return;
      selectBlock(realIdx);
    });

    // Inline edit
    const editor = item.querySelector('.block-text-wrap');
    if (S.isCalibrated) {
      editor.addEventListener('input', () => onBlockEdit(parseInt(editor.dataset.idx), editor));
      editor.addEventListener('focus', () => selectBlock(parseInt(editor.dataset.idx)));
    }

    blockList.appendChild(item);
  });
}

function renderMetrics(block) {
  const r = S.rules;
  const cpsClass = metricClass(block.cps, r.max_cps);
  let html = `<span class="metric ${cpsClass}">CPS ${block.cps}</span>`;
  block.cpl_per_line.forEach((cpl, i) => {
    html += `<span class="metric ${metricClass(cpl, r.max_cpl)}">L${i+1} ${cpl}c</span>`;
  });
  return html;
}

function metricClass(val, max) {
  if (!max) return 'ok';
  if (val > max) return 'error';
  if (val > max * 0.85) return 'warn';
  return 'ok';
}

function blockHasError(block) {
  const r = S.rules;
  return (r.max_cps && block.cps > r.max_cps) || (r.max_cpl && block.cpl_max > r.max_cpl);
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Block selection ────────────────────────────────────────────────────────
function selectBlock(idx) {
  S.selectedIdx = idx;
  document.querySelectorAll('.block-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
  });
  renderPreview();
  if (!S.playing) {
    const b = S.blocks[idx];
    if (b) { S.playerTime = b.start_ms; updatePlayerUI(); }
  }
}

// ── Inline editing ─────────────────────────────────────────────────────────
let _editTimer = null;
function onBlockEdit(idx, el) {
  const block = S.blocks[idx];
  if (!block) return;
  block.lines = el.innerText.split('\n').filter(l => l.trim() !== '');
  block.text = block.lines.join(' ');
  recomputeMetrics(block);
  const metricsEl = el.closest('.block-item').querySelector('.block-metrics');
  if (metricsEl) metricsEl.innerHTML = renderMetrics(block);
  renderPreview();
  // Debounced history save (500ms after last keystroke)
  clearTimeout(_editTimer);
  _editTimer = setTimeout(pushHistory, 500);
}

function recomputeMetrics(block) {
  const dur_s = block.duration_s;
  const total_chars = block.lines.reduce((s, l) => s + l.length, 0);
  block.cps = dur_s > 0 ? Math.round(total_chars / dur_s * 10) / 10 : 0;
  block.cpl_per_line = block.lines.map(l => l.length);
  block.cpl_max = Math.max(...block.cpl_per_line, 0);
}

// ── Split block ────────────────────────────────────────────────────────────
function splitBlock(idx) {
  const block = S.blocks[idx];
  if (!block) return;

  pushHistory();

  const text = block.lines.join(' ');
  const words = text.split(' ');
  if (words.length < 2) return;

  const mid = Math.floor(words.length / 2);
  const textA = words.slice(0, mid).join(' ');
  const textB = words.slice(mid).join(' ');

  const midMs = block.start_ms + Math.round((block.end_ms - block.start_ms) / 2);
  const gapMs = Math.round((S.rules.min_gap || 0.12) * 1000);

  const blockA = {
    ...block,
    lines: [textA],
    end_ms: midMs - gapMs,
    text: textA,
    start_tc: block.start_tc,
    end_tc: msToTC(midMs - gapMs),
    duration_s: (midMs - gapMs - block.start_ms) / 1000,
    modified: true,
  };
  const blockB = {
    index: block.index + 0.5, // temp, will renumber
    lines: [textB],
    start_ms: midMs,
    end_ms: block.end_ms,
    text: textB,
    start_tc: msToTC(midMs),
    end_tc: block.end_tc,
    duration_s: (block.end_ms - midMs) / 1000,
    cps: 0, cpl_per_line: [], cpl_max: 0,
    modified: true,
  };

  recomputeMetrics(blockA);
  recomputeMetrics(blockB);

  S.blocks.splice(idx, 1, blockA, blockB);

  // Renumber all blocks
  S.blocks.forEach((b, i) => { b.index = i + 1; });

  renderBlockList();
  selectBlock(idx);
}

// ── Merge block with previous ──────────────────────────────────────────────
function mergeBlock(idx) {
  if (idx === 0) return;
  pushHistory();
  const prev = S.blocks[idx - 1];
  const curr = S.blocks[idx];

  const mergedLines = [...prev.lines, ...curr.lines];
  const merged = {
    ...prev,
    lines: mergedLines,
    end_ms: curr.end_ms,
    end_tc: curr.end_tc,
    duration_s: (curr.end_ms - prev.start_ms) / 1000,
    text: mergedLines.join(' '),
    modified: true,
  };
  recomputeMetrics(merged);

  S.blocks.splice(idx - 1, 2, merged);
  S.blocks.forEach((b, i) => { b.index = i + 1; });

  renderBlockList();
  selectBlock(Math.max(0, idx - 1));
}

// ── Compare ────────────────────────────────────────────────────────────────
function toggleCompare() {
  S.compareMode = !S.compareMode;
  btnCompare.textContent = S.compareMode ? 'Masquer original' : 'Avant / Après';
  renderBlockList();
}

// ── Preview ────────────────────────────────────────────────────────────────
function renderPreview() {
  const block = S.blocks[S.selectedIdx];
  previewSub.textContent = block ? block.lines.join('\n') : '';
}

// ── Export ─────────────────────────────────────────────────────────────────
async function doExport() {
  const payload = {
    filename: S.filename,
    blocks: S.blocks.map(b => ({ index: b.index, start_ms: b.start_ms, end_ms: b.end_ms, lines: b.lines })),
  };
  const res = await fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) { alert('Erreur export'); return; }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="([^"]+)"/);
  a.download = m ? m[1] : 'calibrated.srt';
  a.click();
  URL.revokeObjectURL(url);
}

// ── Player ─────────────────────────────────────────────────────────────────
function togglePlay() {
  S.playing ? stopPlayer() : startPlayer();
}

function startPlayer() {
  S.playing = true;
  S.playerLastTS = null;
  btnPlay.textContent = '⏸';
  S.playerRAF = requestAnimationFrame(playerTick);
}

function stopPlayer() {
  S.playing = false;
  btnPlay.textContent = '▶';
  if (S.playerRAF) cancelAnimationFrame(S.playerRAF);
}

function playerTick(ts) {
  if (!S.playing) return;
  if (S.playerLastTS !== null) {
    S.playerTime += (ts - S.playerLastTS) * S.playerSpeed;
    if (S.playerTime >= S.playerDuration) { S.playerTime = S.playerDuration; stopPlayer(); }
  }
  S.playerLastTS = ts;
  updatePlayerUI();
  S.playerRAF = requestAnimationFrame(playerTick);
}

function updatePlayerUI() {
  const t = S.playerTime;
  const dur = S.playerDuration || 1;
  playerTC.textContent = msToTC(t);
  playerCursor.style.left = Math.min(100, (t / dur) * 100) + '%';

  const active = S.blocks.findIndex(b => t >= b.start_ms && t < b.end_ms);
  previewSub.textContent = active >= 0 ? S.blocks[active].lines.join('\n') : '';

  if (active >= 0 && active !== S.selectedIdx) {
    S.selectedIdx = active;
    document.querySelectorAll('.block-item').forEach(el => {
      const same = parseInt(el.dataset.idx) === active;
      el.classList.toggle('active', same);
      if (same) el.scrollIntoView({ block: 'nearest' });
    });
  }
}

function msToTC(ms) {
  ms = Math.max(0, Math.round(ms));
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const mil = ms % 1000;
  return `${p2(h)}:${p2(m)}:${p2(s)},${p3(mil)}`;
}
function p2(n) { return String(n).padStart(2,'0'); }
function p3(n) { return String(n).padStart(3,'0'); }

// ── Batch ──────────────────────────────────────────────────────────────────
function addBatchFiles(files) {
  S.batchFiles = [...S.batchFiles, ...files];
  renderBatchFileList();
  $('btn-batch-calibrate').disabled = S.batchFiles.length === 0;
}

function renderBatchFileList() {
  const list = $('batch-file-list');
  list.innerHTML = S.batchFiles.map((f, i) =>
    `<div class="batch-file-item">
      <span>${f.name}</span>
      <button class="btn btn-ghost btn-sm" onclick="removeBatchFile(${i})">✕</button>
    </div>`
  ).join('');
}

window.removeBatchFile = i => {
  S.batchFiles.splice(i, 1);
  renderBatchFileList();
  $('btn-batch-calibrate').disabled = S.batchFiles.length === 0;
};

async function doBatchCalibrate() {
  if (!S.batchFiles.length) return;
  loadingMsg.textContent = `Calibrage de ${S.batchFiles.length} fichier(s)…`;
  loading.classList.remove('hidden');

  const rules = getFormRules();
  const fd = new FormData();
  S.batchFiles.forEach(f => fd.append('files', f));
  fd.append('format', S.batchFormat);
  fd.append('cpl', rules.cpl);
  fd.append('cps', rules.cps);
  fd.append('max_lines', rules.max_lines);
  fd.append('min_duration', rules.min_duration);
  fd.append('max_duration', rules.max_duration);
  fd.append('min_gap', rules.min_gap);
  if (rules.source_fps) fd.append('source_fps', rules.source_fps);
  if (rules.target_fps) fd.append('target_fps', rules.target_fps);
  fd.append('semantic', rules.semantic ? 'true' : 'false');

  try {
    const res = await fetch('/api/batch', { method: 'POST', body: fd });
    if (!res.ok) { alert('Erreur batch'); return; }
    const summaryRaw = res.headers.get('X-Subcal-Summary');
    const summary = summaryRaw ? JSON.parse(summaryRaw) : [];
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'subcal_batch.zip'; a.click();
    URL.revokeObjectURL(url);
    const resultsEl = $('batch-results');
    resultsEl.innerHTML = summary.map(r =>
      `<div class="batch-result-item ${r.errors.length ? 'has-errors' : ''}">
        <strong>${r.filename}</strong> — ${r.report}
        ${r.errors.length ? `<br><span style="color:var(--error)">${r.errors.join(', ')}</span>` : ''}
      </div>`
    ).join('');
  } catch(e) { alert('Erreur : ' + e.message); }
  finally { loading.classList.add('hidden'); }
}

// ── Search & Replace ──────────────────────────────────────────────────────
function openSearchBar() {
  const bar = $('search-bar');
  bar.classList.remove('hidden');
  const inp = $('search-input');
  inp.focus();
  inp.select();
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function updateSearchCount() {
  const q = $('search-input').value.trim();
  if (!q || !S.blocks.length) { $('search-count').textContent = ''; return; }
  let count = 0;
  const re = new RegExp(escapeRegex(q), 'gi');
  S.blocks.forEach(b => b.lines.forEach(l => {
    count += (l.match(re) || []).length;
  }));
  $('search-count').textContent = `${count} résultat${count !== 1 ? 's' : ''}`;
}

function doReplaceAll() {
  const q = $('search-input').value;
  const r = $('replace-input').value;
  if (!q || !S.blocks.length) return;

  const re = new RegExp(escapeRegex(q), 'gi');
  // Count occurrences first (before modifying)
  let total = 0;
  S.blocks.forEach(b => b.lines.forEach(l => { total += (l.match(re) || []).length; }));
  if (total === 0) { $('search-count').textContent = '0 résultat'; return; }

  pushHistory();

  S.blocks.forEach(b => {
    const newLines = b.lines.map(l => l.replace(re, r));
    if (newLines.join('\n') !== b.lines.join('\n')) {
      b.lines = newLines;
      b.text = newLines.join(' ');
      b.modified = true;
      recomputeMetrics(b);
    }
  });

  $('search-count').textContent = `${total} remplacement${total !== 1 ? 's' : ''} effectué${total !== 1 ? 's' : ''}`;
  renderBlockList();
  renderPreview();
}

// ── Normalisation des chiffres ─────────────────────────────────────────────
async function doNormalize() {
  if (!S.blocks.length) return;

  loadingMsg.textContent = 'Normalisation des chiffres…';
  loading.classList.remove('hidden');

  try {
    const res = await fetch('/api/normalize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks: S.blocks }),
    });
    if (!res.ok) { alert('Erreur normalisation'); return; }
    const data = await res.json();

    pushHistory();
    S.blocks = data.blocks;
    renderBlockList();
    selectBlock(S.selectedIdx);
  } catch(e) {
    alert('Erreur : ' + e.message);
  } finally {
    loading.classList.add('hidden');
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────
init();
