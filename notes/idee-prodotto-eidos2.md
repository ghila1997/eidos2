# Idee di prodotto per Eidos 2.0 (non ancora decise)

> Idee emerse costruendo un modulo, non ancora valutate/decise da `saas-architect`.
> Non vincolanti. Da riprendere seriamente quando arriva il momento giusto nella
> roadmap, non da costruire di riflesso mentre si lavora su altro.

## "Eidos Mail" — piano/tier solo classificazione automatica, senza agente conversazionale

**Emersa**: 2026-07-14, costruendo Tappa 2 (Orchestratore + Memoria), parlando di
completezza del connettore Gmail.

**Idea**: un piano più economico dello stesso Eidos (non un prodotto/codebase a
sé) per clienti che vogliono solo "la mail organizzata da sola" senza l'assistente
conversazionale completo. Il tenant su questo piano ha accesso solo alla pipeline
di classificazione (Haiku, già esistente in `codice/orchestratore/classification.py`)
e organizzazione automatica (etichette Gmail via `organize_email`/`mark_email`),
**senza** i tool conversazionali di ricerca/risposta/invio (bastano gli
`allowed_tools` già parametrici in `tools.py` per disattivarli per quel tenant).

**Perché come tier e non prodotto separato**: stessa infrastruttura (tenant_id,
OAuth, DB già multi-tenant da subito), un solo onboarding/fatturazione da
mantenere invece di due. Superficie prodotto = Gmail stesso (etichette/stato
applicati automaticamente) — nessuna interfaccia propria da costruire per questo
piano, il valore si vede direttamente nella casella del cliente.

**Prerequisiti non ancora pronti**:
- Tappa 10 (Automazioni/scheduler) — questo piano richiede classificazione
  "ogni tot/ogni mail arrivata" automatica, non on-demand via chat
- Tappa 9 (Consumi/Billing) — serve un meccanismo di gating per piano (quali
  tool/capacità sono attivi per un tenant), non ancora progettato
- Eventualmente Onboarding, se il piano ha un flusso di attivazione diverso

**Da NON fare**: costruirlo ora, mentre lo scheletro base di Eidos (Tappa 2) è
ancora in validazione con un solo utente reale (il founder) — rischio di
biforcare l'attenzione prima di aver validato la prima cosa, lo stesso errore
che ha affossato Eidos v1.

**Prossimo passo quando arriva il momento**: portare la decisione a
`saas-architect` (è una decisione di mappa/pricing, non un dettaglio di modulo).

## Consenso persistente per categoria e modalità di controllo cliente (Safety Supervisor)

**Emersa**: 2026-07-14, progettando il Safety Supervisor (vedi DECISIONS.md, "Safety Supervisor:
punto unico di autorizzazione per ogni tool call") durante il design di Tappa 3.

**Idea 1 — consenso persistente per categoria**: invece di chiedere conferma a ogni singola
azione `ask_user`, il cliente potrebbe autorizzare una categoria una volta ("ok, non chiedermi
più per l'archiviazione mail") e il Supervisor la ricorda (una specie di `ConsentStore`). Oggi
il Supervisor chiede sempre, senza memoria.

**Vincolo esplicito da rispettare se/quando si costruisce**: alcune categorie (pagamenti,
operazioni bancarie, cancellazioni irreversibili) **non devono mai** ammettere consenso
persistente/bypass, a prescindere da cosa sceglie il cliente — sono le uniche dove "chiedi
sempre" non è negoziabile. Punto sollevato esplicitamente dall'utente.

**Idea 2 — modalità di controllo selezionabile dal cliente** (stile Claude Code:
`default`/`acceptEdits`/`plan`/`bypassPermissions`...): proposta dall'utente, valutazione
richiesta esplicitamente "critica e sincera".

**Valutazione**: **sconsigliata così com'è**. Claude Code è usato da sviluppatori che capiscono
il rischio di ogni modalità; il pubblico di Eidos è PMI/freelance non tecnici (vedi PROJECT.md).
Un selettore globale che può disattivare le conferme rischia che un cliente lo scelga per "essere
meno interrotto" senza capire di aver tolto la rete di sicurezza pensata apposta per evitare danni
costosi (mail sbagliata, file cancellato) — e in tensione con walking skeleton: si aggiungerebbe
complessità di scelta prima ancora che un cliente reale abbia usato il gate base. Se in futuro
serve dare controllo, meglio granulare per categoria con lo stesso vincolo rigido dell'Idea 1
(alcune categorie mai automatizzabili), non un interruttore generale.

**Da NON fare ora**: nessuna delle due, restano idee da rivalutare quando (e se) emerge un
bisogno reale da clienti veri, non ipotizzato in anticipo.

## Store: capacità comprabili/attivabili per tenant (connettori, skill, automazioni, agenti)

**Emersa**: 2026-07-14, discutendo se/come un cliente potrà in futuro aggiungere o togliere
connettori, e generalizzando a skill/automazioni/agenti personalizzati acquistabili.

**Principio generale proposto**: separare il **catalogo** (cosa esiste, condiviso, un solo
deploy — coerente con shared schema già deciso, vedi DECISIONS.md 2026-07-13) dall'**istanza
per tenant** (cosa quel cliente ha attivato + eventuali dati scoped a lui). "Comprare" non
vuol dire installare codice per quel tenant (non ha senso in un'architettura a deploy unico):
vuol dire attivare un entitlement + eseguire il provisioning specifico del tipo. "Disdire" non
vuol dire disinstallare: vuol dire disattivare l'entitlement + disfare quel provisioning,
senza mai toccare dati che il tenant ha già generato nel frattempo.

Il provisioning cambia per tipo di capacità:
- **Connettori** (Gmail, Calendar, Storage): entitlement + connessione OAuth. Disattivare =
  entitlement off + revoca token (non solo il flag, altrimenti resta un token valido
  silenzioso — vedi anche risposta su store connettori, stessa data).
- **Skill/tool aggiuntivi** (stateless): solo entitlement. Attivare/disattivare = un flag che
  il Safety Supervisor controlla prima di esporre quel tool nella sessione — nessun dato da
  gestire.
- **Automazioni** (es. "ogni lunedì fai X"): entitlement + un record di trigger/scheduling
  scoped al tenant, con i parametri configurati all'acquisto. Disattivare = entitlement off +
  disabilita il trigger, **senza cancellare lo storico** di cosa ha già eseguito.
- **Agenti personalizzati con pacchetto di conoscenza**: caso diverso dagli altri, perché il
  pacchetto contiene contenuto vero (documenti) da ingerire nella memoria del tenant
  (chunking/embedding, come `import_mail.py` già fa per le mail). Va taggato con un `pack_id`
  **fin dall'ingestione** — se non si tagga da subito, il retrofit dopo è costoso. Disattivare
  = entitlement off + cancellare solo le righe taggate con quel `pack_id`, mai il resto della
  memoria del tenant.

**Domanda aperta sollevata dall'utente (2026-07-14) — copia per tenant vs sorgente unica**:
se il contenuto di un pacchetto di conoscenza viene ingerito (copiato, chunked/embedded)
separatamente in ogni tenant che lo attiva, aggiornarlo (es. nuove regole fiscali) significa
rifare l'ingestione per ogni cliente che lo ha attivo — un fan-out manuale ogni volta che il
pacchetto cambia. L'alternativa è una sorgente unica condivisa (embeddings del pacchetto non
duplicati per tenant), interrogata insieme alla memoria propria del tenant al momento della
ricerca — ma questo richiede che `match_chunks` (oggi scoped solo a `tenant_id`, vedi
`memoria/db.py`) sappia unire risultati da una fonte condivisa e da una tenant-scoped, e che
il gating "quali pacchetti condivisi questo tenant può vedere" passi comunque dall'entitlement
sopra. Non è deciso quale delle due — da valutare quando si costruisce davvero il primo
pacchetto di conoscenza reale, non in isolamento ora.

Il Safety Supervisor resta il punto unico che controlla anche "questo tenant ha questa
capacità attiva", come criterio in più nella stessa policy dichiarativa (non un meccanismo
di gating parallelo).

**Perché annotarla ora senza costruirla**: il costo di aggiungere il gating dopo è basso se
un dettaglio viene rispettato fin da subito — taggare con un identificatore di provenienza
(`pack_id` o equivalente) qualunque dato scoped-al-tenant che un domani potrebbe dover essere
rimosso selettivamente (pacchetti di conoscenza in primis). Rimandare la costruzione del
gating stesso (tabella entitlement, UI Store, billing) resta corretto — non c'è ancora un
secondo tenant reale — ma il tagging dei dati va tenuto a mente modulo per modulo perché
riguarda lo schema, non la sovrastruttura.

**Da NON fare ora**: costruire tabelle entitlement, UI Store o logica di gating — nessun
cliente reale la richiede ancora e non è prevista prima di Tappa 9 (Billing)/Tappa 10.
Prerequisiti concettualmente simili a "Eidos Mail" sopra: billing/gating per piano non
progettato, e serve prima aver validato lo scheletro con un solo utente.

**Prossimo passo quando arriva il momento**: portare la decisione a `saas-architect` (è
decisione di mappa/architettura del modulo Store, non un dettaglio interno a un modulo
esistente).

## Distribuzione di Agente Locale a un cliente reale non tecnico

**Emersa**: 2026-07-15, testando manualmente `cli_locale.py` (Tappa 3, Ciclo B) per la prima
volta in locale - serviva installare/verificare il CLI Node.js di Claude Code sulla macchina,
gestire un login/credenziale Anthropic, creare un `.env` a mano. Ragionevole per il founder che
sta validando lo scheletro, non lo è per un cliente PMI/freelance (vedi PROJECT.md, pubblico non
tecnico) - vedi anche DECISIONS.md 2026-07-15, "Autenticazione Anthropic per i clienti: solo API
key di Eidos, mai l'abbonamento personale del cliente", che stabilisce che i clienti useranno
un'`ANTHROPIC_API_KEY` di Eidos, non le proprie credenziali.

**Domanda aperta, non risolta**: come deve funzionare per un cliente reale, che non deve:
- installare Node.js/il CLI Claude Code a mano
- gestire un file `.env` con segreti
- capire cosa sia un "sottoprocesso CLI" o un abbonamento/API key Anthropic

Serve un modo per consegnare in modo sicuro l'esecuzione locale (perimetro sul suo PC + una
`ANTHROPIC_API_KEY` di Eidos, mai esposta in chiaro al cliente) - possibili strade da valutare
quando si arriva qui (nessuna scelta fatta): un installer/pacchetto che porta tutto con sé, un
processo locale leggero che ottiene un token temporaneo dal backend Eidos dopo login (invece di
un `.env` statico), o altro. Riguarda anche se/come intercetta il requisito "sessione isolata
dalla macchina ospite" già in ROADMAP.md Tappa 3.

**Perché annotarla ora senza risolverla**: Tappa 3 è deliberatamente single-user/founder, senza
preoccupazioni di distribuzione (walking skeleton, vedi CLAUDE.md) - corretto non risolverlo ora.
Ma è esattamente il tipo di blocker scoperto tardi che ha affossato Eidos v1 se non lo si scrive
da nessuna parte: va ripreso quando si progetta l'onboarding self-service di un cliente reale
(Tappa 8) o comunque prima di offrire Agente Locale a chiunque non sia il founder.

**Da NON fare ora**: costruire un installer o un meccanismo di provisioning credenziali - nessun
secondo utente reale lo richiede ancora.

**Prossimo passo quando arriva il momento**: da valutare con `saas-architect` se tocca la mappa
(es. serve un nuovo componente "distribuzione/installer") o resta un dettaglio di
implementazione di Agente Locale da affrontare con `saas-module-builder`.
