
/* ── Auth ──────────────────────────────────────────────────────── */
const authEmail    = document.getElementById('auth-email');
const authPassword = document.getElementById('auth-password');
const authError    = document.getElementById('auth-error');
const mainContent  = document.getElementById('main-content');

async function checkAuth() {
  try { const r = await fetch(window.API_BASE_URL + '/api/me', { credentials: 'include' }); if (r.ok) { window.location.href = window.PLANNER_URL; return; } } catch (e) {}
  mainContent.style.display = 'flex';
}
async function readApiError(response, fallback='Request failed') {
  try {
    const data = await response.json();
    if (data.detail) { return Array.isArray(data.detail) ? data.detail[0].msg || fallback : data.detail; }
    return data.error || fallback;
  } catch(e) { return fallback; }
}
async function submitAuth(mode) {
  const email = authEmail.value.trim(), password = authPassword.value;
  authError.textContent = '';
  if (!email) { authError.textContent = 'Enter your email address.'; authEmail.focus(); return; }
  if (!password) { authError.textContent = 'Enter your password.'; authPassword.focus(); return; }
  const buttons = [loginBtn, signupBtn];
  buttons.forEach(b => { b.disabled = true; });
  (mode === 'login' ? loginBtn : signupBtn).dataset.label = (mode === 'login' ? loginBtn : signupBtn).textContent;
  (mode === 'login' ? loginBtn : signupBtn).textContent = mode === 'login' ? 'Signing in…' : 'Creating…';
  try {
    const r = await fetch(window.API_BASE_URL + `/api/auth/${mode}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email,password}), credentials: 'include' });
    if (!r.ok) { authError.textContent = await readApiError(r, mode === 'login' ? 'Could not sign in.' : 'Could not create the account.'); return; }
    window.location.href = window.PLANNER_URL;
  } catch(e) { authError.textContent = 'Could not reach the server. Check your connection and try again.'; }
  finally {
    buttons.forEach(b => { b.disabled = false; });
    for (const b of buttons) if (b.dataset.label) { b.textContent = b.dataset.label; delete b.dataset.label; }
  }
}
const loginBtn = document.getElementById('auth-login-btn'), signupBtn = document.getElementById('auth-signup-btn');
document.getElementById('auth-form').addEventListener('submit', e => { e.preventDefault(); authPassword.autocomplete = 'current-password'; submitAuth('login'); });
signupBtn.addEventListener('click', () => { authPassword.autocomplete = 'new-password'; submitAuth('signup'); });
checkAuth();

/* ── Background animation ──────────────────────────────────────── */
(function () {
  const cv  = document.getElementById('bg-canvas');
  const ctx = cv.getContext('2d');
  let W, H, dpr;

  function resize() {
    dpr = window.devicePixelRatio || 1;
    W = cv.parentElement.clientWidth;
    H = cv.parentElement.clientHeight;
    cv.width  = W * dpr;
    cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener('resize', resize);
  resize();

  /* ─── Timeline blocks (scene 0) ─────────────────────────── */
  const TL_BLOCKS = [
    { yFrac: 0.10, hFrac: 0.16, color: '#6c5ce7', delay: 0.0  },
    { yFrac: 0.32, hFrac: 0.13, color: '#00b894', delay: 0.45 },
    { yFrac: 0.51, hFrac: 0.20, color: '#e17055', delay: 0.90 },
    { yFrac: 0.78, hFrac: 0.11, color: '#0984e3', delay: 1.35 },
  ];

  /* ─── Task list rows (scene 1) ──────────────────────────── */
  const LS_ITEMS = [
    { bar: 0.80, color: '#6c5ce7', done: true,  delay: 0.00 },
    { bar: 0.60, color: '#00b894', done: true,  delay: 0.35 },
    { bar: 0.90, color: '#e17055', done: false, delay: 0.70 },
    { bar: 0.45, color: '#0984e3', done: false, delay: 1.05 },
    { bar: 0.70, color: '#d6309e', done: false, delay: 1.40 },
  ];

  /* ─── Bar chart (scene 2) ───────────────────────────────── */
  const CH_HEIGHTS = [0.55, 0.75, 0.40, 0.90, 0.60, 0.80, 0.45];
  const CH_COLORS  = ['#6c5ce7','#00b894','#0984e3','#e17055','#d6309e','#a29bfe','#00b894'];
  const CH_LABELS  = ['M','T','W','T','F','S','S'];

  /* ─── Shared helpers ────────────────────────────────────── */
  function easeOut(t) { return 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3); }

  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  /* hex color → rgba string with alpha */
  function rgba(hex, a) {
    const r = parseInt(hex.slice(1,3),16);
    const g = parseInt(hex.slice(3,5),16);
    const b = parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${a})`;
  }

  /* ─── Scene draw functions ──────────────────────────────── */

  /* Scene 0 — Timeline */
  function drawTimeline(t, masterAlpha) {
    const a   = masterAlpha;
    const lx  = W * 0.10;
    const blL = W * 0.16;
    const blR = W * 0.62;

    /* axis line */
    ctx.save();
    ctx.globalAlpha = a * 0.35;
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(lx, H * 0.04); ctx.lineTo(lx, H * 0.96); ctx.stroke();
    ctx.restore();

    /* time labels */
    ctx.save();
    ctx.globalAlpha = a * 0.85;
    ctx.fillStyle = '#c0c0d8';
    ctx.font = '600 10px Unbounded, sans-serif';
    ctx.textAlign = 'right';
    for (let i = 0; i < 5; i++) {
      const yy = H * 0.06 + (H * 0.88) * (i / 4);
      ctx.fillText((9 + i * 2) + ':00', lx - 8, yy + 4);
    }
    ctx.restore();

    /* blocks */
    TL_BLOCKS.forEach(b => {
      const p  = easeOut((t - b.delay) / 0.9);
      if (p <= 0) return;
      const bw = (blR - blL) * p;
      const yy = H * b.yFrac;
      const bh = H * b.hFrac;

      /* glow */
      ctx.save();
      ctx.globalAlpha = a * 0.75 * p;
      ctx.shadowColor = b.color;
      ctx.shadowBlur  = 28;
      ctx.fillStyle   = b.color;
      roundRect(ctx, blL, yy, bw, bh, 4); ctx.fill();
      ctx.restore();

      /* glass highlight */
      ctx.save();
      ctx.globalAlpha = a * 0.25 * p;
      ctx.fillStyle   = '#fff';
      roundRect(ctx, blL, yy, bw, bh * 0.38, 4); ctx.fill();
      ctx.restore();

      /* tick mark */
      ctx.save();
      ctx.globalAlpha = a * 0.5 * p;
      ctx.strokeStyle = b.color;
      ctx.lineWidth   = 1;
      ctx.beginPath(); ctx.moveTo(lx - 4, yy + bh / 2); ctx.lineTo(lx + 4, yy + bh / 2); ctx.stroke();
      ctx.restore();
    });

    /* "now" indicator */
    const np = easeOut((t - 2.3) / 0.7);
    if (np > 0) {
      const ny = H * 0.42;
      ctx.save();
      ctx.globalAlpha = a * np;
      ctx.shadowColor = '#e17055'; ctx.shadowBlur = 16 * np;
      ctx.strokeStyle = '#e17055'; ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(lx - 6, ny); ctx.lineTo(blR + 16, ny); ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(lx - 6, ny, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = '#e17055'; ctx.fill();
      ctx.restore();
    }
  }

  /* Scene 1 — Task list */
  function drawList(t, masterAlpha) {
    const a      = masterAlpha;
    const itemH  = H * 0.105;
    const gap    = H * 0.032;
    const totalH = LS_ITEMS.length * (itemH + gap) - gap;
    const startY = (H - totalH) / 2;
    const padX   = W * 0.07;
    const itemW  = W * 0.60;

    LS_ITEMS.forEach((item, i) => {
      const p  = easeOut((t - item.delay) / 0.65);
      if (p <= 0) return;
      const yy = startY + i * (itemH + gap);
      const ox = (1 - p) * 32;

      /* card bg */
      ctx.save();
      ctx.globalAlpha = a * 0.85 * p;
      ctx.fillStyle   = '#1c1c20';
      roundRect(ctx, padX + ox, yy, itemW, itemH, 5); ctx.fill();
      ctx.globalAlpha = a * 0.5 * p;
      ctx.strokeStyle = '#2c2c34'; ctx.lineWidth = 1;
      roundRect(ctx, padX + ox, yy, itemW, itemH, 5); ctx.stroke();
      ctx.restore();

      /* checkbox */
      const cx2 = padX + ox + 16;
      const cy2 = yy + itemH / 2;
      ctx.save();
      ctx.globalAlpha = a * p;
      ctx.strokeStyle = item.done ? '#00b894' : '#3a3a4a';
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(cx2, cy2, 6, 0, Math.PI * 2); ctx.stroke();
      if (item.done) {
        ctx.beginPath();
        ctx.moveTo(cx2 - 3.5, cy2); ctx.lineTo(cx2 - 0.5, cy2 + 3); ctx.lineTo(cx2 + 4.5, cy2 - 3);
        ctx.strokeStyle = '#00b894'; ctx.stroke();
      }
      ctx.restore();

      /* progress bar track */
      const barX = padX + ox + 30;
      const barW = (itemW - 44) * item.bar * p;
      const barY = yy + itemH * 0.30;
      const barH2 = itemH * 0.38;
      ctx.save();
      ctx.globalAlpha = a * 0.18 * p;
      ctx.fillStyle   = item.color;
      roundRect(ctx, barX, barY, itemW - 44, barH2, 3); ctx.fill();
      ctx.restore();
      /* fill */
      ctx.save();
      ctx.globalAlpha = a * p;
      ctx.shadowColor = item.color; ctx.shadowBlur = 14 * p;
      ctx.fillStyle   = item.color;
      roundRect(ctx, barX, barY, barW, barH2, 3); ctx.fill();
      ctx.restore();
    });

    /* pulsing AI dot */
    const sp = easeOut((t - 2.5) / 0.5);
    if (sp > 0) {
      const yy  = startY + 2 * (itemH + gap) + itemH / 2;
      const sx  = padX + itemW - 14;
      const pulse = 1 + 0.18 * Math.sin(t * 5.5);
      ctx.save();
      ctx.globalAlpha = a * sp;
      ctx.shadowColor = '#6c5ce7'; ctx.shadowBlur = 22 * pulse * sp;
      ctx.fillStyle   = '#6c5ce7';
      ctx.beginPath(); ctx.arc(sx, yy, 7 * pulse, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }
  }

  /* Scene 2 — Bar chart */
  function drawChart(t, masterAlpha) {
    const a      = masterAlpha;
    const padX   = W * 0.07;
    const padYT  = H * 0.14;
    const padYB  = H * 0.14;
    const bottom = H - padYB;
    const chartH = H - padYT - padYB;
    const chartW = W * 0.60;
    const nBars  = CH_HEIGHTS.length;
    const barGap = chartW * 0.04;
    const barW   = (chartW - barGap * (nBars - 1)) / nBars;

    /* grid lines */
    ctx.save();
    ctx.globalAlpha = a * 0.12;
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 0.5;
    for (let g = 1; g <= 3; g++) {
      const gy = bottom - (chartH * g / 4);
      ctx.beginPath(); ctx.moveTo(padX, gy); ctx.lineTo(padX + chartW, gy); ctx.stroke();
    }
    ctx.restore();

    CH_HEIGHTS.forEach((bh, i) => {
      const p  = easeOut((t - i * 0.18) / 0.85);
      if (p <= 0) return;
      const xx      = padX + i * (barW + barGap);
      const actualH = chartH * bh * p;
      const yy      = bottom - actualH;

      ctx.save();
      ctx.globalAlpha = a * p;
      ctx.shadowColor = CH_COLORS[i]; ctx.shadowBlur = 22 * p;
      ctx.fillStyle   = CH_COLORS[i];
      roundRect(ctx, xx, yy, barW, actualH, 4); ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.globalAlpha = a * 0.25 * p;
      ctx.fillStyle   = '#fff';
      roundRect(ctx, xx, yy, barW, actualH * 0.38, 4); ctx.fill();
      ctx.restore();

      /* day label */
      ctx.save();
      ctx.globalAlpha = a * 0.9 * p;
      ctx.fillStyle   = '#b0b0c8';
      ctx.font        = '600 9px Unbounded, sans-serif';
      ctx.textAlign   = 'center';
      ctx.fillText(CH_LABELS[i], xx + barW / 2, bottom + 14);
      ctx.restore();
    });

    /* trend line */
    const lp = easeOut((t - 1.6) / 1.8);
    if (lp > 0) {
      const pts = CH_HEIGHTS.map((bh, i) => ({
        x: padX + i * (barW + barGap) + barW / 2,
        y: bottom - chartH * bh
      }));
      const drawUpTo = (pts.length - 1) * Math.min(lp, 1);
      ctx.save();
      ctx.globalAlpha = a * lp;
      ctx.shadowColor = '#a29bfe'; ctx.shadowBlur = 18 * lp;
      ctx.strokeStyle = '#a29bfe'; ctx.lineWidth = 2;
      ctx.lineJoin    = 'round';
      ctx.beginPath();
      pts.forEach((p2, i) => {
        if (i > drawUpTo) return;
        i === 0 ? ctx.moveTo(p2.x, p2.y) : ctx.lineTo(p2.x, p2.y);
      });
      ctx.stroke();
      const dotIdx = Math.min(Math.floor(drawUpTo), pts.length - 1);
      const dot    = pts[dotIdx];
      ctx.beginPath(); ctx.arc(dot.x, dot.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#a29bfe'; ctx.fill();
      ctx.restore();
    }
  }

  /* ─── Scene sequencer ──────────────────────────────────── */
  const SCENES  = [drawTimeline, drawList, drawChart];
  const SCENE_HOLD = 6200; /* ms visible before next scene */
  const FADE_MS    = 900;

  let sceneIdx    = 0;
  let sceneStart  = performance.now();
  let sceneT      = 0;    /* seconds since scene reset */
  let prevScene   = -1;
  let prevT       = 0;
  let crossfade   = 0;    /* 0→1 transition progress */
  let transitioning = false;

  /* ─── Main render loop ─────────────────────────────────── */
  let lastTime = performance.now();

  function frame(now) {
    const dt = Math.min(now - lastTime, 50);
    lastTime = now;

    const elapsed = now - sceneStart;

    /* advance scene time only until we start fading out */
    if (elapsed < SCENE_HOLD) {
      sceneT += dt / 1000;
    }

    /* start transition */
    if (!transitioning && elapsed >= SCENE_HOLD) {
      transitioning = true;
      prevScene = sceneIdx;
      prevT     = sceneT;
      sceneIdx  = (sceneIdx + 1) % SCENES.length;
      sceneT    = 0;
      crossfade = 0;
    }
    if (transitioning) {
      crossfade += dt / FADE_MS;
      sceneT    += dt / 1000;
      if (crossfade >= 1) {
        crossfade     = 1;
        transitioning = false;
        prevScene     = -1;
        sceneStart    = now;
        /* don't reset sceneT — let it keep running from where crossfade ended */
      }
    }

    /* clear */
    ctx.clearRect(0, 0, W, H);

    /* draw outgoing scene (fading out) */
    if (transitioning && prevScene >= 0) {
      const outAlpha = 1 - easeOut(crossfade);
      SCENES[prevScene](prevT, outAlpha * 1.4);
    }

    /* draw incoming / steady scene */
    const inAlpha = transitioning ? easeOut(crossfade) : 1.0;
    SCENES[sceneIdx](sceneT, inAlpha * 1.4);

    if (!reducedMotion) requestAnimationFrame(frame);
  }

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  requestAnimationFrame(frame);
})();
