/* Mockup interfaccia Eidos — logica FINTA e scriptata. Nessun backend, nessun
   modello: serve solo a sentire il feel (essere vivente + streaming + log +
   conferma + schede + barra<->cronologia). Throwaway. */
'use strict';

const $ = (id) => document.getElementById(id);
const essere = $('essere');
const bar = $('transcript-bar');
const convo = $('convo');
const historyScroll = $('history-scroll');
const actionsLog = $('actions-log');
const cards = $('cards');
const confirmBox = $('confirm-box');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---- essere vivente: piloto gli stati via postMessage (API del componente) ---- */
function stato(s) { essere.contentWindow.postMessage({ type: 'state', value: s }, '*'); }
function pulse() { essere.contentWindow.postMessage({ type: 'pulse' }, '*'); }
function configEssere() {
  const w = essere.contentWindow;
  w.postMessage({ type: 'config', palette: 'nebulaCosmo' }, '*');
  w.postMessage({ type: 'lab', zoom: 0.85 }, '*'); // 15% più piccolo
}

/* ---- cronologia (persistente nel prodotto vero; qui finta, precaricata) ---- */
const history = [
  { who: 'user', text: 'Ciao, com’è la settimana?' },
  { who: 'assistant', text: 'Hai tre scadenze: il preventivo per Marco (ven 24), il rinnovo polizza Isagro (lun 27) e la fattura Nastro Tecno ancora aperta.' },
];
function renderHistory() {
  historyScroll.innerHTML = history.map((t) =>
    `<div class="turn ${t.who}"><span class="who">${t.who === 'user' ? 'Tu' : 'Eidos'}</span>${t.text}</div>`
  ).join('');
  historyScroll.scrollTop = historyScroll.scrollHeight;
}
renderHistory();

function setConvoOpen(open) {
  convo.classList.toggle('open', open);
  convo.classList.toggle('collapsed', !open);
  document.body.classList.toggle('convo-open', open);
  if (open) renderHistory();
}
$('convo-toggle').onclick = () => setConvoOpen(!convo.classList.contains('open'));
bar.onclick = () => setConvoOpen(true);

/* ---- barra: scrive il testo in streaming ---- */
function setBar(text, final) {
  bar.innerHTML = text || '<span class="ghost">Scrivi qui sotto per iniziare…</span>';
  bar.classList.toggle('final', !!final);
}
async function streamInBar(text) {
  let acc = '';
  for (const ch of text) { acc += ch; setBar(acc, false); await sleep(18); }
  setBar(text, true);
}

/* ---- log azioni ---- */
function logRow(text, done) {
  const row = document.createElement('div');
  row.className = 'log-row' + (done ? ' done' : '');
  row.innerHTML = `<span class="tick">${done ? '✓' : '›'}</span>${text}`;
  actionsLog.appendChild(row);
  return row;
}
function clearLog() { actionsLog.innerHTML = ''; }

/* ---- schede grafiche flottanti ---- */
function spawnCard(kind, title, bodyHTML, x, y) {
  const c = document.createElement('div');
  c.className = 'card';
  c.style.left = x; c.style.top = y;
  c.innerHTML =
    `<div class="card-head"><span class="card-kind">${kind}</span>` +
    `<button class="card-close" aria-label="Chiudi">×</button></div>` +
    `<div class="card-body">${bodyHTML}</div>`;
  c.querySelector('.card-close').onclick = () => c.remove();
  makeDraggable(c, c.querySelector('.card-head'));
  cards.appendChild(c);
  return c;
}
function makeDraggable(el, handle) {
  let sx, sy, ox, oy, drag = false;
  handle.addEventListener('pointerdown', (e) => {
    drag = true; sx = e.clientX; sy = e.clientY;
    ox = el.offsetLeft; oy = el.offsetTop; handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', (e) => {
    if (!drag) return;
    el.style.left = (ox + e.clientX - sx) + 'px';
    el.style.top = (oy + e.clientY - sy) + 'px';
  });
  handle.addEventListener('pointerup', () => { drag = false; });
}

/* ---- conferma (gate) ---- */
function chiediConferma(messaggioHTML) {
  return new Promise((resolve) => {
    $('confirm-message').innerHTML = messaggioHTML;
    confirmBox.hidden = false;
    $('confirm-yes').onclick = () => { confirmBox.hidden = true; resolve(true); };
    $('confirm-no').onclick = () => { confirmBox.hidden = true; resolve(false); };
  });
}

/* ---- scenario canned dopo un invio ---- */
let busy = false;
async function turno(userText) {
  if (busy) return; busy = true;
  history.push({ who: 'user', text: userText });
  clearLog();
  cards.innerHTML = '';
  setBar('Tu: ' + userText, true);
  await sleep(400);

  stato('thinking');
  setBar('…', false);
  const r1 = logRow('Cerco nelle mail di Marco…'); await sleep(900);
  r1.className = 'log-row done'; r1.innerHTML = '<span class="tick">✓</span>Trovate 3 mail da Marco';

  spawnCard('Mail trovate', '', `<ul class="card-list">
    <li><b>Preventivo rev.2</b> — 24 lug</li>
    <li>Re: disponibilità — 21 lug</li>
    <li>Documenti allegati — 18 lug</li></ul>`, '6vw', '30vh');
  await sleep(500);
  spawnCard('Evento collegato', '', `<div class="card-event">
    <div class="date"><span class="d">24</span><span class="m">lug</span></div>
    <div class="info"><b>Call preventivo</b>15:00 — Marco Rossi</div></div>`,
    'calc(100vw - 26vw)', '38vh');

  stato('speaking'); pulse();
  await streamInBar('Ho 3 mail da Marco. L’ultima è il preventivo rev.2 del 24 lug. Vuoi che gli confermi?');
  const resp = 'Ho 3 mail da Marco. L’ultima è il preventivo rev.2 del 24 lug. Vuoi che gli confermi?';
  await sleep(300);
  stato('idle');

  const ok = await chiediConferma(
    'Rispondo a <b>marco.rossi@studio.it</b> nel thread “Preventivo rev.2”:\n“Ciao Marco, confermo il preventivo. Procediamo pure.”');
  if (ok) {
    const r2 = logRow('Invio risposta…'); await sleep(700);
    r2.className = 'log-row done'; r2.innerHTML = '<span class="tick">✓</span>Risposta inviata a Marco';
    pulse(); setBar('Fatto ✓', true);
    history.push({ who: 'assistant', text: resp + ' — (risposta inviata a Marco)' });
  } else {
    setBar('Annullato.', true);
    history.push({ who: 'assistant', text: resp + ' — (annullato)' });
  }
  await sleep(600);
  if (!convo.classList.contains('open')) setBar('', true);
  busy = false;
}

$('text-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const inp = $('text-input');
  const t = inp.value.trim();
  if (!t) return;
  inp.value = '';
  turno(t);
});

/* ---- modalità (solo visivo) ---- */
document.querySelectorAll('#mode-switch button').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('#mode-switch button').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    document.body.dataset.mode = b.dataset.mode;
  };
});

/* ---- sfondo: griglia di puntini in prospettiva (ripresa da v1 initBackground) ---- */
(function bgGrid() {
  const cv = $('bg'), ctx = cv.getContext('2d');
  let w, h;
  function resize() { w = cv.width = innerWidth; h = cv.height = innerHeight; draw(); }
  function draw() {
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
  addEventListener('resize', resize); resize();
})();

/* stato iniziale + palette/zoom (piccolo ritardo: il componente registra il
   listener postMessage dopo il proprio avvio) */
essere.addEventListener('load', () => {
  setTimeout(() => { configEssere(); stato('idle'); }, 300);
});
