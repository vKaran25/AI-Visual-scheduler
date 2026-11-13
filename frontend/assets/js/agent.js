/* Durable assistant UI. All text from models and sources is rendered as text. */
window.agentUI = (() => {
  let active = null, timer = null, generation = 0;
  let pendingRequest = null, deciding = false;
  const terminal = new Set(['completed','failed','cancelled']);
  const DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  function uid() { return crypto.randomUUID(); }
  async function request(path, method='GET', body) {
    const response = await fetch(window.API_BASE_URL + path, {
      method, credentials:'include', headers: body ? {'Content-Type':'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined
    });
    if (response.status === 401) { window.location.href = window.LOGIN_URL; throw new Error('Sign in again.'); }
    if (!response.ok) { const error=new Error(await readApiError(response, 'Request failed')); error.httpStatus=response.status; throw error; }
    return response.json();
  }
  function button(label, handler, variant) {
    const item = document.createElement('button');
    item.type='button'; item.className='btn-secondary' + (variant ? ' '+variant : ''); item.textContent=label;
    item.addEventListener('click', async () => {
      item.disabled=true;
      try { await handler(); } catch(error) { showToast(error.message,'error'); } finally { if(item.isConnected) item.disabled=false; }
    });
    return item;
  }
  // Friendly, student-readable event text: "Study session · Tue 12 Nov · 4:00–6:00 PM (2h)".
  function clock12(time) {
    const hour=Number(time.slice(0,2)), minute=time.slice(3,5);
    return ((hour+11)%12+1)+(minute==='00' ? '' : ':'+minute)+(hour%24<12 ? ' AM' : ' PM');
  }
  function span12(start,end) {
    const a=clock12(start), b=clock12(end);
    return a.slice(-2)===b.slice(-2) ? a.slice(0,-3)+'–'+b : a+'–'+b;
  }
  function niceDate(value) {
    if (!value) return 'Repeating';
    const [y,m,d]=value.split('-').map(Number);
    return new Date(y,m-1,d).toLocaleDateString(undefined,{weekday:'short',day:'numeric',month:'short'});
  }
  function niceDuration(minutes) {
    const hours=Math.floor(minutes/60), rest=Math.round(minutes%60);
    return hours ? hours+'h'+(rest ? ' '+rest+'m' : '') : rest+' min';
  }
  function eventText(value) {
    if (!value) return '';
    const clockMinutes = time => Number(time.slice(0,2))*60 + Number(time.slice(3));
    const minutes = value.durationMinutes ?? (clockMinutes(value.end) - clockMinutes(value.start));
    const when = value.repeatDays && value.repeatDays.length
      ? 'Every '+value.repeatDays.map(d=>DAYS[d]).join(', ')
      : niceDate(value.date);
    return (value.label || 'Event')+' · '+when+' · '+span12(value.start,value.end)+' ('+niceDuration(minutes)+')';
  }
  function preview(container, draft) {
    const heading = document.createElement('strong');
    heading.className='draft-heading';
    heading.textContent='Proposed changes · Not saved yet';
    const list=document.createElement('ul');
    list.className='draft-list';
    for (const change of draft.preview.changes || []) {
      const row=document.createElement('li');
      row.className='draft-'+change.kind;
      const tag=document.createElement('span'); tag.className='draft-tag';
      const body=document.createElement('span');
      if (change.kind==='delete') { tag.textContent='Remove'; body.textContent=eventText(change.before); }
      else if (change.kind==='update') { tag.textContent='Change'; body.textContent=eventText(change.before)+' → '+eventText(change.event); }
      else if (change.kind==='preset_save') { tag.textContent='Save'; body.textContent='Template '+change.name; }
      else { tag.textContent='Add'; body.textContent=eventText(change.event); }
      row.append(tag,body);
      list.append(row);
    }
    const zone=document.createElement('p'); zone.className='draft-zone';
    zone.textContent='Times are in '+currentUser.timezone+'.';
    container.append(heading,list,zone);
  }
  // Only rebuild a run card when something visible changed, so buttons keep focus while polling.
  function signature(run) {
    return JSON.stringify([run.status, run.stage, run.error, run.draft && run.draft.revision,
      run.pending && run.pending.question, run.result && run.result.response, run.result && run.result.saved_event_date]);
  }
  function render(run) {
    let box=aiMessages.querySelector('[data-run-id="'+run.run_id+'"]');
    const created=!box;
    if (!box) { box=document.createElement('div'); box.className='ai-msg agent-run'; box.dataset.runId=run.run_id; aiMessages.append(box); }
    const sig=signature(run);
    if (!created && box.dataset.sig===sig) return;
    box.dataset.sig=sig;
    const nearBottom=aiMessages.scrollHeight-aiMessages.scrollTop-aiMessages.clientHeight<80;
    box.replaceChildren();
    box.dataset.status=run.status;
    const label=document.createElement('p'); label.className='run-stage'; label.textContent=run.stage || run.status; box.append(label);
    if (['queued','running'].includes(run.status)) box.setAttribute('aria-busy','true'); else box.removeAttribute('aria-busy');
    if (run.status==='awaiting_input') {
      const question=document.createElement('p'); question.className='run-question'; question.textContent=run.pending.question || 'Please answer below.'; box.append(question);
      aiPrompt.placeholder='Type your answer…';
      aiPrompt.focus();
    }
    if (run.status==='awaiting_approval' && run.draft) {
      preview(box,run.draft);
      const actions=document.createElement('div'); actions.className='agent-actions';
      actions.append(button('Approve',()=>decide(run,true),'agent-approve'),button('Reject',()=>decide(run,false),'agent-reject'));
      box.append(actions);
      const hint=document.createElement('p'); hint.className='run-hint'; hint.textContent='Nothing is saved until you approve. To change the plan, describe the change in the message box.'; box.append(hint);
    }
    if (run.status==='completed') {
      label.textContent=run.result.response || 'Completed.';
      if (run.result.saved_event_date) {
        box.append(button('View saved event', () => window.calendarUI.showDate(run.result.saved_event_date)));
      }
      for (const source of run.result.sources || []) {
        try {
          const url=new URL(source.url);
          if (url.protocol !== 'https:') continue;
          const link=document.createElement('a'); link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer';
          link.textContent=source.title || url.hostname; box.append(link,document.createElement('br'));
        } catch {}
      }
    }
    if (run.status==='cancelled' && run.result.response) label.textContent=run.result.response;
    if (run.status==='failed') {
      label.textContent=run.error || 'Could not finish. Your progress is saved.';
      box.append(button('Retry saved run', async()=>track(await request('/api/agent/runs/'+run.run_id+'/retry','POST'))));
    }
    if (!terminal.has(run.status)) {
      box.append(button('Cancel request',async()=>track(await request('/api/agent/runs/'+run.run_id+'/cancel','POST'))));
    }
    if (created || nearBottom) aiMessages.scrollTop=aiMessages.scrollHeight;
  }
  function track(run) {
    active=run;
    aiSendBtn.disabled=["queued","running"].includes(run.status);
    currentSessionId=run.session_id;
    try { sessionStorage.setItem('predestination:last-session:'+currentUser.id,run.session_id); } catch {}
    render(run);
    clearTimeout(timer);
    const ticket=++generation;
    if (!terminal.has(run.status) && !['awaiting_input','awaiting_approval'].includes(run.status)) {
      timer=setTimeout(()=>poll(run.run_id,ticket),1000);
    } else {
      fetchSlots(); loadSessions(); memorySuggestions();
    }
    return run;
  }
  let reconnectToast=0;
  async function poll(id,ticket) {
    try {
      const run=await request('/api/agent/runs/'+id);
      if (ticket===generation) track(run);
    } catch(error) {
      if (ticket!==generation) return;
      if (Date.now()-reconnectToast>15000) { reconnectToast=Date.now(); showToast('Connection interrupted. Reconnecting…','error'); }
      timer=setTimeout(()=>poll(id,ticket),3000);
    }
  }
  async function send() {
    const original=aiPrompt.value;
    const text=original.trim();
    if (!text || deciding || aiRequestInFlight || sessionHistoryLoading) return;
    if(pendingRequest) {
      aiRequestInFlight=true;
      try { const recovered=await request(pendingRequest.path,'POST',pendingRequest.body); pendingRequest=null; track(recovered); showToast('Recovered the previous request. Your current text has not been submitted.','info'); }
      catch(error) { showToast(error.message,'error'); }
      finally { aiRequestInFlight=false; }
      return;
    }
    aiRequestInFlight=true; aiSendBtn.disabled=true;
    const userMessage=document.createElement('div'); userMessage.className='user-msg'; userMessage.textContent=text; aiMessages.append(userMessage);
    aiMessages.scrollTop=aiMessages.scrollHeight;
    try {
      let run;
      if (active && active.session_id===currentSessionId && ['awaiting_input','awaiting_approval'].includes(active.status)) {
        pendingRequest=pendingRequest || {path:'/api/agent/runs/'+active.run_id+'/resume',
          body:{interrupt_id:active.pending.interrupt_id,response:text,request_id:uid()}};
      } else {
        if (active && active.session_id===currentSessionId && !terminal.has(active.status)) throw new Error('This request is still running. Wait or cancel it.');
        const start=getAiStartAfter();
        pendingRequest=pendingRequest || {path:'/api/agent/chat',body:{prompt:text, session_id:currentSessionId,
          start_after:start || null,slack:Number(slackSlider.value),request_id:uid()}};
      }
      run=await request(pendingRequest.path,'POST',pendingRequest.body);
      pendingRequest=null;
      if (aiPrompt.value===original) aiPrompt.value='';
      aiPrompt.placeholder='e.g. Plan 6 hours of calculus revision before Friday, after my classes…';
      track(run);
    } catch(error) {
      if(error.httpStatus) pendingRequest=null;
      userMessage.textContent=text+' — '+error.message;
    } finally {
      aiRequestInFlight=false; aiSendBtn.disabled=!!active && active.session_id===currentSessionId && ['queued','running'].includes(active.status);
    }
  }
  async function decide(run,accept) {
    if (active!==run || deciding || aiRequestInFlight || sessionHistoryLoading || pendingRequest) {
      throw new Error('Wait for the current request or review the latest proposal.');
    }
    const box=aiMessages.querySelector('[data-run-id="'+run.run_id+'"]');
    const controls=[...box.querySelectorAll('button')];
    const label=box.querySelector('p');
    const stage=label.textContent;
    deciding=true;
    aiSendBtn.disabled=true;
    controls.forEach(control => { control.disabled=true; });
    label.textContent=accept ? 'Saving…' : 'Rejecting…';
    try {
      track(await request('/api/agent/'+(accept?'confirm':'reject'),'POST',
        {session_id:run.session_id,draft_id:run.draft.id,revision:run.draft.revision}));
    } catch(error) {
      if (error.httpStatus===409) {
        showToast('The calendar changed while you were reviewing. Showing the latest proposal.','error');
        try { track(await request('/api/agent/runs/'+run.run_id)); } catch {}
        return;
      }
      throw error;
    } finally {
      deciding=false;
      if (active===run) {
        label.textContent=stage;
        controls.forEach(control => { control.disabled=false; });
        aiSendBtn.disabled=false;
      }
    }
  }
  async function restore(sessionId) {
    ++generation; clearTimeout(timer); active=null;
    const runs=await request('/api/agent/sessions/'+sessionId+'/runs');
    const run=runs.find(r=>!terminal.has(r.status)) || runs[0];
    if (run && sessionId===currentSessionId) track(run);
  }
  async function restoreRun(runId) {
    const run=await request('/api/agent/runs/'+runId);
    if (currentSessionId!==run.session_id) await resumeSession(run.session_id,'Draft preview');
    track(run);
    window.calendarUI?.openTools('ai');
  }
  async function memorySuggestions() {
    try {
      const proposals=await request('/api/memory-proposals');
      for (const p of proposals) {
        if (aiMessages.querySelector('[data-memory-id="'+p.id+'"]')) continue;
        const box=document.createElement('div'); box.className='ai-msg'; box.dataset.memoryId=p.id;
        const text=document.createElement('p'); text.textContent='Remember for future conversations? '+p.content;
        box.append(text);
        for (const accept of [true,false]) box.append(button(accept?'Remember':'No thanks',async()=>{
          await request('/api/memory-proposals/'+p.id+'/decision','POST',{accept}); box.remove();
          if (!memoryPanel.hidden) loadMemoryPreferences();
        }));
        aiMessages.append(box);
      }
    } catch {}
  }
  // Timezone picker: a labelled dialog instead of a free-text prompt.
  function setupTimezoneDialog(zoneButton) {
    const dialog=document.getElementById('tz-dialog'), select=document.getElementById('tz-select');
    const error=document.getElementById('tz-error'), save=document.getElementById('tz-save');
    const browserZone=Intl.DateTimeFormat().resolvedOptions().timeZone;
    let zones=[];
    try { zones=Intl.supportedValuesOf('timeZone'); } catch {}
    for (const zone of [currentUser.timezone, browserZone, 'UTC', 'Asia/Kolkata']) if (zone && !zones.includes(zone)) zones.unshift(zone);
    select.replaceChildren(...zones.map(zone => { const o=document.createElement('option'); o.value=zone; o.textContent=zone.replace(/_/g,' '); return o; }));
    function open() {
      select.value=currentUser.timezone_confirmed ? currentUser.timezone : browserZone;
      error.textContent='';
      if (!dialog.open) dialog.showModal();
      select.focus();
    }
    zoneButton.addEventListener('click', open);
    document.getElementById('tz-cancel').addEventListener('click', () => dialog.close());
    document.getElementById('tz-form').addEventListener('submit', async event => {
      event.preventDefault();
      save.disabled=true; error.textContent='';
      try {
        currentUser=await request('/api/me/timezone','PUT',{timezone:select.value});
        zoneButton.textContent='Timezone: '+currentUser.timezone;
        dialog.close();
        setDate(window.calendarNow());
        showToast('Timezone confirmed','success');
      } catch(failure) { error.textContent=failure.message || 'Could not save the timezone.'; }
      finally { save.disabled=false; }
    });
    return open;
  }
  async function initialize() {
    const bar=document.createElement('div'); bar.className='timezone-control';
    const zoneButton=document.createElement('button');
    zoneButton.type='button'; zoneButton.textContent='Timezone: '+currentUser.timezone;
    zoneButton.setAttribute('aria-label','Calendar timezone: '+currentUser.timezone+'. Change');
    const openTimezone=setupTimezoneDialog(zoneButton);
    bar.append(zoneButton); userEmail.parentElement.append(bar);
    if(!currentUser.timezone_confirmed) setTimeout(openTimezone, 400);
    let saved=null;
    try { saved=sessionStorage.getItem('predestination:last-session:'+currentUser.id); } catch {}
    if(saved && !currentSessionId) await resumeSession(saved,'Resumed conversation');
    await memorySuggestions();
    let lastSync = null;
    setInterval(async () => {
      if (document.hidden) return;
      try {
        const jobs = await request('/api/google/jobs');
        const completed = jobs.filter(j=>j.status==='completed').map(j=>j.id).join(',');
        if(completed && completed !== lastSync) fetchSlots();
        lastSync=completed;
        for(const job of jobs.filter(j=>j.status==='failed')) {
          if(aiMessages.querySelector('[data-sync-id="'+job.id+'"]')) continue;
          const box=document.createElement('div'); box.className='ai-msg'; box.dataset.syncId=job.id;
          const text=document.createElement('p'); text.textContent=job.error || 'Google synchronization needs attention.';
          box.append(text,button('Retry Google sync',async()=>{await request('/api/google/jobs/'+job.id+'/retry','POST');box.remove();}));
          aiMessages.append(box);
        }
      } catch {}
    },15000);
  }
  return {send,restore,restoreRun,initialize, clear(){active=null;++generation;clearTimeout(timer);pendingRequest=null;}};
})();
async function sendAiMessage(){ return window.agentUI.send(); }
