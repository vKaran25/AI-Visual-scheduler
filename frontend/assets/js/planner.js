
// ── State ─────────────────────────────────────────────────────────
let currentDate = new Date();
currentDate.setHours(0,0,0,0);
let currentUser = null;
let presets = [];
let allSlots = [];          // all busy slots from server
let freeResults = null;     // last free-time search result
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
const memoryToggle = document.getElementById('memory-toggle');
const memoryPanel = document.getElementById('memory-panel');
const memoryList = document.getElementById('memory-list');
const memoryInput = document.getElementById('memory-input');
const memoryStatus = document.getElementById('memory-status');
const memoryAddBtn = document.getElementById('memory-add-btn');

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
    const detail = data.error || data.detail;
    if(Array.isArray(detail)) return detail.map(item => item.msg || String(item)).join('; ');
    return typeof detail === 'string' ? detail : fallback;
  } catch(e) {
    return fallback;
  }
}

async function checkAuth(){
  try {
    const r = await fetch(window.API_BASE_URL + '/api/me', { credentials: 'include' });
    if(!r.ok){
      window.location.href = window.LOGIN_URL;
      return false;
    }
    currentUser = await r.json();
    currentDate = window.calendarNow();
    userEmail.textContent = currentUser.email;
    return true;
  } catch(e) {
    window.location.href = window.LOGIN_URL;
    return false;
  }
}
logoutBtn.addEventListener('click', async ()=>{
  await fetch(window.API_BASE_URL + '/api/auth/logout', {method:'POST', credentials: 'include'});
  window.location.href = window.LOGIN_URL;
});

// Only global preferences belong in this panel; session facts stay in their chat.
let memoryLoadId = 0;
let memoryActionInFlight = false;

function memoryMessage(message, error=false){
  memoryStatus.textContent = message;
  memoryStatus.classList.toggle('error', error);
}

function renderMemoryPreferences(memories){
  memoryList.replaceChildren();
  for(const pref of memories.filter(item => item.type === 'pref' && Number.isInteger(item.id))){
    const row = document.createElement('li');
    row.className = 'memory-item';
    const content = document.createElement('span');
    content.textContent = pref.content;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn-cancel';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', 'Remove preference');
    remove.addEventListener('click', () => removeMemoryPreference(pref.id));
    row.append(content, remove);
    memoryList.appendChild(row);
  }
  if(!memoryList.children.length){
    const empty = document.createElement('li');
    empty.className = 'memory-note';
    empty.textContent = 'No preferences saved yet.';
    memoryList.appendChild(empty);
  }
}

async function loadMemoryPreferences(){
  const requestId = ++memoryLoadId;
  memoryMessage('Loading preferences…');
  try {
    const r = await fetch(window.API_BASE_URL + '/api/memory', {credentials: 'include'});
    if(requestId !== memoryLoadId) return;
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok) throw new Error(await readApiError(r, 'Could not load preferences'));
    const memories = await r.json();
    if(requestId !== memoryLoadId) return;
    if(!Array.isArray(memories)) throw new Error('Unexpected preferences response');
    renderMemoryPreferences(memories);
    memoryMessage('');
  } catch(e){
    if(requestId === memoryLoadId) memoryMessage(e.message || 'Could not load preferences', true);
  }
}

function setMemoryBusy(busy){
  memoryActionInFlight = busy;
  memoryAddBtn.disabled = busy;
  memoryList.querySelectorAll('button').forEach(btn => btn.disabled = busy);
}

async function addMemoryPreference(){
  if(memoryActionInFlight) return;
  const content = memoryInput.value.trim();
  if(!content){ memoryMessage('Enter a preference first.', true); return; }
  setMemoryBusy(true);
  try {
    const r = await fetch(window.API_BASE_URL + '/api/memory', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
      body: JSON.stringify({type: 'pref', content})
    });
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok) throw new Error(await readApiError(r, 'Could not save preference'));
    memoryInput.value = '';
    await loadMemoryPreferences();
    showToast('Preference saved', 'success');
  } catch(e){ memoryMessage(e.message || 'Could not save preference', true); }
  finally { setMemoryBusy(false); }
}

async function removeMemoryPreference(id){
  if(memoryActionInFlight || !window.confirm('Remove this preference from future plans?')) return;
  setMemoryBusy(true);
  try {
    const r = await fetch(window.API_BASE_URL + `/api/memory/${encodeURIComponent(id)}`, {
      method: 'DELETE', credentials: 'include'
    });
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok) throw new Error(await readApiError(r, 'Could not remove preference'));
    await loadMemoryPreferences();
    showToast('Preference removed', 'success');
  } catch(e){ memoryMessage(e.message || 'Could not remove preference', true); }
  finally { setMemoryBusy(false); }
}

memoryToggle.addEventListener('click', () => {
  memoryPanel.hidden = !memoryPanel.hidden;
  const open = !memoryPanel.hidden;
  memoryToggle.setAttribute('aria-expanded', String(open));
  memoryToggle.textContent = open ? 'Preferences ▾' : 'Preferences ▸';
  if(open) loadMemoryPreferences();
  else ++memoryLoadId;
});
document.getElementById('memory-form').addEventListener('submit', e => {
  e.preventDefault();
  addMemoryPreference();
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
  const n=window.calendarNow();
  const m = n.getHours()*60+n.getMinutes();
  nowLine.style.display='block';
  nowLine.style.top = `${m}px`;
}

// ── Fetch & render ────────────────────────────────────────────────
let pendingHighlight = null;
let slotsRequestId = 0;
let freeSearchId = 0;

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
  const requestedDate = dateStr(currentDate);
  const requestId = ++slotsRequestId;
  ++freeSearchId;
  if(freeResults){
    freeResults = null;
    freeResults_.innerHTML = '<div class="free-status info">Schedule changed. Search again for current free time.</div>';
    reHighlightFree(null);
  }
  try {
    const r = await fetch(window.API_BASE_URL + `/api/slots?date=${requestedDate}`, { credentials: 'include' });
    if(requestId !== slotsRequestId) return;
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Failed to load slots'), 'error'); return; }
    const data = await r.json();
    if(requestId !== slotsRequestId) return;
    allSlots = data;
    renderBlocks();
    renderSidebar();
    navigateToStep(detectCurrentStep());
    executePendingHighlight();
    window.calendarUI?.slotsChanged();
  } catch(e){ if(requestId === slotsRequestId) showToast('Failed to load slots','error'); }
}

async function loadPresets(){
  try {
    const r = await fetch(window.API_BASE_URL + '/api/presets', { credentials: 'include' });
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
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
  if(!window.confirm(`Apply "${preset ? preset.name : 'preset'}"? This replaces existing non-Google blocks.`)) return;
  try {
    const r = await fetch(window.API_BASE_URL + `/api/presets/${encodeURIComponent(presetId)}/apply`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({clear_existing: true}),
      credentials: 'include'
    });
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
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

function reHighlightFree(result){
  timeline.querySelectorAll('.free-highlight').forEach(e=>e.remove());
  if(!result) return;
  const ds = dateStr(currentDate);
  result.allocated.filter(b=>b.date===ds).forEach(b=>{
    const el = document.createElement('div');
    el.className = 'free-highlight';
    el.style.top = `${b.startMinutes}px`;
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
    const totalBusy = allSlots.filter(s=>!s.is_pending).reduce((sum, s) => sum + (s.durationMinutes ?? (s.endMinutes - s.startMinutes)), 0);
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
        <button class="btn-primary" data-action="accept-all" title="Accepts entire sessions, including blocks on other days">Accept Sessions (${pendingCount} here)</button>
        <button class="btn-cancel" data-action="reject-all" title="Rejects entire sessions, including blocks on other days">Reject Sessions</button>
        <small style="flex-basis:100%;color:var(--text2);">Affects all days in these sessions.</small>
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

    const duration = formatDuration(s.durationMinutes ?? (s.endMinutes - s.startMinutes));

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
        <button class="bi-del" ${s.is_pending || s.is_gcal ? "disabled" : ""} data-id="${s.id}" title="Delete">\u2715</button>
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
  const dateVal = document.getElementById('ai-start-date').value;
  const timeVal = document.getElementById('ai-start-time').value;
  if(!dateVal || !timeVal) return null;
  const value = `${dateVal}T${timeVal}`;
  const parsed = new Date(value);
  return !isNaN(parsed.getTime()) && dateTimeLocalStr(parsed) === value ? value : null;
}

function defaultAiStart(){
  const nextHalfHour = new Date(Math.ceil(Date.now() / 1800000) * 1800000);
  document.getElementById('ai-start-date').value = dateStr(nextHalfHour);
  document.getElementById('ai-start-time').value = `${pad(nextHalfHour.getHours())}:${pad(nextHalfHour.getMinutes())}`;
}

function setDate(d){
  currentDate = new Date(d); currentDate.setHours(0,0,0,0);
  const ds = dateStr(currentDate);
  dateDisplay.textContent = formatDate(currentDate);
  datePicker.value = ds;
  window.calendarUI?.dateChanged();
  document.getElementById('free-date').value = ds;
  freeResults = null;
  freeResults_.replaceChildren();
  timeline.querySelectorAll('.free-highlight').forEach(el => el.remove());
  fetchSlots();
  updateNowLine();
}

document.getElementById('prev-day').addEventListener('click',()=>{
  if(window.calendarUI) { window.calendarUI.move(-1); return; }
  const d=new Date(currentDate); d.setDate(d.getDate()-1); setDate(d);
});
document.getElementById('next-day').addEventListener('click',()=>{
  if(window.calendarUI) { window.calendarUI.move(1); return; }
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
  document.getElementById('modal-save-template').style.display = 'block';
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
  if(slot.is_pending) { window.agentUI.restoreRun(slot.run_id); return; }
  if(slot.is_gcal) { showToast("Imported Google events are read-only.","info"); return; }
  editingSlotId = slot.id;
  modalTitle.textContent = 'Edit Block';
  modalSave.textContent = 'Save';
  modalDelete.style.display = 'block';
  document.getElementById('modal-save-template').style.display = 'none';
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
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Error'),'error'); return; }
    closeModal();
    showToast(editingSlotId!=null ? 'Block updated' : 'Block added','success');
    await fetchSlots();
  } catch(e){ showToast('Network error','error'); }
});

// ── Delete ────────────────────────────────────────────────────────
modalDelete.addEventListener('click', async ()=>{
  if(editingSlotId==null) return;
  if(await deleteSlot(editingSlotId)) closeModal();
});

async function deleteSlot(id){
  const slot = allSlots.find(s => s.id === id);
  if(slot?.repeatDays?.length && !window.confirm('Delete this recurring block on every matching day?')) return false;
  try {
    const r = await fetch(window.API_BASE_URL + `/api/slots/${id}`,{method:'DELETE', credentials: 'include'});
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(r.ok){ showToast('Block deleted','info'); await fetchSlots(); return true; }
    showToast(await readApiError(r, 'Delete failed'),'error');
  } catch(e){ showToast('Network error','error'); }
  return false;
}

// ── Add Busy Block ─────────────────────────────────────────────────
// Toggle repeat days visibility
document.querySelectorAll('input[name="b-repeat"]').forEach(radio => {
  radio.addEventListener('change', () => {
    const repeatDaysDiv = document.getElementById('b-repeat-days');
    repeatDaysDiv.style.display = radio.value === 'custom' ? 'flex' : 'none';
  });
});

document.getElementById('b-add-btn').addEventListener('click', async () => {
  const start = document.getElementById('b-start').value;
  const end   = document.getElementById('b-end').value;
  const label = document.getElementById('b-label').value.trim() || 'Busy';
  const color = document.getElementById('b-color').value;
  
  if (!start || !end) { showToast('Fill start and end', 'error'); return; }
  if (timeToMinutes(end) <= timeToMinutes(start)) { showToast('End must be after start', 'error'); return; }
  
  const repeatType = document.querySelector('input[name="b-repeat"]:checked').value;
  let repeatDays = [];
  if (repeatType === 'custom') {
    repeatDays = Array.from(document.querySelectorAll('input[name="b-day"]:checked'))
      .map(cb => parseInt(cb.value));
    if (repeatDays.length === 0) { showToast('Select at least one day', 'error'); return; }
  }
  
  try {
    const r = await fetch(window.API_BASE_URL + '/api/slots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start, end, label, color, repeatDays, date: repeatDays.length ? null : dateStr(currentDate) }),
      credentials: 'include'
    });
    if (r.status === 401) { window.location.href = window.LOGIN_URL; return; }
    if (!r.ok) { showToast(await readApiError(r, 'Error'), 'error'); return; }
    showToast('Block added', 'success');
    document.getElementById('b-label').value = '';
    await fetchSlots();
  } catch (e) { showToast('Network error', 'error'); }
});

document.getElementById('b-save-template-btn').addEventListener('click', async () => {
  const start = document.getElementById('b-start').value;
  const end   = document.getElementById('b-end').value;
  const label = document.getElementById('b-label').value.trim() || 'Busy';
  const color = document.getElementById('b-color').value;
  
  if (!start || !end) { showToast('Fill start and end', 'error'); return; }
  if (timeToMinutes(end) <= timeToMinutes(start)) { showToast('End must be after start', 'error'); return; }
  
  const repeatType = document.querySelector('input[name="b-repeat"]:checked').value;
  let repeatDays = [];
  if (repeatType === 'custom') {
    repeatDays = Array.from(document.querySelectorAll('input[name="b-day"]:checked'))
      .map(cb => parseInt(cb.value));
  }
  
  const templateName = prompt('Enter template name:');
  if (!templateName) return;
  
  try {
    const r = await fetch(window.API_BASE_URL + '/api/custom-presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: templateName,
        description: `Custom template: ${label}`,
        blocks: [{ label, start, end, color, repeatDays, date: repeatDays.length ? null : dateStr(currentDate) }]
      }),
      credentials: 'include'
    });
    if (r.status === 401) { window.location.href = window.LOGIN_URL; return; }
    if (!r.ok) { showToast(await readApiError(r, 'Error'), 'error'); return; }
    showToast('Template saved', 'success');
    await loadPresets();
  } catch (e) { showToast('Network error', 'error'); }
});

// ── Preset Remove ──────────────────────────────────────────────────
presetRemoveBtn.addEventListener('click', async () => {
  const presetId = presetSelect.value;
  if (!presetId) { showToast('Select a template first', 'error'); return; }
  if (!confirm('Remove all blocks from this template?')) return;
  
  try {
    const r = await fetch(window.API_BASE_URL + `/api/presets/${encodeURIComponent(presetId)}/remove`, { method: 'DELETE', credentials: 'include' });
    if (r.status === 401) { window.location.href = window.LOGIN_URL; return; }
    if (!r.ok) { showToast(await readApiError(r, 'Remove failed'), 'error'); return; }
    const data = await r.json();
    showToast(`Removed ${data.removed} block(s)`, 'info');
    await fetchSlots();
  } catch (e) { showToast('Network error', 'error'); }
});

// ── Free time search ──────────────────────────────────────────────
document.getElementById('free-search-btn').addEventListener('click', async ()=>{
  const dateVal = document.getElementById('free-date').value;
  const timeVal = document.getElementById('free-time').value;
  const hours   = parseFloat(document.getElementById('free-hours').value);

  if(!dateVal||!timeVal){ showToast('Fill in date and time','error'); return; }
  if(isNaN(hours)||hours<0.5){ showToast('Enter at least 0.5 hours','error'); return; }

  const startDt = `${dateVal}T${timeVal}`;
  const nowIso  = dateTimeLocalStr(new Date());
  if(startDt < nowIso){ showToast('Start time is in the past','error'); return; }

  const btn = document.getElementById('free-search-btn');
  const searchId = ++freeSearchId;
  freeResults = null;
  reHighlightFree(null);
  freeResults_.innerHTML = '<div class="free-status info">Searching…</div>';
  btn.disabled = true; btn.textContent = 'Searching…';

  try {
    const r = await fetch(window.API_BASE_URL + `/api/free?start_dt=${encodeURIComponent(startDt)}&hours=${hours}`, { credentials: 'include' });
    if(searchId !== freeSearchId) return;
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok){
      freeResults_.innerHTML = '<div class="free-status warn">Search failed. Try again.</div>';
      showToast(await readApiError(r, 'Search failed'), 'error'); return;
    }
    const data = await r.json();
    if(searchId !== freeSearchId) return;
    freeResults = data;
    renderFreeResults(data);
    reHighlightFree(data);
  } catch(e){ if(searchId === freeSearchId) showToast('Search failed','error'); }
  finally { btn.disabled=false; btn.textContent='Search'; }
});

document.getElementById('modal-save-template').addEventListener('click', async () => {
  const start = mStart.value, end = mEnd.value;
  if(!start || !end || timeToMinutes(end) <= timeToMinutes(start)){
    showToast('Enter a valid start and end time', 'error'); return;
  }
  const name = prompt('Enter template name:');
  if(!name?.trim()) return;
  const label = mLabel.value.trim() || 'Busy';
  try {
    const r = await fetch(window.API_BASE_URL + '/api/custom-presets', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'include',
      body: JSON.stringify({ name: name.trim(), description: `Custom template: ${label}`,
        blocks: [{ label, start, end, color: selectedColor, repeatDays: selectedDays,
          date: selectedDays.length ? null : dateStr(currentDate) }] })
    });
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok){ showToast(await readApiError(r, 'Could not save template'), 'error'); return; }
    closeModal();
    showToast('Template saved', 'success');
    await loadPresets();
  } catch(e){ showToast('Network error', 'error'); }
});

function renderFreeResults(data){
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
let aiRequestInFlight = false;
let sessionViewId = 0;
let sessionHistoryLoading = false;

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
  if(aiRequestInFlight || sessionHistoryLoading) return;
  const btn = document.getElementById('ai-new-session-btn');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  try {
    const r = await fetch(window.API_BASE_URL + '/api/agent/new-session', { method: 'POST', credentials: 'include' });
    if (r.status === 401) { window.location.href = window.LOGIN_URL; return; }
    if (!r.ok) { showToast('Could not start new session', 'error'); return; }
    const data = await r.json();
    ++sessionViewId;
    window.agentUI.clear();
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
      snapMsg.innerHTML = '✓ New session started. Your calendar will be checked when you make a scheduling request.';
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
  if(aiRequestInFlight) return;
  if (sessionId === currentSessionId) {
    closeSessionsDrawer();
    return;
  }
  const viewId = ++sessionViewId;
  sessionHistoryLoading = true;
  aiSendBtn.disabled = true;
  currentSessionId = sessionId;
  updateSessionLabel(title || 'Resumed session');

  // Update active highlight in list
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.sessionId === sessionId);
  });

  aiMessages.replaceChildren();
  const loading = document.createElement('div');
  loading.className = 'ai-msg';
  loading.textContent = 'Loading conversation…';
  aiMessages.appendChild(loading);
  closeSessionsDrawer();
  try {
    const r = await fetch(window.API_BASE_URL + `/api/agent/sessions/${encodeURIComponent(sessionId)}/messages`, { credentials: 'include' });
    if(viewId !== sessionViewId) return;
    if(r.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!r.ok) throw new Error(await readApiError(r, 'Could not load conversation history'));
    const messages = await r.json();
    if(viewId !== sessionViewId) return;
    if(!Array.isArray(messages)) throw new Error('Unexpected conversation history');
    aiMessages.replaceChildren();
    if(!messages.length){
      loading.textContent = 'No messages in this session yet. Start chatting!';
      aiMessages.appendChild(loading);
    }
    messages.forEach(m => {
      const el = document.createElement('div');
      el.className = m.role === 'user' ? 'user-msg' : 'ai-msg';
      el.textContent = m.content || '';
      aiMessages.appendChild(el);
    });
    aiMessages.scrollTop = aiMessages.scrollHeight;
    loadSessions();
    await window.agentUI.restore(sessionId);
  } catch(e){
    if(viewId === sessionViewId) loading.textContent = `Could not load conversation history: ${e.message}`;
  } finally {
    if(viewId === sessionViewId){
      sessionHistoryLoading = false;
      aiSendBtn.disabled = false;
    }
  }
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
  slackVal.textContent = parseFloat(e.target.value).toFixed(1);
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
  busy: 'Start by adding your busy blocks — classes, work, meetings.',
  templates: 'Apply a template to quickly set up recurring schedules.',
  freetime: 'Search for available time slots across upcoming days.',
  plan: 'Review your AI-generated plan. Use the Slack slider to add buffer time between tasks — higher slack means more breathing room.'
};

const stepToSectionIndex = {
  busy: 0,
  templates: 1,
  freetime: 2,
  plan: 3
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
  if (idx !== undefined && sections[idx]) {
    sections[idx].classList.add('highlighted');
    sections[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

let currentWalkthroughIndex = 0;
const walkthroughOrder = ['busy', 'templates', 'freetime', 'plan'];

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
  window.calendarUI?.setView('day');
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
  if(window.calendarUI) { window.calendarUI.toggleTools('ai'); return; }
  const isOpen = aiChatPanel.classList.toggle('open');
  localStorage.setItem('ai-panel-open', String(isOpen));
  updateAiBtnStyle();
  updateWalkthroughVisibility();
});
aiCloseBtn.addEventListener('click', () => {
  if(window.calendarUI) { window.calendarUI.closeTools(); return; }
  aiChatPanel.classList.remove('open');
  localStorage.setItem('ai-panel-open', 'false');
  closeSessionsDrawer();
  updateAiBtnStyle();
});

document.getElementById('ai-history-btn').addEventListener('click', toggleSessionsDrawer);
document.getElementById('ai-new-session-btn').addEventListener('click', startNewSession);

updateWalkthroughVisibility();

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
    if(res.status === 401){ window.location.href = window.LOGIN_URL; return; }
    if(!res.ok) return;
    const data = await res.json();
    if(data.connected) {
      gcalConnBtn.textContent = 'Disconnect GCal';
      gcalConnBtn.style.background = 'rgba(255,92,122,.1)';
      gcalConnBtn.style.color = 'var(--red)';
      gcalConnBtn.style.borderColor = 'rgba(255,92,122,.3)';
      gcalConnBtn.onclick = async () => {
        const logoutRes = await fetch(window.API_BASE_URL + '/api/google/oauth/logout', {method: 'POST', credentials: 'include'});
        if(logoutRes.status === 401){ window.location.href = window.LOGIN_URL; return; }
        checkGcalStatus();
        fetchSlots();
      };
    } else {
      gcalConnBtn.textContent = 'Connect GCal';
      gcalConnBtn.style.background = 'var(--surface2)';
      gcalConnBtn.style.color = 'var(--text)';
      gcalConnBtn.style.borderColor = 'var(--border)';
      gcalConnBtn.onclick = () => {
         window.open(window.API_BASE_URL + '/api/google/oauth/login', 'Google Auth', 'width=500,height=600');
         const poll = setInterval(async () => {
    const res = await fetch(window.API_BASE_URL + '/api/google/status', { credentials: 'include' });
           if(res.status === 401){ clearInterval(poll); window.location.href = window.LOGIN_URL; return; }
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
  defaultAiStart();
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
  // Open by default; respect the user's previous choice.
  if (!window.calendarUI && localStorage.getItem('ai-panel-open') !== 'false' && !aiChatPanel.classList.contains('open')) {
    aiChatPanel.classList.add('open');
    updateAiBtnStyle();
  }
  window.calendarUI?.start();
}

async function initApp(){
  const authenticated = await checkAuth();
  if(authenticated){
    await startAuthenticatedApp();
    await window.agentUI.initialize();
  }
}

initApp();
setInterval(updateNowLine, 60000);
