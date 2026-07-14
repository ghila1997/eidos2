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
