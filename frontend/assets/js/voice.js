/* Spoken conversation: listen, ask the voice agent, speak the reply, and narrate planner progress.
   Recognition and speech run in the browser; the server decides what to do. Typing always works too. */
(() => {
  const mic = document.getElementById('ai-mic');
  const label = document.getElementById('ai-mic-label');
  const cancel = document.getElementById('ai-mic-cancel');
  const status = document.getElementById('ai-voice-status');
  const handsFree = document.getElementById('ai-handsfree');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  const LABELS = { idle: 'Talk', listening: 'Stop', thinking: 'Thinking…', speaking: 'Stop talking' };
  let state = 'idle', recognition = null, speechQueue = Promise.resolve(), pendingSpeech = 0;
  const voiceRuns = new Set(), narrated = new Set();

  function setState(next, message) {
    state = next;
    mic.dataset.state = next;
    mic.classList.toggle('recording', next === 'listening');
    mic.setAttribute('aria-pressed', String(next === 'listening'));
    label.textContent = LABELS[next];
    cancel.hidden = next !== 'listening';
    if (message !== undefined) status.textContent = message;
  }

  function bubble(className, text) {
    const item = document.createElement('div');
    item.className = className;
    item.textContent = text;
    aiMessages.append(item);
    aiMessages.scrollTop = aiMessages.scrollHeight;
  }

  function pickVoice() {
    const voices = synth ? synth.getVoices() : [];
    const english = voices.filter(v => /^en/i.test(v.lang));
    return english.find(v => /en[-_]IN/i.test(v.lang))
      || english.find(v => /natural|online|google/i.test(v.name))
      || english[0] || null;
  }

  function speakNow(text) {
    return new Promise(resolve => {
      if (!synth || !text) { resolve(); return; }
      const utterance = new SpeechSynthesisUtterance(text);
      const voice = pickVoice();
      if (voice) { utterance.voice = voice; utterance.lang = voice.lang; }
      utterance.rate = 1.05;
      utterance.onend = utterance.onerror = () => resolve();
      setState('speaking', 'Speaking… tap Stop talking to interrupt.');
      synth.speak(utterance);
    });
  }

  // Lines are spoken in order; when the last one finishes, hands-free mode listens again.
  function speak(text) {
    pendingSpeech++;
    speechQueue = speechQueue.then(() => speakNow(text)).then(() => {
      pendingSpeech--;
      if (pendingSpeech === 0 && state === 'speaking') {
        setState('idle', 'Tap Talk to reply, or type below.');
        if (handsFree.checked) listen();
      }
    });
    return speechQueue;
  }

  function stopSpeaking() {
    if (synth) synth.cancel();
    pendingSpeech = 0;
    speechQueue = Promise.resolve();
    setState('idle', 'Stopped. Tap Talk when you are ready.');
  }

  function listen() {
    if (!Recognition || recognition || state === 'thinking') return;
    const current = new Recognition();
    let heard = '';
    recognition = current;
    current.lang = /^en/i.test(navigator.language) ? navigator.language : 'en-IN';
    current.interimResults = true;
    current.continuous = false;
    setState('listening', 'Listening… speak, then pause or tap Stop.');
    current.onresult = event => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) heard += ' ' + text; else interim += text;
      }
      const preview = (heard + ' ' + interim).trim();
      if (preview) status.textContent = 'Heard: ' + preview;
    };
    current.onerror = event => {
      const messages = {
        'not-allowed': 'Microphone permission was denied. Allow it in the address bar, or type instead.',
        'service-not-allowed': 'Speech recognition is not permitted in this browser. Type instead.',
        'audio-capture': 'No microphone was found. Type instead.',
        network: 'Speech recognition needs an internet connection. Type instead.'
      };
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        heard = '';
        setState('idle', messages[event.error] || 'Speech recognition failed. Type instead.');
      }
    };
    current.onend = () => {
      recognition = null;
      const text = heard.trim();
      if (text) send(text);
      else if (state === 'listening') setState('idle', 'I didn’t catch that. Tap Talk to try again.');
    };
    try { current.start(); } catch { recognition = null; setState('idle', 'Could not start the microphone. Type instead.'); }
  }

  async function send(text) {
    setState('thinking', 'Thinking…');
    bubble('user-msg voice-msg', text);
    try {
      const response = await fetch(window.API_BASE_URL + '/api/voice/turn', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: text, session_id: currentSessionId || null, request_id: crypto.randomUUID() })
      });
      if (response.status === 401) { window.location.href = window.LOGIN_URL; return; }
      if (!response.ok) throw new Error(await readApiError(response, 'I could not answer that. Try again or type it.'));
      const reply = await response.json();
      if (reply.session_id) currentSessionId = reply.session_id;
      bubble('ai-msg voice-reply', reply.say);
      if (reply.run) { voiceRuns.add(reply.run.run_id); window.agentUI.follow(reply.run); }
      speak(reply.say);
    } catch (error) {
      bubble('ai-msg voice-reply', error.message);
      setState('idle', error.message);
    }
  }

  // Narrate planner progress for requests started by voice.
  function narration(run) {
    if (run.status === 'awaiting_approval' && run.draft) {
      return 'Here’s what I’d do: ' + window.agentUI.describeDraft(run.draft) + '. Should I save it?';
    }
    if (run.status === 'awaiting_input') return run.pending.question || 'I need a little more information.';
    if (run.status === 'completed') {
      const text = (run.result && run.result.response) || '';
      if (/^Approved calendar changes were saved/.test(text)) return 'Done. It’s on your calendar.';
      if (/^Draft rejected/.test(text)) return 'Okay, nothing was changed.';
      return text.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ');
    }
    if (run.status === 'failed') return 'Sorry, that didn’t work. Try again, or type it instead.';
    return null;
  }
  window.addEventListener('agent-run', event => {
    const run = event.detail;
    if (!voiceRuns.has(run.run_id)) return;
    const key = run.run_id + ':' + run.status + ':' + (run.draft ? run.draft.revision : '');
    const line = narration(run);
    if (!line || narrated.has(key)) return;
    narrated.add(key);
    if (state === 'listening' && recognition) recognition.abort();
    speak(line);
  });

  mic.addEventListener('click', () => {
    if (state === 'speaking') { stopSpeaking(); return; }
    if (state === 'listening') { if (recognition) recognition.stop(); return; }
    if (state === 'thinking') return;
    if (synth) synth.getVoices(); // starts loading voices on first use
    listen();
  });
  cancel.addEventListener('click', () => {
    if (!recognition) return;
    const current = recognition;
    recognition = null;
    current.abort();
    setState('idle', 'Cancelled.');
  });

  if (!Recognition) {
    mic.disabled = true;
    handsFree.disabled = true;
    mic.title = 'Talking needs Chrome or Edge. You can type your request instead.';
    setState('idle', 'Talking needs Chrome or Edge. You can type your request instead.');
  } else {
    setState('idle', 'Tap Talk and speak, like "add a study group tomorrow at 6 PM".');
  }
  window.voiceAgent = { speak, stopSpeaking, get state() { return state; } };
})();
