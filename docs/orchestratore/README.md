# Modulo: Orchestratore + Memoria

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Agente conversazionale singolo (Claude Agent SDK, modello `claude-sonnet-5`) che capisce
l'intento del founder e usa tre connettori completi — Gmail, Google Calendar e Google Drive —
per cercare, rispondere, inoltrare, organizzare, inviare mail, cercare/creare/modificare/
cancellare eventi, e cercare/leggere/creare/organizzare/condividere file per suo conto. Memoria:
poche preferenze sempre caricate, fatti strutturati per entità (upsert, scrittura sempre
esplicita via `remember_fact` o via estrazione automatica da un documento importato, vedi
Tappa 5), ricerca semantica (pgvector) unificata su mail importate + eventi calendario
**conclusi** + fatti salvati + documenti importati (`search_memoria`). Estensione documenti
(Tappa 5): ingestione esplicita di PDF/DOCX/XLSX/immagini (allegato Gmail, file Drive, file
locale via Agente Locale) — dedup cross-origine per hash, archiviazione del file originale
(Supabase Storage), estrazione strutturata verso `memoria_fatti` quando riconosce una
controparte chiara. Ciclo di vita completo (Tappa 5.1): elencare i documenti importati
(`list_documents`), rivederli con link firmato temporaneo all'originale (`get_document`),
dimenticarli (`forget_document`, distruttivo → azione pending; rimuove ricerca, archivio e voce
nei fatti collegati). Le immagini fuori standard API (HEIC da iPhone, TIFF da scanner, foto
oltre i limiti) vengono normalizzate localmente prima della visione — l'originale archiviato
resta intatto. NON fa: subagent paralleli (nessun bisogno di delega ancora), sync/import
automatico (on-demand, l'automatico è Tappa 10), UI oltre CLI (Tappa 7), gestione account
Gmail/Calendar/Drive (S/MIME, filtri, delegati, ACL, quota, Shared Drives — amministrazione non
richiesta tramite chat), fornitori diversi da Google (Outlook/OneDrive: prossimo incremento,
dopo validazione della Suite Google, vedi ROADMAP.md), OCR di documenti oltre 20 pagine
scansionate (rifiutato esplicitamente, troppo costoso per questo caso d'uso).

## Interfacce

- **Espone**: `POST /chat` (messaggio → risposta agente, gestisce la sessione conversazionale),
  `POST /azioni/{id}/conferma` (unico punto in cui un'azione distruttiva diventa reale),
  `GET /oauth/google/authorize` + `GET /oauth/google/callback` (collegamento Gmail),
  `GET /oauth/google_calendar/authorize` + `GET /oauth/google_calendar/callback` (collegamento
  Calendar, consenso separato e incrementale), `GET /oauth/google_drive/authorize` +
  `GET /oauth/google_drive/callback` (collegamento Drive, scope pieno `drive`, consenso separato
  e incrementale), `POST /import-mail` (ingest mail on-demand), `POST /import-calendar` (ingest
  eventi calendario **conclusi** on-demand). Tutti richiedono la sessione di Fondamenta (cookie),
  quindi utilizzabili da qualunque dispositivo loggato.
- **Consuma**: Fondamenta (`get_sessione_corrente`), Supabase Postgres+pgvector+Storage, Gmail
  API, Google Calendar API, Google Drive API, Voyage AI (embedding), Anthropic API pura
  (classificazione mail Haiku, estrazione documenti Haiku/Sonnet — vedi Tappa 5), Claude
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
    un'azione pending), `mark_email`, `organize_email`, `list_labels`, `list_attachments`
    (elenca allegati con `attachment_id` — necessario prima di `get_attachment`/
    `import_document` su Gmail, vedi Tappa 5), `get_attachment` (estrae testo per PDF/DOCX/XLSX
    con strato digitale; per scansioni/immagini suggerisce `import_document` invece di fingere
    di averle lette)
  - Memoria: `search_memoria` (mail + eventi calendario conclusi + fatti + documenti importati,
    un solo tool per evitare che il modello ne usi solo alcuni e perda informazioni),
    `remember_fact` (scrittura sempre esplicita, mai automatica — vincolo nella description del
    tool), `import_document` (Tappa 5 — ingest esplicito di un documento Gmail/Drive in Memoria,
    vedi sotto; per Gmail il `source_id` è `message_id:filename`, MAI l'`attachment_id` che
    cambia a ogni fetch), `list_documents`/`get_document` (Tappa 5.1, immediati — elenco e
    dettagli con link firmato all'originale), `forget_document` (Tappa 5.1, distruttivo —
    crea un'azione pending come le altre cancellazioni)
  - Calendario: `search_events` (live, passato+futuro, tutti i calendari), `check_availability`,
    `respond_to_invite` (immediati), `create_event`/`update_event`/`delete_event` (gate
    condizionale: con partecipanti → azione pending, senza → immediato; `create_event` con `fine`
    omessa usa default 1 ora)
  - Ogni tool calendario cattura `CalendarError` esplicitamente e restituisce un messaggio di
    errore leggibile invece di lasciarla propagare (trappola trovata a STOP 2, vedi sotto)
  - Drive: `search_files`, `read_file` (estrae testo per PDF/DOCX/XLSX digitali e Google Docs/
    Sheets/Slides via export; per scansioni/immagini suggerisce `import_document`), `list_folder`,
    `create_folder`, `create_file`, `update_file_content`, `rename_file`, `move_file`,
    `copy_file`, `list_permissions`, `revoke_permission` (immediati), `share_file`/`trash_file`
    (creano un'azione pending)
- `codice/orchestratore/safety/` — Safety Supervisor: punto unico di autorizzazione per ogni
  tool call (nativo o custom), policy dichiarative in `policies.yaml`, audit log JSONL
- `codice/orchestratore/azioni.py` — azioni distruttive in attesa di conferma umana esplicita,
  dispatch per tipo (`_ESECUTORI`): mail (`send_email`/`reply_email`/`forward_email`/
  `send_draft`/`trash_email`) + calendario (`create_event`/`update_event`/`delete_event`) +
  Drive (`share_file`/`trash_file`) + memoria (`forget_document`, Tappa 5.1)
- `codice/orchestratore/gmail_client.py` — client Gmail completo (httpx puro)
- `codice/orchestratore/calendar_client.py` — client Google Calendar completo (httpx puro):
  cerca (tutti i calendari), crea/modifica/cancella, rispondi a invito (tocca solo il proprio
  `responseStatus`), controlla disponibilità (`freeBusy`), sync incrementale (`syncToken`)
- `codice/orchestratore/drive_client.py` — client Google Drive completo (httpx puro): cerca
  (full-text incluso), legge (export per Google Docs/Sheets/Slides, testo per file `text/*`,
  scarica i byte grezzi per il resto — usato anche da `import_document`), crea/carica,
  organizza in cartelle, copia, condivide, gestisce permessi, cestina
- `codice/orchestratore/oauth_core.py` — parte OAuth generica (state, scambio/refresh token,
  cifratura, storage credenziali) condivisa tra provider
- `codice/orchestratore/oauth.py` / `oauth_calendar.py` / `oauth_drive.py` — wrapper per provider
  (scope, redirect path) sopra `oauth_core.py` — split fatto in Tappa 4 quando è arrivato il
  secondo provider OAuth (vedi DECISIONS.md, "Connettori multi-provider")
- `codice/orchestratore/classification.py` — classificazione mail (Anthropic API pura, Haiku)
  prima dell'ingest
- `codice/orchestratore/embeddings.py` — embedding (Voyage AI, `voyage-3`)
- `codice/orchestratore/import_mail.py` — pipeline ingest mail: fetch → dedup → classifica →
  chunk+embedding+salva
- `codice/orchestratore/import_calendar.py` — pipeline ingest eventi **conclusi** (`fine < adesso`)
  su tutti i calendari: sync incrementale (`syncToken`) → filtra conclusi → dedup →
  chunk+embedding+salva. Eventi futuri restano fuori, gestiti live da `search_events`
- `codice/memoria/db.py` — accesso PostgREST alle tabelle di Memoria, incluse `find_fatti_ilike`
  (match fuzzy su entità), `elimina_chunk_documento` (re-embed dei fatti aggiornati) e
  `set_storage_path` (Tappa 5, valorizzato dopo l'upload)
- `codice/memoria/file_extraction.py` (Tappa 5) — estrazione testo locale gratuita: PDF con
  strato di testo digitale (`pypdf`), DOCX (`python-docx`), XLSX (`openpyxl`); pre-check a
  costo zero per il routing: `pdf_ha_testo_digitale`, `pdf_e_cifrato` (rifiuto esplicito con
  messaggio chiaro, Tappa 5.1), `indici_pagine_scansione` (pagine senza testo MA con immagini
  = scansioni dentro un PDF misto → percorso visivo, per non perderle in silenzio; una pagina
  bianca senza immagini non conta)
- `codice/memoria/document_extraction.py` (Tappa 5) — estrazione campi strutturati, structured
  output via tool forzato (stessa forma di `classification.py`): `estrai_da_testo` (Haiku,
  economico, per testo già pulito) ed `estrai_da_documento_visivo` (Sonnet 5, content block
  nativo `document`/`image` — un'unica chiamata che trascrive/OCR ed estrae insieme; in
  streaming con `max_tokens` 32k, errore esplicito se la trascrizione risulta troncata)
- `codice/memoria/image_normalization.py` (Tappa 5.1) — normalizza le immagini per la visione
  (Pillow + pillow-heif): HEIC/TIFF/BMP → JPEG, resize a lato lungo ≤2576px (tier alta
  risoluzione Sonnet 5), ricompressione se oltre i limiti API — solo per la chiamata, mai
  sull'originale archiviato
- `codice/memoria/storage.py` (Tappa 5) — Supabase Storage (bucket privato `documenti`):
  upload con upsert, `elimina_file` (400/404 tollerati), `crea_url_firmato` (download
  temporaneo dell'originale, Tappa 5.1)
- `codice/memoria/ingest_documento.py` (Tappa 5) — pipeline condivisa tra Orchestratore e Agente
  Locale: dedup per hash dei byte grezzi (solo documenti `stato='completo'`) → routing per
  formato/qualità (digitale+Haiku economico vs scansione/immagine+Sonnet; cap 100k caratteri
  sull'input dell'estrazione campi, la ricerca semantica indicizza sempre tutto) →
  chunk+embedding → upload Storage → upsert `memoria_fatti` solo se un'entità è riconosciuta
  con chiarezza (voce sostituita per `documento_id`, mai accumulata). Atomicità (Tappa 5.1):
  insert con `stato='in_corso'`, `completo` solo a fine pipeline — un ingest interrotto a metà
  non maschera mai il retry come "già presente"; errori API/trascrizione incapsulati in
  `ErroreIngestDocumento` (messaggio pulito, mai traceback al modello)
- `codice/memoria/gestione_documenti.py` (Tappa 5.1) — ciclo di vita: elenca, descrivi (link
  firmato 1h), dimentica (riga + chunk via FK cascade + file Storage + voce nei fatti collegati
  trovata con filtro jsonb `cs`, con re-indicizzazione del fatto)
- `codice/memoria/fatti_indicizzazione.py` (Tappa 5.1) — re-indicizzazione del chunk embedded di
  un fatto, condivisa tra ingest e gestione documenti
- `codice/memoria/eval/eval_estrazione.py` (Tappa 5.1) — eval del comportamento agentico
  dell'estrazione (vedi `docs/eval.md`), non gira in CI
- `codice/cli.py` — client CLI remoto sottile: elenco chiuso e deterministico di frasi di
  conferma accettate (sì/confermo/vai/ok/autorizzo, no/annulla/fermati/stop), non solo `y`/`n`
  esatto — resta un confronto in codice, non un'interpretazione del modello
- `.claude/skills/redazione-email/` — skill di prova reale (non vuota)

## Come si prova

1. Login: `curl -c cookies.txt -X POST https://eidos2-api-production.up.railway.app/login -d '{"email":"...","password":"..."}'`
2. Collega Gmail: apri l'URL restituito da `GET /oauth/google/authorize` (con cookie) in un browser
3. Collega Calendar: apri l'URL restituito da `GET /oauth/google_calendar/authorize` (con cookie) —
   consenso separato, incrementale (`include_granted_scopes`)
4. Collega Drive: apri l'URL restituito da `GET /oauth/google_drive/authorize` (con cookie)
5. Importa: `POST /import-mail` e `POST /import-calendar` (con cookie)
6. CLI: `cd codice && python cli.py` — chatta, es. "che impegni ho questa settimana?", "crea un
   evento domani alle 15 con [email]" (chiede conferma), "ricorda che X mi ha detto Y", "cosa so
   su X?", "cerca la fattura di [fornitore]" → "che allegati ha?" → "importala in memoria"
   (Tappa 5, allegato Gmail/file Drive); da Agente Locale: "importa fattura.pdf in memoria"
   (file locale, dentro il perimetro autorizzato)
7. Ciclo di vita (Tappa 5.1): "che documenti ho in memoria?" (`list_documents`), "fammi
   riscaricare quella fattura" (`get_document`, link valido 1 ora), "dimentica quel documento"
   (`forget_document` → chiede conferma come le altre azioni distruttive)

Test automatici: `codice/tests/test_tools.py`, `test_azioni.py`, `test_gmail_client.py`,
`test_calendar_client.py`, `test_drive_client.py`, `test_import_mail.py`,
`test_import_calendar.py`, `test_oauth.py`, `test_oauth_calendar.py`, `test_oauth_drive.py`,
`test_classification.py`, `test_memoria_db.py`, `test_file_extraction.py`,
`test_document_extraction.py`, `test_ingest_documento.py`, `test_image_normalization.py`,
`test_gestione_documenti.py`, `test_router.py`, `test_cli.py`. Eval (non in CI):
`codice/memoria/eval/eval_estrazione.py` — vedi [docs/eval.md](../eval.md).

## Decisioni rilevanti

- DECISIONS.md — "Safety Supervisor: punto unico di autorizzazione per ogni tool call"
- DECISIONS.md — "Memoria: un solo database, tre modi di ricordare, niente modulo RAG separato"
- DECISIONS.md — "Deploy: Dockerfile esplicito invece di Nixpacks (richiesto dal Claude Agent SDK)"
- DECISIONS.md — "Connettori: criterio di completezza 'cosa fa un umano', non 'tutta l'API'"
- DECISIONS.md — "Verifica reale di reply_email: threading corretto lato destinatario"
- DECISIONS.md — "Tappa 4: Memoria — lettura unificata, scrittura esplicita, calendario vivo vs concluso"
- DECISIONS.md — "Connettori multi-provider: contratti agnostici dal fornitore da subito"
- DECISIONS.md — "Verifica reale di Calendar: scope calendar.events insufficiente per calendarList.list"
- DECISIONS.md 2026-07-16 — "Tappa 5 (Memoria: estensione documenti): routing digitale/visivo",
  "Tappa 5: tre bug reali trovati testando con dati veri", "Tappa 5.1: rivalutazione del modulo
  documenti — ciclo di vita completo, atomicità, casi reali che fallivano male"
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
- L'`attachment_id` Gmail NON è stabile tra fetch diversi dello stesso messaggio: per lo
  scaricamento ci si fida dell'id del chiamante e i metadati si abbinano per dimensione
  (`_scarica_allegato_con_meta`); il `source_id` salvato è `message_id:filename`, mai
  l'attachment_id (con l'id instabile il match per source non scatterebbe mai)
- Dopo un `forget_document` il file è eliminato da Storage, ma un link firmato generato PRIMA
  può continuare a servire una copia dalla cache CDN di Supabase fino alla scadenza del TTL
  (~1h) — trovato con il test reale E3 (Tappa 5.1); la verifica di avvenuta cancellazione va
  fatta sull'endpoint autenticato diretto, non sul link firmato
- Una riga `memoria_documenti` con `stato='in_corso'` è un ingest interrotto: non conta per il
  dedup, si ripara automaticamente al re-import successivo (stesso source o stessi byte)
