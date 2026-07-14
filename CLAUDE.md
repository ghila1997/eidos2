# CLAUDE.md — Eidos 2.0

> Questo file definisce come è organizzato il progetto e come ci si lavora.
> Va riletto all'inizio di ogni sessione e rispettato sempre.

## Il progetto

Assistente operativo AI per imprenditori/PMI/freelance, capace di eseguire azioni reali
(non solo rispondere). Scala: micro-SaaS, obiettivo finale prodotto vendibile.
Stack: Claude Agent SDK (Python), Supabase (Auth+Postgres+pgvector+Storage+RLS), Gmail API,
Stripe Checkout. Indice completo in [PROJECT.md](PROJECT.md).

## Struttura

```
EIDOS2.0/
  CLAUDE.md
  PROJECT.md
  DECISIONS.md
  ROADMAP.md
  notes/          idee non ancora decise per questo progetto (incluse quelle recuperate da Eidos v1)
  docs/           specifiche di modulo (una per modulo, scritte quando il modulo si costruisce)
  codice/         codice del progetto
```

## Origine di questo progetto — leggere prima di tutto

Eidos 2.0 è un **reboot completo** (codice compreso) di un progetto precedente, "Eidos"
(cartella separata `APP/EIDOS`). Quel progetto va **ignorato completamente**: non leggerne
il codice, non riaprirlo, non usarlo come riferimento implicito. Aveva 9 moduli tutti "fatti"
e 373 test verdi, ma zero clienti reali e 3 blocker scoperti solo alla fine (moduli costruiti
in isolamento e mai collegati end-to-end). Le uniche parti recuperate da quel progetto sono
16 idee salvate esplicitamente, non vincolanti, in `notes/idee-salvate-da-eidos-v1.md`: da
riconfermare o cambiare quando si costruisce davvero il modulo a cui si riferiscono, mai da
dare per acquisite.

## Metodo di costruzione: walking skeleton

La causa radice del fallimento di Eidos v1 è stata costruire ogni modulo al 100% in
isolamento, rimandando il collegamento reale tra moduli alla fine. **Non si ripete.**

- Si costruisce prima il percorso più sottile ma vero **end-to-end**: interfaccia →
  orchestratore minimo → un'azione reale eseguita davvero → risposta. Con un solo utente
  (il founder), senza tenancy multi-utente, ruoli, dispositivi o billing.
- Si ispessisce un pezzo alla volta (più azioni, poi più moduli, poi multi-tenant, poi
  billing), mantenendo **sempre** il percorso end-to-end eseguibile.
- La sovrastruttura da SaaS multi-tenant (ruoli, permessi granulari, dispositivi, fatturazione)
  si aggiunge solo dopo che lo scheletro funziona per un utente reale. Vedi ROADMAP.md per
  l'ordine concreto.
- `tenant_id` è comunque presente fin dall'inizio nello schema dati (vedi DECISIONS.md) per
  evitare un retrofit costoso quando arriva il secondo tenant — è un dettaglio di schema, non
  una sovrastruttura da costruire subito.

## Verifica delle capacità del Claude Agent SDK — regola dura, senza eccezioni

Prima di scrivere codice o specifica per QUALSIASI capacità nuova (tool custom, subagent,
memoria, permessi, sessioni, hook, streaming, ecc.), verificare se il Claude Agent SDK la
offre già nativamente, delegando a un subagent `claude-code-guide` che controlla la
documentazione ufficiale live. Non fidarsi di ricordi o di codice visto altrove: l'SDK reale
usa `query()`/`ClaudeSDKClient`, `AgentDefinition` per i subagent, il decorator `@tool` per i
tool custom — non inventare API (es. non esiste una classe `Agent` con `.as_tool()`, non
esiste un "memory tool" che gestisce automaticamente una cartella `/memories/`: quello si
implementa con tool custom scritti a mano). Nessuna eccezione per capacità che "sembrano
ovvie".

## Completezza dei connettori — regola dura

Prima di scegliere quali capacità di un connettore esterno (Gmail, Calendar, Storage, ecc.)
implementare, fare una rassegna sistematica della superficie completa dell'API (tutte le
risorse/metodi che espone), non scegliere a memoria o istinto in base ai soli requisiti
minimi del design. Il criterio di completezza **non è** "tutta l'API" (impostazioni account,
delega, S/MIME e simili restano fuori: sono amministrazione che nessun cliente chiede a un
assistente in chat) **ma** "tutto quello che un essere umano fa normalmente con quella
capacità" (per la mail: cercare, rispondere nel thread giusto, inoltrare, segnare
letta/archiviare/importante, organizzare in cartelle/etichette, leggere allegati, cestinare —
non solo cerca/bozza/invia). Il costo di aggiungere dopo una capacità mancante è basso se le
fondamenta (storage credenziali per tenant, pattern di registrazione tool, gate di conferma
per azioni distruttive) sono già generiche — non è una scusa per rimandare a caso, ma nemmeno
un motivo per bloccare il lancio finché non è coperto tutto lo scibile di un'API.

## Verifica del comportamento agentico (eval)

I test automatici verificano che il codice funzioni; non verificano che l'agente si comporti
bene su casi reali (recupero incompleto, istruzione ostile in un documento letto, ambiguità
nell'intento). Per moduli che toccano comportamento agentico (Orchestratore, Memoria,
Connettori Cloud, Agente Locale), oltre ai test in `codice/<modulo>/tests/`, valutare scenari
scriptati con verità nota in `codice/<modulo>/eval/`, registrati in `docs/eval.md` quando quel
file esiste. Non gira in CI: si lancia prima di dichiarare finito un modulo che tocca
comportamento agentico, e comunque prima della Tappa 10 di ROADMAP.md (checklist di lancio).

## Flusso di lavoro sui moduli

Ogni modulo si costruisce con la skill `saas-module-builder` seguendo questo
ciclo, in una sessione dedicata. **I due stop dell'utente sono obbligatori e non si saltano
mai:**

0. **Controllo arretrati** — prima di aprire il design di una tappa/modulo nuovo, rileggere in
   ROADMAP.md i "Finito quando" delle tappe precedenti e la sezione "Esplicitamente
   rimandato". Se qualcosa risulta incompleto e **non** è già annotato lì come rimandato,
   va segnalato esplicitamente all'utente prima di procedere — non si salta in silenzio.
   Non si applica alle scelte tecniche rimandate "solo se serve" (es. subagent paralleli): quelle
   restano non fatte finché non emerge un bisogno reale, e non sono un arretrato.
1. Design dettagliato del modulo **in chat** (interfacce, entità, decisioni,
   trappole da testare) — nessun file viene scritto in questa fase
2. 🛑 **STOP 1 — l'utente valida il design in chat.** Solo dopo l'ok esplicito
   si procede
3. Codice + test automatici (versione minima end-to-end prima, poi il resto)
4. Gate di qualità con la skill `validation-pipeline`
5. 🛑 **STOP 2 — l'utente testa a mano che funzioni.** Fornirgli istruzioni
   semplici e concrete su come provare. **Nessun commit prima del suo via libera**
6. Commit + integrazione nel main (feature flag se non pronto per gli utenti)
7. Documentazione scritta/aggiornata: README del modulo (fotografa com'è
   venuto davvero), DECISIONS.md se ci sono state decisioni, ROADMAP.md e
   tabella in PROJECT.md aggiornate

## Regole di documentazione

- I documenti di stato (PROJECT.md, ROADMAP.md, README dei moduli) descrivono
  **lo stato attuale**, al presente. Si aggiornano nello stesso passaggio del
  codice, mai "dopo".
- `DECISIONS.md` è **append-only**: mai modificare o cancellare voci esistenti;
  una decisione superata si sostituisce con una nuova voce che la linka.
- Ogni informazione vive in un punto solo; altrove si linka.
- Idee non ancora decise → `notes/`, mai nei documenti di stato.
- Prima di toccare il codice di un modulo esistente, leggere il suo README.
- Se docs e codice si contraddicono: non scegliere in silenzio chi ha ragione,
  portare la discrepanza all'utente.

## Cambiamenti alla mappa del progetto

Nuovi moduli, fusioni, revisioni della roadmap o delle decisioni strutturali
passano dalla skill `saas-architect`, non si improvvisano dentro un ciclo di
costruzione.

## Regole specifiche del progetto

- Un solo motore agentico: Claude Agent SDK. Gli "agenti specializzati" sono subagenti dentro
  lo stesso SDK (`AgentDefinition`), introdotti solo quando serve davvero delega parallela —
  il Modulo Orchestratore/Memoria iniziale parte con un agente singolo e tool custom.
- Ordine di sviluppo dentro ogni modulo che tocca interazione: testo prima, voce dopo.
- Azioni distruttive (invio email, cancellazioni, spesa) richiedono un gate esplicito nel
  codice (non solo un'istruzione nel system prompt): l'utente conferma fuori dal controllo
  del modello prima che l'azione reale avvenga.
