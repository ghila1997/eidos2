# Idee recuperate da Eidos v1

> Non sono decisioni vincolanti per questo progetto. Sono punti di partenza da riconfermare
> o cambiare quando si costruisce davvero il modulo a cui si riferiscono (vedi CLAUDE.md,
> sezione "Origine di questo progetto"). Quando un modulo viene disegnato con
> `saas-module-builder`, chi lo fa deve rileggere le voci di questa lista relative a quel
> modulo e decidere esplicitamente se tenerle, adattarle o buttarle — non darle per
> acquisite in silenzio.

## Fondamenta
- Grant su cartella copre anche le sottocartelle
- Nel controllo di autorizzazione, il ruolo si verifica prima dell'azione "distruttiva";
  le voci condivise dal tenant si cancellano solo dall'owner
- Redazione dei campi sensibili nell'audit log, alla fonte (non a posteriori)
- Tre ruoli — owner/operatore/lettore — con i permessi dell'operatore derivati solo da Grant
  espliciti, non da un elenco fisso nel codice
- Limite dispositivi per utente, con pairing tramite QR (rilevante solo da Tappa 8 in poi)

## Orchestratore
- Autorizzazione dei tool registrati tramite hook PreToolUse, non tramite `can_use_tool`
- Protezione da prompt injection: delimitazione esplicita del contenuto non fidato (letto da
  tool) + rinforzo nel system prompt — nessun classificatore custom in v1
- **Skills del Claude Agent SDK** (nuova, non da Eidos v1 — verificata il 2026-07-13 su
  https://code.claude.com/docs/en/agent-sdk/skills.md): il Claude Agent SDK supporta le Skills
  con lo stesso formato di Claude Code (SKILL.md, frontmatter YAML in `.claude/skills/`),
  invocate autonomamente dal modello in base alla descrizione. Da abilitare esplicitamente via
  `setting_sources` in `ClaudeSDKClient`/`query()` (non automatico come in Claude Code); il
  campo `allowed-tools` dentro SKILL.md non funziona nell'SDK, i permessi si controllano da
  `allowedTools` lato SDK. Buon fit per procedure/playbook aziendali specifici del cliente
  (es. template di risposta, processi ricorrenti) — diverso dai Subagent (`AgentDefinition`),
  che restano per delega parallela con tool-set separato. Da verificare di nuovo su
  documentazione live quando si costruisce il modulo (la regola di CLAUDE.md vale comunque).

## Agente Locale
- Isolamento della sessione SDK dalla macchina ospite (il meccanismo concreto va verificato
  da zero: in Eidos v1 il tentativo basato su `SANDBOX_SETTINGS` nativo non funzionava su
  Windows — non ripartire da quell'implementazione, solo dal principio)

## Memoria (comprende quella che in Eidos v1 era "Documenti Aziendali RAG", ora fusa qui)
- I fatti per tenant si legano a un'entità nominata, con upsert per `entity_key` — non solo
  accumulo narrativo libero (rilevante per le tabelle strutturate, Tappa 2/5 di ROADMAP.md)
- Deduplica cross-origine per hash quando lo stesso contenuto arriva da fonti diverse (es.
  stesso allegato ricevuto via email e caricato anche su storage) — rilevante per l'ingestione
  documenti, Tappa 5

## Connettori Cloud
- OAuth gestito da Eidos per singola capacità (es. "leggere email"), non per fornitore in
  blocco (es. "tutto Google")
- Copertura delle fonti dati: promemoria nel system prompt + manifest a runtime + parallelismo
  nativo nella ricerca — nessuna correzione a posteriori pianificata per v1
- Account cloud personali per utente (non condivisi a livello di tenant)

## Consumi
- Consumo e spesa AI misurati internamente per tenant (una sola chiave di piattaforma,
  attenzione a normalizzare correttamente modelli diversi nel calcolo)
- Tetto di spesa con listino tariffe interno + markup per tenant; avvisi a 80%/100% — in
  Eidos 2.0 questo diventa il meccanismo di limite/avviso sotto un abbonamento flat (vedi
  DECISIONS.md), non fatturazione a consumo diretta

## Metodologia trasversale (già in CLAUDE.md, non da ridiscutere modulo per modulo)
- Verificare sempre se il Claude Agent SDK offre già nativamente una capacità, delegando a un
  subagent `claude-code-guide` che controlla la documentazione ufficiale live, prima di
  progettare o scrivere codice per qualunque capacità nuova

---

## Esplicitamente scartate (da NON portare avanti in nessuna forma)

Le seguenti 8 idee di Eidos v1 sono state scartate esplicitamente dall'utente. Quando si
arriva al modulo pertinente, si riprogetta da zero **senza guardare alla vecchia conclusione**
neanche come riferimento negativo:

1. Niente sandbox nativa del terminale su Windows, solo conferma obbligatoria
2. Modello di conservazione del "Vault" (archivio locale di documenti di Eidos v1, condiviso
   tra Agente Locale e Documenti RAG per indicizzare cartelle locali): copia grezza
   indipendente dalla fonte — **il concetto di Vault stesso non fa parte di Eidos 2.0**, qui
   resta solo come registro di cosa è stato scartato
3. Vault (vedi punto 2): contenuto narrativo sempre, stato mutabile solo da concluso
4. Modello di streaming/conferma one-shot dell'orchestratore verso l'interfaccia
5. Sincronizzazione testo/voce basata su timestamp per carattere di ElevenLabs
6. Flusso di login/sessione Supabase Auth + RLS (il provider Supabase resta, vedi
   DECISIONS.md — è solo il flusso specifico a essere scartato)
7. Voce in streaming continuo via WebSocket ElevenLabs
8. Rivelazione continua del turno audio (gapless, testo autorevole)
