/* Interfaccia Eidos — Tappe 7.1 → 7.3.
   7.1: login + essere vivente + un turno di solo testo in streaming (/ws/session).
   7.2: gate di conferma visivo (scheda "formato mail"), spia stato connessione.
   7.3: superficie conversazione UNICA. In basso, sopra l'input, una superficie
        "ambient" traslucida: i passi del turno e il testo affiorano lì, sfumano
        salendo e a riposo si spengono (l'essere resta il baricentro — si dialoga,
        non si legge). Si espande in cronologia a contrasto pieno (lettura), con
        i passi "fatti in mezzo" apribili per turno. Lo storico persiste per
        tenant e sopravvive al refresh.
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
const convo = $('convo');
const convoToggle = $('convo-toggle');
const ambient = $('ambient');
const history = $('history');
const essere = $('essere-vivente');
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

/* ---- superficie ambient (il turno dal vivo) ----
   Due zone: i passi in alto, il testo che si scrive sotto; l'esito di un'azione
   si aggiunge in coda quando l'azione parte. `settled` = a riposo, si spegne. */
let stepsEl = null;
let sayEl = null;
let timerSettle = null;

// La superficie ambient è un flusso CONTINUO: un nuovo turno NON cancella
// quello prima - si accoda in fondo e le righe vecchie scorrono su e sfumano.
// Così inviare un messaggio è una continuazione fluida, non un reset.
function ambientNuovoTurno(testoUtente) {
  if (timerSettle) { clearTimeout(timerSettle); timerSettle = null; }
  convo.classList.remove('settled');
  const hint = ambient.querySelector('.amb-hint');
  if (hint) hint.remove();                       // via l'accenno iniziale
  if (testoUtente) {
    const u = document.createElement('div');
    u.className = 'amb-user';
    u.textContent = testoUtente;                 // eco discreta del tuo messaggio
    ambient.appendChild(u);
  }
  stepsEl = document.createElement('div');
  stepsEl.className = 'amb-steps';
  sayEl = document.createElement('div');
  sayEl.className = 'amb-say ghost';
  sayEl.textContent = '…';
  ambient.appendChild(stepsEl);
  ambient.appendChild(sayEl);
  ambientTrim();
}

// Non far crescere il DOM all'infinito in una sessione lunga: si vedono solo le
// ultime righe, il resto si può buttare (la cronologia intera è nel DB).
function ambientTrim() {
  while (ambient.children.length > 14) ambient.removeChild(ambient.firstChild);
}

// Dopo un turno il flusso resta (continuità), solo più discreto (.settled):
// qualcosa si vede sempre, l'essere torna baricentro. Si dialoga, non si legge.
function programmaSpegnimento(attesa = 2400) {
  if (timerSettle) clearTimeout(timerSettle);
  timerSettle = setTimeout(() => { convo.classList.add('settled'); timerSettle = null; }, attesa);
}

function ambientStepInizio(id, etichetta) {
  if (!stepsEl) ambientNuovoTurno('');
  const row = document.createElement('div');
  row.className = 'amb-step run';   // "in corso": il pallino pulsa (processo vivo)
  row.dataset.toolId = id || ('t' + Date.now());
  row.innerHTML = `<span class="tick">●</span>${escapeHTML(etichetta || 'Lavoro…')}`;
  stepsEl.appendChild(row);
}
function ambientStepFine(id, esito) {
  const row = stepsEl && stepsEl.querySelector(`[data-tool-id="${cssEscape(id)}"]`);
  if (!row) return;
  const errore = esito === 'errore';
  row.classList.remove('run');
  row.classList.add(errore ? 'errore' : 'done');
  row.querySelector('.tick').textContent = errore ? '✗' : '✓';
}
function assicuraSay() {
  if (!sayEl) {
    sayEl = document.createElement('div');
    sayEl.className = 'amb-say';
    ambient.appendChild(sayEl);
    ambientTrim();
  }
}
function ambientSay(testo) { assicuraSay(); sayEl.className = 'amb-say'; sayEl.textContent = testo; }
function ambientErrore(msg) { assicuraSay(); sayEl.className = 'amb-say err'; sayEl.textContent = msg; }
function ambientEsito(testo) {
  // L'esito di un'azione vive SOLO nel flusso dal vivo, come gli altri log
  // (passi/testo): resta finché c'è la conversazione a schermo, poi scorre su
  // e sparisce. NON si salva in cronologia (niente lista di azioni fatte: la
  // verità di "cosa ho fatto" è in Gmail/Calendar). Vedi DECISIONS 2026-07-29.
  const row = document.createElement('div');
  row.className = 'amb-esito';
  row.innerHTML = `<span class="k">✓</span>${escapeHTML(testo)}`;
  ambient.appendChild(row);
  ambientTrim();
}

/* ---- cronologia (lettura, contrasto pieno) ----
   `storico` = i messaggi salvati (utente / assistente / esito), verità locale
   della conversazione: popolata dall'evento `storico` all'apertura (dal DB,
   sopravvive al refresh) e appesa a ogni turno. I `passi` sull'assistente si
   aprono su richiesta (variante A). */
let storico = [];

// Azioni INLINE come processo (niente espandi, stile Claude Code). Un passo con
// `fatto === false` è ancora in corso (solo dal vivo): pallino che pulsa.
function passiInlineHTML(passi) {
  const arr = Array.isArray(passi) ? passi : [];
  if (!arr.length) return '';
  const righe = arr.map((p) => {
    const running = p.fatto === false;
    const err = p.esito === 'errore';
    const glyph = running ? '●' : (err ? '✗' : '✓');
    const cls = 'passo' + (running ? ' run' : '') + (err ? ' errore' : '');
    return `<div class="${cls}"><span class="tick">${glyph}</span>${escapeHTML(p.etichetta || '')}</div>`;
  }).join('');
  return `<div class="passi-inline">${righe}</div>`;
}

function renderStorico() {
  history.innerHTML = storico.length
    ? storico.map((m) => rigaStorico(m)).join('')
    : '<div class="history-empty">Ancora nessuna conversazione.</div>';
  aggiornaLiveHistory();   // se un turno è in corso, mostralo dal vivo in coda
  history.scrollTop = history.scrollHeight;
}

function rigaStorico(m) {
  if (m.ruolo === 'utente') {
    return `<div class="turn user"><span class="who">Tu</span><div class="msg">${escapeHTML(m.contenuto)}</div></div>`;
  }
  // un turno che ha solo preparato un'azione può non avere testo: niente bolla vuota
  const testo = m.contenuto ? `<div class="msg">${escapeHTML(m.contenuto)}</div>` : '';
  return `<div class="turn assistant"><span class="who">Eidos</span>${testo}${passiInlineHTML(m.passi)}</div>`;
}

// Il turno in corso, mostrato dal vivo IN CODA alla cronologia quando è aperta:
// aprendo a metà esecuzione vedi il processo in tempo reale, non solo a percorso
// finito. Si aggiorna a ogni evento e sparisce a turno chiuso (renderStorico lo
// ricostruisce col turno ormai salvato).
function aggiornaLiveHistory() {
  const esistente = history.querySelector('.live-tail');
  if (!convo.classList.contains('open') || !turnoInCorso) { if (esistente) esistente.remove(); return; }
  const vuoto = history.querySelector('.history-empty');
  if (vuoto) vuoto.remove();
  let tail = esistente;
  if (!tail) { tail = document.createElement('div'); tail.className = 'live-tail'; history.appendChild(tail); }
  const u = turnoUtenteCorrente
    ? `<div class="turn user"><span class="who">Tu</span><div class="msg">${escapeHTML(turnoUtenteCorrente)}</div></div>` : '';
  const testo = rispostaCorrente.trim()
    ? `<div class="msg">${escapeHTML(rispostaCorrente)}</div>` : '<div class="msg ghost">…</div>';
  tail.innerHTML = u + `<div class="turn assistant"><span class="who">Eidos</span>${testo}${passiInlineHTML(passiCorrenti)}</div>`;
  history.scrollTop = history.scrollHeight;
}

function setConvoOpen(open) {
  convo.classList.toggle('open', open);
  document.body.classList.toggle('convo-open', open);
  convoToggle.setAttribute('aria-expanded', String(open));
  convoToggle.setAttribute('aria-label', open ? 'Richiudi cronologia' : 'Espandi cronologia');
  if (open) renderStorico();
}

convoToggle.addEventListener('click', () => setConvoOpen(!convo.classList.contains('open')));
// cliccare il testo ambient apre la cronologia (leggi tutto)
ambient.addEventListener('click', () => { if (!convo.classList.contains('open')) setConvoOpen(true); });

/* ---- gate di conferma: scheda "formato mail" (sempre nitida) ---- */
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
  $('cf-yes').disabled = true; $('cf-no').disabled = true;
  try {
    const r = await fetch(`/azioni/${encodeURIComponent(id)}/conferma`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conferma }),
    });
    if (!r.ok) {
      chiudiConferma();
      if (r.status === 404 || r.status === 409) {
        // scheda davvero non più valida (già risolta/scaduta/altra sessione)
        ambientErrore('Questa conferma non è più valida.');
      } else {
        // l'azione era valida ma l'esecuzione è fallita: mostra il vero motivo
        let msg = 'Non sono riuscito a completare l’azione. Riprova.';
        try { const b = await r.json(); if (b && b.detail) msg = b.detail; } catch { /* corpo non JSON */ }
        ambientErrore(msg);
      }
      return;
    }
    const risposta = await r.json();
    chiudiConferma();
    if (risposta.stato === 'confermata_inviata') {
      // solo conferma dal vivo nel flusso, niente salvataggio in cronologia
      ambientEsito(risposta.esito || 'Fatto');
      programmaSpegnimento(2000);
    } else if (risposta.stato === 'rifiutata') {
      ambientSay('Annullato.');
      programmaSpegnimento(1600);
    } else if (risposta.stato === 'scaduta') {
      ambientErrore('La conferma è scaduta. Richiedila di nuovo.');
    } else {
      ambientSay(`Stato: ${risposta.stato}`);
    }
  } catch {
    // rete assente al momento della conferma: si riprova (scheda resta).
    $('cf-yes').disabled = false; $('cf-no').disabled = false;
    ambientErrore('Connessione assente, riprova a confermare.');
  }
}

/* ---- sessione WebSocket: /ws/session ---- */
let ws = null;
let turnoInCorso = false;
let rispostaCorrente = '';
let turnoUtenteCorrente = '';
let passiCorrenti = [];        // le "cose fatte in mezzo", per la cronologia
let passoPerId = {};
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
      ambientErrore('Connessione persa durante la risposta. Riprova.');
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
    case 'storico':
      // record della conversazione dal DB, inviato all'apertura (anche a ogni
      // riconnessione): è la verità, sostituisce quella locale.
      storico = (e.messaggi || []).map((m) => ({
        ruolo: m.ruolo, contenuto: m.contenuto || '', passi: m.passi || null,
      }));
      if (convo.classList.contains('open')) renderStorico();
      break;
    case 'delta':
      if (!primoDeltaVisto) {
        primoDeltaVisto = true;
        statoEssere('speaking');
        pulseEssere();
      }
      rispostaCorrente += e.testo;
      ambientSay(rispostaCorrente);
      aggiornaLiveHistory();
      break;
    case 'tool_in_corso': {
      const passo = { etichetta: e.etichetta || e.tool || '', esito: 'ok', fatto: false };
      passiCorrenti.push(passo);
      passoPerId[e.id] = passo;
      ambientStepInizio(e.id, passo.etichetta);
      aggiornaLiveHistory();
      break;
    }
    case 'tool_finito':
      if (passoPerId[e.id]) { passoPerId[e.id].esito = e.esito; passoPerId[e.id].fatto = true; }
      ambientStepFine(e.id, e.esito);
      aggiornaLiveHistory();
      break;
    case 'azione_in_attesa':
      // 409 reso come scheda (non errore): c'era già un'azione da confermare.
      turnoInCorso = false;
      abilitaInput(true);
      statoEssere('idle');
      aggiornaLiveHistory();
      mostraConferma(e.azione);
      break;
    case 'fine':
      turnoInCorso = false;
      statoEssere('idle');
      // turno concluso: lo appendo alla cronologia locale (il server lo
      // persiste in parallelo — qui è per vederlo subito senza refetch).
      storico.push({ ruolo: 'utente', contenuto: turnoUtenteCorrente, passi: null });
      storico.push({ ruolo: 'assistente', contenuto: rispostaCorrente.trim(), passi: passiCorrenti.slice() });
      if (convo.classList.contains('open')) renderStorico();
      if (e.azione_in_attesa) {
        // resta in attesa di conferma: l'ambient non si spegne, arriva la scheda
        if (!rispostaCorrente.trim()) ambientSay('Ho preparato l’azione, confermi?');
        mostraConferma(e.azione_in_attesa);
      } else {
        abilitaInput(true);
        if (!rispostaCorrente.trim()) ambientSay('Fatto.');
        programmaSpegnimento();
      }
      break;
    case 'errore':
      turnoInCorso = false;
      abilitaInput(true);
      statoEssere('idle');
      ambientErrore(e.messaggio || 'Errore.');
      aggiornaLiveHistory();
      break;
  }
}

function inviaMessaggio(testo) {
  turnoInCorso = true;
  rispostaCorrente = '';
  turnoUtenteCorrente = testo;
  passiCorrenti = [];
  passoPerId = {};
  primoDeltaVisto = false;
  // NON richiudo la cronologia se è aperta: scrivere è una continuazione, non
  // un motivo per chiudere. Il turno si mostra dal vivo sia in ambient (chiuso)
  // sia in coda alla cronologia (aperto).
  ambientNuovoTurno(testo);   // si accoda, non resetta (continuazione fluida)
  aggiornaLiveHistory();
  abilitaInput(false);
  statoEssere('thinking');

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
    ambientErrore('Sei offline. Il messaggio non è stato inviato.');
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
  // qualcosa si vede sempre: un accenno discreto finché non parte il primo turno
  if (!ambient.querySelector('.amb-say, .amb-step, .amb-user')) {
    ambient.innerHTML = '<div class="amb-say ghost amb-hint">Scrivi o parla per iniziare…</div>';
  }
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
