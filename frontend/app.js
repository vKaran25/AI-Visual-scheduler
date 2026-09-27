
// ── State ─────────────────────────────────────────────────────────
let currentDate = new Date();
currentDate.setHours(0,0,0,0);
let currentUser = null;
let presets = [];
let allSlots = [];          // all busy slots from server
     // last free-time search result
let editingSlotId = null;   // null = add mode, number = edit mode
let selectedColor = '#d81b60';
let selectedDays = [];      // repeat days for modal
let dragStart = null;       // {y, minute}

const COLORS = [
  '#d81b60','#e65100','#f9a825','#2e7d32','#00695c',
  '#0277bd','#4527a0','#6a1b9a','#37474f','#3ddc97'
];
const DAY_NAMES = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

// ── DOM refs ──────────────────────────────────────────────────────
const timeline      = document.getElementById('timeline');
const tWrap         = document.getElementById('timeline-wrap');
const dateDisplay   = document.getElementById('date-display');
const datePicker    = document.getElementById('date-picker');
const blocksCount   = document.getElementById('blocks-count');
const blocksList    = document.getElementById('blocks-list');
const freeResults_  = document.getElementById('free-results');
const nowLine       = document.getElementById('now-line');
const dragPreview   = document.getElementById('drag-preview');
const modalOverlay  = document.getElementById('modal-overlay');
const modalTitle    = document.getElementById('modal-title');
const modalSave     = document.getElementById('modal-save');
const modalDelete   = document.getElementById('modal-delete');
const mStart        = document.getElementById('m-start');
const mEnd          = document.getElementById('m-end');
const mLabel        = document.getElementById('m-label');
const colorSwatches = document.getElementById('color-swatches');
const repeatRow     = document.getElementById('repeat-row');
const everyDayBtn   = document.getElementById('every-day-btn');

const userEmail     = document.getElementById('user-email');
const logoutBtn     = document.getElementById('logout-btn');
const presetSelect  = document.getElementById('preset-select');
const presetSummary = document.getElementById('preset-summary');
const presetApplyBtn = document.getElementById('preset-apply-btn');
const presetRemoveBtn = document.getElementById('preset-remove-btn');

// ── Helpers ───────────────────────────────────────────────────────
function pad(n){ return String(n).padStart(2,'0'); }
function dateStr(d){ return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; }
function minutesToTime(m){ return `${pad(Math.floor(m/60))}:${pad(m%60)}`; }
function timeToMinutes(t){ const [h,m]=t.split(':').map(Number); return h*60+m; }
function dateTimeLocalStr(d){ return `${dateStr(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function topPx(m){ return m * (60/60); } // 1px per minute, 60px/hour
function heightPx(m){ return Math.max(m, 40); }

function formatDate(d){
  const days=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

function isToday(d){
  const n=new Date(); n.setHours(0,0,0,0);
  return d.getTime()===n.getTime();
}

function formatHumanDateTime(value){
  if(!value) return 'now';
  const [datePart, timePart] = String(value).split('T');
  if(!datePart || !timePart) return value;

  const [year, month, day] = datePart.split('-').map(Number);
  const parsedDate = new Date(year, month - 1, day);
  const dateLabel = parsedDate.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  });

  const [hour, minute] = timePart.split(':').map(Number);
  const parsedTime = new Date(2000, 0, 1, hour, minute);
  const timeLabel = parsedTime.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit'
  });

  return `${dateLabel} • ${timeLabel}`;
}

// ── Toast ─────────────────────────────────────────────────────────
function showToast(msg, type='info'){
  const icons = {info:'ℹ', success:'✓', error:'✕'};
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const icon = document.createElement('span');
  icon.className = 'ti';
  icon.textContent = icons[type] || 'ℹ';
  t.replaceChildren(icon, document.createTextNode(String(msg)));
  document.getElementById('toast-container').appendChild(t);
  setTimeout(()=>{ t.classList.add('fade-out'); setTimeout(()=>t.remove(),220); }, 2600);
}

// ── Build timeline grid ───────────────────────────────────────────
async function readApiError(response, fallback='Request failed'){
  try {
    const data = await response.json();
    return data.error || data.detail || fallback;
  } catch(e) {
    return fallback;
  }
}

async function checkAuth(){
  try {
    const r = await fetch(window.API_BASE_URL + '/api/me', { credentials: 'include' });
    if(!r.ok){
      window.location.href = 'landing.html';
      return false;
    }
    currentUser = await r.json();
    userEmail.textContent = currentUser.email;
    return true;
  } catch(e) {
    window.location.href = 'landing.html';
    return false;
  }
}
logoutBtn.addEventListener('click', async ()=>{
  await fetch(window.API_BASE_URL + '/api/auth/logout', {method:'POST', credentials: 'include'});
  window.location.href = 'landing.html';
});

function buildGrid(){
  // Remove old hour rows & half-hour lines
  timeline.querySelectorAll('.hour-row,.half-hour-line').forEach(e=>e.remove());
  for(let h=0;h<24;h++){
    const row = document.createElement('div');
    row.className = 'hour-row';
    row.style.top = `${h*60}px`;
    row.innerHTML = `<span class="hour-label">${pad(h)}:00</span><div class="hour-line"></div>`;
    timeline.appendChild(row);

    if(h<24){
      const hl = document.createElement('div');
      hl.className = 'half-hour-line';
      hl.style.top = `${h*60+30}px`;
      timeline.appendChild(hl);
    }
  }
}

// ── Now line ──────────────────────────────────────────────────────
function updateNowLine(){
  if(!isToday(currentDate)){ nowLine.style.display='none'; return; }
  const n=new Date();
  const m = n.getHours()*60+n.getMinutes();
  nowLine.style.display='block';
  nowLine.style.top = `${m}px`;
}

// ── Fetch & render ────────────────────────────────────────────────
let pendingHighlight = null;

function executePendingHighlight() {
  if (!pendingHighlight) return;
  const { startMinutes } = pendingHighlight;
  pendingHighlight = null;

  tWrap.scrollTo({ top: Math.max(0, startMinutes - 120), behavior: 'smooth' });

  const allBlocks = document.querySelectorAll('.busy-block');
  let closest = null;
  let closestDist = Infinity;
  allBlocks.forEach(el => {
    const blockTop = parseInt(el.style.top);
    const dist = Math.abs(blockTop - startMinutes);
    if (dist < closestDist) {
      closestDist = dist;
      closest = el;
    }
  });
  if (closest) {
    closest.classList.add('highlight-flash');
    setTimeout(() => closest.classList.remove('highlight-flash'), 1800);
  }
}

async function fetchSlots(){
  try {
    const r = await fetch(window.API_BASE_URL + `/api/slots?date=${dateStr(currentDate)}`, { credentials: 'include' });
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Failed to load slots'), 'error'); return; }
    const data = await r.json();
    allSlots = data;
    renderBlocks();
    renderSidebar();
    
    navigateToStep(detectCurrentStep());
    executePendingHighlight();
  } catch(e){ showToast('Failed to load slots','error'); }
}

async function loadPresets(){
  try {
    const r = await fetch(window.API_BASE_URL + '/api/presets', { credentials: 'include' });
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Could not load presets'), 'error'); return; }
    presets = await r.json();
    presetSelect.innerHTML = '';
    presets.forEach(preset=>{
      const opt = document.createElement('option');
      opt.value = preset.id;
      opt.textContent = preset.custom ? `Custom: ${preset.name}` : preset.name;
      presetSelect.appendChild(opt);
    });
    updatePresetSummary();
  } catch(e) {
    presetSelect.innerHTML = '<option value="">Preset load failed</option>';
  }
}

function updatePresetSummary(){
  const preset = presets.find(item=>item.id === presetSelect.value);
  if(!preset){
    presetSummary.textContent = 'Choose a built-in or saved preset.';
    return;
  }
  const blockCount = preset.blocks ? preset.blocks.length : 0;
  presetSummary.textContent = `${preset.description || 'Custom saved preset.'} ${blockCount} block${blockCount === 1 ? '' : 's'}.`;
}

presetSelect.addEventListener('change', updatePresetSummary);
presetApplyBtn.addEventListener('click', async ()=>{
  const presetId = presetSelect.value;
  if(!presetId){ showToast('Choose a preset first', 'error'); return; }
  const preset = presets.find(item=>item.id === presetId);
  const clearExisting = window.confirm(`Apply "${preset ? preset.name : 'preset'}"? Choose OK to replace existing non-Google blocks, or Cancel to add only if there is no overlap.`);
  try {
    const r = await fetch(window.API_BASE_URL + `/api/presets/${encodeURIComponent(presetId)}/apply`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({clear_existing: clearExisting}),
      credentials: 'include'
    });
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Could not apply preset'), 'error'); return; }
    showToast('Preset applied', 'success');
    await fetchSlots();
  } catch(e) {
    showToast('Network error', 'error');
  }
});

function renderBlocks(){
  timeline.querySelectorAll('.busy-block,.free-highlight').forEach(e=>e.remove());
  // Group overlapping blocks for column layout
  const sorted = [...allSlots].sort((a,b)=>a.startMinutes-b.startMinutes);
  const columns = [];
  for(const slot of sorted){
    let placed = false;
    for(let c=0;c<columns.length;c++){
      const col = columns[c];
      const overlaps = col.some(b => b.startMinutes < slot.endMinutes && b.endMinutes > slot.startMinutes);
      if(!overlaps){
        col.push(slot); placed=true; break;
      }
    }
    if(!placed) columns.push([slot]);
  }
  const totalCols = columns.length;
  columns.forEach((col, ci)=>{
    col.forEach(slot=>{
      const el = document.createElement('div');
      el.className = 'busy-block' + (slot.is_pending ? ' pending-block' : '');
      el.dataset.id = slot.id;
      el.style.top = `${slot.startMinutes + 1}px`;
      el.style.height = `${Math.max(20, heightPx(slot.endMinutes-slot.startMinutes) - 3)}px`;
      el.style.background = slot.color;
      if(totalCols > 1){
        const w = (1/totalCols)*100;
        el.style.left = `${60 + ci*(w*(timeline.clientWidth-68)/100)}px`;
        el.style.right = `${(totalCols-ci-1)*(w*(timeline.clientWidth-68)/100) + 8}px`;
      }
      const repeatIcon = slot.repeatDays && slot.repeatDays.length ? ' \u{1f501}' : '';
      el.innerHTML = `
        <div class="blk-label">${escHtml(slot.label||'Busy')}</div>
        <div class="blk-time">${slot.start}\u2013${slot.end}</div>
        ${repeatIcon ? `<div class="blk-repeat">${repeatIcon} Repeating</div>` : ''}
      `;
      el.addEventListener('click', e=>{ e.stopPropagation(); openEditModal(slot); });
      timeline.appendChild(el);
    });
  });
}

px`;
    el.style.height = `${heightPx(b.endMinutes-b.startMinutes)}px`;
    el.title = `Free: ${b.start}–${b.end}`;
    timeline.appendChild(el);
  });
}

function renderSidebar(){
  blocksCount.textContent = allSlots.length;

  let html = '';

  // Day summary
  if (allSlots.length > 0) {
    const totalBusy = allSlots.reduce((sum, s) => sum + (s.endMinutes - s.startMinutes), 0);
    const freeMinutes = 1440 - totalBusy;
    const busyPct = Math.min((totalBusy / 1440) * 100, 100);
    html += `
      <div class="day-summary">
        <div class="day-summary-stats">
          <span class="stat-busy">${formatDuration(totalBusy)} busy</span>
          <span class="stat-free">${formatDuration(freeMinutes)} free</span>
        </div>
        <div class="day-summary-bar">
          <div class="bar-busy" style="width: ${busyPct}%"></div>
        </div>
      </div>
    `;
  }

  // Bulk actions for pending blocks
  const pendingCount = allSlots.filter(s => s.is_pending).length;
  if (pendingCount > 0) {
    html += `
      <div class="bulk-actions">
        <button class="btn-primary" data-action="accept-all">Accept All (${pendingCount})</button>
        <button class="btn-cancel" data-action="reject-all">Reject All</button>
      </div>
    `;
  }

  if (!allSlots.length) {
    blocksList.innerHTML = html + '<div class="empty-state">No blocks for this day</div>';
    return;
  }

  const sorted = [...allSlots].sort((a, b) => a.startMinutes - b.startMinutes);
  sorted.forEach(s => {
    const repeatStr = s.repeatDays && s.repeatDays.length
      ? `\u{1f501} ${s.repeatDays.map(d => DAY_NAMES[d]).join(', ')}`
      : '';

    let badge = '';
    if (s.is_pending) badge = '<span class="bi-badge badge-ai">AI</span>';
    else if (s.is_gcal) badge = '<span class="bi-badge badge-gcal">GCal</span>';
    else if (s.preset_source) badge = '<span class="bi-badge badge-template">Template</span>';
    else badge = '<span class="bi-badge badge-manual">Manual</span>';

    const duration = formatDuration(s.endMinutes - s.startMinutes);

    html += `
      <div class="block-item${s.is_pending ? ' pending' : ''}" data-id="${s.id}">
        <div class="bi-dot" style="background:${s.color}"></div>
        <div class="bi-info">
          <div class="bi-label">${escHtml(s.label || 'Busy')}</div>
          <div class="bi-time">${s.start} – ${s.end}</div>
          ${repeatStr ? `<div class="bi-repeat">${repeatStr}</div>` : ''}
        </div>
        ${badge}
        <span class="bi-duration">${duration}</span>
        <button class="bi-del" data-id="${s.id}" title="Delete">\u2715</button>
      </div>
    `;
  });

  blocksList.innerHTML = html;

  // Attach event listeners
  blocksList.querySelectorAll('.block-item').forEach(el => {
    const id = parseInt(el.dataset.id);
    el.querySelector('.bi-del').addEventListener('click', e => {
      e.stopPropagation();
      deleteSlot(id);
    });
    el.addEventListener('click', () => {
      const slot = allSlots.find(s => s.id === id);
      if (slot) openEditModal(slot);
    });
  });

  // Bulk action event delegation
  blocksList.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const action = btn.dataset.action;
      if (action === 'accept-all') acceptAllPending();
      else if (action === 'reject-all') rejectAllPending();
    });
  });
}

function escHtml(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Date navigation ───────────────────────────────────────────────
function getAiStartAfter(){
  const dateVal = document.getElementById('ai-start-date')?.value;
  const timeVal = document.getElementById('ai-start-time')?.value;
  if(!dateVal || !timeVal) return null;
  return `${dateVal}T${timeVal}`;
}T${timeVal}`;
}



function setDate(d){
  currentDate = new Date(d); currentDate.setHours(0,0,0,0);
  const ds = dateStr(currentDate);
  dateDisplay.textContent = formatDate(currentDate);
  datePicker.value = ds;
  fetchSlots();
  updateNowLine();
}

document.getElementById('prev-day').addEventListener('click',()=>{
  const d=new Date(currentDate); d.setDate(d.getDate()-1); setDate(d);
});
document.getElementById('next-day').addEventListener('click',()=>{
  const d=new Date(currentDate); d.setDate(d.getDate()+1); setDate(d);
});
document.getElementById('today-btn').addEventListener('click',()=>setDate(new Date()));
datePicker.addEventListener('change',e=>{ if(e.target.value) setDate(new Date(e.target.value+'T00:00:00')); });
document.addEventListener('keydown',e=>{
  if(modalOverlay.classList.contains('open')) return;
  if(e.target.closest('input, textarea, select, button')) return;
  if(e.key==='ArrowLeft'){ document.getElementById('prev-day').click(); }
  if(e.key==='ArrowRight'){ document.getElementById('next-day').click(); }
  if(e.key==='t'||e.key==='T'){ document.getElementById('today-btn').click(); }
});

// ── Theme toggle ──────────────────────────────────────────────────
const themeToggle = document.getElementById('theme-toggle');
themeToggle.addEventListener('click',()=>{
  const isDark = document.documentElement.dataset.theme === 'dark';
  document.documentElement.dataset.theme = isDark ? 'light' : 'dark';
  themeToggle.textContent = isDark ? '☽' : '☀';
});

// ── Color swatches setup ──────────────────────────────────────────
function buildSwatches(){
  colorSwatches.innerHTML = '';
  COLORS.forEach(c=>{
    const s = document.createElement('div');
    s.className = 'swatch' + (c===selectedColor?' active':'');
    s.style.background = c;
    s.dataset.color = c;
    s.addEventListener('click',()=>{
      selectedColor = c;
      colorSwatches.querySelectorAll('.swatch').forEach(sw=>sw.classList.remove('active'));
      s.classList.add('active');
    });
    colorSwatches.appendChild(s);
  });
}
buildSwatches();

// ── Day toggle buttons ────────────────────────────────────────────
const dayBtns = repeatRow.querySelectorAll('[data-day]');
dayBtns.forEach(btn=>{
  btn.addEventListener('click',()=>{
    btn.classList.toggle('active');
    selectedDays = Array.from(dayBtns).filter(b=>b.classList.contains('active')).map(b=>+b.dataset.day);
    everyDayBtn.classList.toggle('active', selectedDays.length===7);
  });
});
everyDayBtn.addEventListener('click',()=>{
  const allActive = selectedDays.length===7;
  dayBtns.forEach(b=>b.classList.toggle('active',!allActive));
  selectedDays = allActive ? [] : [0,1,2,3,4,5,6];
  everyDayBtn.classList.toggle('active',!allActive);
});

// ── Modal helpers ─────────────────────────────────────────────────
function openAddModal(startM=null, endM=null){
  editingSlotId = null;
  modalTitle.textContent = 'Add Block';
  modalSave.textContent = 'Add';
  modalDelete.style.display = 'none';
  const saveTplBtn = document.getElementById('modal-save-template');
  if(saveTplBtn) saveTplBtn.style.display = 'block';
  mStart.value = startM!=null ? minutesToTime(startM) : '09:00';
  mEnd.value   = endM!=null   ? minutesToTime(Math.min(endM,1439)) : '10:00';
  mLabel.value = '';
  selectedColor = COLORS[0];
  selectedDays = [];
  buildSwatches();
  dayBtns.forEach(b=>b.classList.remove('active'));
  everyDayBtn.classList.remove('active');
  openModal();
}

function openEditModal(slot){
  editingSlotId = slot.id;
  modalTitle.textContent = 'Edit Block';
  modalSave.textContent = 'Save';
  modalDelete.style.display = 'block';
  const saveTplBtn = document.getElementById('modal-save-template');
  if(saveTplBtn) saveTplBtn.style.display = 'none';
  mStart.value = slot.start;
  mEnd.value   = slot.end;
  mLabel.value = slot.label || '';
  selectedColor = slot.color || COLORS[0];
  selectedDays = slot.repeatDays ? [...slot.repeatDays] : [];
  buildSwatches();
  // Mark active color swatch
  colorSwatches.querySelectorAll('.swatch').forEach(s=>{
    s.classList.toggle('active', s.dataset.color===selectedColor);
  });
  dayBtns.forEach(b=>{
    b.classList.toggle('active', selectedDays.includes(+b.dataset.day));
  });
  everyDayBtn.classList.toggle('active', selectedDays.length===7);
  openModal();
}

function openModal(){ modalOverlay.classList.add('open'); mStart.focus(); }
function closeModal(){ modalOverlay.classList.remove('open'); }

document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal-cancel').addEventListener('click', closeModal);
modalOverlay.addEventListener('click', e=>{ if(e.target===modalOverlay) closeModal(); });
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeModal(); });

// ── Save (add or update) ──────────────────────────────────────────
modalSave.addEventListener('click', async ()=>{
  const start = mStart.value, end = mEnd.value;
  if(!start||!end){ showToast('Start and end required','error'); return; }
  if(timeToMinutes(end)<=timeToMinutes(start)){ showToast('End must be after start','error'); return; }

  const payload = {
    start, end,
    label: mLabel.value.trim() || 'Busy',
    color: selectedColor,
    repeatDays: selectedDays,
    date: selectedDays.length ? null : dateStr(currentDate),
  };

  try {
    let r;
    if(editingSlotId!=null){
      r = await fetch(window.API_BASE_URL + `/api/slots/${editingSlotId}`,{ method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload), credentials: 'include' });
    } else {
      r = await fetch(window.API_BASE_URL + '/api/slots',{ method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload), credentials: 'include' });
    }
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Error'),'error'); return; }
    closeModal();
    showToast(editingSlotId!=null ? 'Block updated' : 'Block added','success');
    await fetchSlots();
  } catch(e){ showToast('Network error','error'); }
});

// ── Delete ────────────────────────────────────────────────────────
modalDelete.addEventListener('click', async ()=>{
  if(editingSlotId==null) return;
  await deleteSlot(editingSlotId);
  closeModal();
});

async function deleteSlot(id){
  try {
    const r = await fetch(window.API_BASE_URL + `/api/slots/${id}`,{method:'DELETE', credentials: 'include'});
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(r.ok){ showToast('Block deleted','info'); await fetchSlots(); }
    else { showToast('Delete failed','error'); }
  } catch(e){ showToast('Network error','error'); }
}

// ── Add Busy Block ─────────────────────────────────────────────────
// Toggle repeat days visibility

});





// ── Preset Remove ──────────────────────────────────────────────────
presetRemoveBtn.addEventListener('click', async () => {
  const presetId = presetSelect.value;
  if (!presetId) { showToast('Select a template first', 'error'); return; }
  if (!confirm('Remove all blocks from this template?')) return;
  
  try {
    const r = await fetch(window.API_BASE_URL + `/api/presets/${encodeURIComponent(presetId)}/remove`, { method: 'DELETE', credentials: 'include' });
    if (r.status === 401) { window.location.href = 'landing.html'; return; }
    if (!r.ok) { showToast(await readApiError(r, 'Remove failed'), 'error'); return; }
    const data = await r.json();
    showToast(`Removed ${data.removed} block(s)`, 'info');
    await fetchSlots();
  } catch (e) { showToast('Network error', 'error'); }
});



// renderFreeResults removed — Free Time is handled internally by AI
function _renderFreeResults_REMOVED(data){
  if(!data.allocated.length){
    freeResults_.innerHTML = '<div class="free-status warn">⚠ No free time found in search range.</div>';
    return;
  }
  // Group by date
  const byDate = {};
  data.allocated.forEach(b=>{
    if(!byDate[b.date]) byDate[b.date] = [];
    byDate[b.date].push(b);
  });

  let html = '';
  if(data.fulfilled){
    html += `<div class="free-status ok">✓ Found ${data.totalAllocated.toFixed(2)}h of free time</div>`;
  } else {
    html += `<div class="free-status warn">⚠ Only found ${data.totalAllocated.toFixed(2)}h (missing ${data.missing.toFixed(2)}h)</div>`;
  }

  Object.entries(byDate).forEach(([date,blocks])=>{
    const d = new Date(date+'T00:00:00');
    const label = isToday(d) ? 'Today' : formatDate(d);
    html += `<div class="free-day-group">
      <div class="free-day-header"><span>${label}</span><span>${date}</span></div>`;
    blocks.forEach(b=>{
      html += `<div class="free-block-item">
        <div class="fb-dot"></div>
        <div class="fb-time">${b.start} – ${b.end}</div>
        <div class="fb-dur">${b.durationStr}</div>
      </div>`;
    });
    html += '</div>';
  });

  freeResults_.innerHTML = html;
}



// ── Timeline drag-to-create ───────────────────────────────────────
let dragStartMin = null, dragEndMin = null, isDragging = false;

function yToMinute(y){
  const rect = timeline.getBoundingClientRect();
  const relY = y - rect.top;
  return Math.max(0, Math.min(1439, Math.round(relY / 60 * 60)));
}

function snapTo15(m){ return Math.round(m/15)*15; }

timeline.addEventListener('mousedown', e=>{
  if(e.target.closest('.busy-block')) return;
  isDragging = true;
  dragStartMin = snapTo15(yToMinute(e.clientY));
  dragEndMin = dragStartMin + 60;
  dragPreview.style.display = 'block';
  updateDragPreview();
});

document.addEventListener('mousemove', e=>{
  if(!isDragging) return;
  dragEndMin = snapTo15(yToMinute(e.clientY));
  if(dragEndMin <= dragStartMin) dragEndMin = dragStartMin + 15;
  updateDragPreview();
});

document.addEventListener('mouseup', e=>{
  if(!isDragging) return;
  isDragging = false;
  dragPreview.style.display = 'none';
  const start = Math.min(dragStartMin, dragEndMin);
  const end   = Math.max(dragStartMin, dragEndMin);
  if(end - start >= 15) openAddModal(start, end);
});

function updateDragPreview(){
  const s = Math.min(dragStartMin, dragEndMin);
  const e = Math.max(dragStartMin, dragEndMin);
  dragPreview.style.top    = `${s}px`;
  dragPreview.style.height = `${Math.max(e-s,15)}px`;
}

// ── Scroll to current hour on load ───────────────────────────────
function scrollToCurrent(){
  const now = new Date();
  const m = isToday(currentDate) ? now.getHours()*60+now.getMinutes() : 8*60;
  tWrap.scrollTop = Math.max(0, m - 120);
}

// ── Plan Review Renderer ───────────────────────────────────────
function renderPlanReview(review) {
  if (!review || !review.days) return null;
  const wrap = document.createElement('div');
  wrap.className = 'plan-review';

  const goal = document.createElement('div');
  goal.className = 'plan-goal';
  goal.textContent = review.goal;
  wrap.appendChild(goal);

  const summary = document.createElement('div');
  summary.className = 'plan-summary';
  summary.textContent = `${review.total_hours}h across ${review.num_days} days \u00b7 ${review.num_blocks} blocks`;
  wrap.appendChild(summary);

  review.days.forEach(day => {
    const dayEl = document.createElement('div');
    dayEl.className = 'plan-day';

    const d = new Date(day.date + 'T00:00:00');
    const dayName = isToday(d) ? 'Today' : d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    const h = Math.floor(day.day_minutes / 60);
    const m = day.day_minutes % 60;
    const durStr = m ? `${h}h ${m}m` : `${h}h`;

    const header = document.createElement('div');
    header.className = 'plan-day-header';
    header.innerHTML = `<span>${dayName}</span><span class="plan-day-duration">${durStr}</span>`;
    dayEl.appendChild(header);

    day.blocks.forEach(block => {
      const taskEl = document.createElement('div');
      taskEl.className = 'plan-task';
      const blockMin = (parseInt(block.end.split(':')[0]) * 60 + parseInt(block.end.split(':')[1])) -
                        (parseInt(block.start.split(':')[0]) * 60 + parseInt(block.start.split(':')[1]));
      const bm = Math.floor(blockMin / 60);
      const bmm = blockMin % 60;
      const blockDur = bm > 0 ? (bmm > 0 ? `${bm}h ${bmm}m` : `${bm}h`) : `${bmm}m`;
      taskEl.innerHTML = `
        <span class="plan-task-time">${escHtml(block.start)}\u2013${escHtml(block.end)}</span>
        <span class="plan-task-label">${escHtml(block.label)}</span>
        <span class="plan-task-dur">${blockDur}</span>
      `;
      const bStartMin = parseInt(block.start.split(':')[0]) * 60 + parseInt(block.start.split(':')[1]);
      taskEl.dataset.date = day.date;
      taskEl.dataset.startMin = bStartMin;
      taskEl.addEventListener('click', () => {
        navigateToBlock(day.date, bStartMin);
      });
      dayEl.appendChild(taskEl);
    });

    wrap.appendChild(dayEl);
  });

  if (review.conflicts && review.conflicts.length) {
    const footer = document.createElement('div');
    footer.className = 'plan-footer';
    footer.style.color = 'var(--red)';
    footer.textContent = `Warning: ${review.conflicts.length} conflict(s) need review.`;
    wrap.appendChild(footer);
  }

  return wrap;
}

// ── Gantt Chart ───────────────────────────────────────────────
const GANTT_COLORS = ['#6c5ce7','#e17055','#00b894','#0984e3','#d6309e','#fdcb6e','#00cec9','#e84393'];

function renderGantt(scheduled) {
  if (!scheduled || !scheduled.length) return null;

  const byDate = {};
  scheduled.forEach(b => {
    if (!byDate[b.date]) byDate[b.date] = [];
    byDate[b.date].push(b);
  });

  const sortedDates = Object.keys(byDate).sort();
  let earliestH = 24, latestH = 0;
  sortedDates.forEach(d => {
    byDate[d].forEach(b => {
      const sh = parseInt(b.start.split(':')[0]);
      const eh = parseInt(b.end.split(':')[0]);
      if (sh < earliestH) earliestH = sh;
      if (eh > latestH) latestH = eh;
    });
  });
  earliestH = Math.max(0, earliestH - 1);
  latestH = Math.min(24, latestH + 1);
  if (latestH <= earliestH) latestH = earliestH + 4;
  const hours = [];
  for (let h = earliestH; h < latestH; h++) hours.push(h);

  const wrap = document.createElement('div');
  wrap.className = 'gantt-wrap';

  const title = document.createElement('div');
  title.className = 'gantt-title';
  title.textContent = 'Planned Schedule';
  wrap.appendChild(title);

  const headerRow = document.createElement('div');
  headerRow.className = 'gantt-row';
  const headerLabel = document.createElement('div');
  headerLabel.className = 'gantt-row-label';
  headerLabel.textContent = '';
  headerRow.appendChild(headerLabel);
  const headerBars = document.createElement('div');
  headerBars.className = 'gantt-row-bars';
  headerBars.style.display = 'flex';
  hours.forEach(() => {
    const marker = document.createElement('div');
    marker.className = 'gantt-hour-header';
    marker.textContent = '';
    headerBars.appendChild(marker);
  });
  headerRow.appendChild(headerBars);
  wrap.appendChild(headerRow);

  const totalH = hours.length;
  let colorIdx = 0;
  const legendItems = [];

  sortedDates.forEach(date => {
    const d = new Date(date + 'T00:00:00');
    const dayLabel = isToday(d) ? 'Today' : formatDate(d);

    const dayLabelEl = document.createElement('div');
    dayLabelEl.className = 'gantt-day-label';
    dayLabelEl.textContent = dayLabel;
    wrap.appendChild(dayLabelEl);

    const row = document.createElement('div');
    row.className = 'gantt-row';

    const rowLabel = document.createElement('div');
    rowLabel.className = 'gantt-row-label';
    rowLabel.textContent = date.slice(5);
    row.appendChild(rowLabel);

    const rowBars = document.createElement('div');
    rowBars.className = 'gantt-row-bars';

    const gridLines = document.createElement('div');
    gridLines.className = 'gantt-hour-markers';
    hours.forEach(() => {
      const line = document.createElement('div');
      line.className = 'gantt-hour-line';
      gridLines.appendChild(line);
    });
    rowBars.appendChild(gridLines);

    byDate[date].forEach(b => {
      const [sh, sm] = b.start.split(':').map(Number);
      const [eh, em] = b.end.split(':').map(Number);
      const startMin = sh * 60 + sm;
      const endMin = eh * 60 + em;
      const dayStartMin = earliestH * 60;

      const leftPct = ((startMin - dayStartMin) / (totalH * 60)) * 100;
      const widthPct = ((endMin - startMin) / (totalH * 60)) * 100;

      const color = GANTT_COLORS[colorIdx % GANTT_COLORS.length];
      colorIdx++;

      const bar = document.createElement('div');
      bar.className = 'gantt-bar';
      bar.style.left = leftPct + '%';
      bar.style.width = Math.max(widthPct, 2) + '%';
      bar.style.background = color;
      bar.textContent = b.label || 'Task';
      bar.title = `${b.label}\n${b.start} \u2013 ${b.end}`;
      bar.dataset.date = b.date;
      bar.dataset.id = b.id || '';
      bar.addEventListener('click', () => {
        navigateToBlock(b.date, startMin);
      });
      rowBars.appendChild(bar);

      legendItems.push({ label: b.label, color });
    });

    row.appendChild(rowBars);
    wrap.appendChild(row);
  });

  if (legendItems.length) {
    const legend = document.createElement('div');
    legend.className = 'gantt-legend';
    legendItems.forEach(item => {
      const li = document.createElement('div');
      li.className = 'gantt-legend-item';
      const dot = document.createElement('div');
      dot.className = 'gantt-legend-dot';
      dot.style.background = item.color;
      li.appendChild(dot);
      li.appendChild(document.createTextNode(item.label));
      legend.appendChild(li);
    });
    wrap.appendChild(legend);
  }

  return wrap;
}

// ── AI Chat Logic ────────────────────────────────────────────────
const aiChatBtn = document.getElementById('ai-chat-btn');
const aiChatPanel = document.getElementById('ai-chat-panel');
const aiCloseBtn = document.getElementById('ai-close-btn');
const aiSendBtn = document.getElementById('ai-send-btn');
const aiPrompt = document.getElementById('ai-prompt');
const aiMessages = document.getElementById('ai-chat-messages');
const slackSlider = document.getElementById('slack-slider');
const slackVal = document.getElementById('slack-val');
let currentSessionId = null;
let currentSessionTitle = '';

function updateSessionLabel(title) {
  currentSessionTitle = title || '';
  const el = document.getElementById('ai-session-label');
  if (el) el.textContent = currentSessionTitle ? `· ${currentSessionTitle}` : '';
}

// ── Sessions list ─────────────────────────────────────────────────
async function loadSessions() {
  const list = document.getElementById('ai-sessions-list');
  if (!list) return;
  list.innerHTML = '<div class="sessions-empty">Loading...</div>';
  try {
    const r = await fetch(window.API_BASE_URL + '/api/agent/sessions', { credentials: 'include' });
    if (!r.ok) { list.innerHTML = '<div class="sessions-empty">Failed to load</div>'; return; }
    const sessions = await r.json();
    if (!sessions.length) {
      list.innerHTML = '<div class="sessions-empty">No sessions yet</div>';
      return;
    }
    list.innerHTML = '';
    sessions.forEach(s => {
      const isCurrent = s.session_id === currentSessionId;
      const item = document.createElement('div');
      item.className = `session-item status-${s.status}` + (isCurrent ? ' active' : '');
      item.dataset.sessionId = s.session_id;

      const fmtTime = (d) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      const fmtDate = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });

      const startD = new Date(s.created_at);
      const startStr = fmtDate(startD) + ' ' + fmtTime(startD);

      // Determine end time:
      // 1. Finished (confirmed/rejected) → use finished_at
      // 2. Currently open in chat → show "active"
      // 3. Everything else (old "active" sessions not currently open) → use last_accessed_at
      let timeRange;
      if (s.finished_at) {
        timeRange = `${startStr} → ${fmtTime(new Date(s.finished_at))}`;
      } else if (isCurrent) {
        timeRange = `${startStr} → active`;
      } else if (s.last_accessed_at) {
        timeRange = `${startStr} → ${fmtTime(new Date(s.last_accessed_at))}`;
      } else {
        timeRange = `${startStr} → ${fmtTime(startD)}`;
      }

      const badgeCls = s.status === 'confirmed' ? 'confirmed' : s.status === 'rejected' ? 'rejected' : (isCurrent ? 'active' : 'confirmed');
      const badgeLbl = s.status === 'confirmed' ? 'Done' : s.status === 'rejected' ? 'Rejected' : (isCurrent ? 'Active' : 'Idle');
      item.innerHTML = `
        <div class="si-dot"></div>
        <div class="si-info">
          <div class="si-title">${escHtml(s.title || 'Untitled')}</div>
          <div class="si-meta">${escHtml(timeRange)}</div>
        </div>
        <span class="si-badge ${badgeCls}">${badgeLbl}</span>
      `;
      item.addEventListener('click', () => resumeSession(s.session_id, s.title));
      list.appendChild(item);
    });
  } catch(e) {
    list.innerHTML = '<div class="sessions-empty">Error loading sessions</div>';
  }
}


async function startNewSession() {
  const btn = document.getElementById('ai-new-session-btn');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  try {
    const r = await fetch(window.API_BASE_URL + '/api/agent/new-session', { method: 'POST', credentials: 'include' });
    if (r.status === 401) { window.location.href = 'landing.html'; return; }
    if (!r.ok) { showToast('Could not start new session', 'error'); return; }
    const data = await r.json();
    currentSessionId = data.session_id;
    updateSessionLabel('New Session');

    // Clear chat messages, keep the welcome block
    const welcome = aiMessages.querySelector('.ai-msg');
    aiMessages.innerHTML = '';
    if (welcome) aiMessages.appendChild(welcome);

    // Show calendar snapshot as a system message
    if (data.calendar_snapshot) {
      const snapMsg = document.createElement('div');
      snapMsg.className = 'ai-msg';
      snapMsg.style.borderColor = 'var(--green)';
      snapMsg.style.background = 'var(--green-bg)';
      snapMsg.innerHTML = '<strong>📅 Calendar snapshot loaded:</strong><br>' +
        escHtml(data.calendar_snapshot).replace(/\n/g, '<br>');
      aiMessages.appendChild(snapMsg);
    } else {
      const snapMsg = document.createElement('div');
      snapMsg.className = 'ai-msg';
      snapMsg.style.borderColor = 'var(--green)';
      snapMsg.innerHTML = '✓ New session started. Your calendar is empty — nothing scheduled yet.';
      aiMessages.appendChild(snapMsg);
    }

    aiMessages.scrollTop = aiMessages.scrollHeight;
    showAiGreeting(aiMessages);
    showToast('New session started', 'success');
    // Close drawer and reload sessions list
    closeSessionsDrawer();
    await loadSessions();
  } catch(e) {
    showToast('Network error', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '＋ New'; }
  }
}

async function resumeSession(sessionId, title) {
  if (sessionId === currentSessionId) {
    closeSessionsDrawer();
    return;
  }
  currentSessionId = sessionId;
  updateSessionLabel(title || 'Resumed session');

  // Update active highlight in list
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.sessionId === sessionId);
  });

  // Clear chat and show loading
  aiMessages.innerHTML = '';
  const loadEl = document.createElement('div');
  loadEl.className = 'ai-msg';
  loadEl.textContent = 'Loading conversation…';
  aiMessages.appendChild(loadEl);

  try {
    const r = await fetch(window.API_BASE_URL + `/api/agent/sessions/${sessionId}/messages`, { credentials: 'include' });
    loadEl.remove();

    if (r.ok) {
      const msgs = await r.json();
      if (msgs.length === 0) {
        const emptyEl = document.createElement('div');
        emptyEl.className = 'ai-msg';
        emptyEl.textContent = 'No messages in this session yet. Start chatting!';
        aiMessages.appendChild(emptyEl);
      } else {
        msgs.forEach(m => {
          const el = document.createElement('div');
          el.className = m.role === 'user' ? 'user-msg' : 'ai-msg';
          el.innerText = m.content;
          aiMessages.appendChild(el);
        });
      }
    } else {
      const errEl = document.createElement('div');
      errEl.className = 'ai-msg';
      errEl.textContent = 'Could not load conversation history.';
      aiMessages.appendChild(errEl);
    }
  } catch(e) {
    loadEl.textContent = 'Network error loading history.';
  }

  aiMessages.scrollTop = aiMessages.scrollHeight;
  showToast('Session resumed', 'info');
  closeSessionsDrawer();
  loadSessions();
}

function openSessionsDrawer() {
  const drawer = document.getElementById('ai-sessions-drawer');
  const btn = document.getElementById('ai-history-btn');
  drawer.classList.add('open');
  btn.classList.add('open');
  loadSessions();
}

function closeSessionsDrawer() {
  const drawer = document.getElementById('ai-sessions-drawer');
  const btn = document.getElementById('ai-history-btn');
  drawer.classList.remove('open');
  btn.classList.remove('open');
}

function toggleSessionsDrawer() {
  const drawer = document.getElementById('ai-sessions-drawer');
  if (drawer.classList.contains('open')) closeSessionsDrawer();
  else openSessionsDrawer();
}


slackSlider.addEventListener('input', e => {
  const pct = Math.round(parseFloat(e.target.value) * 100);
  const bufEl = document.getElementById('buffer-pct');
  if(bufEl) bufEl.textContent = pct + '%';
});

function updateAiBtnStyle() {
  if (aiChatPanel.classList.contains('open')) {
    aiChatBtn.style.background = 'var(--accent)';
    aiChatBtn.style.color = '#fff';
    aiChatBtn.style.borderColor = 'var(--accent)';
  } else {
    aiChatBtn.style.background = 'var(--surface2)';
    aiChatBtn.style.color = 'var(--text2)';
    aiChatBtn.style.borderColor = 'var(--border)';
  }
}

// ── Duration helper ────────────────────────────────────────────────
function formatDuration(m) {
  const h = Math.floor(m / 60);
  const min = m % 60;
  if (h && min) return `${h}h ${min}m`;
  if (h) return `${h}h`;
  return `${min}m`;
}

// ── Guided Workflow Steps ─────────────────────────────────────────
const stepHints = {
  busy: 'Start by blocking off time you can\'t move — classes, work, sleep. Drag on the calendar or click "+ Add Block".',
  templates: 'Apply a template to quickly set up a recurring schedule — student, professional, exam prep.',
  plan: 'Tell the AI what you need to accomplish. It\'ll find the best slots and create a plan for you to review.'
};

const stepToSectionIndex = {
  busy: 0,
  templates: 1,
  plan: -1
};

function detectCurrentStep() {
  const hasPending = allSlots.some(s => s.is_pending);
  if (hasPending) return 'plan';
  if (allSlots.length === 0) return 'busy';
  return 'templates';
}

function getWalkthroughStorageKey() {
  return currentUser?.id ? `ai-planner-walkthrough-completed:${currentUser.id}` : 'ai-planner-walkthrough-completed:guest';
}

function isWalkthroughCompleted() {
  try {
    return localStorage.getItem(getWalkthroughStorageKey()) === 'true';
  } catch {
    return false;
  }
}

function setWalkthroughCompleted(completed = true) {
  try {
    localStorage.setItem(getWalkthroughStorageKey(), completed ? 'true' : 'false');
  } catch {}
}

function updateWalkthroughVisibility() {
  const walkthroughCard = document.getElementById('walkthrough-card');
  const completeNote = document.getElementById('walkthrough-complete-note');
  const prompt = document.getElementById('ai-prompt');
  const shouldShow = !isWalkthroughCompleted();
  if (walkthroughCard) walkthroughCard.style.display = shouldShow ? 'block' : 'none';
  if (completeNote) completeNote.style.display = 'none';
  if (prompt) {
    prompt.placeholder = shouldShow ? 'e.g. Set up a new GitHub repo over 2 hours...' : 'What would you like to plan?';
  }
}

const aiGreetings = [
  "Hey! I'm your AI planner. Tell me what you need to get done and I'll find the best time for it.",
  "All set up! What are you working on today? I'll figure out where it fits.",
  "Ready when you are. Drop me a task and I'll slot it into your schedule.",
  "Let's plan something. What's on your mind?",
  "You're all set. What would you like to schedule?",
  "Go ahead — what do you need done? I'll find the time.",
  "Nice, you're all caught up. What's next on the list?",
  "I'm here to help you plan. What are we working on?"
];

function showAiGreeting(container) {
  const msg = document.createElement('div');
  msg.className = 'ai-msg';
  msg.textContent = aiGreetings[Math.floor(Math.random() * aiGreetings.length)];
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

function markWalkthroughCompleted() {
  setWalkthroughCompleted(true);
  updateWalkthroughVisibility();

  const sidebar = document.getElementById('sidebar');
  if (sidebar) {
    sidebar.querySelectorAll('.sb-section').forEach(s => s.classList.remove('highlighted'));
  }

  const messages = document.getElementById('ai-chat-messages');
  if (!messages) return;
  const existingPrompt = messages.querySelector('[data-walkthrough-complete]');
  if (existingPrompt) return;

  showAiGreeting(messages);
}

function updateStepIndicator(activeStep) {
  const stepsEl = document.getElementById('ai-steps');
  const hintEl = document.getElementById('ai-hint');
  if (!stepsEl || !hintEl) return;

  const steps = stepsEl.querySelectorAll('.ai-step');
  const stepOrder = ['busy', 'templates', 'freetime', 'plan'];
  const activeIdx = stepOrder.indexOf(activeStep);

  steps.forEach((el, i) => {
    el.classList.remove('active', 'completed');
    if (i < activeIdx) el.classList.add('completed');
    else if (i === activeIdx) el.classList.add('active');
  });

  hintEl.textContent = stepHints[activeStep] || '';
}

function highlightSidebarSection(activeStep) {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  const sections = sidebar.querySelectorAll('.sb-section');
  sections.forEach(s => s.classList.remove('highlighted'));

  const idx = stepToSectionIndex[activeStep];
  if (idx !== undefined && idx >= 0 && idx < sections.length && sections[idx]) {
    sections[idx].classList.add('highlighted');
    sections[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

let currentWalkthroughIndex = 0;
const walkthroughOrder = ['busy', 'templates', 'plan'];

function updateWalkthroughButtons() {
  const prevBtn = document.getElementById('wt-prev-btn');
  const nextBtn = document.getElementById('wt-next-btn');
  if (!prevBtn || !nextBtn) return;

  prevBtn.disabled = currentWalkthroughIndex === 0;
  nextBtn.textContent = currentWalkthroughIndex === walkthroughOrder.length - 1 ? 'Complete' : 'Next';
}

function handleWalkthroughNext() {
  if (currentWalkthroughIndex < walkthroughOrder.length - 1) {
    const nextStep = walkthroughOrder[currentWalkthroughIndex + 1];
    navigateToStep(nextStep);
  } else {
    markWalkthroughCompleted();
  }
}

function handleWalkthroughPrev() {
  if (currentWalkthroughIndex > 0) {
    navigateToStep(walkthroughOrder[currentWalkthroughIndex - 1]);
  }
}

document.getElementById('wt-prev-btn')?.addEventListener('click', handleWalkthroughPrev);
document.getElementById('wt-next-btn')?.addEventListener('click', handleWalkthroughNext);

function navigateToStep(activeStep) {
  currentWalkthroughIndex = Math.max(0, walkthroughOrder.indexOf(activeStep));
  if (!isWalkthroughCompleted()) {
    updateStepIndicator(activeStep);
    highlightSidebarSection(activeStep);
    updateWalkthroughButtons();
  }
}

// ── Click-to-navigate from plan/gantt to timeline ─────────────────
function navigateToBlock(blockDate, startMinutes) {
  const targetDate = new Date(blockDate + 'T00:00:00');
  const isDifferentDate = targetDate.getTime() !== currentDate.getTime();

  if (isDifferentDate) {
    pendingHighlight = { startMinutes };
    setDate(targetDate);
  } else {
    tWrap.scrollTo({ top: Math.max(0, startMinutes - 120), behavior: 'smooth' });

    const allBlocks = document.querySelectorAll('.busy-block');
    let closest = null;
    let closestDist = Infinity;
    allBlocks.forEach(el => {
      const blockTop = parseInt(el.style.top);
      const dist = Math.abs(blockTop - startMinutes);
      if (dist < closestDist) {
        closestDist = dist;
        closest = el;
      }
    });
    if (closest) {
      closest.classList.add('highlight-flash');
      setTimeout(() => closest.classList.remove('highlight-flash'), 1800);
    }
  }
}

aiChatBtn.addEventListener('click', () => {
  const isOpen = aiChatPanel.classList.toggle('open');
  localStorage.setItem('ai-panel-open', isOpen ? 'true' : 'false');
  updateAiBtnStyle();
  updateWalkthroughVisibility();
});
aiCloseBtn.addEventListener('click', () => {
  aiChatPanel.classList.remove('open');
  closeSessionsDrawer();
  updateAiBtnStyle();
});

document.getElementById('ai-history-btn').addEventListener('click', toggleSessionsDrawer);
document.getElementById('ai-new-session-btn').addEventListener('click', startNewSession);

updateWalkthroughVisibility();

async function sendAiMessage() {
  const text = aiPrompt.value.trim();
  const startAfter = getAiStartAfter();
  if(!text) return;

  // Disable UI during request
  aiSendBtn.disabled = true;
  aiSendBtn.textContent = '…';
  aiPrompt.disabled = true;

  aiPrompt.value = '';
  
  const uMsg = document.createElement('div');
  uMsg.className = 'user-msg';
  uMsg.innerText = text;
  aiMessages.appendChild(uMsg);
  
  const loadingMsg = document.createElement('div');
  loadingMsg.className = 'ai-msg';
  loadingMsg.innerText = 'Thinking... combining steps and free time...';
  aiMessages.appendChild(loadingMsg);
  aiMessages.scrollTop = aiMessages.scrollHeight;
  
  try {
    const payload = { 
      prompt: text, 
      slack: parseFloat(slackSlider.value),
      start_after: startAfter || null,
      session_id: currentSessionId || null
    };
    const res = await fetch(window.API_BASE_URL + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
      credentials: 'include'
    });
    if(res.status === 401){ loadingMsg.remove(); window.location.href = 'landing.html'; return; }
    const data = await res.json();
    loadingMsg.remove();
    
    if (data.session_id) {
      const isNewSession = data.session_id !== currentSessionId;
      currentSessionId = data.session_id;
      if (data.intent === 'plan' && data.plan) {
        const title = data.plan.title || data.plan.goal || '';
        updateSessionLabel(title);
        // Refresh sessions list so the new session appears in history
        loadSessions();
      } else if (isNewSession) {
        updateSessionLabel('');
      }
    }

    const aMsg = document.createElement('div');
    aMsg.className = 'ai-msg';
    if (data.error) {
       aMsg.innerText = 'Error: ' + data.error;
    } else {
       if (data.intent === 'plan' && data.review) {
          const reviewCard = renderPlanReview(data.review);
          if (reviewCard) aMsg.appendChild(reviewCard);
       } else {
          aMsg.innerHTML = escHtml(data.response || '').replace(/\n/g, '<br>');
       }
       
       if (data.intent === 'plan' && data.scheduled && data.scheduled.length > 0) {
          const gantt = renderGantt(data.scheduled);
          if (gantt) aMsg.appendChild(gantt);

          const actions = document.createElement('div');
          actions.style.marginTop = '10px';
          const sessionIdStr = JSON.stringify(data.session_id).replace(/"/g, '&quot;');
          const containerId = 'actions-' + Date.now();
          actions.id = containerId;
          
          actions.innerHTML = `
            <button class="btn-primary" style="background: var(--green); margin-right: 5px; width: auto;" onclick="acceptAiEvents(${sessionIdStr}, '${containerId}')">Accept</button>
            <button class="btn-cancel" style="width: auto;" onclick="rejectAiEvents(${sessionIdStr}, '${containerId}')">Reject & Remove</button>
          `;
          aMsg.appendChild(actions);
       }
       
       if (data.intent === 'plan') {
          fetchSlots();
       }
    }
    aiMessages.appendChild(aMsg);
    aiMessages.scrollTop = aiMessages.scrollHeight;
  } catch (err) {
    loadingMsg.innerText = 'Request failed: ' + err.message;
  } finally {
    aiSendBtn.disabled = false;
    aiSendBtn.textContent = 'Send';
    aiPrompt.disabled = false;
    aiPrompt.focus();
  }
}

window.acceptAiEvents = async function(sessionId, containerId) {
  const container = document.getElementById(containerId);
  if(container) container.innerHTML = '<span style="color:var(--text2);font-size:11px;">Accepting…</span>';
  try {
    const r = await fetch(window.API_BASE_URL + '/api/chat/accept', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: sessionId}),
      credentials: 'include'
    });
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(r.ok){
      if(container) container.innerHTML = '<span class="bi-badge badge-gcal" style="font-size:10px;padding:3px 8px;">✓ Accepted & saved</span>';
      fetchSlots();
    } else {
      if(container) container.innerHTML = '<span class="bi-badge" style="background:rgba(225,112,85,.15);color:var(--red);font-size:10px;padding:3px 8px;">Accept failed</span>';
    }
  } catch(e) {
    if(container) container.innerHTML = '<span class="bi-badge" style="background:rgba(225,112,85,.15);color:var(--red);font-size:10px;padding:3px 8px;">Network error</span>';
  }
};

window.rejectAiEvents = async function(sessionId, containerId) {
  const container = document.getElementById(containerId);
  if(container) container.innerHTML = '<span style="color:var(--text2);font-size:11px;">Rejecting…</span>';
  try {
    const r = await fetch(window.API_BASE_URL + '/api/chat/reject', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: sessionId}),
      credentials: 'include'
    });
    if(r.status === 401){ window.location.href = 'landing.html'; return; }
    if(r.ok){
      if(container) container.innerHTML = '<span class="bi-badge" style="background:rgba(225,112,85,.15);color:var(--red);font-size:10px;padding:3px 8px;">✕ Rejected & removed</span>';
      fetchSlots();
    } else {
      if(container) container.innerHTML = '<span class="bi-badge" style="background:rgba(225,112,85,.15);color:var(--red);font-size:10px;padding:3px 8px;">Reject failed</span>';
    }
  } catch(e) {
    if(container) container.innerHTML = '<span class="bi-badge" style="background:rgba(225,112,85,.15);color:var(--red);font-size:10px;padding:3px 8px;">Network error</span>';
  }
};

// ── Bulk accept/reject pending blocks ──────────────────────────────
async function acceptAllPending() {
  const pendingSessionIds = [...new Set(allSlots.filter(s => s.is_pending && s.session_id).map(s => s.session_id))];
  for (const sid of pendingSessionIds) {
    try {
      await fetch(window.API_BASE_URL + '/api/chat/accept', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
        credentials: 'include'
      });
    } catch (e) { /* continue */ }
  }
  showToast('All pending blocks accepted', 'success');
  fetchSlots();
}

async function rejectAllPending() {
  const pendingSessionIds = [...new Set(allSlots.filter(s => s.is_pending && s.session_id).map(s => s.session_id))];
  for (const sid of pendingSessionIds) {
    try {
      await fetch(window.API_BASE_URL + '/api/chat/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
        credentials: 'include'
      });
    } catch (e) { /* continue */ }
  }
  showToast('All pending blocks removed', 'info');
  fetchSlots();
}

aiSendBtn.addEventListener('click', sendAiMessage);
aiPrompt.addEventListener('keydown', e => {
  if(e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendAiMessage();
  }
});

// ── Init ──────────────────────────────────────────────────────────
const gcalConnBtn = document.getElementById('gcal-conn-btn');

async function checkGcalStatus() {
  try {
    const res = await fetch(window.API_BASE_URL + '/api/google/status', { credentials: 'include' });
    if(res.status === 401){ window.location.href = 'landing.html'; return; }
    if(!res.ok) return;
    const data = await res.json();
    if(data.connected) {
      gcalConnBtn.textContent = 'Disconnect GCal';
      gcalConnBtn.style.background = 'rgba(255,92,122,.1)';
      gcalConnBtn.style.color = 'var(--red)';
      gcalConnBtn.style.borderColor = 'rgba(255,92,122,.3)';
      gcalConnBtn.onclick = async () => {
        const logoutRes = await fetch(window.API_BASE_URL + '/api/google/oauth/logout', {method: 'POST', credentials: 'include'});
        if(logoutRes.status === 401){ window.location.href = 'landing.html'; return; }
        checkGcalStatus();
        fetchSlots();
      };
    } else {
      gcalConnBtn.textContent = 'Connect GCal';
      gcalConnBtn.style.background = 'var(--surface2)';
      gcalConnBtn.style.color = 'var(--text)';
      gcalConnBtn.style.borderColor = 'var(--border)';
      gcalConnBtn.onclick = () => {
         window.open('/api/google/oauth/login', 'Google Auth', 'width=500,height=600');
         const poll = setInterval(async () => {
    const res = await fetch(window.API_BASE_URL + '/api/google/status', { credentials: 'include' });
           if(res.status === 401){ clearInterval(poll); window.location.href = 'landing.html'; return; }
           if(!res.ok) return;
           const pollingData = await res.json();
           if(pollingData.connected) {
              clearInterval(poll);
              checkGcalStatus();
              fetchSlots();
           }
         }, 1500);
      };
    }
  } catch(e) { }
}

buildGrid();
async function startAuthenticatedApp(){
  await loadPresets();
  setDate(currentDate);
  scrollToCurrent();
  await checkGcalStatus();
  await loadSessions();          // pre-populate session history drawer
  updateWalkthroughVisibility();
  if (isWalkthroughCompleted()) {
    const messages = document.getElementById('ai-chat-messages');
    if (messages && !messages.querySelector('.ai-msg:not(#walkthrough-card):not(#walkthrough-complete-note)')) {
      showAiGreeting(messages);
    }
  }
  // Restore AI panel open/closed from localStorage (default: closed)
  const savedPanelState = localStorage.getItem('ai-panel-open');
  if (savedPanelState === 'true') {
    aiChatPanel.classList.add('open');
    updateAiBtnStyle();
  }

  // Default AI schedule-from to today
  const aiDateInput = document.getElementById('ai-start-date');
  if(aiDateInput) aiDateInput.value = dateStr(new Date());
}

async function initApp(){
  const authenticated = await checkAuth();
  if(authenticated){
    await startAuthenticatedApp();
  }
}

initApp();
setInterval(updateNowLine, 60000);

// ── Quick Add Button ─────────────────────────────────────────────
document.getElementById('quick-add-btn')?.addEventListener('click', () => {
  openAddModal();
});

// ── Modal: Save as Template (unified form) ───────────────────────
document.getElementById('modal-save-template')?.addEventListener('click', async () => {
  const start = mStart.value;
  const end   = mEnd.value;
  const label = mLabel.value.trim() || 'Busy';

  if (!start || !end) { showToast('Fill start and end', 'error'); return; }
  if (timeToMinutes(end) <= timeToMinutes(start)) { showToast('End must be after start', 'error'); return; }

  const templateName = prompt('Enter template name:');
  if (!templateName) return;

  try {
    const r = await fetch(window.API_BASE_URL + '/api/custom-presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: templateName,
        description: `Custom template: ${label}`,
        blocks: [{ label, start, end, color: selectedColor, repeatDays: selectedDays }]
      }),
      credentials: 'include'
    });
    if (r.status === 401) { window.location.href = 'landing.html'; return; }
    if (!r.ok) { showToast(await readApiError(r, 'Error'), 'error'); return; }
    showToast('Template saved', 'success');
    closeModal();
    await loadPresets();
  } catch(e) { showToast('Network error', 'error'); }
});

// ── Alpine.js Memory Panel Component ─────────────────────────────
document.addEventListener('alpine:init', () => {
  Alpine.data('memoryPanel', () => ({
    open: false,
    prefs: [],
    toast: false,

    async load() {
      try {
        const r = await fetch(window.API_BASE_URL + '/api/memory', { credentials: 'include' });
        if (r.ok) {
          const all = await r.json();
          this.prefs = all.filter(m => m.type === 'pref');
        }
      } catch(e) { /* silent */ }
    },

    async remove(id) {
      try {
        const r = await fetch(window.API_BASE_URL + `/api/memory/${id}`, {
          method: 'DELETE',
          credentials: 'include'
        });
        if (r.ok) {
          this.prefs = this.prefs.filter(p => p.id !== id);
          this.toast = true;
          setTimeout(() => { this.toast = false; }, 2000);
        }
      } catch(e) { /* silent */ }
    }
  }));
});
