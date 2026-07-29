# Modulo: Interfaccia Utente

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Interfaccia web dell'assistente: pagina statica servita **same-origin** da FastAPI, con
l'**essere vivente** 3D come baricentro e la conversazione in streaming. Costruita a fasi
verticali 7.1–7.6 (vedi ROADMAP.md); qui è documentata la fetta **realizzata**.

**Fatto (Tappa 7.1 — scheletro end-to-end)**: login (auth cookie esistente), un turno di
**solo testo** in streaming sul canale unico `/ws/session`, essere vivente che reagisce agli
stati (idle→thinking→speaking→idle).

**Fatto (Tappa 7.2 — trasparenza)**: **log azioni dal vivo** (righe `tool_in_corso`→`tool_finito`,
etichette leggibili), **gate di conferma visivo** (scheda formato mail con descrizione fornita dal
server — fonte unica per CLI e web; 409/azione pendente reso come scheda, non come errore),
**spia stato connessione** (online/riconnessione/offline con auto-riconnessione a backoff). Le
azioni pending hanno una **scadenza pigra di 1h** (una scheda dimenticata non parte ore dopo e non
blocca più la chat).

**Cosa NON fa ancora** (fette successive, rimandate apertamente, non tagliate): cronologia
espandibile + persistenza cross-sessione (7.3); schede grafiche flottanti `data_presented`
(7.4); voce/microfono nel browser (7.5); markdown/PWA/accessibilità curata e **rifiniture
grafiche** (7.6). Login Google/Microsoft e login-dev sono presenti nel design ma **nascosti**
fino alla Tappa 8.

## Interfacce

- **Espone**: la pagina su `/`, gli statici su `/static`, il WebSocket `/ws/session` (montati
  via `interfaccia_utente.router.configura(app)` da `codice/app.py`). Protocollo `/ws/session`:
  - client→server: `{"tipo": "messaggio", "testo": "..."}`
  - server→client: `{"evento": "delta", "testo": ...}` ·
    `{"evento": "tool_in_corso", "id": ..., "tool": ..., "etichetta": ...}` ·
    `{"evento": "tool_finito", "id": ..., "esito": "ok"|"errore"}` ·
    `{"evento": "azione_in_attesa", "azione": {..., "descrizione": {...}}}` (409 reso come scheda) ·
    `{"evento": "fine", "risposta": ..., "azione_in_attesa": {..., "descrizione": {...}}|null}` ·
    `{"evento": "errore", "messaggio": ...}`
  - conferma di un'azione: `POST /azioni/{id}/conferma {"conferma": bool}` (endpoint HTTP esistente,
    stesso che usa il CLI) → `{"stato": "confermata_inviata"|"rifiutata"|"scaduta"}`.
- **Consuma**: `fondamenta.auth.get_sessione_corrente` (stesso cookie di sessione, nessun CORS
  perché same-origin), `fondamenta` `/login` e `/me` (usati dal front-end per il login e per
  decidere login vs scena), `orchestratore.agente.motore_per` e `orchestratore.streaming`
  (traduzione turno→eventi, condivisa con la Voce), `orchestratore.azioni` (gate azione pendente +
  TTL pigra `azione_bloccante`), `orchestratore.descrizioni_azioni` (descrizione leggibile, fonte
  unica CLI+web). L'essere vivente è il componente autonomo di `export-essere-vivente/`, copiato in
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
  già in attesa non avvia un nuovo turno: manda l'evento `azione_in_attesa` (la **scheda**, non un
  errore — 7.2), scartando da sola una pendente scaduta (`azioni.azione_bloccante`, TTL pigra).
  Nessun ponte/speculativo/transcript parziale: è semantica vocale, esclusa dal testo
  (DECISIONS.md 2026-07-28 pt.3).
- `codice/orchestratore/streaming.py` — **translator condiviso** turno SDK→eventi UI
  (`delta`/`tool_in_corso`/`tool_finito`/`fine`), usato sia da `turno_vocale.py` (che ci monta
  sopra ponte + speculativo) sia da `sessione_web.py` (nuda). `tool_finito` si ricava dal
  `ToolResultBlock` di una `UserMessage`; `fine` arricchisce l'azione con `descrivi_azione`.
- `codice/orchestratore/descrizioni_azioni.py` — **fonte unica** della descrizione leggibile di
  un'azione pending (`{icona, titolo, riepilogo, dettagli, corpo}`); il CLI e la UI la formattano,
  non la ricalcolano. Robusta a payload diversi (Gmail/Calendar/Drive/Memoria): campi mancanti
  spariscono, tipo sconosciuto ha un fallback.
- `codice/orchestratore/azioni.py` — **TTL pigra** (`TTL_AZIONE`, costante): `azione_scaduta`
  confronta `created_at` con adesso; un "Sì" su un'azione scaduta torna `scaduta` senza eseguire.
  Nessun job/migration (lo scheduler vero è Tappa 10).
- `codice/interfaccia_utente/static/` — `index.html`/`style.css`/`app.js` (vanilla, nessun
  framework), identità visiva ripresa dall'export v1 come stella polare; `app.js` gestisce login,
  connessione WS (con **auto-riconnessione a backoff** e spia stato), streaming nella barra, log
  azioni (righe per `id`), scheda di conferma (formato mail, `fetch` a `/azioni/{id}/conferma`) e
  pilotaggio dell'essere via `postMessage` (palette `nebulaCosmo`, zoom `0.85`).
  `essere_vivente_component.html` + `vendor/three.min.js` copiati as-is dall'export.

## Come si prova

```
cd codice
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8123
```
Apri `http://127.0.0.1:8123/`, fai login con le credenziali reali, scrivi un messaggio: la
risposta si scrive in streaming nella barra in alto mentre l'essere passa
thinking→speaking→idle. Un secondo messaggio riusa la stessa sessione WS. Una richiesta con un
tool mostra le righe di **log** (in corso → ✓). Una richiesta che porta a un invio mail apre la
**scheda di conferma** (formato mail, con descrizione dal server): Sì → parte davvero, No →
annulla; una scheda più vecchia di 1h scade (non invia). Staccando la rete la **spia** in alto a
destra passa a *Riconnessione…/Offline* e torna *Online* al ripristino.

Test automatici: `test_sessione_web.py` (ciclo di sessione; azione pendente → scheda, non errore),
`test_streaming.py` (`tool_finito` accoppiato per `id`, `fine` arricchito con descrizione, etichette),
`test_descrizioni_azioni.py` (fonte unica, robustezza sui payload), `test_azioni.py` (TTL: scaduta
non invia, `azione_bloccante`), `test_router_chat.py` (409 con descrizione), `test_cli.py` (il CLI
formatta la descrizione del server). Il front-end statico è verificato a mano + con un client
scriptato sul server reale allo STOP 2. La traduzione turno→eventi è coperta anche da
`test_turno_vocale.py` (anti-regressione voce).

## Decisioni rilevanti

- DECISIONS.md 2026-07-29 — "Tappa 7.2: trasparenza (log azioni, gate di conferma visivo, spia
  connessione)" (descrizione fonte unica sul server, `tool_finito`, 409-come-scheda, TTL 1h pigra,
  conferma via HTTP esistente, auto-riconnessione)
- DECISIONS.md 2026-07-29 — "Tappa 7.1: scheletro web end-to-end" (canale `/ws/session`, translator condiviso)
- DECISIONS.md 2026-07-28 — "Tappa 7 (Interfaccia Utente): design v1 come stella polare, canale
  unico, scomposizione 7.1–7.6"
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
- **Descrizione azione: il CLI NON importa il modulo del server.** Resta un client HTTP sottile
  (deployabile standalone): consuma la `descrizione` che il server allega, non `descrizioni_azioni`.
  La "fonte unica" è la logica sul server, non un import condiviso.
- **`tool_finito` viene dal `ToolResultBlock` di una `UserMessage`**, non da `content_block_stop`
  (che marca solo la fine della richiesta del modello, non l'esecuzione del tool). Accoppiato per
  `id` al `tool_in_corso` così il log chiude la riga.
- **TTL azioni = costante nel codice, scadenza pigra** (nessuna colonna `expires_at`, nessun job).
  Controllata al volo in `azione_scaduta`/`azione_bloccante`. Lo scheduler vero è Tappa 10.
- **Cookie `Secure` e test via client HTTP**: i cookie di login sono `Secure`; un browser li manda
  a `http://127.0.0.1` (eccezione localhost), ma `httpx` no — un client di test deve estrarre il
  token dalla risposta di `/login` e passarlo come header `Cookie` esplicito (come fa `cli.py`).
