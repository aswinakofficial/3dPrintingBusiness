'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let selectedEngine = 'hunyuan3d';
let selectedGpu = 'A100';
let uploadedFiles = [];
let currentJobId = null;
let statusEventSource = null;
let allJobs = [];
let compareList = []; // [{job_id, engine}]

const ENGINE_COLORS = { trellis: 'blue', meshroom: 'green', hunyuan3d: 'purple', triposg: 'orange', sf3d: 'teal', spar3d: 'cyan', instantmesh: 'yellow' };

const RECOMMENDATIONS = {
  'quality-single':  'triposg',
  'fast-single':     'sf3d',
  'multi-view':      'instantmesh',
  'with-textures':   'hunyuan3d',
  'real-scan':       'meshroom',
};

const QUICKPICK_LABELS = {
  'quality-single':  '📸 1 photo, best quality',
  'fast-single':     '⚡ 1 photo, fastest',
  'multi-view':      '🖼 Multi-view (2–6 photos)',
  'with-textures':   '🎨 PBR textures',
  'real-scan':       '📷 Real scan (50+ photos)',
};

// ── Navigation ────────────────────────────────────────────────────────────────
function showView(name) {
  if (statusEventSource) { statusEventSource.close(); statusEventSource = null; }
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  document.getElementById(`view-${name}`)?.classList.remove('hidden');
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`nav-${name}`)?.classList.add('active');

  if (name === 'history') loadHistory();
  if (name === 'compare') renderCompare();
}

// ── Engine cards ──────────────────────────────────────────────────────────────
async function initEngines() {
  const grid = document.getElementById('engine-cards');
  try {
    const res = await fetch('/engines');
    if (!res.ok) throw new Error(`/engines returned ${res.status}`);
    const engines = await res.json();
    grid.innerHTML = '';
    for (const [key, meta] of Object.entries(engines)) {
      const col = meta.color;
      const card = document.createElement('div');
      card.className = `engine-card bg-gray-900 rounded-xl p-4 ${key === selectedEngine ? 'selected ' + col : ''}`;
      card.id = `engine-card-${key}`;
      card.innerHTML = `
        <div class="flex items-center gap-2 mb-2">
          <span class="text-xs font-semibold px-2 py-0.5 rounded engine-badge-${col}">${meta.label}</span>
        </div>
        <p class="text-xs text-gray-400 leading-relaxed">${meta.desc}</p>
        <p class="text-xs text-gray-600 mt-2">${meta.min_images}–${meta.max_images} image${meta.max_images > 1 ? 's' : ''}</p>
      `;
      card.addEventListener('click', () => selectEngine(key, col));
      grid.appendChild(card);
    }
    updateImageHint();
    document.getElementById('generate-views-row')?.classList.toggle('hidden', selectedEngine !== 'hunyuan3d');
    document.getElementById('meshroom-tips')?.classList.toggle('hidden', selectedEngine !== 'meshroom');
  } catch (e) {
    grid.innerHTML = `<p class="text-red-400 text-sm col-span-full">Failed to load engines: ${e.message}</p>`;
  }
}

function selectEngine(key, col) {
  document.querySelectorAll('.engine-card').forEach(c => {
    c.classList.remove('selected', 'blue', 'green', 'purple', 'orange', 'teal', 'cyan', 'yellow');
  });
  const card = document.getElementById(`engine-card-${key}`);
  card?.classList.add('selected', col || ENGINE_COLORS[key] || 'blue');
  card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  selectedEngine = key;
  document.getElementById('generate-views-row')?.classList.toggle('hidden', key !== 'hunyuan3d');
  document.getElementById('meshroom-tips')?.classList.toggle('hidden', key !== 'meshroom');
  updateImageHint();
}

function applyRecommendation(pick) {
  const key = RECOMMENDATIONS[pick];
  if (key) selectEngine(key, ENGINE_COLORS[key]);
}

// ── Image upload ──────────────────────────────────────────────────────────────
function handleDrop(e) {
  e.preventDefault();
  addFiles(e.dataTransfer.files);
}

function addFiles(fileList) {
  for (const f of fileList) {
    if (f.type.startsWith('image/')) uploadedFiles.push(f);
  }
  renderThumbs();
  updateImageHint();
  suggestEngine();
}

function removeFile(idx) {
  uploadedFiles.splice(idx, 1);
  renderThumbs();
  updateImageHint();
  suggestEngine();
}

function renderThumbs() {
  const strip = document.getElementById('thumb-strip');
  strip.innerHTML = '';
  uploadedFiles.forEach((f, i) => {
    const url = URL.createObjectURL(f);
    const wrap = document.createElement('div');
    wrap.className = 'relative group';
    wrap.innerHTML = `
      <img src="${url}" class="thumb" />
      <button onclick="removeFile(${i})"
        class="absolute -top-1 -right-1 bg-red-600 rounded-full w-4 h-4 text-xs leading-none hidden group-hover:flex items-center justify-center text-white">×</button>
    `;
    strip.appendChild(wrap);
  });
}

function suggestEngine() {
  const banner = document.getElementById('engine-suggest-banner');
  const n = uploadedFiles.length;
  if (!banner) return;

  let suggestion = null;
  if (n === 1) suggestion = { key: 'triposg', label: 'TripoSG (best single-image quality)' };
  else if (n >= 2 && n <= 6) suggestion = { key: 'instantmesh', label: 'InstantMesh (multi-view)' };
  else if (n >= 10) suggestion = { key: 'meshroom', label: 'Meshroom (photogrammetry scan)' };

  if (suggestion && suggestion.key !== selectedEngine) {
    banner.innerHTML = `
      <span class="text-yellow-300">💡 ${n} image${n>1?'s':''} uploaded —</span>
      <button onclick="selectEngine('${suggestion.key}','${ENGINE_COLORS[suggestion.key]}');document.getElementById('engine-suggest-banner').classList.add('hidden')"
        class="underline text-yellow-200 hover:text-white ml-1">
        switch to ${suggestion.label}
      </button>
      <button onclick="document.getElementById('engine-suggest-banner').classList.add('hidden')"
        class="ml-3 text-gray-500 hover:text-white">✕</button>
    `;
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
}

function updateImageHint() {
  const el = document.getElementById('image-hint');
  const limits = { trellis:[1,4], meshroom:[10,50], hunyuan3d:[1,6], triposg:[1,1], sf3d:[1,1], spar3d:[1,1], instantmesh:[1,6] };
  const [lo, hi] = limits[selectedEngine] || [1, 10];
  const n = uploadedFiles.length;
  if (n === 0) {
    el.textContent = `Upload ${lo}–${hi} images for ${selectedEngine}`;
    el.className = 'text-xs text-gray-500 mb-4';
  } else if (n < lo || n > hi) {
    el.textContent = `⚠ ${selectedEngine} needs ${lo}–${hi} images (you have ${n})`;
    el.className = 'text-xs text-orange-400 mb-4';
  } else {
    el.textContent = `✓ ${n} image${n>1?'s':''} ready`;
    el.className = 'text-xs text-green-400 mb-4';
  }
}

function updateGenerateViewsHint() {
  const checked = document.getElementById('toggle-generate-views').checked;
  const hint = document.getElementById('generate-views-hint');
  hint.textContent = checked
    ? 'Zero123++ will run first (~60s) to create front/right/back/left views, then Hunyuan3D-2mv gets all 4'
    : 'Synthesise 4 views from your front image — recommended for single-image inputs';
}

// ── GPU param ─────────────────────────────────────────────────────────────────
function setParam(param, val) {
  if (param === 'gpu') {
    selectedGpu = val;
    document.querySelectorAll('[id^="gpu-"]').forEach(b => b.classList.remove('active'));
    document.getElementById(`gpu-${val}`)?.classList.add('active');
  }
}

// ── Job submission ────────────────────────────────────────────────────────────
async function submitJob() {
  const errEl = document.getElementById('submit-error');
  errEl.classList.add('hidden');

  if (uploadedFiles.length === 0) {
    showError(errEl, 'Please upload at least one image.');
    return;
  }

  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.textContent = 'Submitting…';

  const form = new FormData();
  form.append('engine', selectedEngine);
  form.append('gpu_sku', selectedGpu);
  form.append('max_runtime_minutes', document.getElementById('runtime-slider').value);
  form.append('generate_views', document.getElementById('toggle-generate-views').checked ? 'true' : 'false');
  form.append('target_height_mm', document.getElementById('height-slider').value);
  uploadedFiles.forEach(f => form.append('images', f));

  try {
    const res = await fetch('/jobs', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Submission failed');
    }
    const { job_id } = await res.json();
    uploadedFiles = [];
    renderThumbs();
    openStatusView(job_id, selectedEngine);
  } catch (e) {
    showError(errEl, e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Submit Job';
  }
}

function showError(el, msg) {
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ── Status view ───────────────────────────────────────────────────────────────
function openStatusView(jobId, engine) {
  currentJobId = jobId;
  if (statusEventSource) { statusEventSource.close(); statusEventSource = null; }

  document.getElementById('status-job-id').textContent = jobId;
  document.getElementById('status-engine').textContent = engine || '—';
  setStatusBadge('queued');
  document.getElementById('status-elapsed').textContent = '—';
  document.getElementById('viewer-section').classList.add('hidden');
  document.getElementById('status-error').classList.add('hidden');
  document.getElementById('failure-panel')?.classList.add('hidden');

  showView('status');
  streamStatus(jobId);
}

function streamStatus(jobId) {
  if (statusEventSource) { statusEventSource.close(); }

  const es = new EventSource(`/jobs/${jobId}/stream`);
  statusEventSource = es;

  es.onmessage = async (evt) => {
    let data;
    try { data = JSON.parse(evt.data); } catch { return; }

    setStatusBadge(data.status);
    if (data.elapsed_s != null) {
      const m = Math.floor(data.elapsed_s / 60);
      const s = data.elapsed_s % 60;
      document.getElementById('status-elapsed').textContent = m ? `${m}m ${s}s` : `${s}s`;
    }

    if (data.status === 'succeeded') {
      es.close();
      statusEventSource = null;
      await loadViewer(jobId);
    } else if (data.status === 'failed') {
      es.close();
      statusEventSource = null;
      await showFailure(jobId, data.error);
    }
  };

  es.onerror = () => {
    es.close();
    statusEventSource = null;
    // Fall back to single poll after SSE error
    setTimeout(() => pollStatusOnce(jobId), 5000);
  };
}

async function pollStatusOnce(jobId) {
  try {
    const res = await fetch(`/jobs/${jobId}/status`);
    if (!res.ok) return;
    const data = await res.json();
    setStatusBadge(data.status);
    if (data.status === 'succeeded') {
      await loadViewer(jobId);
    } else if (data.status === 'failed') {
      await showFailure(jobId, data.error);
    } else {
      setTimeout(() => pollStatusOnce(jobId), 5000);
    }
  } catch (_) {
    setTimeout(() => pollStatusOnce(jobId), 10000);
  }
}

async function showFailure(jobId, errorSummary) {
  const errEl = document.getElementById('status-error');
  errEl.textContent = errorSummary || 'Job failed.';
  errEl.classList.remove('hidden');

  const panel = document.getElementById('failure-panel');
  if (!panel) return;
  panel.classList.remove('hidden');

  try {
    const res = await fetch(`/jobs/${jobId}/log`);
    if (res.ok) {
      const { log } = await res.json();
      const pre = document.getElementById('failure-log');
      if (pre) pre.textContent = log || '(container log not available — job may not have started yet)';
    }
  } catch (_) {}
}

function setStatusBadge(status) {
  const el = document.getElementById('status-badge');
  el.className = `status-badge ${status}`;
  el.textContent = status.charAt(0).toUpperCase() + status.slice(1);
}

async function loadViewer(jobId) {
  const section = document.getElementById('viewer-section');
  section.classList.remove('hidden');

  const mv = document.getElementById('model-viewer-main');
  mv.src = `/outputs/${jobId}/mesh`;

  document.getElementById('download-btn').href = `/outputs/${jobId}/mesh`;
  document.getElementById('download-stl-btn').href = `/outputs/${jobId}/stl`;

  // Print quality badge
  try {
    const rpt = await fetch(`/outputs/${jobId}/print-report`).then(r => r.json());
    const score = rpt.print_score ?? 0;
    const scoreColor = score >= 80 ? 'text-green-400' : score >= 50 ? 'text-yellow-400' : 'text-red-400';
    const wt = rpt.watertight ? '<span class="text-green-400">✓</span>' : '<span class="text-red-400">✗</span>';
    const dims = rpt.dimensions_mm
      ? rpt.dimensions_mm.map(d => `${(d/10).toFixed(1)}`).join(' × ') + ' cm'
      : '—';
    const vol = rpt.volume_mm3 != null
      ? `${(rpt.volume_mm3 / 1000).toFixed(1)} cm³`
      : '—';
    const issueHtml = (rpt.issues || []).map(
      i => `<p class="text-xs text-orange-400 mt-1">⚠ ${i}</p>`
    ).join('');
    const texBadge = rpt.textured
      ? '<span class="text-xs text-purple-400 font-semibold">PBR Textured</span>'
      : '';
    document.getElementById('print-quality').innerHTML = `
      <div class="flex justify-between items-center"><span class="text-gray-500">Print Score</span><span class="${scoreColor} font-bold">${score}/100</span></div>
      <div class="flex justify-between items-center"><span class="text-gray-500">Watertight</span><span>${wt}</span></div>
      <div class="flex justify-between items-center"><span class="text-gray-500">Dimensions</span><span class="text-xs">${dims}</span></div>
      <div class="flex justify-between items-center"><span class="text-gray-500">Volume</span><span>${vol}</span></div>
      ${texBadge ? `<div class="mt-1">${texBadge}</div>` : ''}
      ${issueHtml}
    `;
  } catch (_) {
    document.getElementById('print-quality').innerHTML =
      '<p class="text-xs text-gray-600">Report not available</p>';
  }

  // Metadata
  try {
    const meta = await fetch(`/outputs/${jobId}/metadata`).then(r => r.json());
    const stats = document.getElementById('mesh-stats');
    stats.innerHTML = `
      <div class="flex justify-between"><span class="text-gray-500">Vertices</span><span>${(meta.mesh_stats?.vertices||0).toLocaleString()}</span></div>
      <div class="flex justify-between"><span class="text-gray-500">Faces</span><span>${(meta.mesh_stats?.faces||0).toLocaleString()}</span></div>
      <div class="flex justify-between"><span class="text-gray-500">Engine</span><span>${meta.engine||'—'}</span></div>
    `;
  } catch (_) {}

  // Preprocessed thumbnails
  try {
    const imgs = await fetch(`/outputs/${jobId}/preprocessed`).then(r => r.json());
    const thumbs = document.getElementById('input-thumbs');
    thumbs.innerHTML = imgs.map(src => `<img src="${src}" class="thumb-sm" />`).join('');
  } catch (_) {}
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
  const res = await fetch('/jobs');
  allJobs = await res.json();
  renderHistory();
}

function renderHistory() {
  const engineFilter = document.getElementById('filter-engine').value;
  const statusFilter = document.getElementById('filter-status').value;

  let jobs = allJobs;
  if (engineFilter) jobs = jobs.filter(j => j.engine === engineFilter);
  if (statusFilter) jobs = jobs.filter(j => j.status === statusFilter);

  const grid = document.getElementById('history-grid');
  const empty = document.getElementById('history-empty');

  if (jobs.length === 0) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  grid.innerHTML = jobs.map(job => {
    const col = ENGINE_COLORS[job.engine] || 'blue';
    const date = job.created_at ? new Date(job.created_at * 1000).toLocaleString() : '—';
    const thumb = job.has_mesh && job.status === 'succeeded'
      ? `<div class="h-40 bg-gray-950 flex items-center justify-center rounded-t-xl overflow-hidden">
           <model-viewer src="/outputs/${job.job_id}/mesh" auto-rotate
             style="width:100%;height:100%;background:#030712" camera-controls>
           </model-viewer>
         </div>`
      : `<div class="h-40 bg-gray-950 flex items-center justify-center rounded-t-xl text-gray-700 text-4xl">${job.status === 'running' ? '⏳' : job.status === 'failed' ? '✗' : '○'}</div>`;

    return `
      <div class="job-card bg-gray-900 rounded-xl overflow-hidden" onclick="openJob('${job.job_id}', '${job.engine}', '${job.status}')">
        ${thumb}
        <div class="p-3">
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-semibold px-2 py-0.5 rounded engine-badge-${col}">${job.engine}</span>
            <span class="status-badge ${job.status}">${job.status}</span>
          </div>
          <p class="text-xs text-gray-500 mt-2 font-mono truncate">${job.job_id}</p>
          <p class="text-xs text-gray-600">${date}</p>
        </div>
      </div>
    `;
  }).join('');
}

function openJob(jobId, engine, status) {
  if (status === 'running' || status === 'queued') {
    openStatusView(jobId, engine);
  } else {
    currentJobId = jobId;
    document.getElementById('status-job-id').textContent = jobId;
    document.getElementById('status-engine').textContent = engine;
    document.getElementById('status-elapsed').textContent = '—';
    setStatusBadge(status);
    document.getElementById('viewer-section').classList.add('hidden');
    document.getElementById('status-error').classList.add('hidden');
    document.getElementById('failure-panel')?.classList.add('hidden');
    showView('status');
    if (status === 'succeeded') loadViewer(jobId);
    if (status === 'failed') showFailure(jobId, null);
  }
}

// ── Compare ───────────────────────────────────────────────────────────────────
function addToCompare(jobId) {
  if (!jobId) return;
  if (compareList.find(j => j.job_id === jobId)) return;
  if (compareList.length >= 3) compareList.shift();
  const engine = document.getElementById('status-engine').textContent;
  compareList.push({ job_id: jobId, engine });
  showView('compare');
}

function removeFromCompare(jobId) {
  compareList = compareList.filter(j => j.job_id !== jobId);
  renderCompare();
}

function clearCompare() {
  compareList = [];
  renderCompare();
}

function renderCompare() {
  const grid = document.getElementById('compare-grid');
  const empty = document.getElementById('compare-empty');

  if (compareList.length === 0) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  grid.innerHTML = compareList.map(({ job_id, engine }) => {
    const col = ENGINE_COLORS[engine] || 'blue';
    return `
      <div class="bg-gray-900 rounded-xl overflow-hidden">
        <div style="height:420px">
          <model-viewer src="/outputs/${job_id}/mesh" auto-rotate camera-controls
            style="width:100%;height:100%;background:#111827" shadow-intensity="1">
          </model-viewer>
        </div>
        <div class="p-3 flex items-center justify-between">
          <div>
            <span class="text-xs font-semibold px-2 py-0.5 rounded engine-badge-${col}">${engine}</span>
            <p class="text-xs text-gray-500 mt-1 font-mono truncate">${job_id}</p>
          </div>
          <button onclick="removeFromCompare('${job_id}')" class="text-gray-600 hover:text-red-400 text-sm transition">✕</button>
        </div>
      </div>
    `;
  }).join('');
}

// ── Boot ──────────────────────────────────────────────────────────────────────
initEngines();
showView('submit');
