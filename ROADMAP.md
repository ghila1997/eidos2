# Roadmap di implementazione — Eidos 2.0

> Ordine di costruzione dei moduli, walking skeleton: prima il percorso end-to-end più
> sottile ma vero, poi si ispessisce. Ogni modulo si approfondisce in sessione dedicata
> ("approfondiamo il modulo X").

## Tappa 1 — Fondamenta (versione minima, single-user)

- Scheletro repo, deploy in produzione di un "hello world", CI minima
- Autenticazione del founder come singolo utente su Supabase; `tenant_id` presente nello
  schema fin da subito ma con un solo tenant valorizzato
- **Sblocca**: tutto il resto. **Non serve ancora**: ruoli multipli, dispositivi/pairing,
  inviti team, billing
- **Finito quando**: il founder si autentica e un commit su main arriva in produzione da solo

## Tappa 2 — Orchestratore minimo + Memoria (prima istanza)

- Agente singolo (Claude Agent SDK, `ClaudeSDKClient`), tool custom via `@tool`
- Memoria, versione minima: poche righe sempre caricate (preferenze base) + ricerca semantica
  (pgvector) alimentata da import reale delle mail (Gmail API, OAuth lettura+invio). Le
  tabelle strutturate per fatti su clienti/progetti si abbozzano ma restano vuote finché
  l'agente non impara qualcosa in conversazione (l'estrazione automatica dai documenti arriva
  in Tappa 5, ma lo schema si disegna già ora per non doverlo rifare)
- Filtro/classificazione delle mail **prima** dell'ingestione: non tutto quello che arriva in
  casella va salvato in memoria (newsletter, notifiche, spam esclusi). Il meccanismo esatto
  (subagente dedicato via `AgentDefinition`, o un passaggio di classificazione più leggero con
  structured output) si decide costruendo il modulo, verificando prima le capacità SDK reali —
  ma va progettato come componente riusabile: la stessa logica serve anche per classificare le
  mail in generale (priorità, categoria), non solo per filtrare cosa ingerire
- `draft_email` + `send_email` con conferma esplicita y/n nel loop CLI (gate nel codice, non
  nel modello)
- Interfaccia: CLI testuale
- **Skills del Claude Agent SDK** (vedi `notes/idee-salvate-da-eidos-v1.md`, sezione
  Orchestratore): abilitare `setting_sources` e predisporre `.claude/skills/` da subito, anche
  se all'inizio con una sola skill di prova — più facile abilitarlo ora che aggiungerlo dopo
- **Sblocca**: il primo vero "aha moment" (cercare nei propri dati e agire davvero)
- **Finito quando**: il founder usa l'assistente da CLI per cercare qualcosa nelle mail reali
  e farsi inviare un'email vera, con conferma esplicita prima dell'invio

## Tappa 3 — Agente Locale (prima azione reale sul PC)

- File/cartelle: almeno un'azione concreta (leggere/scrivere/organizzare un documento reale)
- Sessione isolata dalla macchina ospite (da riprogettare da zero, nessuna decisione ereditata)
- **Finito quando**: un comando in linguaggio naturale produce un'azione reale verificabile su
  un file del PC del founder

## Tappa 4 — Connettori Cloud (oltre email)

- Calendario, storage cloud; OAuth gestito per singola capacità, non per fornitore in blocco
- **Finito quando**: il founder crea/legge un evento di calendario reale tramite l'assistente

## Tappa 5 — Memoria: estensione documenti (non un modulo a parte)

- Ingestione documenti oltre le mail (PDF, file locali, storage cloud), deduplica
  cross-origine per hash, archiviazione del file originale (storage)
- Estrazione strutturata: oltre a rendere il documento cercabile per argomento (embedding),
  si estraggono i campi rilevanti (es. importo e scadenza di una fattura) e si scrivono nelle
  tabelle strutturate di Memoria — non solo riassunto/ricerca semantica
- **Finito quando**: una domanda su un documento reale caricato produce una risposta corretta
  con fonte citata, e i campi chiave di un documento tipico (es. fattura) sono interrogabili
  come dati strutturati, non solo trovabili per ricerca semantica

## Tappa 6 — Voce

- STT/TTS, progettati da zero (nessuna decisione ereditata da Eidos v1)
- **Finito quando**: una conversazione vocale completa (domanda parlata → azione → risposta
  parlata) funziona per il founder

## Tappa 7 — Interfaccia Utente

- Oltre la CLI: interfaccia multimodale (voce/testo/componenti), log azioni visibile, conferme
- **Finito quando**: il founder usa l'assistente senza terminale, con log delle azioni visibile

## Tappa 8 — Fondamenta multi-tenant (SaaS-ificazione)

- Ruoli owner/operatore/lettore con permessi via Grant, limite dispositivi per utente
- **Onboarding self-service**: un cliente nuovo si registra, collega i propri account cloud
  (Gmail, calendario) tramite un vero flusso OAuth con schermata/endpoint dedicati — senza
  intervento manuale del founder. Nel progetto precedente questa parte era stata dimenticata
  fino all'ultimo audit (la logica OAuth esisteva ma nessuno schermo/endpoint la richiamava):
  qui è un criterio esplicito di "finito", non un dettaglio implicito
- **Sblocca**: primo cliente reale oltre il founder
- **Finito quando**: un secondo utente reale (non il founder) si registra da solo, collega un
  proprio account cloud senza aiuto, si autentica in un tenant separato e opera con permessi
  corretti

## Tappa 9 — Consumi + Billing

- Modulo Consumi (misura interna per tenant) + abbonamento flat via Stripe Checkout, soglia
  di consumo con avvisi 80%/100%
- **Sostenibilità del prezzo**: prima di fissare il prezzo dell'abbonamento, stimare il costo
  reale per tenant (Claude API + embedding + Supabase) sul traffico atteso, per verificare che
  il flat regga il margine — non solo "abbonamento flat" come idea, ma un numero verificato
- **Finito quando**: un cliente paga l'abbonamento, lo stato si riflette nell'app, e il prezzo
  scelto è coperto dal costo stimato per tenant

## Tappa 10 — Automazioni

- Il Claude Agent SDK non offre nulla di nativo per schedulazione o trigger su eventi (verificato
  sulla doc ufficiale 2026-07-13: Sessions serve a riprendere una conversazione, Hooks intercetta
  tool call dentro una sessione già in corso — nessuno dei due "risveglia" l'agente da solo).
  Serve infrastruttura dedicata: scheduler (es. APScheduler) per esecuzioni a orario fisso,
  webhook/poller per trigger su eventi (riusa le connessioni già attive dei Connettori Cloud,
  es. nuova mail), storage delle definizioni automazione per tenant (Supabase)
- Esecuzione: ogni automazione, quando scatta, invoca l'Orchestratore con un prompt costruito
  dalla definizione salvata — stesso gate di conferma sulle azioni distruttive già in vigore
  per il resto del prodotto, nessuna eccezione perché l'azione parte da un trigger automatico
- **Finito quando**: un cliente reale crea un'automazione (es. "ogni lunedì mattina riepilogo
  email non lette") che si esegue da sola, rispettando i gate di conferma esistenti

## Tappa 11 — Prima del primo cliente esterno reale (checklist di lancio)

Cinque cose che un prodotto "quasi finito" dimentica facilmente perché nessun modulo le
possiede da solo — vanno verificate esplicitamente prima di aprire a un cliente pagante
non-founder, non date per scontate:

- **Skills pronte all'uso**: almeno un set di skill reali (procedure/playbook aziendali,
  template di risposta) scritte e testate in `.claude/skills/`, non solo la capacità abilitata
  a vuoto dalla Tappa 2 — un cliente nuovo deve trovare qualcosa di già utile, non una funzione
  tecnica senza contenuto
- **Privacy/GDPR**: diritto alla cancellazione dati di un cliente reale — verificare che
  cancellare un fatto/documento lo tolga davvero ovunque, **audit log incluso** (nel progetto
  precedente `forget()` non toccava l'audit log, dove il contenuto restava in chiaro)
- **Backup dei dati**: policy di backup/restore per email/documenti/fatti dei clienti
- **Osservabilità in produzione**: come si scopre che un cliente reale ha un problema (log
  minimi + alert), non solo log locali visti dal founder durante lo sviluppo
- **Eval del comportamento agentico**: oltre ai test automatici del codice, scenari verificati
  a mano/scriptati sul comportamento reale dell'agente (vedi CLAUDE.md, sezione eval)

**Finito quando**: le quattro voci sopra hanno una risposta scritta (anche minima), non sono
più "dimenticate silenziosamente"

## Tappe successive

| Ordine | Modulo | Perché ora | Finito quando |
|---|---|---|---|
| 12 | Primo cliente esterno reale | Scheletro end-to-end + billing + Automazioni + checklist di lancio (Tappa 11) coperti | Un cliente pagante non-founder usa il prodotto in autonomia |

## Esplicitamente rimandato

- Fatturazione a consumo/token (Stripe metered billing) — si rivaluta quando serve
  differenziare i piani per consumo reale
- Sandboxing nativo del terminale — mitigazione attuale resta la conferma obbligatoria
  sulle azioni distruttive, da riprogettare da zero quando si arriva al tema
- Multi-dispositivo/pairing, ruoli granulari — rimandati alla Tappa 8
- Tutte le 8 idee esplicitamente scartate di Eidos v1 (modello Vault, streaming
  orchestratore, sync voce, flusso auth precedente, voice streaming continuo, turn-taking
  audio) — si riprogettano da zero quando si arriva al modulo pertinente, senza guardare
  alla vecchia conclusione
