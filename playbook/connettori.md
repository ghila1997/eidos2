# Playbook — implementare un connettore

> Checklist operativa, estratta da come è stato costruito davvero il connettore Gmail
> (Tappa 2), non scritta a priori. Si applica al prossimo connettore (Calendar, Storage —
> Tappa 4 di ROADMAP.md) e si aggiorna se un caso reale smentisce un punto.
>
> Principi generali (perché, non cosa fare passo passo) restano in CLAUDE.md: questo file è
> il "come, concretamente" — non duplicarli qui, linkarli.

## 0. Prima di scrivere codice

- Rassegna sistematica della superficie completa dell'API — criterio "cosa fa un essere
  umano normalmente con questa capacità", non "tutta l'API" (amministrazione account esclusa)
  né "solo i requisiti minimi del design". Vedi CLAUDE.md, "Completezza dei connettori", e
  DECISIONS.md 2026-07-14 "Connettori: criterio di completezza".
- Verificare se il Claude Agent SDK offre già qualcosa nativamente per il pattern che serve
  (streaming, sessioni, ecc.) prima di costruirlo a mano — vedi CLAUDE.md, sezione
  "Verifica delle capacità del Claude Agent SDK".

## 1. Struttura del codice (pattern Gmail)

- `<connettore>_client.py` — client HTTP puro (`httpx`, niente SDK pesanti se evitabile),
  una funzione per capacità, nessuna dipendenza dal framework agente. Vedi
  `codice/orchestratore/gmail_client.py`.
- `tools.py` — wiring dei tool custom (`@tool`) esposti al modello: azioni reversibili/a
  basso rischio eseguono subito, azioni distruttive creano un'azione pending (vedi punto 3).
- `azioni.py` — dispatch delle azioni pending per tipo, eseguite solo dall'endpoint di
  conferma (vedi `codice/orchestratore/azioni.py`, `_ESECUTORI`).
- `oauth.py` — OAuth per singola capacità, scope minimo necessario per quello che il
  connettore fa davvero (non per fornitore in blocco), refresh token cifrato a riposo.

## 2. Gate di conferma per azioni distruttive

- Ogni azione che invia, cancella, spende o modifica in modo non reversibile passa da
  un'azione pending + un endpoint di conferma separato, mai da un semplice `input()` nel loop
  né da un'esecuzione diretta del modello — vedi CLAUDE.md, "Regole specifiche del progetto".
- Azioni reversibili e a basso rischio (segnare letta, archiviare, etichettare) eseguono
  subito, senza conferma — non tutto merita lo stesso gate.

## 3. Sync incrementale (se il connettore importa dati)

- Preferire un cursore nativo preciso offerto dalla piattaforma (es. `historyId` di Gmail)
  a una finestra temporale a bassa granularità (es. `after:<data>`, che riscansiona l'intera
  giornata) — vedi `codice/orchestratore/gmail_client.py::lista_messaggi_nuovi`.
- Gestire il caso in cui il cursore scada lato piattaforma (finestra di conservazione
  limitata): fallback a un fetch pieno + nuovo cursore, mai un errore che blocca l'import.
  Il dedup a valle (hash/source_id, prima di classificare/embeddare) copre gli eventuali
  elementi ripescati dal fetch pieno — non serve altra logica di deduplica nel client.

## 4. Test

- Unit test del client con mock HTTP (`respx_mock`, coerente con `test_memoria_db.py` e
  `test_gmail_client.py`) — un test per funzione, non solo il caso felice.
- Le "trappole" contano più della copertura: casi che un umano si aspetterebbe funzionino
  (risposta nel thread giusto, non duplicare un'etichetta/risorsa già esistente, dedup prima
  di rifare lavoro costoso) vanno testati esplicitamente, non lasciati alla copertura
  incidentale di altri test.
- Verifica end-to-end reale (non mockata) contro l'account vero prima di dichiarare finita
  una capacità rischiosa — i mock verificano che il codice giri, non che il comportamento
  osservato dal destinatario reale sia corretto. Vedi DECISIONS.md 2026-07-14 "Verifica reale
  di `reply_email`".

## 5. Documentazione (stesso passaggio del codice, non dopo)

- README del modulo (`docs/<modulo>/README.md`): sezione "Trappole note / attenzioni"
  aggiornata con quello che si è scoperto costruendo, anche i limiti della piattaforma esterna
  che non sono un nostro bug (es. vista "Inviata" di Gmail).
- DECISIONS.md: nuova voce se è emersa una scelta non ovvia durante l'implementazione
  (scope OAuth cambiato, alternativa scartata, comportamento inatteso della piattaforma) —
  mai riscrivere una voce esistente, append-only.

## Quando questo playbook non basta

Se il prossimo connettore rivela un pattern nuovo non coperto qui (es. webhook/push invece di
polling, paginazione multi-pagina, rate limiting), si aggiorna questo file con il caso reale —
non si scrive la generalizzazione prima di averla vista funzionare almeno una volta.
