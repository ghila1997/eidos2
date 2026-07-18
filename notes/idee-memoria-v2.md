# Idee sulla memoria — valutazione del documento "Architettura di memoria per un assistente tipo Jarvis v2" (2026-07-19)

> Idee non ancora decise. Esito della valutazione rigorosa del documento esterno contro lo
> stato reale del modulo Memoria (Tappe 2–5.1). Verdetto complessivo: l'architettura
> implementata coincide già con la "scorciatoia pratica" che il documento stesso raccomanda
> (Postgres+pgvector, un solo motore, logiche di query separate, un punto di accesso unico);
> le voci sotto sono ciò che resta da decidere o da tenere in tasca. Le proposte respinte
> sono in fondo, con la motivazione, per non rivalutarle da capo alla prossima occasione.

## Adottato subito (fatto il 2026-07-19)

- **Eval di retrieval con verità nota** — `codice/memoria/eval/eval_retrieval.py`, 10
  scenari sui dati reali del tenant, registrato in `docs/eval.md`. Copre anche la trappola
  di Tappa 4 (fatto sepolto sotto chunk più simili) mai scriptata prima. È la risposta al
  punto più solido del documento: senza metriche, "ottimizzato" è un'opinione.

## Orientamento preso (2026-07-19) — da formalizzare nel ciclo modulo dopo la Tappa 6

- **Proposta di fatti in conversazione (`propose_fact`), con conferma via azione pending.**
  Il documento propone estrazione automatica dei fatti a fine sessione; contraddice
  DECISIONS.md 2026-07-15 ("scrittura sempre esplicita, mai automatica", motivata dal
  rischio di corrompere lo stato canonico upsert). Discusso col founder (2026-07-19),
  orientamento condiviso — non ancora una decisione formale (quella va presa a STOP 1
  del mini-ciclo, con nuova voce in DECISIONS.md che supera quella del 15/07):
  - **Forma**: niente batch "a fine sessione" — verificato (doc SDK 2026-07-19) che in un
    backend HTTP quel momento non esiste (l'hook `Stop` scatta a fine turno, non a fine
    conversazione; `SessionEnd` è solo TypeScript). Invece: il modello, quando sente in
    conversazione un fatto che vale la pena ricordare, chiama un tool `propose_fact` che
    crea un'**azione pending** col meccanismo esistente (`azioni.py`); l'utente conferma
    fuori dal controllo del modello, come per email/cancellazioni. Zero infrastruttura
    nuova; funziona uguale in voce (Tappa 6) e nella UI (Tappa 7, lista "memorie proposte").
  - **Rischio residuo**: frizione da proposte troppo frequenti — si governa con la
    description del tool e si misura con un eval gemello di `eval_retrieval`/`remember_fact`
    ("menzione banale → nessuna proposta").
  - **Quando**: dopo la chiusura della Tappa 6, in sessione dedicata (design in chat →
    STOP 1 → codice+test → STOP 2). Non si infila di lato nel lavoro voce in corso.

## Candidati a bisogno futuro (non ora — nessuna evidenza misurata che servano)

- **Garanzia ilike sui fatti estesa alle query multi-parola.** Misurato con
  `eval_retrieval` (2026-07-19): `find_fatti_ilike` matcha la query intera contro
  l'`entity_key` slugificata, quindi "Mario Rossi" (spazio) non attiva la garanzia — il
  fatto oggi arriva comunque via ranking semantico, ma è il percorso da cui la decisione
  2026-07-15 voleva essere indipendente. Fix piccolo (slugificare/tokenizzare la query),
  ma è codice di prodotto: al primo miss reale, via ciclo modulo.
- **Log degli errori di retrieval** (query, fonti interrogate, esito, fonte corretta):
  alimenta il test set nel tempo. Si integra naturalmente nell'osservabilità di Tappa 11
  (ROADMAP.md), non prima.
- **Indice lessicale ibrido (full-text/BM25) sui chunk.** Solo se gli eval mostrano miss
  sui nomi propri/codici. Evidenza attuale contraria: i nomi propri dentro sheet vengono
  recuperati dagli embedding (PASS a similarità 0.37, eval 2026-07-19). Postgres ha già
  il full-text nativo: costo contenuto quando servirà.
- **Bi-temporalità dei fatti** (`valid_from`/`valid_until`/`source_episode_id` su
  `memoria_fatti`): utile quando i fatti inizieranno a mutare/contraddirsi davvero. A
  differenza di `tenant_id` (retrofit costoso, messo subito), sono colonne nullable
  aggiungibili in un giorno: non si anticipa.
- **Classi di stabilità/decadimento dei fatti** (anagrafica ≈ permanente, stato ≈ giorni;
  fatti scaduti retrocessi a "da riverificare"): stessa logica — a bisogno, insieme alla
  bi-temporalità.
- **Suggerimento proattivo di automazioni da pattern osservati** ("ogni mattina chiedi
  meteo+notizie" → regola *proposta*, mai attivata in silenzio): è una feature del modulo
  Automazioni, da valutare quando si costruisce la Tappa 10.

## Respinto (con motivo — non rivalutare senza fatti nuovi)

- **Framework di memoria esterni (Mem0, Letta/MemGPT, Zep/Graphiti)**: il layer di memoria
  esiste già, validato con dati reali; aggiungerne uno significherebbe doppia pipeline di
  estrazione e doppia latenza (lo dice anche il documento: "mai due framework insieme").
  Contraddirebbe "un solo database Postgres" (DECISIONS.md 2026-07-13).
- **Knowledge graph temporale (Zep/Graphiti) per l'episodica**: nessun caso reale di
  conflitto temporale emerso in 4 tappe di uso vero; la bi-temporalità, se servirà, sono
  poche colonne su Postgres (vedi sopra).
- **Layer di orchestrazione del retrieval separato (router per fonte, fusion, re-ranker
  cross-encoder, livelli 0–3 espliciti)**: in un sistema agentico il router adattivo è il
  modello stesso (chiama `search_memoria` zero, una o N volte nel loop SDK, che ha già
  stop condition native). Un router per fonte reintrodurrebbe esattamente il rischio che
  la lettura unificata ha eliminato (DECISIONS.md 2026-07-15: con più tool di lettura
  sovrapposti il modello ne usa solo alcuni e perde informazione). Costruirlo ora sarebbe
  infrastruttura in isolamento senza caso reale — la classe di errore del reboot v1.
