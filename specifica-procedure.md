# Spec — Procedure di Eidos: Assistenze, Automazioni, Attese, Risorse

> Versione ottimizzata, ricavata dalla discussione di design (2026-07-28) a partire dalla
> bozza `specifica-automa.md`. Definisce i quattro oggetti che l'utente crea/usa, chi può
> crearli, come girano e dove si implementano.
>
> **Stato: proposta di design.** Non è ancora integrata nei documenti di governo
> (ROADMAP/DECISIONS/PROJECT): quel passaggio è una sessione `saas-architect`, perché cambia
> la mappa del progetto (ridefinisce la Tappa 10). Vedi §11.

---

## 0. I due principi che reggono tutto

1. **Cosa è un'Automazione**: *scrivere fuori senza che nessuno guardi = Automazione.* Basta un
   trigger **oppure** una scrittura esterna perché una procedura sia un'Automazione, non
   un'Assistenza.
2. **Chi può creare cosa lo decide il rischio, non l'oggetto.** L'errore da evitare non è "far
   creare al cliente" in assoluto: è far generare da zero, a un non tecnico, procedure che
   scrivono fuori senza presidio. La creazione libera si apre dove il raggio d'azione di un
   errore è piccolo, e si chiude dove è grande — vedi §4.2.

---

## 1. I quattro oggetti

| | **Assistenza** | **Automazione** | **Attesa** | **Risorsa** |
|---|---|---|---|---|
| Cos'è | Procedura guidata | Procedura autonoma ricorrente | Procedura effimera | Materiale riutilizzabile |
| Chi la avvia | L'utente, esplicitamente | Un trigger | Un evento singolo | Nessuno, viene usata |
| Chi decide i passi | Il modello | Il file (YAML) | Il file | — |
| Umano presente | Sempre | No (salvo approvazioni) | No | — |
| Scritture esterne | **Mai** (solo azione singola confermata) | Sì, dichiarate | No (di norma) | Mai |
| Motore | Agentico (Agent SDK) | Deterministico (esecutore) | Deterministico | — |
| Ciclo di vita | Permanente | Permanente | One-shot con scadenza | Permanente |
| Dove sta in UI | Catalogo | Catalogo | Lista "In attesa" | Libreria |

---

## 2. Assistenza

Procedura che l'utente lancia e **supervisiona**. Descrive *come affrontare* un tipo di lavoro,
non i passi esatti: il modello mantiene la libertà di scegliere il percorso perché c'è un umano
che vede ogni passaggio e può correggere.

**Esempi:** "fammi il report della settimana", "analizza questa polizza", "cerca nei documenti
del cliente X tutto sul contenzioso".

### Confine read-only — decisione vincolante
L'Assistenza **non ha accesso ai connettori in scrittura**. Non è una regola nel prompt: **è il
motore che non glieli espone.** Quando un'Assistenza gira, il motore riceve il **solo set di
tool di sola lettura** + le Risorse referenziate.

Questo confine è ciò che regge lo *zero attrito in creazione* (§sotto): puoi permetterti niente
gate solo perché l'oggetto non può causare danni irreversibili. Se lo violi (tool di scrittura
esposti a un'Assistenza) devi mettere il gate pesante delle Automazioni — quindi non violarlo.

### Azione singola supervisionata
Se durante l'Assistenza l'utente chiede di inviare/salvare qualcosa, il sistema **non** dà il
tool di scrittura al modello: propone l'**azione singola** (destinatario + contenuto) con
conferma esplicita via **Safety Supervisor** (`ask_user`). La conferma è dell'utente
sull'istanza specifica, non un'autorizzazione permanente alla procedura.

### Formato
Markdown non strutturato (istruzione per il modello) + frontmatter.

```markdown
---
id: analisi_polizza
nome: "Analisi di una polizza"
risorse: [glossario_assicurativo, tono_aziendale]
connettori_lettura: [drive, crm]
---
# Analisi di una polizza
1. Identifica tipo, contraente, decorrenza, massimali
2. Elenca coperture ed esclusioni in linguaggio semplice
3. Segnala clausole insolite o penalizzanti
4. Se un dato non è leggibile, dillo — non dedurlo
Non valutare la convenienza economica. Non calcolare premi.
```

### Creazione
Zero attrito. L'utente descrive a parole, il sistema genera il markdown, l'utente rilegge e
salva. Nessun test, nessuna approvazione, nessuna verifica permessi oltre quelli che l'utente
già possiede. Chi crea: **chiunque** (founder o cliente), perché non può scrivere fuori.

### Il valore è nel contorno, non nel markdown
Un markdown di istruzioni è banale. Il valore dell'Assistenza vive in tre cose, che fanno parte
della stessa costruzione, non "dopo":
- **Catalogo/scoperta** — "cosa può fare Eidos per me" (serve UI, vedi §11).
- **Riuso delle Risorse** — il template del report non duplicato (§3).
- **Scope di lettura effettivi** — questa Assistenza vede CRM+Drive e nient'altro.

Senza queste tre, un'Assistenza è un prompt salvato con un nome.

### Igiene (non dimenticarla)
A differenza delle Attese, le Assistenze sono permanenti: il catalogo si riempie di varianti di
"fammi il report" che divergono. Prevedere dedup/merge o almeno una revisione periodica. Minore,
ma da mettere a piano.

---

## 3. Risorsa

Materiale riutilizzabile. Non viene eseguito, viene **usato** da Assistenze e Automazioni,
referenziato **per id** (mai copiato: un posto solo da aggiornare).

| Tipo | Esempio |
|---|---|
| Template di output | Layout report, formato lettera, struttura pratica |
| Identità visiva | Colori, font, logo |
| Conoscenza di dominio | Glossario, procedure interne, normativa |
| Tono e stile | Come si scrive ai clienti in questa azienda |
| Regole | Cosa non dire mai, quando passare a un umano |

**Creazione:** libera, nessun gate — caricare un template non tocca sistemi né invia niente.
**Eccezione:** le Risorse di tipo **Regole** che restringono la sicurezza si gestiscono come
**configurazione admin**, non come contenuto utente libero.

**Formato:** markdown (conoscenza, tono), JSON/YAML (template, identità visiva), file caricato
(resto). Versionate.

---

## 4. Automazione

Procedura che parte da un trigger ed esegue **passi fissi** definiti nel file, non decisi dal
modello. Il modello viene chiamato **solo dentro i singoli passi** `ai`, per i compiti che
richiedono giudizio.

**È un'Automazione se** ha un trigger (orario/evento/webhook) **oppure** scrive verso l'esterno.

### 4.1 Livelli di rischio (calcolati, non scelti dall'utente)

| Livello | Condizione | Requisiti in creazione |
|---|---|---|
| **L1 — Notifica** | Legge + notifica interna | Conferma |
| **L2 — Scrittura interna** | Scrive solo dentro Eidos (crea documenti, archivia) | Conferma + riepilogo effetti |
| **L3 — Scrittura esterna** | Invia mail, scrive su CRM/file | Approvazione + **dry-run su dati reali senza effetti** + verifica permessi |
| **L4 — Irreversibile/massivo** | Cancellazioni, invii a molti, movimenti contabili | Tutto L3 + approvazione admin + tetto di esecuzioni |

Il livello lo calcola il sistema dal blocco `effects`. `effects` è derivato dai **connettori
dichiarati nei passi** (statico, al salvataggio) — non da uno scan semantico. Guardia: un passo
che sceglie un connettore in modo dinamico **deve dichiarare esplicitamente il proprio inviluppo
di effetti**, così `effects` non è mai sotto-dichiarato (vedi §Errori da evitare).

### 4.2 Chi può creare — split per rischio (l'ottimizzazione centrale)

La scala di rischio decide anche **chi può creare da zero**, non solo il gate:

- **L1 e Attese → il cliente crea liberamente a voce.** Nessuna scrittura esterna: un errore
  manda solo una notifica inutile, raggio d'azione minimo, autocorreggibile. Qui l'autoring
  vocale aperto è sicuro **e** è dove sta il "wow" del prodotto.
- **L3 → il cliente NON genera da zero: configura un template che hai scritto e testato tu.**
  Il cliente sceglie "Sollecito pagamenti" e fornisce i **parametri** (quali clienti, dopo
  quanti giorni, che tono), a loro volta validabili. Lo scheletro pericoloso è pre-testato. La
  voce resta l'interfaccia: *configura*, non *inventa*.
- **L4 → solo admin/founder.**

**Il loop concierge (copre la coda lunga senza aprire l'autoring libero delle scritture):**
la richiesta idiosincratica ("quando arriva una fattura da X, archiviala in cartella Y e
aggiorna il foglio Z") non si risolve dando al cliente la creazione libera di scritture. Il
cliente **la richiede** → tu la scrivi e la testi → diventa **un nuovo template del catalogo**.
Il catalogo compone dalla domanda reale. È il "scrivi 10 procedure reali prima" reso permanente.

> **Nota di prodotto.** Non costruire l'autoring vocale libero delle Automazioni-scrittura come
> feature di punta: alto rischio, alto supporto, e la domanda che coprirebbe è piccola e la
> copri meglio col loop concierge. La domanda reale delle PMI è concentrata (~20-30 automazioni
> coprono il 90%): un buon catalogo parametrizzabile batte la generazione libera.

### 4.3 Formato (rappresentazione interna — il cliente non la vede mai)

```yaml
id: report_vendite_giornaliero
version: 1.0.0
nome: "Report vendite giornaliero"
trigger: { type: schedule, cron: "0 9 * * 1-5", timezone: Europe/Rome }
effects:
  reads:  [gestionale.vendite]
  writes: [email.send]
  risk_level: L3            # calcolato dai connettori dei passi, non dall'utente
steps:
  - id: dati
    type: connector
    connector: gestionale.vendite
    input: { periodo: ieri }
    on_empty: → stop_silenzioso
    on_error: → notifica_errore
  - id: commento
    type: ai
    prompt: "Commenta l'andamento in massimo 3 righe"
    input: "{{dati}}"
    output_schema: { testo: string }
    on_uncertain: → salta
  - id: invio
    type: connector
    connector: email.send
    to: "{{owner.email}}"
    body: ["{{commento.testo}}"]
    idempotency_key: "report-{{date}}"
```

**Regole del formato (obbligatorie):**
1. Lista piatta di passi con id espliciti. Niente annidamento (renderizzabile come sequenza
   leggibile da un non tecnico).
2. Tipi di passo chiusi: `connector`, `ai`, `render`, `logic`, `human`. Aggiungerne uno è una
   decisione di piattaforma.
3. Ogni passo `ai` dichiara `output_schema`. Output non conforme → il passo **fallisce**, non
   propaga dati sbagliati. È ciò che rende il flusso davvero deterministico.
4. Ogni passo dichiara i percorsi d'errore (`on_error`/`on_empty`/`on_uncertain`). Il validatore
   rifiuta chi non li ha.
5. `effects` in testa (§4.1).
6. Idempotenza su ogni scrittura esterna (i workflow ripartono: retry, crash, doppio trigger).
7. Niente cicli in v1. Solo sequenza e ramificazione; al massimo `for_each` con tetto dichiarato.

### 4.4 Flusso di creazione + rete di sicurezza universale

1. Descrizione (a voce o testo) → il sistema rileva trigger/scrittura → percorso Automazione.
2. Intervista solo sul non deducibile (quale mittente, quale destinatario).
3. **Riepilogo in linguaggio naturale** con la **riga degli effetti** sempre visibile.
4. Se L3+: scelta del punto di approvazione umana.
5. Se L3+: **dry-run su dati reali senza effetti**.
6. Verifica permessi dell'utente sulle risorse toccate.
7. Validazione contro i limiti d'uso del verticale (compliance).
8. Attivazione. **Nessuna L3+ si attiva senza un dry-run riuscito.**

**Rete di sicurezza, chiunque abbia creato** (founder, cliente-configuratore, template): prima
che una scrittura vada live → **riepilogo NL + riga effetti + dry-run + approvazione**. Il
dry-run è ciò che becca l'automazione *ben formata ma sbagliata* (destinatario giusto di formato
ma persona sbagliata; commento ben formato ma semanticamente falso): il determinismo garantisce
che giri sempre uguale, **non** che sia corretta — la correttezza la verifica il dry-run.

### 4.5 Motore (esecutore deterministico)

Non è l'Agent SDK. Legge YAML, esegue i passi in ordine, gestisce stato/retry/timeout/
idempotenza, e chiama il modello **solo** nei passi `ai` (via Messages API — la stessa già usata
da `classification.py`/`chiusura_impegni.py`, non un secondo motore *agentico*: l'unico motore
agentico resta l'Agent SDK per le Assistenze).

**Requisiti:**
- Stato persistente per esecuzione (riprendibile dopo crash).
- Timeout per passo e per esecuzione.
- Retry con backoff sui passi `connector`.
- Tetto di costo e di esecuzioni per automazione.
- Log per passo, visibile all'utente.
- Sospensione automatica dopo N fallimenti consecutivi.

### 4.6 Sicurezza, permessi, versioni

**Un solo punto di autorizzazione — il Safety Supervisor.** Nessun percorso parallelo:
- **Al salvataggio**: `effects` contro permessi utente + limiti `compliance/verticali/<settore>.md`.
- **A runtime**: ogni chiamata a connettore passa dal Supervisor (allow/deny/ask_user).

**Permessi:** una procedura non fa più di chi la esegue. Gira con le credenziali di un **owner**
esplicito, mai "di sistema". Owner perde l'accesso → l'automazione si **sospende**, non fallisce
in silenzio. L4 richiede ruolo admin.

**Versioni:** versione fissata. Un aggiornamento non tocca le esecuzioni in corso; ogni
esecuzione conserva la versione con cui è partita. Mai aggiornamento automatico.

### 4.7 Osservabilità (non tecnica)
Per ogni esecuzione: timeline dei passi con esito · passo fallito evidenziato col motivo in
linguaggio naturale · cosa è stato scritto fuori e cosa no · rilancio dal punto di fallimento.
**Metrica:** se una procedura fallita genera un ticket verso di te, l'osservabilità non basta.

---

## 5. Attesa

Procedura **effimera**: vive per un singolo evento, poi si spegne. Tecnicamente un'Automazione
L1, ma con ciclo di vita e collocazione diversi.

**Esempi:** "avvisami quando arriva la mail da Giorgio", "ricordamelo giovedì", "avvisami se il
cliente non risponde entro 3 giorni".

**Le tre proprietà:** one-shot (scatta una volta, notifica, si disattiva) · scade (data di fine
di default) · anonima (nessun nome, non nel catalogo).

```yaml
lifecycle: one_shot
expires_at: +30d            # default, non chiesto
on_expire: notifica_e_archivia
```

- **Job di scadenza obbligatorio fin da subito** (o accumuli trigger zombie). Alla scadenza non
  sparisce in silenzio: *"Aspettavo una mail da Giorgio da 30 giorni, non è arrivata. Continuo o
  chiudo?"* — un tocco proroga, uno chiude.
- **Collocazione UI:** lista separata "In attesa", non nel catalogo delle Automazioni.
- **Distinzione da `impegni`** (lavoro già in corso in `chiusura_impegni.py` / `memoria_impegni`):
  l'impegno è un **fatto nella Memoria** (stato del business, rilevato passivamente all'ingest);
  l'Attesa è una **notifica programmata** creata esplicitamente, con scadenza. Non fonderli nello
  schema. Un'Attesa che deve **scrivere fuori** è un'Automazione **L3 `lifecycle: one_shot`** e
  passa dal percorso severo, scadenza inclusa.

---

## 6. Classificazione automatica

L'utente non sceglie una categoria tecnica: il sistema classifica da tre domande lette dalla
lingua.

1. Parte da sola? ("ogni", "quando", "appena")
2. Scrive fuori da Eidos? (invia/crea/modifica/cancella)
3. Ricorrente o una volta sola? ("ogni lunedì" → Automazione, ha un nome, entra nel catalogo;
   "quando arriva X", "ricordamelo giovedì" → Attesa, lista "In attesa", scade)

| | Lanciata dall'utente | Parte da sola |
|---|---|---|
| **Solo legge** | Assistenza | Automazione L1 / Attesa |
| **Scrive fuori** | Automazione L3 | Automazione L3+ |

- Ambiguità → default **Attesa** (reversibile, si prolunga con un tocco).
- Se durante un'Assistenza emerge una scrittura esterna: **non bloccare, converti.** *"Questa
  invia email → va creata come Automazione, ti porto lì, i passi che hai descritto li tengo."*

---

## 7. Modello dati

```
Tenant
 ├── Risorse       (id, tipo, versione, contenuto)
 ├── Assistenze    (id, markdown, risorse[], connettori_lettura[])
 └── Automazioni   (id, yaml, versione, stato, effects, risk_level,
                    ultima_esecuzione, fallimenti_consecutivi)
Esecuzioni         (automazione_id, stato, passo_corrente, log[], costo, idempotency_keys[])
```

- Tutto partizionato per tenant a livello di database.
- Assistenze/Automazioni referenziano le Risorse per id, non le copiano.
- Le Automazioni hanno versione fissata; le esecuzioni conservano il riferimento alla versione
  con cui sono partite.

---

## 8. Legame con la compliance

Il gate di creazione dell'Automazione è il punto in cui i documenti di compliance diventano
esecutivi: al salvataggio `effects` è validato contro i limiti in `compliance/verticali/<settore>.md`.
Se il verticale dichiara "non calcoliamo premi" e un'automazione lo fa, è **rifiutata al
salvataggio**. Le Assistenze non hanno questo gate (non producono effetti irreversibili), ma le
loro regole di dominio vivono nelle Risorse di tipo **Regole** (configurazione, non contenuto
libero). Da prevedere nei ToS: responsabilità delle procedure create dal cliente.

---

## 9. Terminologia

Verso l'utente: **Assistenze, Automazioni, Attese, Risorse** (o "Modelli"). Le Attese possono non
avere nome esposto ("cose che Eidos sta aspettando"). **Evita "skill"** verso l'utente: è
l'ibrido confuso di istruzione+risorsa, la principale fonte di confusione.

---

## 10. Errori da evitare

| Errore | Conseguenza |
|---|---|
| Far scegliere all'utente tra Assistenza e Automazione | Sceglie sempre la più facile, anche per cose che scrivono fuori |
| Dare i connettori in scrittura al motore agentico (Assistenza) | Perdi il controllo su ciò che il sistema fa da solo |
| Dedurre gli effetti scansionando i passi | Salta i connettori dinamici → `effects` sotto-dichiarato |
| Punto di approvazione solo alla fine | L'umano approva un errore ben scritto prodotto tre passi prima |
| Nessun percorso per i casi "non lo so" (`on_uncertain`) | È il 30% dei casi reali, non compare mai nei prototipi |
| Automazioni senza tetto di costo | Un loop mal fatto brucia il margine |
| Aggiornare in automatico le versioni | Il comportamento cambia sotto i piedi del cliente |
| Trattare le Attese come Automazioni permanenti | Catalogo pieno di procedure morte, trigger zombie |
| Attese senza scadenza | Restano attive per sempre e nessuno le spegne |
| Autoring vocale libero delle Automazioni-scrittura | Alto rischio + alto supporto per domanda piccola → usa i template + concierge |
| Costruire l'esecutore a vuoto | Motore che non regge i casi reali → validalo su ≥10 automazioni scritte a mano |

---

## 11. Dove si implementa (proposta — da formalizzare via `saas-architect`)

Ordine walking-skeleton. Ogni fase è eseguibile end-to-end prima della successiva.
**Vincolo duro: non invertire Fase C e Fase D.**

### Fase A — Assistenze + Risorse
- **Motore:** già esistente (Agent SDK). Nessun esecutore, nessun trigger.
- **Da costruire:** tabelle `Risorse` e `Assistenze` (§7); CRUD; creazione a zero attrito;
  **esecuzione con set di tool read-only** (scoping per Assistenza); azione singola supervisionata
  via Supervisor; risoluzione Risorse per id.
- **Valore cliente pieno** solo con catalogo (serve UI) e multi-tenant.
- **Collocazione ROADMAP:** lo scheletro (usabile da founder via CLI) può iniziare presto come
  estensione dell'Orchestratore; il **catalogo client-facing** dipende da **Tappa 7 (UI)** e
  **Tappa 8 (multi-tenant)**. Alimenta anche la Tappa 11 ("Skills pronte all'uso" → qui
  diventano Assistenze + Risorse reali).

### Fase B — Automazioni L1 + Attese
- **Da costruire:** scheduler + ricezione trigger su evento (riusa le connessioni dei Connettori
  Cloud; per Gmail `users.watch` + Pub/Sub, già individuato in ROADMAP Tappa 10); tabella
  `Esecuzioni`; notifiche interne; le Attese (tre campi lifecycle + lista UI separata + **job di
  scadenza**). Motore ancora agentico/leggero: nessuna scrittura esterna.
- **Chi crea:** cliente, liberamente a voce (§4.2).
- **Collocazione ROADMAP:** è la prima metà dell'attuale **Tappa 10 (Automazioni)**.

### Fase C — Automazioni L3 (esecutore deterministico)
- **Da costruire:** l'esecutore completo (§4.5); il formato YAML + validatore; `effects` +
  risk-level (§4.1); dry-run; punti di approvazione; idempotenza; aggancio al Safety Supervisor
  al salvataggio e a runtime (§4.6).
- **Gate di uscita dalla fase:** **tu** scrivi ≥10 Automazioni L3 reali a mano, le fai girare sul
  motore vero su dati veri, correggi finché non funzionano corrette e non presidiate. Sono quelle
  che dicono quali primitive servono davvero.
- **Collocazione ROADMAP:** è la seconda metà (il grosso) dell'attuale **Tappa 10**. Ridefinisce
  la Tappa 10 corrente, che oggi prevede automazioni *agentiche* con gate di conferma — design da
  superare, perché il gate `ask_user` richiede un umano che qui non c'è (vedi DECISIONS da
  scrivere).

### Fase D — Creazione dal cliente (voce)
- **Da costruire sopra un motore già provato:** lo strato **traduzione intento-vocale → spec
  corretta** e la **verifica per il cliente** (riepilogo NL + riga effetti + dry-run +
  approvazione). Per L3 il cliente **configura template** (§4.2), non genera da zero; loop
  concierge per la coda lunga.
- **Prerequisiti:** Fase C provata sui casi reali del founder **e** multi-tenant (**Tappa 8**).
- **Collocazione ROADMAP:** dopo la Tappa 10, come apertura al cliente reale (area Tappa 11-12).

### Decisioni da formalizzare in `DECISIONS.md` (via `saas-architect`)
1. Esecutore deterministico come **secondo layer di esecuzione** (non secondo motore agentico:
   l'Agent SDK resta unico per le Assistenze; gli step `ai` usano Messages API già in uso) —
   riconciliazione con la regola "un solo motore agentico".
2. `effects` derivato dai connettori dichiarati nei passi + guardia sui connettori dinamici.
3. Split di **autorship per rischio** (L1/Attese liberi; L3 template configurabili; L4 admin) +
   loop concierge — supera l'ipotesi "il cliente crea tutto a voce".
4. Confine read-only dell'Assistenza imposto via **tool-scoping**, non via prompt.
5. Superamento del design "automazioni agentiche con gate di conferma" dell'attuale Tappa 10.
