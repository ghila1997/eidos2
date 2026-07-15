# Modulo: Orchestratore + Memoria

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Agente conversazionale singolo (Claude Agent SDK, modello `claude-sonnet-5`) che capisce
l'intento del founder e usa due connettori completi — Gmail e Google Calendar — per cercare,
rispondere, inoltrare, organizzare, inviare mail, e cercare/creare/modificare/cancellare eventi
per suo conto. Memoria: poche preferenze sempre caricate, fatti strutturati per entità (upsert,
scrittura sempre esplicita via `remember_fact`), ricerca semantica (pgvector) unificata su mail
importate + eventi calendario **conclusi** + fatti salvati (`search_memoria`). NON fa: subagent
paralleli (nessun bisogno di delega ancora), sync/import automatico (on-demand, l'automatico è
Tappa 10), estrazione strutturata da documenti generici (Tappa 5), UI oltre CLI (Tappa 7),
gestione account Gmail/Calendar (S/MIME, filtri, delegati, ACL calendari — amministrazione non
richiesta tramite chat), fornitori diversi da Google (Outlook: prossimo incremento, dopo
validazione di questo, vedi ROADMAP.md).

## Interfacce

- **Espone**: `POST /chat` (messaggio → risposta agente, gestisce la sessione conversazionale),
  `POST /azioni/{id}/conferma` (unico punto in cui un'azione distruttiva diventa reale),
  `GET /oauth/google/authorize` + `GET /oauth/google/callback` (collegamento Gmail),
  `GET /oauth/google_calendar/authorize` + `GET /oauth/google_calendar/callback` (collegamento
  Calendar, consenso separato e incrementale), `POST /import-mail` (ingest mail on-demand),
  `POST /import-calendar` (ingest eventi calendario **conclusi** on-demand). Tutti richiedono la
  sessione di Fondamenta (cookie), quindi utilizzabili da qualunque dispositivo loggato.
- **Consuma**: Fondamenta (`get_sessione_corrente`), Supabase Postgres+pgvector, Gmail API,
  Google Calendar API, Voyage AI (embedding), Anthropic API pura (classificazione Haiku), Claude
  Agent SDK (conversazione, richiede il CLI Node.js `@anthropic-ai/claude-code` come sottoprocesso
  — vedi `Dockerfile`).

## Come funziona

- `codice/orchestratore/router.py` — endpoint FastAPI, system prompt con preferenze + **data/ora
  corrente iniettata a ogni richiesta** (il modello non la indovina più), wiring Agent SDK
  (`query()` con `resume` per riprendere la sessione tra richieste HTTP; fallback a sessione nuova
  se quella salvata non esiste più nel container — vedi DECISIONS.md)
- `codice/orchestratore/tools.py` — tool custom:
  - Mail: `search_memoria` (lettura unificata, vedi sotto), `draft_email`, `send_email`,
    `reply_email`, `forward_email`, `send_draft`, `trash_email` (questi ultimi cinque creano
    un'azione pending), `mark_email`, `organize_email`, `list_labels`, `get_attachment`
  - Memoria: `search_memoria` (mail + eventi calendario conclusi + fatti, un solo tool per evitare
    che il modello ne usi solo alcuni e perda informazioni), `remember_fact` (scrittura sempre
    esplicita, mai automatica — vincolo nella description del tool)
  - Calendario: `search_events` (live, passato+futuro, tutti i calendari), `check_availability`,
    `respond_to_invite` (immediati), `create_event`/`update_event`/`delete_event` (gate
    condizionale: con partecipanti → azione pending, senza → immediato; `create_event` con `fine`
    omessa usa default 1 ora)
  - Ogni tool calendario cattura `CalendarError` esplicitamente e restituisce un messaggio di
    errore leggibile invece di lasciarla propagare (trappola trovata a STOP 2, vedi sotto)
- `codice/orchestratore/safety/` — Safety Supervisor: punto unico di autorizzazione per ogni
  tool call (nativo o custom), policy dichiarative in `policies.yaml`, audit log JSONL
- `codice/orchestratore/azioni.py` — azioni distruttive in attesa di conferma umana esplicita,
  dispatch per tipo (`_ESECUTORI`): mail (`send_email`/`reply_email`/`forward_email`/
  `send_draft`/`trash_email`) + calendario (`create_event`/`update_event`/`delete_event`)
- `codice/orchestratore/gmail_client.py` — client Gmail completo (httpx puro)
- `codice/orchestratore/calendar_client.py` — client Google Calendar completo (httpx puro):
  cerca (tutti i calendari), crea/modifica/cancella, rispondi a invito (tocca solo il proprio
  `responseStatus`), controlla disponibilità (`freeBusy`), sync incrementale (`syncToken`)
- `codice/orchestratore/oauth_core.py` — parte OAuth generica (state, scambio/refresh token,
  cifratura, storage credenziali) condivisa tra provider
- `codice/orchestratore/oauth.py` / `oauth_calendar.py` — wrapper per provider (scope, redirect
  path) sopra `oauth_core.py` — split fatto in Tappa 4 quando è arrivato il secondo provider OAuth
  (vedi DECISIONS.md, "Connettori multi-provider")
- `codice/orchestratore/classification.py` — classificazione mail (Anthropic API pura, Haiku)
  prima dell'ingest
- `codice/orchestratore/embeddings.py` — embedding (Voyage AI, `voyage-3`)
- `codice/orchestratore/import_mail.py` — pipeline ingest mail: fetch → dedup → classifica →
  chunk+embedding+salva
- `codice/orchestratore/import_calendar.py` — pipeline ingest eventi **conclusi** (`fine < adesso`)
  su tutti i calendari: sync incrementale (`syncToken`) → filtra conclusi → dedup →
  chunk+embedding+salva. Eventi futuri restano fuori, gestiti live da `search_events`
- `codice/memoria/db.py` — accesso PostgREST alle tabelle di Memoria, incluse `find_fatti_ilike`
  (match fuzzy su entità) e `elimina_chunk_documento` (re-embed dei fatti aggiornati)
- `codice/cli.py` — client CLI remoto sottile: elenco chiuso e deterministico di frasi di
  conferma accettate (sì/confermo/vai/ok/autorizzo, no/annulla/fermati/stop), non solo `y`/`n`
  esatto — resta un confronto in codice, non un'interpretazione del modello
- `.claude/skills/redazione-email/` — skill di prova reale (non vuota)

## Come si prova

1. Login: `curl -c cookies.txt -X POST https://eidos2-api-production.up.railway.app/login -d '{"email":"...","password":"..."}'`
2. Collega Gmail: apri l'URL restituito da `GET /oauth/google/authorize` (con cookie) in un browser
3. Collega Calendar: apri l'URL restituito da `GET /oauth/google_calendar/authorize` (con cookie) —
   consenso separato, incrementale (`include_granted_scopes`)
4. Importa: `POST /import-mail` e `POST /import-calendar` (con cookie)
5. CLI: `cd codice && python cli.py` — chatta, es. "che impegni ho questa settimana?", "crea un
   evento domani alle 15 con [email]" (chiede conferma), "ricorda che X mi ha detto Y", "cosa so
   su X?"

Test automatici: `codice/tests/test_tools.py`, `test_azioni.py`, `test_gmail_client.py`,
`test_calendar_client.py`, `test_import_mail.py`, `test_import_calendar.py`, `test_oauth.py`,
`test_oauth_calendar.py`, `test_classification.py`, `test_memoria_db.py`, `test_router.py`,
`test_cli.py`.

## Decisioni rilevanti

- DECISIONS.md — "Safety Supervisor: punto unico di autorizzazione per ogni tool call"
- DECISIONS.md — "Memoria: un solo database, tre modi di ricordare, niente modulo RAG separato"
- DECISIONS.md — "Deploy: Dockerfile esplicito invece di Nixpacks (richiesto dal Claude Agent SDK)"
- DECISIONS.md — "Connettori: criterio di completezza 'cosa fa un umano', non 'tutta l'API'"
- DECISIONS.md — "Verifica reale di reply_email: threading corretto lato destinatario"
- DECISIONS.md — "Tappa 4: Memoria — lettura unificata, scrittura esplicita, calendario vivo vs concluso"
- DECISIONS.md — "Connettori multi-provider: contratti agnostici dal fornitore da subito"
- DECISIONS.md — "Verifica reale di Calendar: scope calendar.events insufficiente per calendarList.list"
- CLAUDE.md — "Completezza dei connettori", "Azioni distruttive" (gate di conferma)

## Trappole note / attenzioni

- `send_email`/`reply_email`/`forward_email`/`send_draft`/`trash_email` e
  `create_event`/`update_event`/`delete_event` **con partecipanti** non eseguono mai subito:
  creano un'azione in `azioni_pending`, solo `/azioni/{id}/conferma` (chiamata dall'utente, mai
  dal modello) esegue l'azione vera — coperto da `test_azioni.py`/`test_tools.py`
- Scope Google Calendar: `calendar.events` da solo **non** copre `calendarList.list` (l'elenco
  calendari, usato per la ricerca multi-calendario) — serve anche `calendar.calendarlist.readonly`.
  Trovato a STOP 2 testando con dati reali (403 silenzioso, il modello rispondeva "nessun evento"
  invece di segnalare l'errore) — verificato contro la doc ufficiale Google, non a naso
- Un "evento suggerito da Gmail" (rilevato automaticamente da un'email di conferma, bordo
  tratteggiato in Calendar UI) **non** è un vero evento e non è raggiungibile dall'API standard
  finché l'utente non lo conferma esplicitamente nell'interfaccia Google — limite noto della
  piattaforma, non un bug nostro
- Il system prompt inietta data/ora corrente a ogni richiesta: senza questo il modello indovinava
  "oggi" (sbagliando anche di un giorno), critico per "domani"/"questa settimana"/ecc.
- Il modello non deve chiedere una conferma testuale ridondante prima di chiamare un tool che
  crea già un'azione pending — la vera conferma è il gate strutturale dopo, chiederla due volte è
  friction inutile (istruzione esplicita nel system prompt)
- La sessione conversazionale (Agent SDK) vive su disco locale del container: se il container
  viene rideployato a metà conversazione, la sessione si perde e si riparte da una nuova (gestito,
  non un errore) — nessun dato di Memoria coinvolto
- Reply threading Gmail: verificato che funziona lato destinatario reale; la cartella "Inviata"
  del mittente può mostrare i messaggi separati per una stranezza nota di Gmail
- "Cancellare" una mail sposta nel cestino (`messages.trash`), non elimina in modo permanente —
  lo scope OAuth (`gmail.modify`) non consente l'eliminazione immediata, scelta deliberata
- L'import mail incrementale usa `users.history.list` (historyId); l'import calendario usa
  `events.list` con `syncToken` — entrambi con fallback a fetch pieno se il cursore scade lato
  provider (404/410), dedup a valle copre eventuali elementi ripescati
- `claude-agent-sdk` richiede il CLI Node.js come sottoprocesso runtime: build via `Dockerfile`
  (non Nixpacks), versione >=0.2.118
