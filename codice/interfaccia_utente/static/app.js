/* Interfaccia Eidos — Tappa 7.1 (scheletro web end-to-end).
   Login (auth cookie esistente) + essere vivente + un turno di solo testo in
   streaming sul canale unico /ws/session. Niente log/conferme/schede/voce:
   sono le tappe 7.2-7.6. Vanilla JS, nessun framework (DECISIONS 2026-07-28).*/
'use strict';

const $ = (id) => document.getElementById(id);
const loginSection = $('login');
const appSection = $('app');
const loginForm = $('login-form');
const loginError = $('login-error');
const textForm = $('text-form');
const textInput = $('text-input');
const sendButton = textForm.querySelector('button');
const bar = $('transcript-bar');
const essere = $('essere-vivente');

/* ---- essere vivente: pilotaggio via postMessage (API del componente) ---- */
let essereCaricato = false;
let appMostrata = false;

function statoEssere(s) {
  if (essere.contentWindow) essere.contentWindow.postMessage({ type: 'state', value: s }, '*');
}
function pulseEssere() {
  if (essere.contentWindow) essere.contentWindow.postMessage({ type: 'pulse' }, '*');
}
function configuraEssere() {
  const w = essere.contentWindow;
  if (!w) return;
  w.postMessage({ type: 'config', palette: 'nebulaCosmo' }, '*'); // config di produzione
  w.postMessage({ type: 'lab', zoom: 0.85 }, '*');                // −15%, validato sul mockup
  statoEssere('idle');
}
essere.addEventListener('load', () => {
  essereCaricato = true;
  // il componente registra il listener postMessage subito dopo il proprio
  // avvio: un piccolo ritardo evita che config/stato vadano persi.
  if (appMostrata) setTimeout(configuraEssere, 300);
});

/* ---- barra risposta ---- */
function mostraBar(html, opts = {}) {
  bar.innerHTML = html;
  bar.classList.toggle('idle', !!opts.idle);
}

/* ---- sessione WebSocket: /ws/session ---- */
let ws = null;
let turnoInCorso = false;
let rispostaCorrente = '';
let primoDeltaVisto = false;

function urlWS() {
  const schema = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${schema}://${location.host}/ws/session`;
}

function connettiWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  ws = new WebSocket(urlWS());
  ws.addEventListener('message', (ev) => gestisciEvento(JSON.parse(ev.data)));
  ws.addEventListener('close', () => {
    // La spia di connessione (online/riconnessione/offline) e' Tappa 7.2:
    // in 7.1 non falliamo in modo rumoroso, ci si riconnette al prossimo invio.
    if (turnoInCorso) {
      turnoInCorso = false;
      abilitaInput(true);
      statoEssere('idle');
      mostraBar('<span class="err">Connessione persa. Riprova.</span>');
    }
  });
}

function gestisciEvento(e) {
  switch (e.evento) {
    case 'delta':
      if (!primoDeltaVisto) {
        primoDeltaVisto = true;
        statoEssere('speaking');
        pulseEssere();
      }
      rispostaCorrente += e.testo;
      mostraBar(escapeHTML(rispostaCorrente));
      break;
    case 'tool_in_corso':
      // Il log azioni visibile e' Tappa 7.2: qui l'essere resta "thinking".
      break;
    case 'fine':
      turnoInCorso = false;
      abilitaInput(true);
      statoEssere('idle');
      if (e.azione_in_attesa) {
        // Il gate di conferma visivo (scheda Si'/No) e' Tappa 7.2.
        mostraBar(escapeHTML(rispostaCorrente) +
          '<br><span class="ghost">— c’è un’azione in attesa di conferma</span>');
      } else if (rispostaCorrente.trim()) {
        mostraBar(escapeHTML(rispostaCorrente));
      } else {
        mostraBar('', { idle: true });
      }
      break;
    case 'errore':
      turnoInCorso = false;
      abilitaInput(true);
      statoEssere('idle');
      mostraBar(`<span class="err">${escapeHTML(e.messaggio || 'Errore.')}</span>`);
      break;
  }
}

function inviaMessaggio(testo) {
  turnoInCorso = true;
  rispostaCorrente = '';
  primoDeltaVisto = false;
  abilitaInput(false);
  statoEssere('thinking');
  mostraBar('<span class="ghost">…</span>');

  const spedisci = () => ws.send(JSON.stringify({ tipo: 'messaggio', testo }));
  if (ws && ws.readyState === WebSocket.OPEN) {
    spedisci();
  } else {
    connettiWS();
    ws.addEventListener('open', spedisci, { once: true });
  }
}

function abilitaInput(on) {
  sendButton.disabled = !on;
  textInput.disabled = !on;
  if (on) textInput.focus();
}

textForm.addEventListener('submit', (ev) => {
  ev.preventDefault();
  const testo = textInput.value.trim();
  if (!testo || turnoInCorso) return;
  textInput.value = '';
  inviaMessaggio(testo);
});

/* ---- autenticazione ---- */
async function mostraApp() {
  loginSection.hidden = true;
  appSection.hidden = false;
  appMostrata = true;
  if (essereCaricato) setTimeout(configuraEssere, 100);
  connettiWS();
  textInput.focus();
}

function mostraLogin() {
  appSection.hidden = true;
  loginSection.hidden = false;
  $('login-email').focus();
}

loginForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  loginError.hidden = true;
  const email = $('login-email').value.trim();
  const password = $('login-password').value;
  try {
    const r = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) throw new Error('login fallito');
    await mostraApp();
  } catch {
    loginError.textContent = 'Credenziali non valide.';
    loginError.hidden = false;
  }
});

async function avvia() {
  try {
    const r = await fetch('/me');
    if (r.ok) { await mostraApp(); return; }
  } catch { /* rete assente: si mostra il login */ }
  mostraLogin();
}

/* ---- utilita' ---- */
function escapeHTML(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* ---- sfondo: griglia di puntini in prospettiva + rispetta reduced-motion ---- */
(function sfondo() {
  const cv = $('bg'), ctx = cv.getContext('2d');
  let w, h;
  function resize() { w = cv.width = innerWidth; h = cv.height = innerHeight; disegna(); }
  function disegna() {
    ctx.clearRect(0, 0, w, h);
    const step = 30, cx = w / 2, cy = h * 0.42;
    for (let x = 0; x < w; x += step) for (let y = 0; y < h; y += step) {
      const d = Math.hypot(x - cx, y - cy) / Math.hypot(w, h);
      const a = Math.max(0, 0.5 - d * 0.5);
      if (a <= 0.01) continue;
      ctx.fillStyle = `rgba(160,175,255,${a})`;
      ctx.fillRect(x, y, 1.9, 1.9);
    }
  }
  addEventListener('resize', resize);
  resize();
})();

avvia();
