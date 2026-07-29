# Modulo: Interfaccia Utente

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Interfaccia web dell'assistente: pagina statica servita **same-origin** da FastAPI, con
l'**essere vivente** 3D come baricentro e la conversazione in streaming. Costruita a fasi
verticali 7.1–7.6 (vedi ROADMAP.md); qui è documentata la fetta **realizzata**.

**Fatto (Tappa 7.1 — scheletro end-to-end)**: login (auth cookie esistente), un turno di
**solo testo** in streaming sul canale unico `/ws/session`, essere vivente che reagisce agli
stati (idle→thinking→speaking→idle).

**Cosa NON fa ancora** (fette successive, rimandate apertamente, non tagliate): scheda di
conferma visiva Sì/No e log azioni dal vivo e spia stato connessione (7.2); cronologia
espandibile + persistenza cross-sessione (7.3); schede grafiche flottanti `data_presented`
(7.4); voce/microfono nel browser (7.5); markdown/PWA/accessibilità curata (7.6). Login
Google/Microsoft e login-dev sono presenti nel design ma **nascosti** fino alla Tappa 8.

## Interfacce

- **Espone**: la pagina su `/`, gli statici su `/static`, il WebSocket `/ws/session` (montati
  via `interfaccia_utente.router.configura(app)` da `codice/app.py`). Protocollo `/ws/session`:
  - client→server: `{"tipo": "messaggio", "testo": "..."}`
  - server→client: `{"evento": "delta", "testo": ...}` · `{"evento": "tool_in_corso", "tool": ...}`
    · `{"evento": "fine", "risposta": ..., "azione_in_attesa": ...}` · `{"evento": "errore", "messaggio": ...}`
- **Consuma**: `fondamenta.auth.get_sessione_corrente` (stesso cookie di sessione, nessun CORS
  perché same-origin), `fondamenta` `/login` e `/me` (usati dal front-end per il login e per
  decidere login vs scena), `orchestratore.agente.motore_per` e `orchestratore.streaming`
  (traduzione turno→eventi, condivisa con la Voce), `orchestratore.azioni` (gate azione
  pendente). L'essere vivente è il componente autonomo di `export-essere-vivente/`, copiato in
  `static/` (iframe + Three.js locale, API `postMessage`).

## Come funziona

- `codice/interfaccia_utente/router.py` — `configura(app)` monta gli statici e include il
  router (rotta `/` che serve `static/index.html`, WS `/ws/session`). Il WS autentica col
  cookie (`get_sessione_corrente(websocket)`); non autenticato → chiusura `4401`. Converte
  `WebSocketDisconnect` in `sessione_web.ConnessioneChiusa` così il ciclo è testabile senza un
  vero WebSocket (stesso pattern del turno vocale).
- `codice/interfaccia_utente/sessione_web.py` — `gestisci_sessione(tenant_id, ricevi, invia)`:
  legge un messaggio del client per volta, per ognuno esegue un turno di testo intero
  (`streaming.traduci_turno(..., canale="testo")`) inoltrando gli eventi, poi resta pronto per
  il successivo. Il canale è **persistente** (più turni sulla stessa connessione). Un'azione
  già in attesa blocca il turno con un evento `errore` leggibile (la scheda Sì/No è 7.2).
  Nessun ponte/speculativo/transcript parziale: è semantica vocale, esclusa dal testo
  (DECISIONS.md 2026-07-28 pt.3).
- `codice/orchestratore/streaming.py` — **translator condiviso** turno SDK→eventi UI
  (`delta`/`tool_in_corso`/`fine`), usato sia da `turno_vocale.py` (che ci monta sopra ponte +
  speculativo) sia da `sessione_web.py` (nuda). Un solo posto per la forma degli eventi.
- `codice/interfaccia_utente/static/` — `index.html`/`style.css`/`app.js` (vanilla, nessun
  framework), identità visiva ripresa dall'export v1 come stella polare; `app.js` gestisce
  login, connessione WS, streaming nella barra e pilotaggio dell'essere via `postMessage`
  (palette `nebulaCosmo`, zoom `0.85`). `essere_vivente_component.html` + `vendor/three.min.js`
  copiati as-is dall'export.

## Come si prova

```
cd codice
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8123
```
Apri `http://127.0.0.1:8123/`, fai login con le credenziali reali, scrivi un messaggio: la
risposta si scrive in streaming nella barra in alto mentre l'essere passa
thinking→speaking→idle. Un secondo messaggio riusa la stessa sessione WS. Una richiesta che
porta a un invio mail chiude con "— c'è un'azione in attesa di conferma" (scheda Sì/No: 7.2).

Test automatici: `codice/tests/test_sessione_web.py` (ciclo di sessione con motore finto e
I/O iniettabile — un turno, due turni, errore pulito, errore che non chiude la sessione, gate
azione pendente, messaggio vuoto, chiusura). Il front-end statico è verificato a mano allo
STOP 2 (stessa convenzione dei wrapper I/O della Voce). La traduzione turno→eventi è coperta
anche dai test vocali esistenti (`test_turno_vocale.py`).

## Decisioni rilevanti

- DECISIONS.md 2026-07-28 — "Tappa 7 (Interfaccia Utente): design v1 come stella polare, canale
  unico, scomposizione 7.1–7.6" (stack statico same-origin, `/ws/session` distinto dal WS
  vocale, essere `nebulaCosmo`/0.85, barra↔cronologia unificata come futuro requisito)
- ROADMAP.md — Tappa 7 (fette 7.1–7.6)

## Trappole note / attenzioni

- **`/ws/session` è un canale distinto dal WS vocale `/chat/stream`**, non un suo riuso: il
  testo non trascina ponte/speculativo/transcript parziali (pensati per la voce). La sola cosa
  condivisa è `orchestratore/streaming.py` (la forma degli eventi) — se cambia lì, cambia per
  entrambi i canali, per questo ha i suoi test.
- **La pagina `/` non è protetta**: si carica sempre, poi il JS chiama `/me` (il cookie è
  httponly, la decisione login-vs-scena la prende il server, non il client leggendo il cookie).
- **`configura(app)` va chiamata per ultima** in `app.py`: monta lo static su `/static` e la
  rotta `/`. Oggi non maschera altre rotte, ma l'ordine è esplicito per non farlo in futuro.
- **La config dell'essere va (ri)mandata quando l'iframe è caricato E la scena è visibile**:
  `#app` parte `hidden` (display:none) finché non c'è login — `app.js` configura l'essere sia
  sul `load` dell'iframe sia allo sblocco della scena, con un piccolo ritardo (il componente
  registra il listener `postMessage` subito dopo il proprio avvio).
- **Font da Google Fonts via `@import`**: richiede rete ma degrada con grazia al font di
  sistema (il componente essere non usa font propri, Three.js è locale).
