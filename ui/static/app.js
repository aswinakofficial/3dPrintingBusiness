'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let selectedEngine = 'hunyuan3d';
let selectedGpu = 'A100';
let uploadedFiles = [];
let currentJobId = null;
let statusPollTimer = null;
let allJobs = [];
let compareList = []; // [{job_id, engine}]

const ENGINE_COLORS = { trellis: 'blue', meshroom: 'green', hunyuan3d: 'purple', triposg: 'orange', sf3d: 'teal', spar3d: 'cyan', instantmesh: 'yellow' };

// ── Navigation ────────────────────────────────────────────────────────────────
function showView(name) {
  clearTimeout(statusPollTimer);
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
  selectedEngine = key;
  document.getElementById('generate-views-row')?.classList.toggle('hidden', key !== 'hunyuan3d');
  document.getElementById('meshroom-tips')?.classList.toggle('hidden', key !== 'meshroom');
  updateImageHint();
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
}

function removeFile(idx) {
  uploadedFiles.splice(idx, 1);
  renderThumbs();
  updateImageHint();
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

function updateImageHint() {
  const el = document.getElementById('image-hint');
  const selected = document.querySelector(`.engine-card.selected`);
  if (!selected) return;
  const key = selectedEngine;
  // Fetch limits from DOM label text (or use hardcoded fallback)
  const limits = { trellis:[1,4], meshroom:[10,50], hunyuan3d:[1,6], triposg:[1,1], sf3d:[1,1], spar3d:[1,1], instantmesh:[1,6] };
  const [lo, hi] = limits[key] || [1, 10];
  const n = uploadedFiles.length;
  if (n === 0) {
    el.textContent = `Upload ${lo}–${hi} images for ${key}`;
    el.className = 'text-xs text-gray-500 mb-4';
  } else if (n < lo || n > hi) {
    el.textContent = `⚠ ${key} needs ${lo}–${hi} images (you have ${n})`;
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
  clearInterval(statusPollTimer);

  document.getElementById('status-job-id').textContent = jobId;
  document.getElementById('status-engine').textContent = engine || '—';
  setStatusBadge('queued');
  document.getElementById('status-elapsed').textContent = '—';
  document.getElementById('viewer-section').classList.add('hidden');
  document.getElementById('status-error').classList.add('hidden');

  showView('status');
  pollStatus(jobId);
}

async function pollStatus(jobId) {
  try {
    const res = await fetch(`/jobs/${jobId}/status`);
    if (!res.ok) return;
    const data = await res.json();

    setStatusBadge(data.status);
    if (data.elapsed_s !== null && data.elapsed_s !== undefined) {
      const m = Math.floor(data.elapsed_s / 60);
      const s = data.elapsed_s % 60;
      document.getElementById('status-elapsed').textContent = m ? `${m}m ${s}s` : `${s}s`;
    }

    if (data.status === 'succeeded') {
      await loadViewer(jobId);
      return;
    }
    if (data.status === 'failed') {
      const errEl = document.getElementById('status-error');
      errEl.textContent = data.error || 'Job failed.';
      errEl.classList.remove('hidden');
      return;
    }
  } catch (_) {}

  statusPollTimer = setTimeout(() => pollStatus(jobId), 3000);
}

function setStatusBadge(status) {
  const el = document.getElementById('status-badge');
  el.className = `status-badge ${status}`;
  el.textContent = status.charAt(0).toUpperCase() + status.slice(1);
}

async function loadViewer(jobId) {
  const section = document.getElementById('viewer-section');
  section.classList.remove('hidden');

  // Load 3D model
  const mv = document.getElementById('model-viewer-main');
  mv.src = `/outputs/${jobId}/mesh`;

  // Download link
  document.getElementById('download-btn').href = `/outputs/${jobId}/mesh`;

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
    showView('status');
    if (status === 'succeeded') loadViewer(jobId);
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
