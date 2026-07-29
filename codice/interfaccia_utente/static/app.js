/* Interfaccia Eidos — Tappe 7.1 + 7.2.
   7.1: login + essere vivente + un turno di solo testo in streaming (/ws/session).
   7.2: log azioni dal vivo, gate di conferma visivo (scheda "formato mail" con
   descrizione fornita dal server), spia stato connessione con auto-riconnessione.
   Vanilla JS, nessun framework (DECISIONS 2026-07-28). */
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
const actionsLog = $('actions-log');
const confirmBox = $('confirm-box');
const connStatus = $('conn-status');

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

/* ---- log azioni: righe in corso (›) -> fatto (✓) / errore (✗), per id ---- */
function pulisciLog() { actionsLog.innerHTML = ''; }

function logInizio(id, etichetta) {
  const row = document.createElement('div');
  row.className = 'log-row';
  row.dataset.toolId = id || ('t' + Date.now());
  row.innerHTML = `<span class="tick">›</span>${escapeHTML(etichetta || 'Lavoro…')}`;
  actionsLog.appendChild(row);
}
function logFine(id, esito) {
  const row = actionsLog.querySelector(`[data-tool-id="${cssEscape(id)}"]`);
  if (!row) return;
  const errore = esito === 'errore';
  row.classList.add(errore ? 'errore' : 'done');
  row.querySelector('.tick').textContent = errore ? '✗' : '✓';
}
function logRigaEsito(testo, errore) {
  const row = document.createElement('div');
  row.className = 'log-row ' + (errore ? 'errore' : 'done');
  row.innerHTML = `<span class="tick">${errore ? '✗' : '✓'}</span>${escapeHTML(testo)}`;
  actionsLog.appendChild(row);
}

/* ---- gate di conferma: scheda "formato mail" ---- */
let azioneCorrente = null;

function oraLeggibile(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
}

function mostraConferma(azione) {
  azioneCorrente = azione;
  const d = azione.descrizione || { titolo: 'Conferma richiesta', dettagli: [], corpo: null };
  const ora = oraLeggibile(azione.created_at);
  const righe = (d.dettagli || [])
    .map((r) => `<span class="k">${escapeHTML(r.etichetta)}</span><span class="v">${escapeHTML(r.valore)}</span>`)
    .join('');
  confirmBox.innerHTML =
    `<div class="cf-head">` +
      `<span class="cf-icon">${escapeHTML(d.icona || '⚙')}</span>` +
      `<span class="cf-title" id="cf-title">${escapeHTML(d.titolo || 'Conferma richiesta')}</span>` +
      (ora ? `<span class="cf-time">preparata · ${ora}</span>` : '') +
    `</div>` +
    (righe ? `<div class="cf-details">${righe}</div>` : '') +
    (d.corpo ? `<div class="cf-body">${escapeHTML(d.corpo)}</div>` : '') +
    `<div class="confirm-actions">` +
      `<span class="cf-ask">Vuoi procedere?</span>` +
      `<button type="button" class="secondary" id="cf-no">Annulla</button>` +
      `<button type="button" class="enter" id="cf-yes">Sì, procedi</button>` +
    `</div>`;
  confirmBox.hidden = false;
  $('cf-yes').addEventListener('click', () => risolviConferma(true));
  $('cf-no').addEventListener('click', () => risolviConferma(false));
  $('cf-yes').focus();
  abilitaInput(false); // finché c'è una scheda aperta l'input resta bloccato
}

function chiudiConferma() {
  confirmBox.hidden = true;
  confirmBox.innerHTML = '';
  azioneCorrente = null;
  abilitaInput(true);
}

async function risolviConferma(conferma) {
  if (!azioneCorrente) return;
  const id = azioneCorrente.id;
  const titolo = (azioneCorrente.descrizione || {}).titolo || 'Azione';
  $('cf-yes').disabled = true; $('cf-no').disabled = true;
  try {
    const r = await fetch(`/azioni/${encodeURIComponent(id)}/conferma`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conferma }),
    });
    if (!r.ok) {
      // 404 (già risolta/altra sessione) o 409: la scheda non è più valida.
      chiudiConferma();
      mostraBar('<span class="ghost">Questa conferma non è più valida.</span>');
      return;
    }
    const stato = (await r.json()).stato;
    chiudiConferma();
    if (stato === 'confermata_inviata') {
      logRigaEsito(`${titolo}: fatto`, false);
      mostraBar('Fatto ✓', { idle: false });
    } else if (stato === 'rifiutata') {
      mostraBar('<span class="ghost">Annullato.</span>', { idle: true });
    } else if (stato === 'scaduta') {
      mostraBar('<span class="err">La conferma è scaduta. Richiedila di nuovo.</span>');
    } else {
      mostraBar(`<span class="ghost">Stato: ${escapeHTML(stato)}</span>`);
    }
  } catch {
    // rete assente al momento della conferma: si riprova (scheda resta).
    $('cf-yes').disabled = false; $('cf-no').disabled = false;
    mostraBar('<span class="err">Connessione assente, riprova a confermare.</span>');
  }
}

/* ---- sessione WebSocket: /ws/session ---- */
let ws = null;
let turnoInCorso = false;
let rispostaCorrente = '';
let primoDeltaVisto = false;
let chiusuraVoluta = false;
let tentativiRiconn = 0;
let timerRiconn = null;

function urlWS() {
  const schema = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${schema}://${location.host}/ws/session`;
}

function setConn(stato) {
  connStatus.dataset.stato = stato;
  connStatus.querySelector('.txt').textContent =
    stato === 'online' ? 'Online' : stato === 'riconnessione' ? 'Riconnessione…' : 'Offline';
}

function connettiWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  if (!navigator.onLine) { setConn('offline'); return; }
  chiusuraVoluta = false;
  ws = new WebSocket(urlWS());
  ws.addEventListener('open', () => { tentativiRiconn = 0; setConn('online'); });
  ws.addEventListener('message', (ev) => gestisciEvento(JSON.parse(ev.data)));
  ws.addEventListener('close', () => {
    if (chiusuraVoluta) return;
    if (turnoInCorso) {
      // il turno era in volo: il motore server-side non lo riemette, va detto.
      turnoInCorso = false;
      statoEssere('idle');
      mostraBar('<span class="err">Connessione persa durante la risposta. Riprova.</span>');
    }
    programmaRiconnessione();
  });
}

function programmaRiconnessione() {
  if (timerRiconn) return;
  if (!navigator.onLine) { setConn('offline'); return; }
  setConn('riconnessione');
  const attesa = Math.min(15000, 1000 * 2 ** tentativiRiconn); // backoff 1s→15s
  tentativiRiconn += 1;
  timerRiconn = setTimeout(() => { timerRiconn = null; connettiWS(); }, attesa);
}

addEventListener('online', () => { tentativiRiconn = 0; connettiWS(); });
addEventListener('offline', () => setConn('offline'));

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
      logInizio(e.id, e.etichetta || e.tool);
      break;
    case 'tool_finito':
      logFine(e.id, e.esito);
      break;
    case 'azione_in_attesa':
      // 409 reso come scheda (non errore): c'era già un'azione da confermare.
      turnoInCorso = false;
      abilitaInput(true);
      statoEssere('idle');
      mostraConferma(e.azione);
      break;
    case 'fine':
      turnoInCorso = false;
      statoEssere('idle');
      if (e.azione_in_attesa) {
        if (rispostaCorrente.trim()) mostraBar(escapeHTML(rispostaCorrente));
        mostraConferma(e.azione_in_attesa);
      } else {
        abilitaInput(true);
        if (rispostaCorrente.trim()) mostraBar(escapeHTML(rispostaCorrente));
        else mostraBar('', { idle: true });
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
  pulisciLog();
  abilitaInput(false);
  statoEssere('thinking');
  mostraBar('<span class="ghost">…</span>');

  const spedisci = () => ws.send(JSON.stringify({ tipo: 'messaggio', testo }));
  if (ws && ws.readyState === WebSocket.OPEN) {
    spedisci();
    return;
  }
  connettiWS();
  if (ws) {
    ws.addEventListener('open', spedisci, { once: true });
  } else {
    // offline: nessun socket. Non lasciare l'input bloccato in eterno.
    turnoInCorso = false;
    abilitaInput(true);
    statoEssere('idle');
    mostraBar('<span class="err">Sei offline. Il messaggio non è stato inviato.</span>');
  }
}

function abilitaInput(on) {
  // con una scheda di conferma aperta l'input resta bloccato comunque.
  const bloccato = !on || !confirmBox.hidden;
  sendButton.disabled = bloccato;
  textInput.disabled = bloccato;
  if (!bloccato) textInput.focus();
}

textForm.addEventListener('submit', (ev) => {
  ev.preventDefault();
  const testo = textInput.value.trim();
  if (!testo || turnoInCorso || !confirmBox.hidden) return;
  textInput.value = '';
  inviaMessaggio(testo);
});

/* ---- autenticazione ---- */
async function mostraApp() {
  loginSection.hidden = true;
  appSection.hidden = false;
  appMostrata = true;
  setConn(navigator.onLine ? 'online' : 'offline');
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
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
function cssEscape(s) {
  return String(s).replace(/["\\]/g, '\\$&');
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
