(() => {
  const mic = document.getElementById('ai-mic');
  const cancel = document.getElementById('ai-mic-cancel');
  const status = document.getElementById('ai-voice-status');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let active = null;

  function finish(recognition, message) {
    if (active !== recognition) return false;
    active = null;
    mic.textContent = 'Record';
    mic.disabled = false;
    cancel.hidden = true;
    status.textContent = message;
    return true;
  }

  mic.addEventListener('click', () => {
    if (active) {
      status.textContent = 'Processing speech…';
      mic.disabled = true;
      active.stop();
      return;
    }
    if (!Recognition) {
      status.textContent = 'Voice input is unavailable in this browser. You can type your request.';
      return;
    }
    const recognition = new Recognition();
    const original = aiPrompt.value;
    let transcript = '';
    active = recognition;
    recognition.interimResults = false;
    mic.textContent = 'Stop';
    cancel.hidden = false;
    status.textContent = 'Starting microphone…';
    recognition.onstart = () => {
      if (active === recognition && !mic.disabled) status.textContent = 'Listening…';
    };
    recognition.onspeechend = () => {
      if (active === recognition) status.textContent = 'Processing speech…';
    };
    recognition.onresult = event => {
      if (active !== recognition) return;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) transcript += ' ' + event.results[i][0].transcript;
      }
    };
    recognition.onerror = event => {
      const messages = {
        'not-allowed': 'Microphone permission was denied.',
        'service-not-allowed': 'Speech recognition permission was denied.',
        'audio-capture': 'No microphone was available.',
        'no-speech': 'No speech was heard.',
        network: 'Speech recognition lost its connection.'
      };
      finish(recognition, (messages[event.error] || 'Speech recognition failed.') + ' Try again or type your request.');
    };
    recognition.onend = () => {
      transcript = transcript.trim();
      if (!finish(recognition, transcript ? 'Transcript ready. Edit it, then select Review request.' :
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
