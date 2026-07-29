# Modulo: Interfaccia Utente

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Interfaccia web dell'assistente: pagina statica servita **same-origin** da FastAPI, con
l'**essere vivente** 3D come baricentro e la conversazione in streaming. Costruita a fasi
verticali 7.1–7.6 (vedi ROADMAP.md); qui è documentata la fetta **realizzata**.

**Fatto (Tappa 7.1 — scheletro end-to-end)**: login (auth cookie esistente), un turno di
**solo testo** in streaming sul canale unico `/ws/session`, essere vivente che reagisce agli
stati (idle→thinking→speaking→idle).

**Fatto (Tappa 7.2 — trasparenza)**: **gate di conferma visivo** (scheda formato mail con
descrizione fornita dal server — fonte unica per CLI e web; 409/azione pendente reso come scheda,
non come errore), **spia stato connessione** (online/riconnessione/offline con auto-riconnessione a
backoff). Le azioni pending hanno una **scadenza pigra di 1h**.

**Fatto (Tappa 7.3 — superficie conversazione unica + cronologia persistente)**: barra, log azioni
e cronologia sono **una sola superficie "ambient"** in basso, larga quanto l'input.
- **Dialogo (default)**: i **passi** del turno come processo dal vivo (stile Claude Code, il pallino
  pulsa finché non finisce → ✓/✗) + il testo, **traslucidi**; un nuovo turno **si accoda** (flusso
  continuo, non un reset), le righe vecchie scorrono su e sfumano (si tengono ~le ultime 4); a riposo
  restano ma più discrete (qualcosa si vede sempre, l'essere resta baricentro — *si dialoga, non si
  legge*). Il messaggio dell'utente compare come eco discreta che apre il turno.
- **Lettura (espansa, col chevron)**: cronologia a contrasto pieno, azioni **inline** (niente
  "espandi"), l'essere **arretra dolce** (non sparisce). Aprendo a metà esecuzione il turno in corso
  si vede dal vivo in coda. Scrivere non richiude la cronologia.
- **Persistenza per-messaggio** per tenant (utente/assistente/esito, coi passi del turno): sopravvive
  a refresh **e** a riavvio del server. L'**esito** di un'azione ("Mail inviata a …") entra nella
  cronologia da qualunque canale, scritto nel punto unico di conferma.

**Cosa NON fa ancora** (fette successive, rimandate apertamente): schede grafiche flottanti
`data_presented` (7.4 — diventeranno messaggi con `tipo`+`payload` nello stesso log, riapribili come
allegati; punti aperti in `notes/interfaccia-prodotto-finito.md`); voce/microfono nel browser +
modalità Normale/Silenziosa/Spenta (7.5 — la modalità silenziosa riuserà l'inversione della modalità
lettura); markdown/PWA/accessibilità curata e **rifiniture grafiche** — inclusi i numeri fini di
traslucenza/tempi/arretramento essere (7.6). Login Google/Microsoft e login-dev sono nel design ma
**nascosti** fino alla Tappa 8.

## Interfacce

- **Espone**: la pagina su `/`, gli statici su `/static`, il WebSocket `/ws/session` (montati
  via `interfaccia_utente.router.configura(app)` da `codice/app.py`). Protocollo `/ws/session`:
  - client→server: `{"tipo": "messaggio", "testo": "..."}`
  - server→client, primo evento all'apertura: `{"evento": "storico", "messaggi": [{"ruolo":
    "utente"|"assistente"|"esito", "contenuto": ..., "passi": [{"etichetta","esito"}]|null}, ...]}`
  - poi, per ogni turno: `{"evento": "delta", "testo": ...}` ·
    `{"evento": "tool_in_corso", "id", "tool", "etichetta"}` ·
    `{"evento": "tool_finito", "id", "esito": "ok"|"errore"}` ·
    `{"evento": "azione_in_attesa", "azione": {..., "descrizione": {...}}}` (409 reso come scheda) ·
    `{"evento": "fine", "risposta": ..., "azione_in_attesa": {...}|null}` ·
    `{"evento": "errore", "messaggio": ...}`
  - conferma di un'azione: `POST /azioni/{id}/conferma {"conferma": bool}` (endpoint HTTP esistente,
    stesso del CLI) → `{"stato": "confermata_inviata"|"rifiutata"|"scaduta", "esito": "Mail inviata a …"?}`
    (`esito` presente solo su `confermata_inviata`).
- **Consuma**: `fondamenta.auth.get_sessione_corrente` (stesso cookie di sessione, nessun CORS),
  `fondamenta` `/login` e `/me`, `orchestratore.agente.motore_per` + `orchestratore.streaming`
  (traduzione turno→eventi, condivisa con la Voce), `orchestratore.azioni` (gate + TTL),
  `orchestratore.descrizioni_azioni` (descrizione scheda), `orchestratore.conversazione` (record
  della conversazione: `salva_turno`/`get_messaggi`; `salva_esito` lo chiama `azioni.conferma_azione`).
  L'essere vivente è il componente autonomo di `export-essere-vivente/`, copiato in `static/`.

## Come funziona

- `codice/orchestratore/conversazione.py` — **record della conversazione per-messaggio** (vive
  nell'Orchestratore, non nell'interfaccia: lo scrive anche il flusso di conferma). `salva_turno`
  scrive utente+assistente in una POST (coi `passi` sull'assistente, `created_at` a 1ms di distanza
  per l'ordine), `salva_esito` aggiunge un messaggio `esito`, `get_messaggi` legge gli ultimi N in
  ordine crescente (sempre scoping per tenant). REST server-side con service role key, RLS senza
  policy (tabella `conversazione_messaggi`, migration `20260729120000`).
- `codice/orchestratore/azioni.py` — `conferma_azione` è il **punto unico** da cui passa ogni
  conferma (web/CLI/voce): a esecuzione riuscita scrive l'esito in cronologia
  (`conversazione.salva_esito`, resiliente) e lo ritorna nel payload. Il testo è
  `descrizioni_azioni.esito_azione` (frase al passato; import locale per evitare il ciclo con `azioni`).
- `codice/interfaccia_utente/sessione_web.py` — `gestisci_sessione`: all'apertura manda `storico`
  (resiliente: se il DB è giù, cronologia vuota, la chat non muore); per ogni messaggio esegue un
  turno, raccoglie i `passi` (accoppiando `tool_in_corso`/`tool_finito` per id) e a turno riuscito
  chiama `conversazione.salva_turno` (fallimento loggato, non rompe il canale). Un'azione già in
  attesa manda la scheda, non avvia un turno.
- `codice/orchestratore/streaming.py` — translator condiviso turno SDK→eventi (invariato da 7.1/7.2;
  la forma degli eventi non cambia, è cambiata solo la resa client).
- `codice/interfaccia_utente/static/` — `index.html`/`style.css`/`app.js` (vanilla). `app.js`:
  - **superficie ambient** (`#ambient`): flusso continuo costruito incrementalmente (eco utente →
    passi come processo → testo), le righe vecchie sfumano (mask + max-height), a riposo `.settled`
    (più discreto, non sparisce), hover → pieno;
  - **cronologia** (`#history`): resa da `storico` (array di messaggi), azioni inline
    (`passiInlineHTML`), l'essere arretra (`body.convo-open`); il turno in corso si mostra dal vivo
    in coda (`aggiornaLiveHistory`, `.live-tail`) quando è aperta;
  - resto invariato: login, WS con auto-riconnessione + spia, scheda di conferma (che appende l'esito
    al flusso e alla cronologia), pilotaggio essere via `postMessage`.

## Come si prova

```
cd codice
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8123
```
Apri `http://127.0.0.1:8123/`, login reale. Scrivi un messaggio con un'azione (es. una ricerca in
memoria): i **passi** affiorano traslucidi come processo (pallino che pulsa → ✓), il testo si scrive,
il flusso resta (più discreto) a riposo. Un secondo messaggio **si accoda** (non cancella). Una
richiesta di invio mail apre la **scheda di conferma** nitida: Sì → parte e compare "✓ Mail inviata
a …" nel flusso e in cronologia. Il **chevron** (⌃) sopra l'input apre la **cronologia** a contrasto
pieno con le azioni inline; aprendola a metà turno vedi il processo dal vivo in coda; scrivere non la
chiude. **Refresh** → la cronologia c'è ancora (è su Supabase: sopravvive anche al riavvio del server).

La migration `20260729120000_conversazione_messaggi.sql` va applicata al progetto Supabase
(`supabase db push`, oppure SQL Editor) prima della prova.

Test automatici: `test_conversazione.py` (anti-leak, ordine, bound, passi sul messaggio giusto),
`test_sessione_web.py` (evento `storico`/`messaggi`, salvataggio solo su turno riuscito, passi
raccolti, degrado resiliente), `test_azioni.py` (esito scritto alla conferma, ritornato nel payload),
`test_descrizioni_azioni.py` (`esito_azione`), `test_streaming.py`/`test_router_chat.py`/`test_cli.py`
(invariati). Il front-end statico è verificato a mano dal founder sul server reale allo STOP 2.

## Decisioni rilevanti

- DECISIONS.md 2026-07-29 — "Tappa 7.3: superficie conversazione unica (ambient) + cronologia
  persistente per-messaggio" (log per-messaggio, record nell'Orchestratore, esito scritto in
  `conferma_azione`, superficie unica ambient vs bar+log separati, recede via righe non opacità)
- DECISIONS.md 2026-07-29 — "Tappa 7.2: trasparenza" · "Tappa 7.1: scheletro web end-to-end"
- DECISIONS.md 2026-07-28 — "Tappa 7 (Interfaccia Utente): design v1 come stella polare, canale
  unico, scomposizione 7.1–7.6"
- ROADMAP.md — Tappa 7 (fette 7.1–7.6) e "Esplicitamente rimandato" (arretrato ricerca inbox Gmail live)

## Trappole note / attenzioni

- **La cronologia mostrata è nel DB; il contesto dell'agente no.** Un refresh non perde il contesto
  (il motore è cache-ato per tenant, stesso processo); un **riavvio server** azzera il contesto
  dell'agente (decisione Orchestratore: niente resume di sessioni vecchie) ma la cronologia resta.
  Non è un bug: la cronologia è un record, non la memoria conversazionale del modello.
- **`conversazione.salva_esito` sta in `conferma_azione`, non nella UI**: è il punto unico per ogni
  canale. `descrizioni_azioni` importa `azioni` → in `conferma_azione` l'import di
  `conversazione`/`descrizioni_azioni` è **locale** per non creare un ciclo.
- **Ordine dei due messaggi di un turno**: `created_at` esplicito a 1ms di distanza (utente prima),
  perché il default `now()` di un insert batch li lascerebbe pari e l'ordine sarebbe indefinito.
- **Persistenza e lettura resilienti**: se il DB è giù o la tabella non è migrata, `get_messaggi`
  degrada a cronologia vuota e `salva_turno`/`salva_esito` loggano e proseguono — la chat non muore
  per un problema di cronologia (secondaria rispetto al dialogo).
- **La superficie ambient è aggiornata anche quando la cronologia è aperta** (è solo `display:none`):
  così collassando a metà turno il flusso è già lì. Il turno in corso appare in cronologia via
  `aggiornaLiveHistory` (una `.live-tail` che `renderStorico` sostituisce a turno chiuso).
- **Il `passo` "in corso"** ha `fatto:false` (solo dal vivo): reso col pallino che pulsa. I passi
  persistiti non hanno `fatto` → resi come già conclusi.
- Trappole di 7.1/7.2 ancora valide: `/ws/session` distinto dal WS vocale; pagina `/` non protetta
  (decisione via `/me`); `configura(app)` per ultima; config essere (ri)mandata a iframe caricato e
  scena visibile; cookie `Secure` e client di test via header `Cookie` esplicito; il CLI resta un
  client HTTP sottile (consuma `descrizione`/`esito` che il server allega, non importa i moduli).
