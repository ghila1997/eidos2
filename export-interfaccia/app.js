/*
  Client dell'Interfaccia Utente di Eidos. Vanilla JS, nessun build step
  (coerente con essere_vivente_component.html: stesso principio di
  semplicita'). Un solo WebSocket multiplexa testo, audio (mic in ingresso,
  voce TTS in uscita) ed eventi -- vedi docs/modules/08-interfaccia-utente.md.
*/
(function () {
  'use strict';

  const els = {
    login: document.getElementById('login'),
    loginProviders: document.getElementById('login-providers'),
    loginOr: document.getElementById('login-or'),
    loginGoogle: document.getElementById('login-google'),
    loginMicrosoft: document.getElementById('login-microsoft'),
    loginEmailForm: document.getElementById('login-email-form'),
    loginEmail: document.getElementById('login-email'),
    loginPassword: document.getElementById('login-password'),
    loginDevForm: document.getElementById('login-dev-form'),
    loginDevId: document.getElementById('login-dev-id'),
    loginError: document.getElementById('login-error'),
    loginLead: document.querySelector('.login-lead'),
    loginAuth: document.querySelector('.auth'),
    pairingClaim: document.getElementById('pairing-claim'),
    pairingClaimStatus: document.getElementById('pairing-claim-status'),
    pairingClaimError: document.getElementById('pairing-claim-error'),
    app: document.getElementById('app'),
    essereFrame: document.getElementById('essere-vivente'),
    transcriptBar: document.getElementById('transcript-bar'),
    micButton: document.getElementById('mic-button'),
    modeButtons: document.querySelectorAll('[data-mode]'),
    actionsLog: document.getElementById('actions-log'),
    confirmBox: document.getElementById('confirm-box'),
    confirmMessage: document.getElementById('confirm-message'),
    confirmYes: document.getElementById('confirm-yes'),
    confirmNo: document.getElementById('confirm-no'),
    historyPanel: document.getElementById('history-panel'),
    historyTab: document.getElementById('history-tab'),
    historyList: document.getElementById('history-list'),
    cards: document.getElementById('cards'),
    textForm: document.getElementById('text-form'),
    textInput: document.getElementById('text-input'),
    usage: document.getElementById('usage'),
    usageMonth: document.getElementById('usage-month'),
    usageSpent: document.getElementById('usage-spent'),
    usageBudget: document.getElementById('usage-budget'),
    usageFill: document.getElementById('usage-fill'),
    audioUnlock: document.getElementById('audio-unlock'),
    devicesTab: document.getElementById('devices-tab'),
    devicesPanel: document.getElementById('devices-panel'),
    devicesList: document.getElementById('devices-list'),
    pairingStart: document.getElementById('pairing-start'),
    pairingQr: document.getElementById('pairing-qr'),
    pairingHint: document.getElementById('pairing-hint'),
    pairingExpiry: document.getElementById('pairing-expiry'),
    pairingError: document.getElementById('pairing-error'),
    connectionsList: document.getElementById('connections-list'),
    connectCapability: document.getElementById('connect-capability'),
    connectProvider: document.getElementById('connect-provider'),
    connectStart: document.getElementById('connect-start'),
    connectionsError: document.getElementById('connections-error'),
  };

  const TYPEWRITER_FALLBACK_CHARS_PER_SECOND = 15; // config.TYPEWRITER_FALLBACK_CHARS_PER_SECOND (ADR 012)
  const VOICE_LEVEL_THRESHOLD = 0.04; // livello mic (RMS 0-1) sopra cui l'utente "sta parlando"
  const VOICE_SILENCE_HOLD_MS = 500; // sotto soglia per questo tempo = ha smesso di parlare

  // ---------- ascolto continuo (docs/modules/08-interfaccia-utente.md) ----------
  const PCM_SAMPLE_RATE = 16000;
  const PCM_SEND_CHUNK_MS = 100; // pezzi spediti ogni ~100ms, coerente con Voce in streaming
  const PRE_ROLL_MS = 300; // audio tenuto prima della soglia: il nome non arriva mai mozzato
  const BURST_TAIL_MS = 2000; // coda dopo fine voce prima di chiudere la raffica (dormiente)
  const SEND_CHUNK_SAMPLES = Math.round((PCM_SAMPLE_RATE * PCM_SEND_CHUNK_MS) / 1000);
  const PRE_ROLL_SAMPLES = Math.round((PCM_SAMPLE_RATE * PRE_ROLL_MS) / 1000);

  let ws = null;
  let sessionToken = null;
  let mode = 'normale';
  let dataPresentedThisTurn = false; // evita di riaprire le stesse schede gia' aperte da data_presented
  let pendingMeta = null; // tts_alignment ricevuto, in attesa del frame audio a cui si riferisce
  let localTranscriptBuffer = ''; // testo finale accumulato per la cronologia, vedi turn_started

  // ---------- audio gapless + rivelazione testo continua per turno (ADR 023) ----------
  let audioCtx = null;
  let nextStartTime = 0; // AudioContext-time: quando iniziera' il prossimo pezzo pianificato
  const chunkQueue = []; // {arrayBuffer, meta} grezzi in attesa di decodifica, in ordine di arrivo
  let processingChunks = false;
  const textSegmentQueue = []; // {text, alignment, start, end} pianificati (solo ad audio non bloccato)
  let turnRevealedText = ''; // testo del turno corrente gia' rivelato (si accoda, mai si sostituisce)
  let revealLoopActive = false;
  const blockedRevealQueue = []; // testi grezzi in attesa mentre l'audio e' bloccato (ordine di arrivo)
  let revealingBlocked = false;

  // ---------- fatti per lo stato dell'Essere Vivente ----------
  let awaitingFinal = false; // turno inviato all'Orchestratore, final_result non ancora arrivato
  let userSpeaking = false; // fatto 1: voce dell'utente sopra soglia (con isteresi), dal blocco PCM
  let lastVoiceAt = 0;
  let currentMicLevel = 0; // livello del blocco PCM corrente, mandato al componente in listening
  let ttsAnalyser = null; // livello reale della riproduzione TTS, mandato al componente
  let ttsLevelBuf = null;

  // ---------- microfono continuo (dormiente a raffiche / conversazione a stream) ----------
  let micStream = null; // MediaStream del microfono, acquisito una volta, mai per singolo turno
  let pcmCtx = null;
  let pcmWorkletNode = null;
  let micActive = false; // la cattura continua e' avviata (indipendente dal regime)
  let listenRegime = 'dormiente'; // 'dormiente' | 'conversazione' -- rispecchia UISession.listen_state
  let burstOpen = false; // dormiente: una raffica di voce e' in corso (audio_start gia' mandato)
  let continuousOpen = false; // conversazione: la sessione unica e' aperta (audio_start gia' mandato)
  let lastVoiceAtBurst = 0; // per la coda della raffica (BURST_TAIL_MS), diverso da lastVoiceAt sopra
  let sendBufferChunks = []; // Int16Array[] accumulati, non ancora spediti (fino a SEND_CHUNK_SAMPLES)
  let sendBufferSamples = 0;
  let preRollChunks = []; // Int16Array[] recenti, anello di ~PRE_ROLL_MS
  let preRollSamples = 0;

  function resetTurnState() {
    // Ad ogni turno nuovo: nessun residuo del turno precedente scorre nella
    // barra. Le code si svuotano soltanto -- i cicli di rivelazione attivi
    // (revealLoopActive/revealingBlocked) si spengono da soli al prossimo
    // giro trovandole vuote, non serve azzerarli qui.
    turnRevealedText = '';
    chunkQueue.length = 0;
    textSegmentQueue.length = 0;
    blockedRevealQueue.length = 0;
  }

  // ---------- Essere Vivente (postMessage, contratto gia' definito) ----------
  // Lo stato non si imposta in punti sparsi del codice: una sola regola lo
  // ricalcola dai tre fatti misurabili -- voce dell'utente rilevata, audio TTS
  // in riproduzione, turno aperto -- vedi docs/modules/08-interfaccia-utente.md
  // (sezione Essere Vivente). Priorita': listening > speaking > thinking > idle.

  let lastEssereStato = null;

  function setEssereStato(stato) {
    if (stato === lastEssereStato) return;
    lastEssereStato = stato;
    els.essereFrame.contentWindow.postMessage({ type: 'state', value: stato }, '*');
  }

  function sendEssereLevel(value) {
    els.essereFrame.contentWindow.postMessage({ type: 'level', value }, '*');
  }

  function pulseEssere() {
    els.essereFrame.contentWindow.postMessage({ type: 'pulse' }, '*');
  }

  function audioInRiproduzione() {
    // fatto 3: l'orologio dell'AudioContext non ha ancora raggiunto la fine
    // dell'ultimo pezzo pianificato. Con l'audio bloccato (suspended) non c'e'
    // nulla di udibile: non e' "in riproduzione".
    return !!audioCtx && audioCtx.state === 'running' && audioCtx.currentTime < nextStartTime;
  }

  function turnoAperto() {
    // fatto 2: dall'invio del testo (awaitingFinal) fino a final_result E
    // esaurimento del turno: audio pianificato non finito (orologio congelato
    // compreso) o testo non ancora rivelato (percorso bloccato compreso).
    if (awaitingFinal) return true;
    // audio pianificato non ancora finito -- solo a orologio in moto: se
    // l'audio e' bloccato (suspended) conta la rivelazione del testo, non
    // un audio che partira' solo a sblocco avvenuto
    if (audioCtx && audioCtx.state === 'running' && audioCtx.currentTime < nextStartTime) return true;
    return chunkQueue.length > 0 || textSegmentQueue.length > 0
      || blockedRevealQueue.length > 0 || revealingBlocked;
  }

  function utenteInAscoltoAttivo() {
    // "listening" e' una reazione visibile alla voce dell'utente: ha senso
    // solo a conversazione aperta. Da dormiente l'assistente ignora tutto
    // (non ha ancora sentito il nome) -- deve restare fermo anche se in
    // sottofondo qualcuno parla, altrimenti sembra reagire a chi non ha
    // ancora attivato niente.
    return userSpeaking && listenRegime === 'conversazione';
  }

  function updateEssereStato() {
    if (utenteInAscoltoAttivo()) setEssereStato('listening');
    else if (audioInRiproduzione()) setEssereStato('speaking');
    else if (turnoAperto()) setEssereStato('thinking');
    else setEssereStato('idle');
  }

  // Giro continuo: manda il livello vero al componente (voce dell'utente
  // quando parla -- gia' calcolato blocco per blocco in onPcmBlock, con
  // isteresi VOICE_SILENCE_HOLD_MS contro lo sfarfallio tra una parola e
  // l'altra -- riproduzione TTS quando parla l'assistente) e ricalcola lo
  // stato.
  function essereLoop() {
    if (micActive && utenteInAscoltoAttivo()) {
      sendEssereLevel(currentMicLevel);
    } else if (ttsAnalyser && audioInRiproduzione()) {
      ttsAnalyser.getFloatTimeDomainData(ttsLevelBuf);
      let sum = 0;
      for (let i = 0; i < ttsLevelBuf.length; i++) sum += ttsLevelBuf[i] * ttsLevelBuf[i];
      sendEssereLevel(Math.min(1, Math.sqrt(sum / ttsLevelBuf.length) * 4));
    }
    updateEssereStato();
    requestAnimationFrame(essereLoop);
  }
  requestAnimationFrame(essereLoop);

  // Dimensione e altezza dell'Essere Vivente nella schermata: 1 / 0 = auto-fit
  // pieno, centrata (l'aspetto originale, confermato). Si ritarano col
  // pannello ?dimensioni e si fissano qui.
  const ESSERE_ZOOM = 1.0;
  const ESSERE_OFFSET_Y = 0.12;

  function applyEssereDimensioni() {
    els.essereFrame.contentWindow.postMessage(
      { type: 'lab', zoom: ESSERE_ZOOM, offsetY: ESSERE_OFFSET_Y }, '*');
  }
  els.essereFrame.addEventListener('load', applyEssereDimensioni);
  // se l'iframe fosse gia' carico quando questo script parte, il load non
  // rifira: mando subito, il componente ignora messaggi arrivati troppo presto
  applyEssereDimensioni();

  // ---------- taratura dimensione/altezza (solo con ?dimensioni nell'URL) ----------
  // Pannello temporaneo di laboratorio DENTRO la schermata vera: pilota le leve
  // zoom/offsetY del componente (canale type:'lab') per trovare i valori giusti
  // guardando l'Essere Vivente esattamente dove sta in produzione. Senza il
  // parametro nell'URL non viene creato niente e nessun messaggio parte:
  // l'interfaccia resta identica. Trovati i valori, si fissano e questo blocco
  // si toglie (o resta, dietro il parametro, per ritarature future).

  function setupLabDimensioni() {
    if (!new URLSearchParams(location.search).has('dimensioni')) return;

    const KEY = 'eidosLabDimensioni';
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { saved = {}; }

    const box = document.createElement('div');
    box.id = 'lab-dimensioni';
    box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:999;display:flex;'
      + 'flex-direction:column;gap:10px;padding:14px 16px;border-radius:14px;'
      + 'background:rgba(18,20,42,0.82);border:1px solid rgba(150,165,255,0.25);'
      + 'backdrop-filter:blur(8px);font-size:12px;color:#9aa3c7;min-width:250px';
    box.innerHTML =
      '<b style="color:#eef1ff;letter-spacing:.12em;text-transform:uppercase;font-size:11px">Taratura dimensioni</b>'
      + '<label style="display:flex;gap:8px;align-items:center">Scala'
      + '<input id="lab-zoom" type="range" min="20" max="180" value="' + (ESSERE_ZOOM * 100) + '" style="flex:1;accent-color:#8aa0ff">'
      + '<span id="lab-zoom-val" style="color:#eef1ff;min-width:40px;text-align:right"></span></label>'
      + '<label style="display:flex;gap:8px;align-items:center">Altezza'
      + '<input id="lab-offy" type="range" min="-80" max="80" value="' + (ESSERE_OFFSET_Y * 100) + '" style="flex:1;accent-color:#8aa0ff">'
      + '<span id="lab-offy-val" style="color:#eef1ff;min-width:40px;text-align:right"></span></label>'
      + '<span id="lab-summary" style="font-variant-numeric:tabular-nums">zoom: 1.00 · offsetY: 0.00</span>'
      + '<button id="lab-reset" type="button" style="align-self:flex-start;font:inherit;color:#9aa3c7;'
      + 'background:rgba(0,0,0,.25);border:0;border-radius:8px;padding:5px 10px;cursor:pointer">Reset</button>';
    document.body.appendChild(box);

    const zoom = box.querySelector('#lab-zoom');
    const offy = box.querySelector('#lab-offy');
    const zoomVal = box.querySelector('#lab-zoom-val');
    const offyVal = box.querySelector('#lab-offy-val');
    const summary = box.querySelector('#lab-summary');
    if (typeof saved.zoom === 'number') zoom.value = saved.zoom;
    if (typeof saved.offsetY === 'number') offy.value = saved.offsetY;

    function show() {
      zoomVal.textContent = zoom.value + '%';
      offyVal.textContent = offy.value + '%';
      summary.textContent = 'zoom: ' + (zoom.value / 100).toFixed(2) + ' · offsetY: ' + (offy.value / 100).toFixed(2);
    }
    function apply() {
      els.essereFrame.contentWindow.postMessage(
        { type: 'lab', zoom: zoom.value / 100, offsetY: offy.value / 100 }, '*');
    }
    function persist() {
      localStorage.setItem(KEY, JSON.stringify({ zoom: Number(zoom.value), offsetY: Number(offy.value) }));
    }
    zoom.addEventListener('input', () => { show(); persist(); apply(); });
    offy.addEventListener('input', () => { show(); persist(); apply(); });
    // reset = i valori fissati in produzione, non piu' i default del componente
    box.querySelector('#lab-reset').addEventListener('click', () => {
      zoom.value = ESSERE_ZOOM * 100; offy.value = ESSERE_OFFSET_Y * 100;
      show(); persist(); apply();
    });
    show();

    // il componente parte con i suoi default: al load riallineo con il pannello
    els.essereFrame.addEventListener('load', apply);
    if (els.essereFrame.contentWindow) apply();
  }

  setupLabDimensioni();

  // ---------- login (Supabase Auth, ADR 017) ----------

  const SUPABASE_JS = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

  function showLoginError(message) {
    els.loginError.textContent = message;
    els.loginError.hidden = false;
  }

  // ---------- dispositivi (ADR 020): device_id stabile, kind, label ----------

  const DEVICE_ID_KEY = 'eidos_device_id';

  function getDeviceId() {
    let id = localStorage.getItem(DEVICE_ID_KEY);
    if (!id) {
      id = crypto.randomUUID ? crypto.randomUUID() : `dev-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      localStorage.setItem(DEVICE_ID_KEY, id);
    }
    return id;
  }

  // Euristica lato client, non una scelta dell'utente: touch + schermo piccolo
  // -> mobile, touch + schermo grande -> tablet, nessun touch -> pc. Per un
  // companion accoppiato via QR il kind e' comunque quello dichiarato al
  // claim (vedi handlePairingClaimIfPresent), questa euristica vale solo per
  // il login diretto (che tenta 'pc' o quel che rileva -- un companion senza
  // pairing viene comunque respinto da fondamenta.DeviceError, per costruzione).
  function detectKind() {
    const touch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    if (!touch) return 'pc';
    return Math.min(window.innerWidth, window.innerHeight) >= 600 ? 'tablet' : 'mobile';
  }

  function deviceLabel() {
    const ua = navigator.userAgent || '';
    const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome'
      : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
    return `${browser} su ${navigator.platform || 'dispositivo'}`;
  }

  const KIND_LABELS_DEVICE = { pc: 'PC', mobile: 'Mobile', tablet: 'Tablet' };

  async function loginRequest(accessToken, device) {
    const body = { access_token: accessToken };
    if (device) Object.assign(body, device);
    return fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  function renderDeviceRow(container, d, actionLabel, onAction) {
    const row = document.createElement('div');
    row.className = 'device-row';
    const seen = d.last_seen ? new Date(d.last_seen).toLocaleString('it-IT') : '';
    const info = document.createElement('div');
    info.innerHTML = `<span class="device-kind">${escHtml(KIND_LABELS_DEVICE[d.kind] || d.kind)}</span>`
      + `<span class="device-label">${escHtml(d.label || '')}</span>`
      + `<span class="device-seen">${escHtml(seen)}</span>`;
    row.appendChild(info);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = actionLabel;
    btn.addEventListener('click', onAction);
    row.appendChild(btn);
    container.appendChild(row);
    return row;
  }

  // Il posto per quel tipo di dispositivo e' occupato (409 da /login): apre il
  // pannello Dispositivi con l'elenco gia' ricevuto (niente giro in piu' per
  // rileggerlo) e lascia scegliere quale rimuovere. Serve una sessione per
  // chiamare /devices/deregister: se ne apre una "spoglia" (senza device_id),
  // che non compete per nessun posto -- fondamenta.register_device gira solo
  // se device_id/kind sono presenti.
  async function resolveDeviceLimit(accessToken, detail) {
    let bareToken = null;
    return new Promise((resolve) => {
      els.devicesList.innerHTML = '';
      const note = document.createElement('p');
      note.className = 'device-limit-note';
      note.textContent = `Hai già un dispositivo "${KIND_LABELS_DEVICE[detail.kind] || detail.kind}" collegato: rimuovilo per continuare da qui.`;
      els.devicesList.appendChild(note);
      detail.active.forEach((d) => {
        renderDeviceRow(els.devicesList, d, 'Rimuovi e continua', async () => {
          if (!bareToken) {
            const bare = await loginRequest(accessToken, null);
            if (!bare.ok) { resolve(false); return; }
            bareToken = (await bare.json()).session_token;
          }
          await fetch('/devices/deregister', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${bareToken}` },
            body: JSON.stringify({ device_id: d.device_id }),
          });
          els.devicesPanel.classList.remove('open');
          resolve(true);
        });
      });
      els.devicesPanel.classList.add('open');
      showLoginError('Scegli un dispositivo da rimuovere qui a fianco per continuare l\'accesso.');
    });
  }

  // Passo comune a ogni via di login: preso l'access_token da Supabase (o l'id
  // in modalità sviluppo), registra il dispositivo (ADR 020) e apre la
  // UISession lato server. `forcedKind` lo passa il flusso di pairing (il
  // companion accoppiato e' sempre quel kind, non quel che detectKind()
  // ricalcolerebbe).
  async function enterWithToken(accessToken, forcedKind) {
    const device = { device_id: getDeviceId(), kind: forcedKind || detectKind(), label: deviceLabel() };
    let res = await loginRequest(accessToken, device);
    if (res.status === 409) {
      const { detail } = await res.json();
      const proceed = await resolveDeviceLimit(accessToken, detail);
      if (!proceed) return;
      res = await loginRequest(accessToken, device);
    }
    if (!res.ok) {
      if (res.status === 403) {
        showLoginError('Questo dispositivo va accoppiato dal PC (pannello Dispositivi → "Aggiungi dispositivo").');
      } else {
        showLoginError('Accesso non riuscito. Utente non collegato o sessione non valida.');
      }
      return;
    }
    const body = await res.json();
    sessionToken = body.session_token;
    els.login.hidden = true;
    els.app.hidden = false;
    connect();
    refreshUsage();
    refreshDevices();
    refreshConnections();
    // Mic sempre acceso in Normale/Silenziosa (docs/modules/08-interfaccia-utente.md
    // "Ascolto continuo e attivazione col nome"); in Spenta il pulsante mic lo
    // richiede al primo click (gesto utente esplicito).
    if (mode !== 'spenta') startMic();
  }

  // ---------- pairing di un companion via QR (ADR 020) ----------

  function renderPairingQr(code) {
    const url = `${location.origin}/?pair=${encodeURIComponent(code)}`;
    const qr = qrcode(0, 'M'); // typeNumber 0 = dimensione automatica
    qr.addData(url);
    qr.make();
    els.pairingQr.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2 });
    els.pairingQr.hidden = false;
  }

  els.pairingStart?.addEventListener('click', async () => {
    els.pairingError.hidden = true;
    const res = await fetch('/pairing/start', { method: 'POST', headers: { Authorization: `Bearer ${sessionToken}` } });
    if (!res.ok) {
      els.pairingQr.hidden = true;
      els.pairingHint.hidden = true;
      els.pairingError.textContent = 'Serve un PC come dispositivo principale prima di poter accoppiare un altro dispositivo.';
      els.pairingError.hidden = false;
      return;
    }
    const body = await res.json();
    renderPairingQr(body.code);
    els.pairingExpiry.textContent = new Date(body.expires_at).toLocaleTimeString('it-IT');
    els.pairingHint.hidden = false;
  });

  async function refreshDevices() {
    if (!sessionToken) return;
    const res = await fetch('/devices', { headers: { Authorization: `Bearer ${sessionToken}` } });
    if (!res.ok) return;
    const body = await res.json();
    els.devicesList.innerHTML = '';
    body.devices.forEach((d) =>
      renderDeviceRow(els.devicesList, d, 'Scollega', async () => {
        await fetch('/devices/deregister', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken}` },
          body: JSON.stringify({ device_id: d.device_id }),
        });
        refreshDevices();
      })
    );
  }

  els.devicesTab?.addEventListener('click', () => {
    els.devicesPanel.classList.toggle('open');
    if (els.devicesPanel.classList.contains('open')) {
      refreshDevices();
      refreshConnections();
    }
  });

  // ---------- account cloud collegati (ADR 024: personali per utente) ----------

  // Specchio di PROVIDERS_PER_CAPABILITY lato server (credential_store.py):
  // il server rifiuta comunque un abbinamento non valido, qui serve solo a
  // proporre le scelte giuste.
  const PROVIDERS_BY_CAPABILITY = {
    email: [['gmail', 'Gmail'], ['outlook_mail', 'Outlook']],
    calendario: [['google_calendar', 'Google Calendar'], ['outlook_calendar', 'Outlook Calendar']],
    storage: [['google_drive', 'Google Drive'], ['onedrive', 'OneDrive'], ['dropbox', 'Dropbox']],
    messaggistica: [['slack', 'Slack'], ['teams', 'Teams']],
  };
  const CAPABILITY_LABELS = {
    email: 'Email', calendario: 'Calendario', storage: 'File cloud', messaggistica: 'Messaggi',
  };

  function fillProviderOptions() {
    if (!els.connectProvider) return;
    const providers = PROVIDERS_BY_CAPABILITY[els.connectCapability.value] || [];
    els.connectProvider.innerHTML = '';
    providers.forEach(([value, label]) => {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = label;
      els.connectProvider.appendChild(opt);
    });
  }
  els.connectCapability?.addEventListener('change', fillProviderOptions);
  fillProviderOptions();

  function showConnectionsError(message) {
    els.connectionsError.textContent = message;
    els.connectionsError.hidden = false;
  }

  async function connectionsPost(path, payload) {
    els.connectionsError.hidden = true;
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken}` },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let detail = '';
      try { detail = (await res.json()).detail || ''; } catch (_) { /* corpo non JSON */ }
      showConnectionsError(detail || 'Operazione non riuscita.');
      return false;
    }
    return true;
  }

  function renderConnectionRow(c) {
    const row = document.createElement('div');
    row.className = 'connection-row';
    const info = document.createElement('div');
    const star = c.is_default ? '★ ' : '';
    const who = c.own ? '' : ' (di un altro utente)';
    info.innerHTML = `<span class="connection-label">${star}${escHtml(c.display_label)}</span>`
      + `<span class="connection-provider">${escHtml(c.provider)}${escHtml(who)}</span>`;
    row.appendChild(info);

    if (c.own && !c.is_default) {
      const defaultBtn = document.createElement('button');
      defaultBtn.type = 'button';
      defaultBtn.textContent = 'Predefinito';
      defaultBtn.title = 'Usa questo account quando non ne nomini uno';
      defaultBtn.addEventListener('click', async () => {
        if (await connectionsPost('/connections/default', {
          capability: c.capability, connection_id: c.connection_id,
        })) refreshConnections();
      });
      row.appendChild(defaultBtn);
    }

    // Interruttore "memoria aziendale" (sync verso il Vault condiviso).
    const syncLabel = document.createElement('label');
    syncLabel.className = 'connection-sync';
    const sync = document.createElement('input');
    sync.type = 'checkbox';
    sync.checked = !!c.sync_enabled;
    sync.title = 'Se attivo, i contenuti di questo account entrano nella memoria aziendale condivisa';
    sync.addEventListener('change', async () => {
      const payload = {
        capability: c.capability, connection_id: c.connection_id, enabled: sync.checked,
      };
      if (!c.own) payload.user_id = c.user_id; // solo l'owner arriva qui su account altrui
      if (!(await connectionsPost('/connections/sync', payload))) sync.checked = !sync.checked;
    });
    syncLabel.appendChild(sync);
    syncLabel.appendChild(document.createTextNode(' memoria'));
    row.appendChild(syncLabel);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Scollega';
    btn.addEventListener('click', async () => {
      const payload = { capability: c.capability, connection_id: c.connection_id };
      if (!c.own) payload.user_id = c.user_id;
      if (await connectionsPost('/connections/disconnect', payload)) refreshConnections();
    });
    row.appendChild(btn);
    return row;
  }

  async function refreshConnections() {
    if (!sessionToken || !els.connectionsList) return;
    const res = await fetch('/connections', { headers: { Authorization: `Bearer ${sessionToken}` } });
    if (!res.ok) return;
    const body = await res.json();
    els.connectionsList.innerHTML = '';
    const byCapability = {};
    body.connections.forEach((c) => {
      (byCapability[c.capability] = byCapability[c.capability] || []).push(c);
    });
    Object.keys(CAPABILITY_LABELS).forEach((capability) => {
      const items = byCapability[capability];
      if (!items) return;
      const heading = document.createElement('h4');
      heading.textContent = CAPABILITY_LABELS[capability];
      els.connectionsList.appendChild(heading);
      items.forEach((c) => els.connectionsList.appendChild(renderConnectionRow(c)));
    });
    if (!body.connections.length) {
      const empty = document.createElement('p');
      empty.className = 'connections-empty';
      empty.textContent = 'Nessun account collegato.';
      els.connectionsList.appendChild(empty);
    }
  }

  els.connectStart?.addEventListener('click', async () => {
    els.connectionsError.hidden = true;
    const res = await fetch('/oauth/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken}` },
      body: JSON.stringify({
        capability: els.connectCapability.value,
        provider: els.connectProvider.value,
      }),
    });
    if (!res.ok) {
      let detail = '';
      try { detail = (await res.json()).detail || ''; } catch (_) { /* corpo non JSON */ }
      showConnectionsError(detail || 'Impossibile avviare il collegamento.');
      return;
    }
    const body = await res.json();
    // Si naviga al fornitore per l'autorizzazione; si torna su /oauth/callback.
    window.location.assign(body.url);
  });

  // Companion che apre il link scansionato (?pair=<codice>): schermata dedicata
  // al posto del login normale, niente OAuth/password -- il codice sostituisce
  // la scelta di provider (ADR 020).
  function showPairingClaimError(message) {
    els.pairingClaimStatus.textContent = '';
    els.pairingClaimError.textContent = message;
    els.pairingClaimError.hidden = false;
  }

  async function handlePairingClaimIfPresent() {
    const code = new URLSearchParams(location.search).get('pair');
    if (!code) return false;

    els.loginLead.hidden = true;
    els.loginAuth.hidden = true;
    els.pairingClaim.hidden = false;
    history.replaceState(null, '', location.pathname); // il codice e' monouso, non resta nell'URL

    let cfg = {};
    try {
      cfg = await (await fetch('/auth-config')).json();
    } catch (_) {
      /* gestito sotto: cfg resta vuoto */
    }
    if (!cfg.supabase_url || !cfg.supabase_anon_key) {
      showPairingClaimError('Accoppiamento non disponibile: Supabase non configurato su questo server.');
      return true;
    }

    const kind = detectKind() === 'pc' ? 'mobile' : detectKind(); // un companion non e' mai 'pc'
    const res = await fetch('/pairing/claim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, kind }),
    }).catch(() => null);
    if (!res || !res.ok) {
      const detail = res ? (await res.json().catch(() => ({}))).detail : null;
      if (detail && detail.error === 'device_limit') {
        showPairingClaimError(`Hai già un dispositivo "${KIND_LABELS_DEVICE[detail.kind] || detail.kind}" collegato: rimuovilo dal pannello Dispositivi sul PC, poi genera un nuovo QR.`);
      } else {
        showPairingClaimError('Codice di accoppiamento non valido o scaduto: genera un nuovo QR dal PC.');
      }
      return true;
    }
    const secret = (await res.json()).pairing_secret;

    // Import/creazione client e scambio del segreto per una sessione: qualunque
    // eccezione qui (CDN irraggiungibile, rete a singhiozzo) non deve lasciare
    // l'utente bloccato su "Accoppiamento in corso..." senza feedback ne' via
    // d'uscita -- da qui in poi tutto e' avvolto in un try/catch esplicito.
    try {
      const { createClient } = await import(SUPABASE_JS);
      const supabase = createClient(cfg.supabase_url, cfg.supabase_anon_key);
      const { data, error } = await supabase.auth.verifyOtp({ token_hash: secret, type: 'email' });
      if (error || !data.session) {
        showPairingClaimError('Non è stato possibile completare l\'accoppiamento: il codice potrebbe essere già stato usato. Genera un nuovo QR dal PC.');
        return true;
      }
      els.pairingClaimStatus.textContent = 'Registrazione dispositivo…';
      await enterWithToken(data.session.access_token, kind);
    } catch (err) {
      console.error('pairing: accoppiamento fallito', err);
      showPairingClaimError('Errore di rete durante l\'accoppiamento: riprova aprendo di nuovo il link dal QR.');
    }
    return true;
  }

  async function initAuth() {
    if (await handlePairingClaimIfPresent()) return;

    let cfg = {};
    try {
      cfg = await (await fetch('/auth-config')).json();
    } catch (_) {
      /* rete assente: si cade sul login di sviluppo sotto */
    }

    // Supabase non configurato: login di sviluppo (l'id fa da token, il
    // test-double di Fondamenta lo tratta come identità -- vedi ADR 017).
    if (!cfg.supabase_url || !cfg.supabase_anon_key) {
      els.loginDevForm.hidden = false;
      els.loginDevForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const id = els.loginDevId.value.trim();
        if (id) enterWithToken(id);
      });
      return;
    }

    const { createClient } = await import(SUPABASE_JS);
    const supabase = createClient(cfg.supabase_url, cfg.supabase_anon_key);

    // Ritorno da un redirect OAuth: supabase-js ha già la sessione dall'URL.
    const { data } = await supabase.auth.getSession();
    if (data.session) {
      await enterWithToken(data.session.access_token);
      return;
    }

    els.loginProviders.hidden = false;
    els.loginEmailForm.hidden = false;
    els.loginOr.hidden = false; // il separatore "oppure" ha senso solo con entrambe le vie

    const oauth = (provider) => () =>
      supabase.auth.signInWithOAuth({ provider, options: { redirectTo: location.origin } });
    els.loginGoogle.addEventListener('click', oauth('google'));
    els.loginMicrosoft.addEventListener('click', oauth('azure'));

    els.loginEmailForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      els.loginError.hidden = true;
      const { data: signIn, error } = await supabase.auth.signInWithPassword({
        email: els.loginEmail.value.trim(),
        password: els.loginPassword.value,
      });
      if (error || !signIn.session) {
        showLoginError('Email o password non corretti.');
        return;
      }
      await enterWithToken(signIn.session.access_token);
    });
  }

  initAuth();

  // ---------- WebSocket ----------

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/session?token=${sessionToken}`);
    ws.binaryType = 'arraybuffer';
    ws.addEventListener('message', onMessage);
    ws.addEventListener('close', () => {
      // turno chiuso forzato: niente piu' final_result in arrivo, le code non
      // hanno piu' senso; congela il fatto "audio pianificato" sull'adesso.
      awaitingFinal = false;
      resetTurnState();
      if (audioCtx) nextStartTime = audioCtx.currentTime;
      // la sessione lato server non c'e' piu': il regime locale ricade su
      // dormiente, coerente col default di una UISession nuova.
      listenRegime = 'dormiente';
      burstOpen = false;
      continuousOpen = false;
    });
  }

  function onMessage(event) {
    if (event.data instanceof ArrayBuffer) {
      // L'ultimo tts_alignment ricevuto si riferisce a QUESTO frame (il server lo
      // manda subito prima del suo audio, ADR 012); si consuma qui e basta.
      queueAudio(event.data, pendingMeta);
      pendingMeta = null;
      return;
    }
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case 'transcript':
        // Barra di trascrizione per la voce dell'UTENTE (STT in corso) --
        // caso diverso dalla voce dell'assistente, che si rivela invece in
        // sync con l'audio TTS (vedi 'tts_alignment' sotto). Il testo finale
        // utile (concatenazione degli is_final) e' tenuto solo per mostrarlo
        // in cronologia a turn_started -- la decisione di inoltrarlo o no
        // all'Orchestratore e' del server (attivazione col nome, utterance_end),
        // il client non la controlla piu' (docs/modules/08-interfaccia-utente.md
        // "Ascolto continuo e attivazione col nome").
        showTranscript(msg.text, msg.is_final);
        if (msg.is_final) localTranscriptBuffer += msg.text;
        break;
      case 'listen_state':
        setListenRegime(msg.value);
        els.micButton.classList.toggle('listening', msg.value === 'conversazione');
        break;
      case 'turn_started':
        // Unico segnale affidabile di "un turno e' appena partito", sia per
        // un testo digitato (il client lo sa gia', l'ha appena mandato lui)
        // sia per una frase che il server inoltra da solo (attivazione col
        // nome, frase finita in conversazione) -- e' qui che si apre lo stato
        // "thinking" dell'Essere Vivente (turnoAperto) e si mostra in
        // cronologia il testo detto a voce, se non era gia' un testo digitato.
        if (localTranscriptBuffer.trim()) {
          const spoken = localTranscriptBuffer.trim();
          addHistory('utente', spoken);
          showTranscript(spoken, true);
        }
        localTranscriptBuffer = '';
        dataPresentedThisTurn = false;
        resetTurnState();
        awaitingFinal = true;
        break;
      case 'step_started':
        logAction(msg.tool_name, 'in corso', '⏳');
        break;
      case 'step_completed':
        logAction(msg.tool_name, msg.status, msg.status === 'success' ? '✓' : '✗');
        break;
      case 'text_delta':
        // Non alimenta piu' la barra: il testo autorevole per la rivelazione
        // arriva gia' abbinato al suo pezzo audio nel messaggio tts_alignment
        // (ADR 023) -- text_delta serve solo a mostrare il log/altre viste che
        // ne avessero bisogno in futuro, oggi nessuna.
        break;
      case 'tts_alignment':
        pendingMeta = msg;
        break;
      case 'data_presented':
        // Arriva PRIMA di final_result: le schede si aprono subito, senza
        // aspettare il resto della risposta discorsiva (che continua ad
        // arrivare via text_delta, ignorato -- vedi sopra).
        dataPresentedThisTurn = true;
        (msg.data || []).forEach(openCard);
        break;
      case 'needs_confirmation':
        // il turno si ferma qui in attesa del si'/no: per gli stati e' chiuso
        awaitingFinal = false;
        showConfirm(msg.message);
        break;
      case 'final_result':
        // La barra di trascrizione non si tocca qui: arriva sempre dopo
        // tutto l'audio del turno (il server aspetta la sintesi prima di
        // mandare final_result), quindi la rivelazione sincronizzata ha gia'
        // mostrato tutto quello che andava detto. Il testo completo va
        // comunque in cronologia, letto o no.
        awaitingFinal = false; // il turno resta "aperto" solo finche' l'audio pianificato non finisce
        addHistory('assistente', msg.text || msg.summary || '');
        // Le schede di msg.data sono le stesse gia' aperte da data_presented
        // (stesso turno): non riaprirle una seconda volta.
        if (!dataPresentedThisTurn) (msg.data || []).forEach(openCard);
        refreshUsage();
        break;
      case 'error':
        awaitingFinal = false; // turno chiuso forzato
        logAction('errore', msg.message, '✗');
        break;
    }
  }

  function sendJson(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  // ---------- testo ----------

  els.textForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = els.textInput.value.trim();
    if (!text) return;
    addHistory('utente', text);
    showTranscript(text, true);
    // dataPresentedThisTurn/resetTurnState/awaitingFinal: centralizzati nel
    // gestore di turn_started (arriva per ogni turno, digitato o a voce).
    sendJson({ type: 'text', text });
    els.textInput.value = '';
  });

  // ---------- microfono ----------

  // Mic sempre acceso in Normale/Silenziosa (docs/modules/08-interfaccia-utente.md
  // "Ascolto continuo e attivazione col nome"): un solo pipeline PCM continuo,
  // gia' catturato prima ancora che l'utente clicchi il pulsante. Il pulsante
  // non accende/spegne piu' la registrazione -- da dormiente manda "wake"
  // (apre la conversazione senza inoltrare nulla), gia' in conversazione
  // manda "stop" (secondo modo per fermare l'ascolto, insieme al comando
  // vocale "‹nome›, stop").

  function int16From(float32) {
    const out = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  function mergeInt16(chunks, totalSamples) {
    const out = new Int16Array(totalSamples);
    let offset = 0;
    chunks.forEach((c) => { out.set(c, offset); offset += c.length; });
    return out;
  }

  function queueForSend(pcm16) {
    sendBufferChunks.push(pcm16);
    sendBufferSamples += pcm16.length;
    if (sendBufferSamples >= SEND_CHUNK_SAMPLES) flushSendBuffer();
  }

  function flushSendBuffer() {
    if (!sendBufferSamples) return;
    const merged = mergeInt16(sendBufferChunks, sendBufferSamples);
    sendBufferChunks = [];
    sendBufferSamples = 0;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(merged.buffer);
  }

  function pushToPreRoll(pcm16) {
    preRollChunks.push(pcm16);
    preRollSamples += pcm16.length;
    while (preRollSamples > PRE_ROLL_SAMPLES && preRollChunks.length > 1) {
      preRollSamples -= preRollChunks.shift().length;
    }
  }

  function drainPreRoll() {
    const merged = mergeInt16(preRollChunks, preRollSamples);
    preRollChunks = [];
    preRollSamples = 0;
    return merged;
  }

  // ---------- regime dormiente: raffiche a cancello VAD ----------

  function openBurst() {
    burstOpen = true;
    localTranscriptBuffer = ''; // niente leftover di una raffica scartata prima
    sendJson({ type: 'audio_start', mime_type: 'audio/pcm' });
    const preRoll = drainPreRoll(); // include gia' il blocco corrente (pushToPreRoll gia' fatto)
    if (preRoll.length && ws && ws.readyState === WebSocket.OPEN) ws.send(preRoll.buffer);
  }

  function closeBurst() {
    flushSendBuffer();
    burstOpen = false;
    sendJson({ type: 'audio_end' });
  }

  // ---------- regime conversazione: sessione unica continua ----------

  function ensureContinuousOpen() {
    if (continuousOpen) return;
    continuousOpen = true;
    sendJson({ type: 'audio_start', mime_type: 'audio/pcm' });
  }

  function closeContinuous() {
    if (!continuousOpen) return;
    flushSendBuffer();
    continuousOpen = false;
    sendJson({ type: 'audio_end' });
  }

  function setListenRegime(value) {
    if (value === listenRegime) return;
    listenRegime = value;
    if (value === 'conversazione') {
      burstOpen = false; // il server ha gia' chiuso la raffica di attivazione
      ensureContinuousOpen();
    } else {
      closeContinuous();
    }
  }

  // ---------- blocco PCM in arrivo dal worklet (~8ms l'uno) ----------

  function onPcmBlock(float32) {
    let sum = 0;
    for (let i = 0; i < float32.length; i++) sum += float32[i] * float32[i];
    const rms = Math.sqrt(sum / float32.length);
    const now = performance.now();
    if (rms >= VOICE_LEVEL_THRESHOLD) { lastVoiceAt = now; userSpeaking = true; }
    else if (now - lastVoiceAt > VOICE_SILENCE_HOLD_MS) userSpeaking = false;
    currentMicLevel = Math.min(1, rms * 6);

    const pcm16 = int16From(float32);
    pushToPreRoll(pcm16);

    if (listenRegime === 'conversazione') {
      ensureContinuousOpen();
      queueForSend(pcm16); // silenzio compreso: serve al fornitore per l'utterance_end
      return;
    }

    // dormiente: cancello VAD -- si spedisce solo a cavallo di voce vera
    if (rms >= VOICE_LEVEL_THRESHOLD) {
      lastVoiceAtBurst = now;
      if (!burstOpen) {
        openBurst(); // include gia' il blocco corrente via il pre-roll appena aggiornato
        return;
      }
      queueForSend(pcm16);
    } else if (burstOpen) {
      if (now - lastVoiceAtBurst > BURST_TAIL_MS) {
        closeBurst();
      } else {
        queueForSend(pcm16); // coda: il fornitore deve vedere il silenzio per chiudere la frase
      }
    }
    // altrimenti: dormiente, silenzio, nessuna raffica aperta -- solo pre-roll, niente invio
  }

  async function startMic() {
    if (micActive) return;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      pcmCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: PCM_SAMPLE_RATE });
      await pcmCtx.audioWorklet.addModule('/static/pcm-worklet.js');
      const source = pcmCtx.createMediaStreamSource(micStream);
      pcmWorkletNode = new AudioWorkletNode(pcmCtx, 'pcm-capture');
      pcmWorkletNode.port.onmessage = (e) => onPcmBlock(e.data);
      source.connect(pcmWorkletNode);
      // non si collega a pcmCtx.destination: e' solo cattura, mai riprodotta
      // (niente eco del proprio microfono sulle casse).
      micActive = true;
    } catch (err) {
      // Permesso non ancora concesso o mic assente: resta spento, il
      // pulsante mic riprova al prossimo click (gesto utente esplicito).
      console.error('microfono non disponibile:', err);
    }
  }

  function stopMic() {
    if (pcmWorkletNode) { pcmWorkletNode.port.onmessage = null; pcmWorkletNode.disconnect(); pcmWorkletNode = null; }
    if (pcmCtx) { pcmCtx.close(); pcmCtx = null; }
    if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
    micActive = false;
    burstOpen = false;
    continuousOpen = false;
    sendBufferChunks = []; sendBufferSamples = 0;
    preRollChunks = []; preRollSamples = 0;
    userSpeaking = false;
    sendEssereLevel(0);
  }

  els.micButton.addEventListener('click', async () => {
    if (mode === 'spenta') return;
    if (!micActive) { await startMic(); return; }
    sendJson({ type: listenRegime === 'dormiente' ? 'wake' : 'stop' });
  });

  // ---------- barra di trascrizione ----------

  let transcriptIdleTimer = null;
  function showTranscript(text, isFinal) {
    els.transcriptBar.textContent = text;
    els.transcriptBar.classList.toggle('final', isFinal);
    // una riga sola: tieni visibile la coda (il testo vecchio scorre indietro)
    els.transcriptBar.scrollLeft = els.transcriptBar.scrollWidth;
    // auto-fade: acceso mentre c'e' testo, si smorza dopo qualche secondo di quiete
    els.transcriptBar.classList.remove('idle');
    clearTimeout(transcriptIdleTimer);
    transcriptIdleTimer = setTimeout(() => els.transcriptBar.classList.add('idle'), 5000);
  }

  // ---------- log azioni ----------

  function logAction(toolName, status, icon) {
    const row = document.createElement('div');
    row.className = 'log-row';
    row.textContent = `${icon} ${toolName}: ${status}`;
    // il log cresce verso l'alto e sfuma sotto l'Essere Vivente (mask CSS): la riga
    // nuova va in fondo, le vecchie salgono. Teniamo solo le ultime, il resto e' gia'
    // dissolto dalla mask.
    els.actionsLog.appendChild(row);
    while (els.actionsLog.children.length > 30) els.actionsLog.removeChild(els.actionsLog.firstChild);
  }

  // ---------- conferme ----------

  function showConfirm(message) {
    els.confirmMessage.textContent = message;
    els.confirmBox.hidden = false;
  }

  function answerConfirm(value) {
    els.confirmBox.hidden = true;
    awaitingFinal = true; // confirm_and_retry produce un final_result: turno riaperto
    sendJson({ type: 'confirm', value });
  }

  els.confirmYes.addEventListener('click', () => answerConfirm(true));
  els.confirmNo.addEventListener('click', () => answerConfirm(false));

  // ---------- cronologia (richiudibile, chiusa di default) ----------

  els.historyTab.addEventListener('click', () => {
    els.historyPanel.classList.toggle('open');
  });

  function addHistory(who, text) {
    if (!text) return;
    const row = document.createElement('div');
    row.className = `history-row history-${who}`;
    row.textContent = text;
    els.historyList.appendChild(row);
  }

  // ---------- schede (finestre grafiche flottanti) ----------
  //
  // Ogni TypedFact e' una finestra che si posa da sola nello spazio libero intorno
  // all'Essere Vivente; quando lo spazio e' pieno, le nuove compaiono in posizione
  // casuale (mai su essere/log). Trascinabili dal titolo, click = in primo piano.
  // La dimensione massima e' la fascia laterale libera (variabili CSS --cmw/--cmh).

  const MAX_OPEN_CARDS = 8; // config.MAX_OPEN_CARDS (client); oltre, la piu' vecchia si chiude
  const CARD_TOPSAFE = 84;  // sotto la barra voce
  const CARD_BOTSAFE = 110; // sopra i controlli/modalita'
  const CARD_PAD = 12;
  let cardZTop = 10;

  const KIND_LABELS = {
    list: 'Lista', table: 'Tabella', event: 'Evento', location: 'Luogo',
    chart: 'Grafico', card: 'Scheda', form: 'Modulo',
  };

  function escHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  // Traduce il payload (libero) nel corpo del widget in base al kind; kind/campi
  // sconosciuti -> scheda generica leggibile (nessun errore).
  function cardBodyHtml(fact) {
    const p = fact.payload || {};
    const title = p.title ? `<div class="card-title">${escHtml(p.title)}</div>` : '';
    switch (fact.kind) {
      case 'list': {
        const items = (p.items || []).map((i) => `<li>${escHtml(typeof i === 'object' ? JSON.stringify(i) : i)}</li>`).join('');
        return title + `<ul class="card-list">${items}</ul>`;
      }
      case 'table': {
        const th = (p.columns || []).map((c) => `<th>${escHtml(c)}</th>`).join('');
        const tr = (p.rows || []).map((r) => `<tr>${(r || []).map((c) => `<td>${escHtml(c)}</td>`).join('')}</tr>`).join('');
        return title + `<table class="card-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
      }
      case 'event': {
        const info = `<b>${escHtml(p.title || p.name || 'Evento')}</b>${escHtml([p.time, p.place].filter(Boolean).join(' · '))}`;
        return `<div class="card-event"><div class="date"><span class="d">${escHtml(p.day || p.date || '')}</span><span class="m">${escHtml(p.month || '')}</span></div><div class="info">${info}</div></div>`;
      }
      case 'location': {
        return `<div class="card-loc"><div class="pin">📍</div><div class="txt"><b>${escHtml(p.label || p.title || 'Luogo')}</b>${escHtml(p.address || '')}</div></div>`;
      }
      case 'chart': {
        const vals = (p.values || []).map(Number);
        const max = Math.max(1, ...vals);
        const bars = vals.map((v) => `<div class="bar" style="height:${Math.max(4, (v / max) * 100)}%"></div>`).join('');
        return title + `<div class="card-chart">${bars}</div>`;
      }
      case 'card': {
        const fields = p.fields
          ? Object.entries(p.fields).map(([k, v]) => `<li><span style="color:var(--muted)">${escHtml(k)}</span>&nbsp;${escHtml(v)}</li>`).join('')
          : '';
        const text = p.text ? `<p class="card-note">${escHtml(p.text)}</p>` : '';
        return title + (fields ? `<ul class="card-list">${fields}</ul>` : '') + text;
      }
      default:
        return title + `<p class="card-note">${escHtml(JSON.stringify(p, null, 2))}</p>`;
    }
  }

  function rectOverlap(a, b) {
    return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
  }
  function reservedZones() {
    return [
      { x: innerWidth * 0.37, y: innerHeight * 0.16, w: innerWidth * 0.26, h: innerHeight * 0.58 }, // essere
      { x: innerWidth * 0.28, y: innerHeight - CARD_BOTSAFE - 150, w: innerWidth * 0.44, h: 150 },  // zona log
    ];
  }
  // primo posto libero attorno all'essere (scansione); null se pieno
  function placeCard(w, h) {
    const reserved = reservedZones();
    const ex = [...els.cards.children].map((c) => ({ x: c.offsetLeft - CARD_PAD, y: c.offsetTop - CARD_PAD, w: c.offsetWidth + CARD_PAD * 2, h: c.offsetHeight + CARD_PAD * 2 }));
    for (let y = CARD_TOPSAFE; y + h <= innerHeight - CARD_BOTSAFE; y += 20) {
      for (let x = 8; x + w <= innerWidth - 8; x += 20) {
        const r = { x, y, w, h };
        if (reserved.some((z) => rectOverlap(r, z))) continue;
        if (ex.some((e) => rectOverlap(r, e))) continue;
        return [x, y];
      }
    }
    return null;
  }
  function clampCard(card, x, y) {
    x = Math.max(8, Math.min(innerWidth - card.offsetWidth - 8, x));
    y = Math.max(CARD_TOPSAFE, Math.min(innerHeight - CARD_BOTSAFE - card.offsetHeight, y));
    return [x, y];
  }
  function bringCardFront(card) { card.style.zIndex = ++cardZTop; }
  function dragCard(card) {
    const head = card.querySelector('.card-head');
    let dx, dy, on = false;
    head.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.card-close')) return;
      on = true; head.setPointerCapture(e.pointerId);
      const r = card.getBoundingClientRect(); dx = e.clientX - r.left; dy = e.clientY - r.top;
      bringCardFront(card);
    });
    head.addEventListener('pointermove', (e) => {
      if (!on) return;
      const [x, y] = clampCard(card, e.clientX - dx, e.clientY - dy);
      card.style.left = x + 'px'; card.style.top = y + 'px';
    });
    head.addEventListener('pointerup', () => { on = false; });
    card.addEventListener('pointerdown', () => bringCardFront(card));
  }
  // dimensione massima scheda = fascia laterale libera (ricalcolata su resize)
  function updateCardMax() {
    document.documentElement.style.setProperty('--cmw', Math.round(innerWidth * 0.37 - 20) + 'px');
    document.documentElement.style.setProperty('--cmh', Math.round(innerHeight - CARD_TOPSAFE - CARD_BOTSAFE - 8) + 'px');
  }
  updateCardMax();
  window.addEventListener('resize', updateCardMax);

  function openCard(fact) {
    const card = document.createElement('div');
    card.className = 'card';
    const kindLabel = KIND_LABELS[fact.kind] || fact.kind;
    card.innerHTML = `<div class="card-head"><span class="card-kind">${escHtml(kindLabel)}</span>`
      + `<button class="card-close" aria-label="Chiudi">×</button></div>`
      + `<div class="card-body">${cardBodyHtml(fact)}</div>`;
    els.cards.appendChild(card);
    const w = card.offsetWidth, h = card.offsetHeight;
    let pos = placeCard(w, h);
    if (!pos) { // spazio pieno -> posizione casuale (mai su essere/log)
      const reserved = reservedZones(); let x, y, t = 0;
      do {
        x = 8 + Math.random() * (innerWidth - 16 - w);
        y = CARD_TOPSAFE + Math.random() * (innerHeight - CARD_TOPSAFE - CARD_BOTSAFE - h);
        t++;
      } while (t < 40 && reserved.some((z) => rectOverlap({ x, y, w, h }, z)));
      pos = [x, y];
    }
    card.style.left = pos[0] + 'px'; card.style.top = pos[1] + 'px'; card.style.zIndex = ++cardZTop;
    card.querySelector('.card-close').addEventListener('click', () => card.remove());
    dragCard(card);
    while (els.cards.children.length > MAX_OPEN_CARDS) els.cards.removeChild(els.cards.firstChild);
  }

  // ---------- modalita' ----------

  els.modeButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const previousMode = mode;
      mode = btn.dataset.mode;
      els.modeButtons.forEach((b) => b.classList.toggle('active', b === btn));
      document.body.dataset.mode = mode;
      sendJson({ type: 'mode', value: mode });
      if (mode === 'spenta') stopMic(); // mic rilasciato per davvero, si riattiva solo dal click
      else if (previousMode === 'spenta') startMic();
    });
  });

  // ---------- audio gapless + rivelazione testo continua per turno (ADR 023) ----------
  // Un AudioContext per pagina, i pezzi si pianificano uno via l'altro sulla stessa
  // linea temporale (nextStartTime) senza il distacco di avvio di un elemento <audio>
  // per pezzo (~140ms misurati, la causa residua degli scatti dopo ADR 022). Il testo
  // arriva gia' abbinato al proprio pezzo audio dal server (tts_alignment.text,
  // autorevole -- il client non ricostruisce piu' nulla, vedi ADR 023 Contesto): una
  // coda di segmenti attraversata da un solo ciclo di rivelazione per l'intero turno.

  function ensureAudioContext() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      nextStartTime = audioCtx.currentTime;
    }
    return audioCtx;
  }
  ensureAudioContext(); // creato subito, parte 'suspended' finche' l'utente non clicca
  // "Attiva audio" (resume() nel click handler sotto) -- gia' pronto al primo pezzo audio.

  function estimateDuration(text) {
    return Math.max(text.length / TYPEWRITER_FALLBACK_CHARS_PER_SECOND, 0.3);
  }

  function queueAudio(arrayBuffer, meta) {
    chunkQueue.push({ arrayBuffer, meta: meta || { text: '' } });
    if (!processingChunks) processChunkQueue();
  }

  async function processChunkQueue() {
    processingChunks = true;
    const ctx = ensureAudioContext();
    while (chunkQueue.length) {
      const { arrayBuffer, meta } = chunkQueue.shift();
      let audioBuffer = null;
      try {
        audioBuffer = await ctx.decodeAudioData(arrayBuffer);
      } catch (err) {
        // Pezzo audio corrotto/non decodificabile: il testo si rivela comunque
        // sotto, solo quel pezzo resta muto.
      }
      const text = meta.text || '';
      const alignment = (meta.characters && meta.character_start_times_seconds)
        ? { characters: meta.characters, starts: meta.character_start_times_seconds }
        : null;

      if (ctx.state !== 'running' || revealingBlocked || blockedRevealQueue.length) {
        // Audio bloccato (nessun gesto utente ancora): il pezzo si pianifica comunque,
        // partira' da solo quando l'utente sblocca (l'orologio dell'AudioContext resta
        // congelato fino ad allora) -- ma il testo non aspetta quell'orologio, si
        // rivela subito, in ordine, a ritmo fisso (enqueueBlockedReveal). Si resta su
        // questo percorso finche' l'arretrato bloccato non e' del tutto smaltito, anche
        // se l'utente sblocca a meta' animazione: evita che le due rivelazioni scrivano
        // sulla barra nello stesso momento.
        if (audioBuffer) scheduleBuffer(ctx, audioBuffer);
        if (text) enqueueBlockedReveal(text);
        continue;
      }

      const start = audioBuffer ? scheduleBuffer(ctx, audioBuffer) : Math.max(nextStartTime, ctx.currentTime);
      const duration = audioBuffer ? audioBuffer.duration : estimateDuration(text);
      if (!audioBuffer) nextStartTime = start + duration;
      if (text) {
        textSegmentQueue.push({ text, alignment, start, end: start + duration });
        if (!revealLoopActive) {
          revealLoopActive = true;
          requestAnimationFrame(runRevealLoop);
        }
      }
    }
    processingChunks = false;
  }

  function ensureTtsAnalyser(ctx) {
    // I pezzi TTS passano da un analyser prima dell'uscita: e' il livello
    // reale della voce dell'assistente, mandato al componente in "speaking".
    if (!ttsAnalyser) {
      ttsAnalyser = ctx.createAnalyser();
      ttsAnalyser.fftSize = 1024;
      ttsLevelBuf = new Float32Array(ttsAnalyser.fftSize);
      ttsAnalyser.connect(ctx.destination);
    }
    return ttsAnalyser;
  }

  function scheduleBuffer(ctx, audioBuffer) {
    const when = Math.max(nextStartTime, ctx.currentTime);
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ensureTtsAnalyser(ctx));
    source.start(when);
    nextStartTime = when + audioBuffer.duration;
    return when;
  }

  function runRevealLoop() {
    const now = audioCtx.currentTime;
    while (textSegmentQueue.length && now >= textSegmentQueue[0].end) {
      turnRevealedText += textSegmentQueue.shift().text;
    }
    if (textSegmentQueue.length && now >= textSegmentQueue[0].start) {
      showTranscript(turnRevealedText + revealPartial(textSegmentQueue[0], now), false);
      pulseEssere();
    } else {
      showTranscript(turnRevealedText, false);
    }
    if (textSegmentQueue.length) {
      requestAnimationFrame(runRevealLoop);
    } else {
      revealLoopActive = false;
      // niente setEssereStato qui: un buco tra due pezzi non e' fine turno,
      // lo stato lo decide la regola unica sui fatti (updateEssereStato)
    }
  }

  function revealPartial(segment, now) {
    if (segment.alignment) {
      const { characters, starts } = segment.alignment;
      let revealed = 0;
      while (revealed < characters.length && segment.start + starts[revealed] <= now) revealed++;
      return characters.slice(0, revealed).join('');
    }
    const frac = Math.min(1, Math.max(0, (now - segment.start) / (segment.end - segment.start)));
    return segment.text.slice(0, Math.floor(segment.text.length * frac));
  }

  function enqueueBlockedReveal(text) {
    // Rivelazione a ritmo fisso per un pezzo il cui audio e' ancora bloccato --
    // in coda seriale, cosi' piu' pezzi arrivati mentre l'audio e' bloccato si
    // rivelano in ordine invece di accavallarsi sulla stessa barra.
    blockedRevealQueue.push(text);
    if (!revealingBlocked) runBlockedRevealQueue();
  }

  function runBlockedRevealQueue() {
    const text = blockedRevealQueue.shift();
    if (text === undefined) {
      revealingBlocked = false;
      return;
    }
    revealingBlocked = true;
    const base = turnRevealedText;
    const start = performance.now();
    function tick() {
      const elapsed = (performance.now() - start) / 1000;
      const revealed = Math.min(text.length, Math.floor(elapsed * TYPEWRITER_FALLBACK_CHARS_PER_SECOND));
      showTranscript(base + text.slice(0, revealed), false);
      if (revealed < text.length) { requestAnimationFrame(tick); return; }
      turnRevealedText = base + text;
      runBlockedRevealQueue();
    }
    requestAnimationFrame(tick);
  }

  els.audioUnlock.addEventListener('click', () => {
    els.audioUnlock.hidden = true;
    ensureAudioContext().resume();
  });

  // ---------- indicatore consumi ----------

  // Budget mensile in EUR: segnaposto finche' l'entitlement/piano del tenant non lo
  // espone in UsageReport (roadmap "quote"). La barra mostra spesa/budget del mese.
  const MONTHLY_BUDGET_EUR = 10;

  function renderUsage(spentUsd) {
    const spent = spentUsd || 0;
    els.usageMonth.textContent = new Date().toLocaleDateString('it-IT', { month: 'long' });
    els.usageSpent.textContent = '€' + spent.toFixed(2).replace('.', ',');
    els.usageBudget.textContent = '/ €' + MONTHLY_BUDGET_EUR.toFixed(2).replace('.', ',');
    const pct = Math.max(0, Math.min(100, (spent / MONTHLY_BUDGET_EUR) * 100));
    els.usageFill.style.width = pct + '%';
    els.usageFill.classList.toggle('warn', pct >= 85);
  }

  async function refreshUsage() {
    if (!sessionToken) return;
    const res = await fetch('/usage', { headers: { Authorization: `Bearer ${sessionToken}` } });
    if (!res.ok) return;
    const body = await res.json();
    renderUsage(body.cost_usd);
  }

  // ---------- PWA ----------

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }

  // ---------- sfondo condiviso: carta millimetrata nel buio ----------
  // Puntini agli incroci di una griglia (passo 30px), piu' luminosi verso il
  // centro, con variazione casuale ma stabile (stesso seme a ogni ridisegno,
  // cosi' il parallasse non fa sfarfallare). Statico (nessun movimento autonomo
  // che distrae), con un leggero parallasse al puntatore che fa "sentire" la
  // profondita'. Dietro login e app (l'Essere Vivente e' trasparente, quindi
  // la griglia si vede anche dietro di lui).
  (function initBackground() {
    const cv = document.getElementById('bg');
    if (!cv) return;
    const ctx = cv.getContext('2d');
    const reduce = window.matchMedia('(prefers-reduced-motion:reduce)').matches;
    let W, H, dpr = Math.min(window.devicePixelRatio || 1, 2);
    let ox = 0, oy = 0, tox = 0, toy = 0, raf = 0;

    function rng(seed) {
      let s = seed;
      return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
    }
    function resize() {
      cv.width = window.innerWidth * dpr;
      cv.height = window.innerHeight * dpr;
      cv.style.width = window.innerWidth + 'px';
      cv.style.height = window.innerHeight + 'px';
      W = window.innerWidth; H = window.innerHeight;
      render();
    }
    function render() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const CX = W / 2, CY = H / 2;
      const step = 30, shift = 10;
      const px = ox * shift, py = oy * shift;
      const r = rng(5);
      // un passo oltre i bordi, cosi' lo spostamento del parallasse non scopre margini vuoti
      for (let x = 0; x <= W + step; x += step) {
        for (let y = 0; y <= H + step; y += step) {
          const d = Math.hypot(x - CX, y - CY) / (Math.max(W, H) * 0.6);
          const s = 0.8 + (1 - Math.min(d, 1)) * 0.6;
          const a = 0.10 + (1 - Math.min(d, 1)) * 0.14 + r() * 0.03;
          ctx.beginPath(); ctx.arc(x + px, y + py, s, 0, 7);
          ctx.fillStyle = 'rgba(160,190,235,' + a.toFixed(3) + ')';
          ctx.fill();
        }
      }
    }
    function easeStep() {
      ox += (tox - ox) * 0.06; oy += (toy - oy) * 0.06;
      render();
      if (Math.abs(tox - ox) > 0.001 || Math.abs(toy - oy) > 0.001) raf = requestAnimationFrame(easeStep);
      else raf = 0;
    }
    window.addEventListener('pointermove', (e) => {
      if (reduce) return;
      tox = (e.clientX / window.innerWidth - 0.5) * 2;
      toy = (e.clientY / window.innerHeight - 0.5) * 2;
      if (!raf) raf = requestAnimationFrame(easeStep);
    }, { passive: true });
    window.addEventListener('resize', resize);
    resize();
  })();
})();
