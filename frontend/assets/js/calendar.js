/* Additive calendar UI, backed by the same blocks, editors, and planner. */
(function () {
  'use strict';
  const core = window.CalendarCore;
  const el = id => document.getElementById(id);
  const read = (name, fallback) => { try { return localStorage.getItem(name) || fallback; } catch { return fallback; } };
  const save = (name, value) => { try { localStorage.setItem(name, value); } catch { /* Storage can be unavailable in private browsing. */ } };
  const node = (tag, className, text) => { const n = document.createElement(tag); if (className) n.className = className; if (text !== undefined) n.textContent = text; return n; };
  const dateLabel = d => d.toLocaleDateString(undefined, {weekday:'long', month:'long', day:'numeric', year:'numeric'});
  const panel = el('tools-panel');
  let view = read('calendar-view', 'month');
  if (!['month','week','day'].includes(view)) view = 'month';
  let rangeData = {}, loadedRange = '', rangeRequest = 0, ready = false;
  let tab = read('calendar-tools-tab', 'schedule') === 'ai' ? 'ai' : 'schedule';
  let quickSaving = false;
  let weekScrollNeeded = true;
  const root = document.documentElement;
  root.dataset.style = read('calendar-style', 'calendar') === 'predestination' ? 'predestination' : 'calendar';
  root.dataset.theme = read('calendar-theme', root.dataset.theme) === 'light' ? 'light' : 'dark';
  el('calendar-style').value = root.dataset.style;
  el('theme-toggle').textContent = root.dataset.theme === 'dark' ? '☀' : '☽';
  el('theme-toggle').setAttribute('aria-label', 'Switch dark or light mode');

  function dates() { return core.datesForView(currentDate, view); }
  function rangeKey() { const list = dates(); return `${core.key(list[0])}/${core.key(list[list.length - 1])}`; }
  function status(message = '', error = false) {
    const box = el('calendar-status');
    box.hidden = !message;
    box.dataset.error = String(error);
    box.replaceChildren(document.createTextNode(message));
    if (error) { const retry = node('button', '', 'Retry'); retry.type = 'button'; retry.addEventListener('click', refreshRange); box.append(retry); }
  }
  async function refreshRange() {
    const id = ++rangeRequest;
    if (!ready || view === 'day') { status(); return; }
    const requested = rangeKey();
    if (requested !== loadedRange) { rangeData = {}; renderCalendar(); }
    status('Loading your calendar…');
    try {
      const [start, end] = requested.split('/');
      const response = await fetch(`${window.API_BASE_URL}/api/slots/range?start=${start}&end=${end}`, {credentials:'include'});
      if (id !== rangeRequest) return;
      if (response.status === 401) { window.location.href = window.LOGIN_URL; return; }
      if (!response.ok) throw new Error(await readApiError(response, 'Could not load the calendar.'));
      const data = await response.json();
      if (id !== rangeRequest) return;
      rangeData = data;
      loadedRange = requested;
      status();
      renderCalendar();
    } catch (error) {
      if (id !== rangeRequest) return;
      rangeData = {}; loadedRange = '';
      renderCalendar();
      status(error.message || 'Could not load the calendar.', true);
    }
  }
  function updateHeading() {
    let heading = currentDate.toLocaleDateString(undefined, {month:'long',year:'numeric'});
    if (view === 'week') {
      const list = dates();
      heading = `${list[0].toLocaleDateString(undefined,{month:'short',day:'numeric'})} – ${list[6].toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'})}`;
    } else if (view === 'day') heading = currentDate.toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric'});
    el('calendar-heading').textContent = heading;
    el('prev-day').title = `Previous ${view}`;
    el('prev-day').setAttribute('aria-label', `Previous ${view}`);
    el('next-day').title = `Next ${view}`;
    el('next-day').setAttribute('aria-label', `Next ${view}`);
    el('quick-text').placeholder = `Add an event, e.g. Meeting tomorrow at 8`;
  }
  function setView(next) {
    if (!['month','week','day'].includes(next)) return;
    const changed = next !== view;
    view = next;
    save('calendar-view', view);
    el('month-view').hidden = view !== 'month';
    el('week-view').hidden = view !== 'week';
    el('timeline-wrap').hidden = view !== 'day';
    document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === view)));
    updateHeading();
    if (changed) weekScrollNeeded = true;
    renderCalendar();
    refreshRange();
    if (view === 'day') { renderBlocks(); scrollToCurrent(); }
  }
  function chooseDate(date) { setDate(new Date(date)); }
  function editEvent(slot, date) {
    if(slot.is_pending) { window.agentUI.restoreRun(slot.run_id); return; }
    if(slot.is_gcal) { showToast("Imported Google events are read-only.","info"); return; }
    chooseDate(date);
    openEditModal(slot);
  }
  function eventButton(slot, date) {
    const button = node('button', `calendar-event${slot.is_pending ? ' pending' : ''}`);
    button.type = 'button';
    button.style.setProperty('--event-color', /^#[0-9a-f]{3,8}$/i.test(slot.color) ? slot.color : 'var(--accent)');
    button.append(node('span', 'event-time', slot.start), document.createTextNode(slot.label || 'Busy'));
    button.title = `${slot.label || 'Busy'} · ${slot.start}–${slot.end}${slot.is_pending ? ' · Pending AI plan' : ''}`;
    button.setAttribute('aria-label', `${button.title}, ${dateLabel(date)}. Edit event`);
    button.addEventListener('click', () => editEvent(slot, date));
    return button;
  }
  function renderMonth() {
    const container = el('month-view');
    const weekdays = node('div', 'month-weekdays');
    ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].forEach(name => weekdays.append(node('span','',name)));
    const grid = node('div', 'month-grid');
    const today = core.key(window.calendarNow()), selected = core.key(currentDate);
    dates().forEach(date => {
      const key = core.key(date);
      const cell = node('div', 'month-cell');
      const add = node('button','cell-add','+');
      add.type = 'button';
      add.setAttribute('aria-label', `Add event on ${dateLabel(date)}`);
      add.addEventListener('click', () => { chooseDate(date); openAddModal(); });
      cell.append(add);
      cell.classList.toggle('outside', date.getMonth() !== currentDate.getMonth());
      cell.classList.toggle('today', key === today);
      cell.classList.toggle('selected', key === selected);
      const number = node('button', 'day-number', String(date.getDate()));
      number.type = 'button';
      number.setAttribute('aria-label', `Select ${dateLabel(date)}`);
      number.setAttribute('aria-pressed', String(key === selected));
      if (key === today) number.setAttribute('aria-current', 'date');
      number.addEventListener('click', () => chooseDate(date));
      cell.append(number);
      const slots = [...(rangeData[key] || [])].sort((a,b) => a.startMinutes - b.startMinutes);
      // Keep the overview readable; the Day view always exposes every block.
      const capacity = window.innerHeight < 850 ? 1 : 2;
      slots.slice(0,capacity).forEach(slot => cell.append(eventButton(slot,date)));
      if (slots.length > capacity) {
        const more = node('button','more-events',`+${slots.length - capacity} more`);
        more.type = 'button';
        more.setAttribute('aria-label', `See all ${slots.length} events on ${dateLabel(date)}`);
        more.addEventListener('click', () => { chooseDate(date); setView('day'); });
        cell.append(more);
      }
      cell.addEventListener('click', e => { if (e.target === cell) chooseDate(date); });
      grid.append(cell);
    });
    container.replaceChildren(weekdays, grid);
  }
  function renderWeek() {
    const container = el('week-view');
    const scroll = container.scrollTop;
    const header = node('div','week-header');
    header.append(node('span'));
    const body = node('div','week-body');
    const hours = node('div','week-hours');
    for (let h=0; h<24; h++) { const label = node('span','',`${String(h).padStart(2,'0')}:00`); label.style.top = `${h*60}px`; hours.append(label); }
    body.append(hours);
    const today = core.key(window.calendarNow());
    dates().forEach(date => {
      const key = core.key(date);
      const heading = node('button','week-date',date.toLocaleDateString(undefined,{weekday:'short'}));
      heading.type = 'button';
      heading.append(node('strong','',String(date.getDate())));
      heading.classList.toggle('today',key === today);
      heading.classList.toggle('selected',key === core.key(currentDate));
      heading.setAttribute('aria-label', `Open day planner for ${dateLabel(date)}`);
      heading.addEventListener('click', () => { chooseDate(date); setView('day'); });
      header.append(heading);
      const column = node('div','week-column');
      column.title = 'Double-click an empty time to add a block';
      const slots = [...(rangeData[key] || [])].sort((a,b) => a.startMinutes-b.startMinutes);
      const groups = [];
      slots.forEach(slot => {
        let group = groups[groups.length-1];
        if (!group || slot.startMinutes >= group.end) { group = {end:slot.endMinutes,slots:[]}; groups.push(group); }
        group.end = Math.max(group.end, slot.endMinutes); group.slots.push(slot);
      });
      groups.forEach(group => {
        const ends = [], items = [];
        group.slots.forEach(slot => {
          let lane = ends.findIndex(end => end <= slot.startMinutes);
          if (lane === -1) lane = ends.length;
          ends[lane] = slot.endMinutes;
          items.push({slot,lane});
        });
        items.forEach(({slot,lane}) => {
          const button = eventButton(slot,date);
          button.classList.add('week-event');
          button.style.top = `${slot.startMinutes+1}px`;
          button.style.height = `${Math.max(15,slot.endMinutes-slot.startMinutes-2)}px`;
          button.style.left = `calc(${lane*100/ends.length}% + 2px)`;
          button.style.width = `calc(${100/ends.length}% - 4px)`;
          column.append(button);
        });
      });
      if (key === today) { const now = window.calendarNow(); const line = node('div','week-now'); line.style.top = `${now.getHours()*60+now.getMinutes()}px`; column.append(line); }
      column.addEventListener('dblclick', e => {
        if (e.target !== column) return;
        const minutes = Math.min(1410,Math.max(0,Math.floor((e.clientY-column.getBoundingClientRect().top)/15)*15));
        chooseDate(date); openAddModal(minutes,Math.min(1439,minutes+60));
      });
      body.append(column);
    });
    container.replaceChildren(header,body);
    container.scrollTop = weekScrollNeeded ? 420 : scroll;
    weekScrollNeeded = false;
  }
  function renderCalendar() { if (view === 'month') renderMonth(); else if (view === 'week') renderWeek(); }

  function syncTools() {
    const open = !panel.hidden;
    el('sidebar').hidden = tab !== 'schedule';
    el('ai-chat-panel').classList.toggle('open', open && tab === 'ai');
    el('ai-chat-panel').hidden = tab !== 'ai';
    el('tools-toggle').setAttribute('aria-expanded',String(open));
    el('ai-chat-btn').setAttribute('aria-expanded',String(open && tab === 'ai'));
    el('tools-backdrop').hidden = !open || !window.matchMedia('(max-width:900px)').matches;
    [['schedule-tab','schedule'],['planner-tab','ai']].forEach(([id,value]) => { el(id).setAttribute('aria-selected',String(tab === value)); el(id).tabIndex = tab === value ? 0 : -1; });
    save('calendar-tools-open',String(open));
    save('calendar-tools-tab',tab);
    updateAiBtnStyle();
    // Day block widths depend on available space when columns overlap.
    if (view === 'day') requestAnimationFrame(renderBlocks);
  }
  function openTools(next = tab) { tab = next; panel.hidden = false; syncTools(); }
  function closeTools() { panel.hidden = true; closeSessionsDrawer(); syncTools(); el('tools-toggle').focus(); }
  function toggleTools(next = tab) { if (!panel.hidden && next === tab) closeTools(); else openTools(next); }
  el('tools-toggle').addEventListener('click', () => toggleTools());
  el('tools-close').addEventListener('click',closeTools);
  el('tools-backdrop').addEventListener('click',closeTools);
  el('schedule-tab').addEventListener('click',() => openTools('schedule'));
  el('planner-tab').addEventListener('click',() => openTools('ai'));
  document.querySelector('.tools-tabs').addEventListener('keydown', e => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return;
    e.preventDefault(); openTools(tab === 'ai' ? 'schedule' : 'ai'); el(tab === 'ai' ? 'planner-tab' : 'schedule-tab').focus();
  });
  el('sidebar').setAttribute('role','tabpanel'); el('sidebar').setAttribute('aria-labelledby','schedule-tab');
  el('ai-chat-panel').setAttribute('role','tabpanel'); el('ai-chat-panel').setAttribute('aria-labelledby','planner-tab');
  // Mobile account controls trigger the existing handlers, including Google status.
  const account = node('div','mobile-account');
  ['gcal-conn-btn','logout-btn'].forEach(id => {
    const button = node('button','header-small-btn',el(id).textContent);
    button.type = 'button'; button.addEventListener('click', () => el(id).click()); account.append(button);
    new MutationObserver(() => { button.textContent = el(id).textContent; }).observe(el(id),{childList:true,subtree:true,characterData:true});
  });
  panel.append(account);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !el('quick-dialog').open && !modalOverlay.classList.contains('open') && !panel.hidden) closeTools();
  });
  window.addEventListener('resize', () => { if (!panel.hidden) syncTools(); });
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click',() => setView(button.dataset.view)));
  el('calendar-style').addEventListener('change',e => { root.dataset.style = e.target.value; save('calendar-style',e.target.value); });
  el('theme-toggle').addEventListener('click',() => save('calendar-theme',root.dataset.theme));

  const dialog = el('quick-dialog');
  el('quick-manual').addEventListener('click', () => {
    const draft = core.parseQuickEntry(el('quick-text').value,window.calendarNow(),currentDate);
    ['label','date','hour','minute','period','duration'].forEach(name => { el('quick-'+name).value = draft[name]; });
    el('quick-note').textContent = draft.notes.join(' ');
    el('quick-error').textContent = '';
    dialog.showModal();
    el(!draft.hour ? 'quick-hour' : !draft.period ? 'quick-period' : !draft.duration ? 'quick-duration' : 'quick-label').focus();
  });
  el('quick-form').addEventListener('submit', e => {
    e.preventDefault();
    if (quickSaving) return;
    const text = el('quick-text').value.trim();
    if(!text) return;
    openTools('ai');
    window.agentUI.send(text);
    el('quick-text').value = '';
  });
  function cancelQuick() { if (!quickSaving) { dialog.close(); el('quick-text').focus(); } }
  el('quick-cancel').addEventListener('click',cancelQuick);
  el('quick-cancel-x').addEventListener('click',cancelQuick);
  dialog.addEventListener('cancel', e => { if (quickSaving) e.preventDefault(); });
  el('quick-confirm-form').addEventListener('submit', async e => {
    e.preventDefault();
    if (quickSaving) return;
    let payload;
    try {
      const values = Object.fromEntries(['label','date','hour','minute','period','duration'].map(name => [name,el(`quick-${name}`).value]));
      payload = core.quickPayload(values);
    } catch (error) { el('quick-error').textContent = error.message; return; }
    quickSaving = true;
    const controls = [...el('quick-confirm-form').querySelectorAll('input,select,button')];
    controls.forEach(control => { control.disabled = true; });
    el('quick-save').textContent = 'Adding…'; el('quick-error').textContent = '';
    try {
      const response = await fetch(`${window.API_BASE_URL}/api/slots`,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if (response.status === 401) { window.location.href = window.LOGIN_URL; return; }
      if (!response.ok) throw new Error(await readApiError(response,'Could not add this event.'));
      dialog.close();
      el('quick-text').value = '';
      chooseDate(core.fromKey(payload.date));
      showToast(`${payload.label} added · ${payload.start}–${payload.end}`,'success');
      el('quick-text').focus();
    } catch (error) { el('quick-error').textContent = error.message || 'Could not reach the scheduler. Please try again.'; }
    finally { quickSaving = false; controls.forEach(control => { control.disabled = false; }); el('quick-save').textContent = 'Add to calendar'; }
  });

  window.calendarUI = {
    setView, toggleTools, openTools, closeTools,
    move(direction) { chooseDate(core.moveDate(currentDate,view,direction)); },
    dateChanged() { updateHeading(); if (loadedRange !== rangeKey()) rangeData = {}; renderCalendar(); refreshRange(); },
    slotsChanged() { if (ready) refreshRange(); },
    start() { ready = true; refreshRange(); }
  };
  setView(view);
  panel.hidden = read('calendar-tools-open','false') !== 'true';
  syncTools();
  // Authentication may already have completed while deferred assets loaded.
  if (currentUser) window.calendarUI.start();
})();
