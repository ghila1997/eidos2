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

// Il log è per fasi, non per chiamata: N chiamate consecutive dello stesso
// tool sono UNA riga con un contatore che sale ("Preparo il cestinamento · 12"
// → "· 30"). Trenta righe identiche non sono informazione, sono una cascata:
// il numero di righe deve restare leggibile qualunque cosa faccia l'assistente.
function scriviRigaStep(row) {
  const n = Number(row.dataset.quante || 1);
  const conta = n > 1 ? ` · ${n}` : '';
  const avanzamento = row.dataset.avanzamento ? ` · ${row.dataset.avanzamento}` : '';
  const tick = row.classList.contains('errore') ? '✗'
    : row.classList.contains('run') ? '●' : '✓';
  row.innerHTML = `<span class="tick">${tick}</span>${escapeHTML(row.dataset.etichetta || '')}` +
    `<span class="conta">${escapeHTML(conta + avanzamento)}</span>`;
}

function ambientStepInizio(id, etichetta) {
  if (!stepsEl) ambientNuovoTurno('');
  const nome = etichetta || 'Lavoro…';
  // Stessa etichetta dell'ultima riga? Non se ne apre una nuova: si conta.
  const ultima = stepsEl.lastElementChild;
  if (ultima && ultima.dataset.etichetta === nome) {
    ultima.dataset.quante = String(Number(ultima.dataset.quante || 1) + 1);
    ultima.dataset.toolId = id || ultima.dataset.toolId;   // l'ultimo id apre/chiude la riga
    ultima.classList.remove('done', 'errore');
    ultima.classList.add('run');
    scriviRigaStep(ultima);
    return;
  }
  const row = document.createElement('div');
  row.className = 'amb-step run';   // "in corso": il pallino pulsa (processo vivo)
  row.dataset.toolId = id || ('t' + Date.now());
  row.dataset.etichetta = nome;
  row.dataset.quante = '1';
  // Le righe "Preparo ..." sono azioni soltanto PROPOSTE: restano in sospeso
  // finché non passano dal gate. Marcandole, la conferma può trasformarle
  // nella fase successiva ("Cestino le mail · 4/30") invece di lasciarle lì
  // col ✓ a sembrare cose già fatte.
  if (nome.startsWith('Preparo')) row.dataset.preparata = '1';
  scriviRigaStep(row);
  stepsEl.appendChild(row);
}
function ambientStepFine(id, esito) {
  const row = stepsEl && stepsEl.querySelector(`[data-tool-id="${cssEscape(id)}"]`);
  if (!row) return;
  const errore = esito === 'errore';
  row.classList.remove('run');
  row.classList.add(errore ? 'errore' : 'done');
  scriviRigaStep(row);
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
function ambientEsito(testo, classe = 'done') {
  // Una riga di log come le altre, in coda ai passi del turno che l'ha
  // preparata: sotto "Preparo l'invio della mail" compare "✓ Mail inviata a X".
  // Non è un'altra categoria di evento - è la stessa cosa dei passi, solo
  // avvenuta dopo la conferma; prima lampeggiava a parte e spariva in 2s,
  // lasciando il log fermo su "Preparo" senza dire mai se fosse partita.
  // In cronologia continua a non andare (DECISIONS 2026-07-29: la verità di
  // "cosa ho fatto" sta in Gmail/Calendar).
  if (!stepsEl) ambientNuovoTurno('');
  // La superficie a quel punto è quasi sempre già a riposo (.settled, opacità
  // 0.5): il turno è finito da un pezzo, la conferma arriva quando l'utente
  // clicca. Senza risvegliarla la riga dell'esito finiva mezza trasparente in
  // fondo a un flusso spento - c'era, ma non si vedeva. Ed è l'unica riga che
  // dice cos'è successo davvero.
  convo.classList.remove('settled');
  // Le righe delle azioni proposte sono superate: al loro posto UNA riga che
  // dice cosa è successo davvero. Trenta "Preparo il cestinamento" col ✓
  // raccontavano una cosa non ancora avvenuta e non venivano mai chiuse.
  stepsEl.querySelectorAll('[data-preparata]').forEach((r) => r.remove());
  const row = document.createElement('div');
  row.className = `amb-step ${classe}`;
  row.innerHTML = `<span class="tick">${classe === 'errore' ? '✗' : '✓'}</span>${escapeHTML(testo)}`;
  stepsEl.appendChild(row);
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
    const conta = p.quante > 1 ? `<span class="conta"> · ${p.quante}</span>` : '';
    return `<div class="${cls}"><span class="tick">${glyph}</span>${escapeHTML(p.etichetta || '')}${conta}</div>`;
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
  // Con la cronologia aperta l'ambient è `display: none` (vedi style.css): tutto
  // quello che ci scriviamo lì diventa invisibile. L'esecuzione di un gruppo di
  // azioni e il suo esito devono comparire ANCHE qui, altrimenti chi sta
  // leggendo la cronologia conferma 30 cestinamenti e non vede mai il
  // risultato — successo davvero, e sembrava che non funzionasse niente.
  const daMostrare = turnoInCorso || faseAzione;
  if (!convo.classList.contains('open') || !daMostrare) { if (esistente) esistente.remove(); return; }
  const vuoto = history.querySelector('.history-empty');
  if (vuoto) vuoto.remove();
  let tail = esistente;
  if (!tail) { tail = document.createElement('div'); tail.className = 'live-tail'; history.appendChild(tail); }
  const u = turnoUtenteCorrente
    ? `<div class="turn user"><span class="who">Tu</span><div class="msg">${escapeHTML(turnoUtenteCorrente)}</div></div>` : '';
  const testo = rispostaCorrente.trim()
    ? `<div class="msg">${escapeHTML(rispostaCorrente)}</div>` : '<div class="msg ghost">…</div>';
  const passi = passiCorrenti.slice();
  if (faseAzione) passi.push(faseAzione);
  tail.innerHTML = u + `<div class="turn assistant"><span class="who">Eidos</span>${testo}${passiInlineHTML(passi)}</div>`;
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

/* ---- gate di conferma: scheda "formato mail" (sempre nitida) ----
   Una scheda sola anche quando il turno prepara N azioni (es. 21 mail nel
   cestino): la decisione umana è una, chiederla 21 volte non è più sicuro,
   è solo più faticoso — e prima portava l'utente a vederne una e perdere di
   vista le altre 20. Le voci si possono escludere una per una prima di
   confermare: `escluse` tiene gli id tolti, e partono comunque tutti al
   server (a `false`), così un'esclusione resta una decisione registrata. */
let azioneCorrente = null;
let escluse = new Set();

function oraLeggibile(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
}

function vociAttive() {
  const voci = (azioneCorrente?.descrizione?.voci) || [];
  return voci.filter((v) => !escluse.has(v.id));
}

function renderVoci() {
  const voci = (azioneCorrente?.descrizione?.voci) || [];
  return voci
    .map((v) => {
      const fuori = escluse.has(v.id);
      return (
        `<li class="cf-voce${fuori ? ' fuori' : ''}" data-id="${escapeHTML(v.id)}">` +
          `<span class="cf-voce-testo">${escapeHTML(v.riepilogo || '')}</span>` +
          `<button type="button" class="cf-voce-x" data-id="${escapeHTML(v.id)}" ` +
            `title="${fuori ? 'Rimetti nella lista' : 'Togli dalla lista'}" ` +
            `aria-label="${fuori ? 'Rimetti' : 'Togli'} ${escapeHTML(v.riepilogo || '')}">` +
            `${fuori ? '↺' : '×'}</button>` +
        `</li>`
      );
    })
    .join('');
}

function aggiornaContoConferma() {
  const attive = vociAttive().length;
  const yes = $('cf-yes');
  const lista = $('cf-lista');
  if (lista) lista.innerHTML = renderVoci();
  if (yes) {
    yes.textContent = attive > 1 ? `Sì, procedi (${attive})` : 'Sì, procedi';
    // niente da eseguire = niente da confermare: resta solo "Annulla"
    yes.disabled = attive === 0;
  }
  const rimaste = $('cf-rimaste');
  if (rimaste) {
    const fuori = escluse.size;
    rimaste.textContent = fuori ? `${fuori} ${fuori > 1 ? 'escluse' : 'esclusa'}` : '';
  }
  agganciaX();
}

function agganciaX() {
  confirmBox.querySelectorAll('.cf-voce-x').forEach((b) => {
    b.onclick = () => {
      const id = b.dataset.id;
      if (escluse.has(id)) escluse.delete(id); else escluse.add(id);
      aggiornaContoConferma();
    };
  });
}

function mostraConferma(azione) {
  azioneCorrente = azione;
  escluse = new Set();
  const d = azione.descrizione || { titolo: 'Conferma richiesta', dettagli: [], corpo: null };
  const prima = (azione.azioni || [])[0] || {};
  const ora = oraLeggibile(prima.created_at);
  const righe = (d.dettagli || [])
    .map((r) => `<span class="k">${escapeHTML(r.etichetta)}</span><span class="v">${escapeHTML(r.valore)}</span>`)
    .join('');
  confirmBox.innerHTML =
    `<div class="cf-head">` +
      `<span class="cf-icon">${escapeHTML(d.icona || '⚙')}</span>` +
      `<span class="cf-title" id="cf-title">${escapeHTML(d.titolo || 'Conferma richiesta')}</span>` +
      (ora ? `<span class="cf-time">preparata · ${ora}</span>` : '') +
    `</div>` +
    (d.multipla ? `<ul class="cf-lista" id="cf-lista">${renderVoci()}</ul>` : '') +
    (righe ? `<div class="cf-details">${righe}</div>` : '') +
    (d.corpo ? `<div class="cf-body">${escapeHTML(d.corpo)}</div>` : '') +
    `<div class="confirm-actions">` +
      `<span class="cf-ask">Vuoi procedere?</span>` +
      `<span class="cf-rimaste" id="cf-rimaste"></span>` +
      `<button type="button" class="secondary" id="cf-no">Annulla</button>` +
      `<button type="button" class="enter" id="cf-yes">Sì, procedi</button>` +
    `</div>`;
  confirmBox.hidden = false;
  $('cf-yes').addEventListener('click', () => risolviConferma(true));
  $('cf-no').addEventListener('click', () => risolviConferma(false));
  if (d.multipla) aggiornaContoConferma();
  $('cf-yes').focus();
  abilitaInput(false); // finché c'è una scheda aperta l'input resta bloccato
}

function chiudiConferma() {
  confirmBox.hidden = true;
  confirmBox.innerHTML = '';
  azioneCorrente = null;
  escluse = new Set();
  abilitaInput(true);
}

async function risolviConferma(conferma) {
  if (!azioneCorrente) return;
  // Tutte le voci partono, anche quelle escluse: a `false`. Un'esclusione è
  // una decisione ("questa no"), non un'omissione — e lascia il gruppo pulito
  // invece di lasciare pendenti invisibili che riemergono al turno dopo.
  const decisioni = {};
  for (const a of (azioneCorrente.azioni || [])) {
    decisioni[a.id] = conferma && !escluse.has(a.id);
  }
  if (!Object.keys(decisioni).length) { chiudiConferma(); return; }
  const quante = Object.values(decisioni).filter(Boolean).length;

  // La scheda se ne va e la fase parte SUBITO, prima della chiamata: il server
  // esegue in background e i suoi eventi possono arrivare prima che questa
  // funzione riprenda dopo l'await. Creando la riga dopo, un `azione_fine`
  // veloce trovava la fase non ancora aperta, mostrava l'esito e poi si
  // apriva una riga "Eseguo… 0/N" che non si chiudeva più, con l'input
  // bloccato. Aprirla prima toglie la corsa alla radice.
  chiudiConferma();
  if (!conferma) {
    // anche l'annullamento chiude le righe "Preparo ...": restare aperte
    // suggerirebbe che qualcosa sia ancora in corso.
    ambientEsito(`Annullato (${Object.keys(decisioni).length} azioni)`, 'errore');
    programmaSpegnimento(1600);
  } else {
    iniziaFaseEsecuzione(quante);
  }

  try {
    const r = await fetch('/azioni/conferma-gruppo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decisioni }),
    });
    if (r.ok) return;   // 202: il resto lo raccontano azione_progresso/azione_fine
    let msg = 'Non sono riuscito a completare l’azione. Riprova.';
    try { const b = await r.json(); if (b && b.detail) msg = b.detail; } catch { /* corpo non JSON */ }
    chiudiFaseEsecuzione(msg, true);
  } catch {
    // La richiesta non è nemmeno partita: niente è stato avviato sul server.
    chiudiFaseEsecuzione('Connessione assente: non ho avviato niente, riprova.', true);
  }
}

/* ---- fase di esecuzione: una riga che conta mentre il gruppo va avanti ----
   Vive in DUE posti perché le due superfici si escludono a vicenda: la riga
   nell'ambient (chiuso) e `faseAzione` nella cronologia (aperta, dove
   l'ambient è display:none). Un esito visibile solo in una delle due viste è
   un esito che metà delle volte non si vede. */
let rigaEsecuzione = null;
let faseAzione = null;

function iniziaFaseEsecuzione(totale) {
  if (!stepsEl) ambientNuovoTurno('');
  convo.classList.remove('settled');
  stepsEl.querySelectorAll('[data-preparata]').forEach((r) => r.remove());
  rigaEsecuzione = document.createElement('div');
  rigaEsecuzione.className = 'amb-step run';
  rigaEsecuzione.dataset.etichetta = 'Eseguo le azioni confermate';
  rigaEsecuzione.dataset.quante = '1';
  rigaEsecuzione.dataset.avanzamento = `0/${totale}`;
  scriviRigaStep(rigaEsecuzione);
  stepsEl.appendChild(rigaEsecuzione);
  ambientTrim();
  faseAzione = { etichetta: `Eseguo le azioni confermate · 0/${totale}`, esito: 'ok', fatto: false };
  aggiornaLiveHistory();
  abilitaInput(false);   // finché il gruppo gira non si apre un turno nuovo
}

function aggiornaFaseEsecuzione(fatte, totale) {
  if (rigaEsecuzione) {
    rigaEsecuzione.dataset.avanzamento = `${fatte}/${totale}`;
    scriviRigaStep(rigaEsecuzione);
  }
  if (faseAzione) {
    faseAzione.etichetta = `Eseguo le azioni confermate · ${fatte}/${totale}`;
    aggiornaLiveHistory();
  }
}

function chiudiFaseEsecuzione(esito, errore) {
  // La riga di avanzamento diventa la riga di esito: una sola riga racconta
  // tutta la fase, dall'inizio al risultato.
  if (rigaEsecuzione) { rigaEsecuzione.remove(); rigaEsecuzione = null; }
  ambientEsito(esito || 'Fatto', errore ? 'errore' : 'done');
  faseAzione = { etichetta: esito || 'Fatto', esito: errore ? 'errore' : 'ok', fatto: true };
  aggiornaLiveHistory();
  abilitaInput(true);
  programmaSpegnimento();
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
let rifiutiConsecutivi = 0;   // handshake rifiutati di fila = sessione scaduta

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
  let apertaDavvero = false;
  ws.addEventListener('open', () => { apertaDavvero = true; tentativiRiconn = 0; setConn('online'); });
  ws.addEventListener('message', (ev) => gestisciEvento(JSON.parse(ev.data)));
  ws.addEventListener('close', () => {
    if (chiusuraVoluta) return;
    if (turnoInCorso) {
      // il turno era in volo: il motore server-side non lo riemette, va detto.
      turnoInCorso = false;
      statoEssere('idle');
      ambientErrore('Connessione persa durante la risposta. Riprova.');
    }
    // Chiusa senza essersi mai aperta = il server ha rifiutato l'handshake,
    // quasi sempre perché la sessione è scaduta. Ritentare all'infinito con
    // la spia su "riconnessione" lascia l'utente davanti a una UI che sembra
    // viva ma non riceve più niente: nessun esito di azione, nessuna risposta.
    // Meglio dirlo e fermarsi (STOP 2, 2026-07-30: sessione scaduta = eventi
    // persi in silenzio).
    if (!apertaDavvero) {
      rifiutiConsecutivi += 1;
      if (rifiutiConsecutivi >= 3) {
        setConn('offline');
        ambientErrore('Sessione scaduta: ricarica la pagina per rientrare.');
        return;   // niente altri tentativi
      }
    } else {
      rifiutiConsecutivi = 0;
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

const IN_LOCALE = location.hostname === '127.0.0.1' || location.hostname === 'localhost';

function gestisciEvento(e) {
  // In locale traccia gli eventi delle azioni: sono rari e sono quelli su cui
  // serve poter capire "è arrivato al browser o no?" senza indovinare.
  if (IN_LOCALE && String(e.evento || '').startsWith('azione')) console.debug('[eidos]', e);
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
      const etichetta = e.etichetta || e.tool || '';
      // Stessa aggregazione del flusso dal vivo, anche nei passi salvati in
      // cronologia: trenta voci identiche resterebbero lì per sempre.
      const ultimo = passiCorrenti[passiCorrenti.length - 1];
      if (ultimo && ultimo.etichetta === etichetta) {
        ultimo.quante = (ultimo.quante || 1) + 1;
        ultimo.fatto = false;
        passoPerId[e.id] = ultimo;
      } else {
        // niente `quante` finché è 1: una chiamata singola resta come prima
        const passo = { etichetta, esito: 'ok', fatto: false };
        passiCorrenti.push(passo);
        passoPerId[e.id] = passo;
      }
      ambientStepInizio(e.id, etichetta);
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
    // Avanzamento di un gruppo di azioni confermate: NON nasce da un messaggio
    // dell'utente, arriva mentre il server esegue (la POST di conferma ha già
    // risposto 202 e la scheda è sparita).
    case 'azione_progresso':
      aggiornaFaseEsecuzione(e.fatte, e.totale);
      break;
    case 'azione_fine':
      // `differito`: l'esito era rimasto senza nessuno a cui consegnarlo (socket
      // caduto, sessione scaduta) e arriva ora, all'apertura del canale. Va
      // detto che è roba di prima, non una cosa appena successa.
      chiudiFaseEsecuzione(e.differito ? `${e.esito} (mentre eri disconnesso)` : e.esito, e.errore);
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
  faseAzione = null;   // l'esito del gruppo precedente appartiene al turno prima
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
