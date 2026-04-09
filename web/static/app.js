/* SubCal — Interface web (Phase 2) */

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  file: null,
  filename: '',
  blocks: [],          // calibrated blocks (mutable)
  originalBlocks: [],  // original blocks for compare
  rules: {},
  selectedIndex: 0,    // currently highlighted block
  compareMode: false,
  filterModified: false,
  filterErrors: false,
  format: '16:9',      // current format preset
  presets: {},
  // Player
  playerRunning: false,
  playerTime: 0,       // ms
  playerSpeed: 1,
  playerRAF: null,
  playerLastTS: null,
  playerDuration: 0,
  // Batch
  batchMode: false,
  batchFiles: [],
  batchFormat: '16:9',
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const importPanel   = $('import-panel');
const batchPanel    = $('batch-panel');
const editorPanel   = $('editor-panel');
const loading       = $('loading');
const dropZone      = $('drop-zone');
const fileInput     = $('file-input');
const btnCalibrate  = $('btn-calibrate');
const btnNew        = $('btn-new');
const btnExport     = $('btn-export');
const btnCompare    = $('btn-compare');
const btnPlay       = $('btn-play');
const blockList     = $('block-list');
const previewFrame  = $('preview-frame');
const previewSub    = $('preview-subtitle');
const previewBg     = $('preview-bg');
const playerTC      = $('player-tc');
const playerCursor  = $('player-cursor');
const playerProgress = $('player-progress');
const playerSpeed   = $('player-speed');
const filterModified = $('filter-modified');
const filterErrors  = $('filter-errors');
const fpsBadge      = $('fps-badge');
const editorFilename = $('editor-filename');
const editorReport  = $('editor-report');

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  const res = await fetch('/api/presets');
  state.presets = await res.json();
  applyPresetToUI('16:9');
  setupEventListeners();
}

// ── Event listeners ────────────────────────────────────────────────────────
function setupEventListeners() {
  // Drop zone
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f && f.name.endsWith('.srt')) setFile(f);
  });
  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

  // Format buttons
  document.querySelectorAll('.btn-format').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.closest('#batch-format-btns')) return; // handled separately
      document.querySelectorAll('#import-panel .btn-format').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.format = btn.dataset.format;
      applyPresetToUI(state.format);
    });
  });

  // Config sliders
  const sliders = [
    ['cfg-cpl', 'lbl-cpl', v => v],
    ['cfg-cps', 'lbl-cps', v => v],
    ['cfg-lines', 'lbl-lines', v => v],
    ['cfg-mindur', 'lbl-mindur', v => parseFloat(v).toFixed(1)],
    ['cfg-maxdur', 'lbl-maxdur', v => parseFloat(v).toFixed(1)],
    ['cfg-gap', 'lbl-gap', v => v],
  ];
  sliders.forEach(([id, lbl, fmt]) => {
    const el = $(id);
    el.addEventListener('input', () => { $(lbl).textContent = fmt(el.value); checkFPSBadge(); });
  });

  $('cfg-fps-src').addEventListener('change', checkFPSBadge);
  $('cfg-fps-tgt').addEventListener('change', checkFPSBadge);

  // Calibrate
  btnCalibrate.addEventListener('click', doCalibrate);

  // Editor actions
  btnNew.addEventListener('click', showImport);
  btnExport.addEventListener('click', doExport);
  btnCompare.addEventListener('click', toggleCompare);
  filterModified.addEventListener('change', () => { state.filterModified = filterModified.checked; renderBlockList(); });
  filterErrors.addEventListener('change', () => { state.filterErrors = filterErrors.checked; renderBlockList(); });

  // Preview format toggle
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

  // Player
  btnPlay.addEventListener('click', togglePlay);
  playerSpeed.addEventListener('change', () => { state.playerSpeed = parseFloat(playerSpeed.value); });
  $('player-progress-wrap').addEventListener('click', e => {
    const rect = playerProgress.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    state.playerTime = Math.round(ratio * state.playerDuration);
    updatePlayerUI();
  });

  // Batch mode toggle
  $('btn-batch-toggle').addEventListener('click', toggleBatchMode);
  const batchDrop = $('batch-drop-zone');
  const batchInput = $('batch-file-input');
  batchDrop.addEventListener('dragover', e => { e.preventDefault(); batchDrop.classList.add('dragover'); });
  batchDrop.addEventListener('dragleave', () => batchDrop.classList.remove('dragover'));
  batchDrop.addEventListener('drop', e => {
    e.preventDefault();
    batchDrop.classList.remove('dragover');
    addBatchFiles(Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.srt')));
  });
  batchDrop.addEventListener('click', () => batchInput.click());
  batchInput.addEventListener('change', () => addBatchFiles(Array.from(batchInput.files)));

  document.querySelectorAll('#batch-format-btns .btn-format').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#batch-format-btns .btn-format').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.batchFormat = btn.dataset.format;
    });
  });

  $('btn-batch-calibrate').addEventListener('click', doBatchCalibrate);
}

// ── File handling ──────────────────────────────────────────────────────────
function setFile(f) {
  state.file = f;
  state.filename = f.name;
  dropZone.classList.add('has-file');
  dropZone.querySelector('p').textContent = f.name;
  btnCalibrate.disabled = false;
}

function applyPresetToUI(fmt) {
  const p = state.presets[fmt];
  if (!p) return;
  $('cfg-cpl').value = p.max_cpl; $('lbl-cpl').textContent = p.max_cpl;
  $('cfg-cps').value = p.max_cps; $('lbl-cps').textContent = p.max_cps;
  $('cfg-lines').value = p.max_lines; $('lbl-lines').textContent = p.max_lines;
}

function checkFPSBadge() {
  const src = $('cfg-fps-src').value;
  const tgt = $('cfg-fps-tgt').value;
  if (src && tgt && src !== tgt) {
    fpsBadge.textContent = `Conversion framerate active : ${src} → ${tgt} fps (ratio ${(parseFloat(tgt)/parseFloat(src)).toFixed(5)})`;
    fpsBadge.classList.remove('hidden');
  } else {
    fpsBadge.classList.add('hidden');
  }
}

// ── Calibrate ──────────────────────────────────────────────────────────────
async function doCalibrate() {
  if (!state.file) return;
  loading.classList.remove('hidden');

  const fd = new FormData();
  fd.append('file', state.file);
  fd.append('format', state.format);
  fd.append('cpl',   $('cfg-cpl').value);
  fd.append('cps',   $('cfg-cps').value);
  fd.append('max_lines', $('cfg-lines').value);
  fd.append('min_duration', $('cfg-mindur').value);
  fd.append('max_duration', $('cfg-maxdur').value);
  fd.append('min_gap', (parseFloat($('cfg-gap').value) / 1000).toFixed(3));
  const fpsSrc = $('cfg-fps-src').value;
  const fpsTgt = $('cfg-fps-tgt').value;
  if (fpsSrc) fd.append('source_fps', fpsSrc);
  if (fpsTgt) fd.append('target_fps', fpsTgt);
  fd.append('semantic', $('cfg-semantic').checked ? 'true' : 'false');

  try {
    const res = await fetch('/api/calibrate', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json();
      alert('Erreur : ' + (err.detail || res.statusText));
      return;
    }
    const data = await res.json();
    state.blocks = data.blocks;
    state.originalBlocks = data.original_blocks;
    state.rules = data.rules;

    // Compute player duration from last block end
    state.playerDuration = state.blocks.length
      ? state.blocks[state.blocks.length - 1].end_ms
      : 0;
    state.playerTime = 0;
    stopPlayer();

    editorFilename.textContent = data.filename;
    editorReport.textContent = data.report;

    showEditor();
    renderBlockList();
    selectBlock(0);
  } catch (e) {
    alert('Erreur réseau : ' + e.message);
  } finally {
    loading.classList.add('hidden');
  }
}

// ── Panel visibility ───────────────────────────────────────────────────────
function showImport() {
  stopPlayer();
  editorPanel.classList.add('hidden');
  if (state.batchMode) {
    batchPanel.classList.remove('hidden');
  } else {
    importPanel.classList.remove('hidden');
  }
}

function showEditor() {
  importPanel.classList.add('hidden');
  batchPanel.classList.add('hidden');
  editorPanel.classList.remove('hidden');
}

function toggleBatchMode() {
  state.batchMode = !state.batchMode;
  if (state.batchMode) {
    importPanel.classList.add('hidden');
    batchPanel.classList.remove('hidden');
    $('btn-batch-toggle').textContent = 'Fichier unique';
  } else {
    batchPanel.classList.add('hidden');
    importPanel.classList.remove('hidden');
    $('btn-batch-toggle').textContent = 'Batch';
  }
}

// ── Block list rendering ───────────────────────────────────────────────────
function renderBlockList() {
  blockList.innerHTML = '';
  const blocks = state.blocks.filter(b => {
    if (state.filterModified && !b.modified) return false;
    if (state.filterErrors && !blockHasError(b)) return false;
    return true;
  });

  blocks.forEach((block, i) => {
    const item = document.createElement('div');
    item.className = 'block-item' +
      (block.modified ? ' modified' : '') +
      (blockHasError(block) ? ' has-error' : '') +
      (state.compareMode ? ' compare-mode' : '') +
      (block.index - 1 === state.selectedIndex ? ' active' : '');
    item.dataset.idx = block.index - 1;

    // Original text for compare
    const orig = state.originalBlocks.find(o => o.index === block.index);
    const origText = orig ? orig.lines.join('\n') : '';

    item.innerHTML = `
      <div class="block-index">${block.index}</div>
      <div class="block-content">
        <div class="block-timecodes">${block.start_tc} → ${block.end_tc} (${block.duration_s.toFixed(2)}s)</div>
        <div class="block-original">${escHtml(origText)}</div>
        <div class="block-text-wrap" contenteditable="true" spellcheck="false" data-idx="${block.index - 1}">${escHtml(block.lines.join('\n'))}</div>
        ${block.modified ? '<span class="badge-modified">modifié</span>' : ''}
      </div>
      <div class="block-metrics">
        ${renderMetrics(block)}
      </div>`;

    // Click to select
    item.addEventListener('click', e => {
      if (e.target.classList.contains('block-text-wrap')) return;
      selectBlock(parseInt(item.dataset.idx));
    });

    // Inline editing
    const editor = item.querySelector('.block-text-wrap');
    editor.addEventListener('input', () => onBlockEdit(parseInt(editor.dataset.idx), editor));
    editor.addEventListener('focus', () => selectBlock(parseInt(editor.dataset.idx)));

    blockList.appendChild(item);
  });
}

function renderMetrics(block) {
  const r = state.rules;
  const cpsClass = !r.max_cps ? 'ok' : block.cps > r.max_cps ? 'error' : block.cps > r.max_cps * 0.85 ? 'warn' : 'ok';
  let html = `<span class="metric ${cpsClass}">CPS ${block.cps}</span>`;
  block.cpl_per_line.forEach((cpl, i) => {
    const cls = !r.max_cpl ? 'ok' : cpl > r.max_cpl ? 'error' : cpl > r.max_cpl * 0.85 ? 'warn' : 'ok';
    html += `<span class="metric ${cls}">L${i+1} ${cpl}c</span>`;
  });
  return html;
}

function blockHasError(block) {
  const r = state.rules;
  if (r.max_cps && block.cps > r.max_cps) return true;
  if (r.max_cpl && block.cpl_max > r.max_cpl) return true;
  return false;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Block selection & preview ──────────────────────────────────────────────
function selectBlock(idx) {
  state.selectedIndex = idx;
  // Update active class
  document.querySelectorAll('.block-item').forEach(item => {
    item.classList.toggle('active', parseInt(item.dataset.idx) === idx);
  });
  renderPreview();
  updatePlayerTimeToBlock(idx);
}

function renderPreview() {
  const block = state.blocks[state.selectedIndex];
  if (!block) { previewSub.textContent = ''; return; }
  previewSub.textContent = block.lines.join('\n');
}

function updatePlayerTimeToBlock(idx) {
  const block = state.blocks[idx];
  if (!block) return;
  state.playerTime = block.start_ms;
  updatePlayerUI();
}

// ── Inline editing ─────────────────────────────────────────────────────────
function onBlockEdit(idx, el) {
  const block = state.blocks[idx];
  if (!block) return;
  const text = el.innerText;
  block.lines = text.split('\n').filter(l => l.trim() !== '');
  block.text = block.lines.join(' ');

  // Recompute metrics
  const dur_s = block.duration_s;
  const total_chars = block.lines.reduce((s, l) => s + l.length, 0);
  block.cps = dur_s > 0 ? Math.round(total_chars / dur_s * 10) / 10 : 0;
  block.cpl_per_line = block.lines.map(l => l.length);
  block.cpl_max = Math.max(...block.cpl_per_line, 0);

  // Update metrics in DOM without full re-render
  const metricsEl = el.closest('.block-item').querySelector('.block-metrics');
  if (metricsEl) metricsEl.innerHTML = renderMetrics(block);

  renderPreview();
}

// ── Compare toggle ─────────────────────────────────────────────────────────
function toggleCompare() {
  state.compareMode = !state.compareMode;
  btnCompare.textContent = state.compareMode ? 'Masquer original' : 'Avant / Après';
  renderBlockList();
}

// ── Export ─────────────────────────────────────────────────────────────────
async function doExport() {
  const payload = {
    filename: state.filename,
    blocks: state.blocks.map(b => ({
      index: b.index,
      start_ms: b.start_ms,
      end_ms: b.end_ms,
      lines: b.lines,
    })),
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
  const match = cd.match(/filename="([^"]+)"/);
  a.download = match ? match[1] : 'calibrated.srt';
  a.click();
  URL.revokeObjectURL(url);
}

// ── Player ─────────────────────────────────────────────────────────────────
function togglePlay() {
  if (state.playerRunning) {
    stopPlayer();
  } else {
    startPlayer();
  }
}

function startPlayer() {
  state.playerRunning = true;
  state.playerLastTS = null;
  btnPlay.textContent = '⏸';
  requestAnimationFrame(playerTick);
}

function stopPlayer() {
  state.playerRunning = false;
  btnPlay.textContent = '▶';
  if (state.playerRAF) cancelAnimationFrame(state.playerRAF);
}

function playerTick(ts) {
  if (!state.playerRunning) return;
  if (state.playerLastTS !== null) {
    const elapsed = (ts - state.playerLastTS) * state.playerSpeed;
    state.playerTime += elapsed;
    if (state.playerTime >= state.playerDuration) {
      state.playerTime = state.playerDuration;
      stopPlayer();
    }
  }
  state.playerLastTS = ts;
  updatePlayerUI();
  state.playerRAF = requestAnimationFrame(playerTick);
}

function updatePlayerUI() {
  const t = state.playerTime;
  const dur = state.playerDuration || 1;

  // Timecode display
  playerTC.textContent = msToTC(t);

  // Progress cursor
  const pct = Math.min(100, (t / dur) * 100);
  playerCursor.style.left = pct + '%';

  // Find active block
  const active = state.blocks.findIndex(b => t >= b.start_ms && t < b.end_ms);
  if (active >= 0) {
    previewSub.textContent = state.blocks[active].lines.join('\n');
    // Scroll to active block if changed
    if (active !== state.selectedIndex) {
      state.selectedIndex = active;
      const item = blockList.querySelector(`[data-idx="${active}"]`);
      if (item) item.scrollIntoView({ block: 'nearest' });
      document.querySelectorAll('.block-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === active);
      });
    }
  } else {
    previewSub.textContent = '';
  }
}

function msToTC(ms) {
  const h   = Math.floor(ms / 3_600_000);
  const m   = Math.floor((ms % 3_600_000) / 60_000);
  const s   = Math.floor((ms % 60_000) / 1_000);
  const mil = Math.floor(ms % 1_000);
  return `${pad2(h)}:${pad2(m)}:${pad2(s)},${pad3(mil)}`;
}
function pad2(n) { return String(n).padStart(2, '0'); }
function pad3(n) { return String(n).padStart(3, '0'); }

// ── Batch ──────────────────────────────────────────────────────────────────
function addBatchFiles(files) {
  state.batchFiles = [...state.batchFiles, ...files];
  renderBatchFileList();
  $('btn-batch-calibrate').disabled = state.batchFiles.length === 0;
}

function renderBatchFileList() {
  const list = $('batch-file-list');
  if (state.batchFiles.length === 0) {
    list.classList.add('hidden');
    return;
  }
  list.classList.remove('hidden');
  list.innerHTML = state.batchFiles.map((f, i) =>
    `<div class="batch-file-item">
      <span>${f.name}</span>
      <button class="btn btn-ghost btn-sm" onclick="removeBatchFile(${i})">✕</button>
    </div>`
  ).join('');
}

window.removeBatchFile = function(i) {
  state.batchFiles.splice(i, 1);
  renderBatchFileList();
  $('btn-batch-calibrate').disabled = state.batchFiles.length === 0;
};

async function doBatchCalibrate() {
  if (state.batchFiles.length === 0) return;
  loading.classList.remove('hidden');

  const fd = new FormData();
  state.batchFiles.forEach(f => fd.append('files', f));
  fd.append('format', state.batchFormat);
  fd.append('cpl',   $('cfg-cpl').value);
  fd.append('cps',   $('cfg-cps').value);
  fd.append('max_lines', $('cfg-lines').value);
  fd.append('min_duration', $('cfg-mindur').value);
  fd.append('max_duration', $('cfg-maxdur').value);
  fd.append('min_gap', (parseFloat($('cfg-gap').value) / 1000).toFixed(3));
  fd.append('semantic', $('cfg-semantic') && $('cfg-semantic').checked ? 'true' : 'false');

  try {
    const res = await fetch('/api/batch', { method: 'POST', body: fd });
    if (!res.ok) { alert('Erreur batch'); return; }

    const summaryHeader = res.headers.get('X-Subcal-Summary');
    const summary = summaryHeader ? JSON.parse(summaryHeader) : [];

    // Download ZIP
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'subcal_batch.zip';
    a.click();
    URL.revokeObjectURL(url);

    // Show summary
    const resultsEl = $('batch-results');
    resultsEl.classList.remove('hidden');
    resultsEl.innerHTML = summary.map(r =>
      `<div class="batch-result-item ${r.errors.length ? 'has-errors' : ''}">
        <strong>${r.filename}</strong> — ${r.report}
        ${r.errors.length ? `<br><span style="color:var(--error)">${r.errors.join(', ')}</span>` : ''}
      </div>`
    ).join('');
  } catch (e) {
    alert('Erreur réseau : ' + e.message);
  } finally {
    loading.classList.add('hidden');
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────
init();
