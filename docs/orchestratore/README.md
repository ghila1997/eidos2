# Modulo: Orchestratore + Memoria (prima istanza)

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Agente conversazionale singolo (Claude Agent SDK, modello `claude-sonnet-5`) che capisce
l'intento del founder e usa un connettore Gmail completo per cercare, rispondere,
inoltrare, organizzare e inviare mail per suo conto. Memoria: poche preferenze sempre
caricate, fatti strutturati per entità (schema pronto, ancora vuoto), ricerca semantica
(pgvector) su mail importate. NON fa: subagent paralleli (nessun bisogno di delega
ancora), sync/import automatico (on-demand, l'automatico è Tappa 10), estrazione
strutturata da documenti generici (Tappa 5), UI oltre CLI (Tappa 7), gestione account
Gmail (S/MIME, filtri, delegati, vacation responder — amministrazione non richiesta
tramite chat).

## Interfacce

- **Espone**: `POST /chat` (messaggio → risposta agente, gestisce la sessione conversazionale),
  `POST /azioni/{id}/conferma` (unico punto in cui un'azione distruttiva diventa reale),
  `GET /oauth/google/authorize` + `GET /oauth/google/callback` (collegamento Gmail),
  `POST /import-mail` (ingest on-demand). Tutti richiedono la sessione di Fondamenta
  (cookie), quindi utilizzabili da qualunque dispositivo loggato.
- **Consuma**: Fondamenta (`get_sessione_corrente`), Supabase Postgres+pgvector, Gmail API,
  Voyage AI (embedding), Anthropic API pura (classificazione Haiku), Claude Agent SDK
  (conversazione, richiede il CLI Node.js `@anthropic-ai/claude-code` come sottoprocesso —
  vedi `Dockerfile`).

## Come funziona

- `codice/orchestratore/router.py` — endpoint FastAPI, system prompt con preferenze,
  wiring Agent SDK (`query()` con `resume` per riprendere la sessione tra richieste HTTP;
  fallback a sessione nuova se quella salvata non esiste più nel container — vedi DECISIONS.md)
- `codice/orchestratore/tools.py` — tool custom: `search_emails`, `draft_email`,
  `send_email`, `reply_email`, `forward_email`, `send_draft`, `trash_email` (questi ultimi
  cinque creano un'azione pending, non eseguono subito), `mark_email`, `organize_email`,
  `list_labels`, `get_attachment` (immediati, reversibili)
- `codice/orchestratore/safety/` — Safety Supervisor: punto unico di autorizzazione per ogni
  tool call (nativo o custom), policy dichiarative in `policies.yaml`, audit log JSONL. Ogni
  funzione tool lo chiama in testa invece di decidere da sé se serve conferma (vedi
  DECISIONS.md, "Safety Supervisor: punto unico di autorizzazione per ogni tool call")
- `codice/orchestratore/azioni.py` — azioni distruttive in attesa di conferma umana esplicita,
  dispatch per tipo (`_ESECUTORI`, firma `(tenant_id, payload)`)
- `codice/orchestratore/gmail_client.py` — client Gmail completo (httpx puro): mail,
  reply/forward con threading corretto, modify, labels, allegati, drafts
- `codice/orchestratore/oauth.py` — OAuth Google (scope `gmail.modify`+`gmail.labels`),
  cifratura refresh token (Fernet)
- `codice/orchestratore/classification.py` — classificazione mail (Anthropic API pura,
  Haiku) prima dell'ingest, riusabile per classificazione generale
- `codice/orchestratore/embeddings.py` — embedding (Voyage AI, `voyage-3`)
- `codice/orchestratore/import_mail.py` — pipeline ingest on-demand: fetch → dedup
  (hash/source_id) → classifica → chunk+embedding+salva
- `codice/memoria/db.py` — accesso PostgREST alle tabelle di Memoria
- `codice/cli.py` — client CLI remoto sottile (nessuna logica agente, solo I/O via HTTP)
- `.claude/skills/redazione-email/` — skill di prova reale (non vuota)

## Come si prova

1. Login: `curl -c cookies.txt -X POST https://eidos2-api-production.up.railway.app/login -d '{"email":"...","password":"..."}'`
2. Collega Gmail: apri l'URL restituito da `GET /oauth/google/authorize` (con cookie) in un browser, concedi il consenso
3. Importa: `POST /import-mail` (con cookie)
4. CLI: `cd codice && python cli.py` — chatta, es. "cerca nelle mie mail X", "rispondi a quella mail dicendo Y" (chiede conferma `[y/n]`)

Test automatici: `codice/tests/test_tools.py`, `test_azioni.py`, `test_gmail_client.py`,
`test_import_mail.py`, `test_oauth.py`, `test_classification.py`, `test_memoria_db.py`.

## Decisioni rilevanti

- DECISIONS.md — "Safety Supervisor: punto unico di autorizzazione per ogni tool call"
- DECISIONS.md — "Memoria: un solo database, tre modi di ricordare, niente modulo RAG separato"
- DECISIONS.md — "Deploy: Dockerfile esplicito invece di Nixpacks (richiesto dal Claude Agent SDK)"
- DECISIONS.md — "Connettori: criterio di completezza 'cosa fa un umano', non 'tutta l'API'"
- DECISIONS.md — "Verifica reale di reply_email: threading corretto lato destinatario"
- CLAUDE.md — "Completezza dei connettori", "Azioni distruttive" (gate di conferma)

## Trappole note / attenzioni

- `send_email`/`reply_email`/`forward_email`/`send_draft`/`trash_email` non eseguono mai
  subito: creano un'azione in `azioni_pending`, solo `/azioni/{id}/conferma` (chiamata
  dall'utente, mai dal modello) esegue l'azione vera — coperto da `test_azioni.py`/`test_tools.py`
- La sessione conversazionale (Agent SDK) vive su disco locale del container: se il
  container viene rideployato a metà conversazione, la sessione si perde e si riparte da
  una nuova (gestito, non un errore) — nessun dato di Memoria coinvolto
- Reply threading: verificato che funziona lato destinatario reale; la cartella "Inviata"
  del mittente può mostrare i messaggi separati per una stranezza nota di Gmail, non del
  nostro codice (vedi DECISIONS.md)
- "Cancellare" una mail sposta nel cestino (`messages.trash`), non elimina in modo
  permanente — lo scope OAuth (`gmail.modify`) non consente l'eliminazione immediata,
  scelta deliberata (vedi DECISIONS.md)
- L'import incrementale usa `users.history.list` (cursore = historyId Gmail, preciso a
  livello di singolo evento). Se l'historyId scade lato Gmail (404, finestra di
  conservazione limitata) o manca (primo import), fa fallback a un fetch pieno via
  `messages.list` + nuovo historyId da `users.getProfile` — dedup esistente copre eventuali
  mail già importate ripescate dal fetch pieno
- `claude-agent-sdk` richiede il CLI Node.js come sottoprocesso runtime: build via
  `Dockerfile` (non Nixpacks), versione >=0.2.118 (la 0.1.69 aveva un bug nella risposta
  dei tool custom)
