/* Durable assistant UI. All text from models and sources is rendered as text. */
window.agentUI = (() => {
  let active = null, timer = null, generation = 0;
  let pendingRequest = null;
  const terminal = new Set(['completed','failed','cancelled']);
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
  function button(label, handler) {
    const item = document.createElement('button');
    item.type='button'; item.className='btn-secondary'; item.textContent=label;
    item.addEventListener('click', async () => {
      item.disabled=true;
      try { await handler(); } catch(error) { showToast(error.message,'error'); } finally { if(item.isConnected) item.disabled=false; }
    });
    return item;
  }
  function eventText(value) {
    if (!value) return '';
    const repeat = value.repeatDays && value.repeatDays.length ? ' weekly ('+value.repeatDays.join(', ')+')' : '';
    return (value.label || 'Event')+' · '+(value.date || 'Repeating')+' '+value.start+'–'+value.end+repeat;
  }
  function preview(container, draft) {
    const heading = document.createElement('strong');
    heading.textContent='Proposed changes — times are not reserved';
    const list=document.createElement('ul');
    for (const change of draft.preview.changes || []) {
      const row=document.createElement('li');
      row.textContent=change.kind === 'delete' ? 'Delete: '+eventText(change.before) :
        change.kind === 'update' ? 'Move/edit: '+eventText(change.before)+' → '+eventText(change.event) :
        change.kind === 'preset_save' ? 'Save preset: '+change.name : 'Add: '+eventText(change.event);
      list.append(row);
    }
    container.append(heading,list);
  }
  function render(run) {
    let box=aiMessages.querySelector('[data-run-id="'+run.run_id+'"]');
    if (!box) { box=document.createElement('div'); box.className='ai-msg agent-run'; box.dataset.runId=run.run_id; aiMessages.append(box); }
    box.replaceChildren();
    const label=document.createElement('p'); label.textContent=run.stage || run.status; box.append(label);
    if (run.status==='awaiting_input') {
      const question=document.createElement('p'); question.textContent=run.pending.question || 'Please answer below.'; box.append(question);
      aiPrompt.placeholder='Answer the question…';
    }
    if (run.status==='awaiting_approval' && run.draft) {
      preview(box,run.draft);
      box.append(button('Approve',()=>decide(run,true)),button('Reject',()=>decide(run,false)));
      const hint=document.createElement('p'); hint.textContent='To revise, describe the change in the message box.'; box.append(hint);
    }
    if (run.status==='completed') {
      label.textContent=run.result.response || 'Completed.';
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
    aiMessages.scrollTop=aiMessages.scrollHeight;
  }
  function track(run) {
    active=run;
    aiSendBtn.disabled=["queued","running"].includes(run.status);
    currentSessionId=run.session_id;
    sessionStorage.setItem('predestination:last-session:'+currentUser.id,run.session_id);
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
  async function poll(id,ticket) {
    try {
      const run=await request('/api/agent/runs/'+id);
      if (ticket===generation) track(run);
    } catch(error) {
      if (ticket!==generation) return;
      showToast('Progress connection interrupted. Reconnecting…','error');
      timer=setTimeout(()=>poll(id,ticket),3000);
    }
  }
  async function send(textOverride) {
    const text=(textOverride || aiPrompt.value).trim();
    if (!text || aiRequestInFlight || sessionHistoryLoading) return;
    if(pendingRequest) {
      aiRequestInFlight=true;
      try { const recovered=await request(pendingRequest.path,'POST',pendingRequest.body); pendingRequest=null; track(recovered); showToast('Recovered the previous request. Your current text has not been submitted.','info'); }
      catch(error) { showToast(error.message,'error'); }
      finally { aiRequestInFlight=false; }
      return;
    }
    aiRequestInFlight=true; aiSendBtn.disabled=true;
    const userMessage=document.createElement('div'); userMessage.className='user-msg'; userMessage.textContent=text; aiMessages.append(userMessage);
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
      pendingRequest=null; aiPrompt.value=''; track(run);
    } catch(error) {
      if(error.httpStatus) pendingRequest=null;
      userMessage.textContent=text+' — '+error.message;
    } finally {
      aiRequestInFlight=false; aiSendBtn.disabled=!!active && active.session_id===currentSessionId && ['queued','running'].includes(active.status);
    }
  }
  async function decide(run,accept) {
    const data=await request('/api/agent/'+(accept?'confirm':'reject'),'POST',
      {session_id:run.session_id,draft_id:run.draft.id,revision:run.draft.revision});
    track(data);
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
  async function bulk(accept) {
    const drafts=await request('/api/agent/drafts');
    if (!drafts.length) { showToast('No drafts waiting for approval.','info'); return; }
    const review=document.createElement('dialog'); review.className='agent-bulk-review';
    for (const draft of drafts) preview(review,draft);
    review.append(button(accept?'Approve these exact changes':'Reject these drafts',async()=>{
      for (const draft of drafts) await request('/api/agent/'+(accept?'confirm':'reject'),'POST',
        {session_id:draft.session_id,draft_id:draft.id,revision:draft.revision});
      review.close(); review.remove(); await fetchSlots();
      if(currentSessionId) await restore(currentSessionId);
    }),button('Close',()=>{review.close();review.remove();}));
    document.body.append(review); review.showModal();
  }
  async function initialize() {
    const bar=document.createElement('div'); bar.className='timezone-control';
    const zoneButton=button('Timezone: '+currentUser.timezone,async()=>{
      const value=window.prompt('Calendar timezone (IANA name, for example Asia/Kolkata)',currentUser.timezone_confirmed ? currentUser.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone);
      if(!value) return;
      currentUser=await request('/api/me/timezone','PUT',{timezone:value});
      zoneButton.textContent='Timezone: '+currentUser.timezone;
      setDate(window.calendarNow());
      showToast('Timezone confirmed','success');
    });
    bar.append(zoneButton); userEmail.parentElement.append(bar);
    if(!currentUser.timezone_confirmed) showToast('Confirm your timezone before asking the assistant to schedule.','info');
    const saved=sessionStorage.getItem('predestination:last-session:'+currentUser.id);
    if(saved && !currentSessionId) await resumeSession(saved,'Resumed conversation');
    await memorySuggestions();
    let lastSync = null;
    setInterval(async () => {
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
    },5000);
  }
  return {send,restore,restoreRun,bulk,initialize, clear(){active=null;++generation;clearTimeout(timer);pendingRequest=null;}};
})();
async function sendAiMessage(){ return window.agentUI.send(); }
async function acceptAllPending(){ return window.agentUI.bulk(true); }
async function rejectAllPending(){ return window.agentUI.bulk(false); }
