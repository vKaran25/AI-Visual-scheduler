(() => {
  const mic = document.getElementById('ai-mic');
  const label = document.getElementById('ai-mic-label');
  const cancel = document.getElementById('ai-mic-cancel');
  const status = document.getElementById('ai-voice-status');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let active = null;

  // Tell people up front when voice cannot work; typing is always available.
  if (!Recognition) {
    mic.disabled = true;
    mic.title = 'Voice input needs Chrome or Edge. You can type your request instead.';
    status.textContent = 'Voice input needs Chrome or Edge. You can type your request instead.';
  }

  function setRecording(on) {
    mic.classList.toggle('recording', on);
    mic.setAttribute('aria-pressed', String(on));
    label.textContent = on ? 'Stop' : 'Speak';
    cancel.hidden = !on;
  }

  function finish(recognition, message) {
    if (active !== recognition) return false;
    active = null;
    setRecording(false);
    mic.disabled = false;
    status.textContent = message;
    return true;
  }

  mic.addEventListener('click', () => {
    if (active) {
      status.textContent = 'Finishing up…';
      active.stop();
      return;
    }
    if (!Recognition) return;
    const recognition = new Recognition();
    const original = aiPrompt.value;
    let transcript = '';
    active = recognition;
    recognition.lang = navigator.language || 'en-US';
    recognition.interimResults = true;
    recognition.continuous = false;
    setRecording(true);
    status.textContent = 'Starting microphone…';
    recognition.onstart = () => {
      if (active === recognition) status.textContent = 'Listening… speak your request, then press Stop.';
    };
    recognition.onresult = event => {
      if (active !== recognition) return;
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) transcript += ' ' + text; else interim += text;
      }
      const heard = (transcript + ' ' + interim).trim();
      if (heard) status.textContent = 'Heard: ' + heard;
    };
    recognition.onerror = event => {
      const messages = {
        'not-allowed': 'Microphone permission was denied. Allow it in the address bar, or type your request.',
        'service-not-allowed': 'Speech recognition is not permitted in this browser.',
        'audio-capture': 'No microphone was found.',
        'no-speech': 'No speech was heard.',
        network: 'Speech recognition needs an internet connection.'
      };
      finish(recognition, (messages[event.error] || 'Speech recognition failed.') + ' You can type your request instead.');
    };
    recognition.onend = () => {
      transcript = transcript.trim();
      if (!finish(recognition, transcript ? 'Transcript ready. Check it, then press Ask assistant.' :
        'No speech was heard. Try again or type your request.')) return;
      if (transcript) {
        aiPrompt.value = aiPrompt.value === original ? transcript : [aiPrompt.value.trim(), transcript].filter(Boolean).join(' ');
        aiPrompt.focus();
      }
    };
    try {
      recognition.start();
    } catch {
      finish(recognition, 'Could not start the microphone. Try again or type your request.');
    }
  });

  cancel.addEventListener('click', () => {
    const recognition = active;
    if (!recognition) return;
    finish(recognition, 'Recording cancelled.');
    recognition.abort();
    aiPrompt.focus();
  });
})();
