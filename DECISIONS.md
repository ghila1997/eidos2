# Decisioni architetturali

> Log append-only: le voci non si modificano né si cancellano. Se una decisione
> viene superata, si aggiunge una nuova voce che la sostituisce e la linka.

---

## 2026-07-13 — Reboot completo del progetto precedente (Eidos v1)

**Contesto**: Eidos v1 (cartella separata `APP/EIDOS`) aveva tutti i 9 moduli segnati "Fatto",
373 test verdi, 24 ADR, integrazione end-to-end dichiarata completata — ma zero clienti reali,
e l'audit del 2026-07-12 ha trovato 3 blocker critici (sessione locale mai avviata, nessun
endpoint OAuth reale, nessun flusso di creazione grant) scoperti solo a quel punto perché ogni
modulo era stato costruito e validato in isolamento, senza mai collegarlo davvero al resto.

**Decisione**: ripartire da zero, codice compreso, in un nuovo progetto (Eidos 2.0). Delle 24
decisioni prese in Eidos v1, se ne salvano 16 come idee di partenza non vincolanti (vedi
`notes/idee-salvate-da-eidos-v1.md`), le altre 8 si riprogettano senza guardare alla vecchia
conclusione quando si arriva al tema.

**Alternative considerate**: completare i 3 blocker sul progetto esistente (scartata:
l'obiettivo era ripartire architetturalmente "sul pulito", non solo tappare i buchi residui);
riusare il codice esistente mantenendo solo le decisioni buone (scartata: l'utente ha scelto
il reboot totale del codice per evitare di trascinare debito nascosto).

**Conseguenze**: si perdono 373 test e codice funzionante; si riparte più lenti ma senza
ereditare in silenzio scelte che l'utente giudica in parte sbagliate.

---

## 2026-07-13 — Metodo di costruzione: walking skeleton, non moduli-a-canna-fumaria

**Contesto**: la causa radice dei 3 blocker finali di Eidos v1 era l'ordine di costruzione —
ogni modulo portato al 100% isolatamente, collegamento reale lasciato per ultimo.

**Decisione**: si costruisce prima il percorso più sottile ma vero end-to-end (interfaccia →
orchestratore minimo → un'azione reale → risposta), con un solo utente (il founder), senza
tenancy multi-utente/ruoli/dispositivi/billing. Si ispessisce un pezzo alla volta mantenendo
sempre il percorso eseguibile; la sovrastruttura SaaS multi-tenant arriva dopo (vedi
ROADMAP.md).

**Alternative considerate**: mappa a moduli più accorpata o diversa (scartata: il problema non
erano i confini dei moduli ma l'ordine/metodo di costruzione); pattern a capacità incrementali
senza moduli fissi (scartata: il progetto deve arrivare a un prodotto SaaS strutturato e
vendibile, serve più struttura di un accumulo libero di capacità).

**Conseguenze**: Fondamenta si costruisce prima nella sua versione minima single-user; il
multi-tenant/ruoli/dispositivi/billing arriva solo dopo che lo scheletro end-to-end funziona.

---

## 2026-07-13 — Multi-tenancy: shared schema + tenant_id da subito

**Contesto**: micro-SaaS con team di una persona, ma obiettivo dichiarato è un prodotto SaaS
multi-tenant vendibile a più clienti.

**Decisione**: shared schema Postgres con `tenant_id` su ogni tabella fin dall'inizio, anche
nella fase single-user (un solo tenant valorizzato), invece di introdurlo in un secondo
momento.

**Alternative considerate**: isolamento per-tenant (schema/DB separato per cliente) — scartata,
over-engineering prima di avere clienti; aggiungere `tenant_id` solo all'arrivo del secondo
cliente — scartata, retrofit costoso su dati e RLS già scritti.

**Conseguenze**: RLS Supabase applicabile fin da subito; nessuna migrazione dolorosa quando
arriva il secondo tenant.

---

## 2026-07-13 — Auth: Supabase Auth + RLS come piattaforma, flusso di sessione da riprogettare

**Contesto**: Eidos v1 aveva un ADR sul flusso di sessione Supabase Auth+RLS, esplicitamente
scartato dall'utente insieme ad altre 7 idee. Il progetto prevede fin dal setup iniziale
un'ingestione pesante di dati (file locali, mail) che deve rispettare l'isolamento tenant.

**Decisione**: si mantiene Supabase come piattaforma unificata (Auth + Postgres + pgvector +
Storage + RLS nello stesso posto), utile proprio per l'isolamento tenant sui dati ingeriti a
livello DB. Il *flusso* di sessione/login si riprogetta da zero quando si costruisce
Fondamenta, senza ereditare l'implementazione precedente.

**Alternative considerate**: provider auth separato (Auth0, Clerk) — scartato, avrebbe
richiesto orchestrare due sistemi (auth + DB) proprio nella fase più delicata per l'isolamento
tenant sui dati ingeriti.

**Conseguenze**: un solo servizio da configurare per dati e identità; il design del flusso di
sessione resta comunque lavoro pieno da fare in Fondamenta.

---

## 2026-07-13 — Billing: abbonamento flat + soglia di consumo come limite d'uso

**Contesto**: il prezzo a consumo puro (fatturazione per token) richiede integrazione di
metered billing complessa; l'obiettivo immediato è arrivare a un prodotto vendibile senza
costruire troppa infrastruttura di billing prima di avere clienti reali.

**Decisione**: piano in abbonamento flat (Stripe Checkout); il modulo Consumi traccia il
consumo interno per tenant e applica avvisi/blocco alla soglia inclusa nel piano (80%/100%),
non fatturazione per singolo token.

**Alternative considerate**: Stripe usage-based/metered billing — scartata per ora, troppa
complessità di integrazione per il primo cliente; rivalutabile quando servirà differenziare i
piani per consumo reale.

**Conseguenze**: Consumi resta un modulo di misura e limite, non di fatturazione dinamica; più
semplice da costruire e testare nella fase iniziale.

---

## 2026-07-13 — Memoria: un solo database, tre modi di ricordare, niente modulo RAG separato

**Contesto**: la prima bozza di roadmap teneva "Memoria" e "Documenti Aziendali (RAG)" come
due moduli separati, ricopiando il confine di Eidos v1 senza ridiscuterlo — la stessa capacità
(chunking + embedding + ricerca semantica) sarebbe stata costruita due volte. Inoltre un file
di lavoro che cresce nel tempo (preferenze, note su molti clienti/progetti) non scala se va
riletto per intero a ogni sessione.

**Decisione**: Memoria è un modulo unico, un solo database Postgres, con tre modi di ricordare:
(1) poche righe sempre caricate ad ogni sessione (preferenze minime, davvero piccole); (2)
tabelle strutturate interrogate su richiesta per entità (`entity_key`, upsert) — fatti su
clienti/progetti, popolate sia da ciò che l'agente impara in conversazione sia da estrazione
automatica dai documenti ingeriti; (3) ricerca semantica (pgvector) su email/documenti. I
documenti originali si archiviano come file (storage), non solo come testo estratto. È il
prodotto completo a richiedere l'estrazione strutturata dai documenti (non solo ricerca
semantica): va quindi predisposta nello schema fin dalla prima istanza (Tappa 2 di
ROADMAP.md), anche se l'estrazione per ogni tipo di documento si costruisce a mano a mano
(Tappa 5).

**Alternative considerate**: due moduli separati Memoria + Documenti RAG come in Eidos v1 —
scartata, confine artificiale sulla stessa capacità tecnica; file di lavoro monolitico letto
per intero ad ogni sessione — scartata, non scala oltre poche decine di KB; rimandare
l'estrazione strutturata a "quando serve" — scartata, l'utente la vuole nel prodotto completo
e va progettata ora per non rifare lo schema dopo.

**Conseguenze**: un solo modulo Memoria da progettare e costruire invece di due; la Tappa 2
della roadmap include già lo schema per fatti strutturati anche se resta perlopiù vuoto finché
non arriva la Tappa 5 (documenti); l'estrazione strutturata dai documenti richiede una
pipeline aggiuntiva (parsing/estrazione per tipo di documento) da progettare quando si
costruisce quella tappa.

---

## 2026-07-13 — Fondamenta: nuovo progetto Supabase pulito invece di riusare "EIDOS"

**Contesto**: costruendo Tappa 1 (Fondamenta), il progetto Supabase già collegato al progetto
("EIDOS", ref `nnnbtbmiaqkgylllwufw`, creato 2026-07-07) risultava avere 11 migration remote
già applicate — schema di Eidos v1 ancora presente nel database reale, nonostante il reboot
completo deciso lo stesso giorno riguardasse esplicitamente anche l'infrastruttura, non solo
il codice locale.

**Decisione**: creato un nuovo progetto Supabase pulito ("eidos2", ref
`ivuywauiqywlmxjxdppk`, regione eu-west-2) via Supabase CLI, schema applicato da zero
(migration `20260713153000_fondamenta_tenants.sql`: `tenants` + `tenant_members`). Il vecchio
progetto "EIDOS" resta intatto e non collegato — da archiviare/cancellare separatamente,
decisione lasciata all'utente. `.env` e `.mcp.json` aggiornati al nuovo progetto.

**Alternative considerate**: ripulire lo schema v1 sul progetto esistente (DROP + riapplica) —
scartata dall'utente, preferito isolamento netto senza rischio di residui; lasciare lo schema
v1 intatto e accodare Fondamenta sopra — scartata, avrebbe lasciato tabelle orfane nello stesso
DB e vanificato lo scopo del reboot "sul pulito".

**Conseguenze**: due progetti Supabase esistono nello stesso account nel breve periodo (quello
vecchio va gestito a parte, fuori da questo ciclo di costruzione); nessun dato/tabella di
Eidos v1 nel database che il prodotto usa davvero da qui in avanti.

---

## 2026-07-14 — Ambienti: nessuno staging per ora, un solo Supabase fino a Tappa 3

**Contesto**: un solo ramo (`main`) collegato a Railway, push su `main` = deploy diretto in
produzione (vedi docs/fondamenta/README.md); un solo progetto Supabase (`eidos2`), nessun
ambiente di test separato. L'utente ha chiesto come testare aggiornamenti futuri senza
toccare produzione.

**Decisione**: per ora si resta su un solo ambiente, coerente col metodo walking skeleton
(single-user, overhead minimo — vedi "Metodo di costruzione: walking skeleton" sopra). Il
codice si sviluppa e prova in locale prima del push; il push su `main` resta il gate verso
produzione (STOP 2 del ciclo modulo in CLAUDE.md già impone test manuale prima del commit).
Il database resta il progetto Supabase di produzione finché le azioni eseguibili restano a
basso rischio (Tappa 2, dati solo del founder). **Prima di iniziare Tappa 3 (Agente Locale) o
Tappa 4 (Connettori Cloud)** — dove l'agente inizia a eseguire azioni reali più rischiose su
file/calendario — va aperto un secondo progetto Supabase dedicato a sviluppo/test, con le
stesse migration applicate.

**Alternative considerate**: aprire subito un ambiente di staging separato (Railway + Supabase)
— scartata per ora, overhead prematuro con un solo utente e azioni ancora a basso rischio
(coerente col principio "la scelta più semplice che non chiude porte"); restare su un solo
ambiente per sempre — scartata, il rischio cresce con le azioni reali delle Tappe 3-4 e un
retrofit tardivo costerebbe di più.

**Conseguenze**: nessun lavoro extra ora; da Tappa 3 in poi la roadmap include l'apertura di un
secondo progetto Supabase come prerequisito, non più rimandabile a piacere.

---

## 2026-07-14 — Deploy: Dockerfile esplicito invece di Nixpacks (richiesto dal Claude Agent SDK)

**Contesto**: costruendo Tappa 2 (Orchestratore), il primo test reale di `/chat` falliva con un
errore vago ("bug di formato nella risposta del server MCP") nonostante la logica dei tool
custom, verificata in isolamento in locale con dati reali, funzionasse correttamente. Verifica
con `claude-code-guide` sulla documentazione ufficiale: il Claude Agent SDK Python richiede il
CLI Node.js di Claude Code (`@anthropic-ai/claude-code`) come sottoprocesso runtime — `query()`
e `ClaudeSDKClient` lo lanciano ed è tramite quel sottoprocesso che i tool custom vengono
davvero eseguiti. Il build Railway (Nixpacks, rilevamento automatico Python via
`requirements.txt`) non installava Node.js/npm né quel CLI: causa esatta del fallimento.

**Decisione**: sostituito Nixpacks con un `Dockerfile` esplicito alla root del repo
(`railway.json` aggiornato con `"builder": "DOCKERFILE"`). Il Dockerfile installa Node.js+npm
via apt, poi `@anthropic-ai/claude-code` via npm, poi le dipendenze Python da
`codice/requirements.txt`, copia `.claude/skills/` dentro `codice/.claude/` (stessa working
directory da cui gira `uvicorn`, per la scoperta skill via `setting_sources` - evita di
affidarsi al rilevamento della root del repo via `.git`, assente nell'immagine). Root
`requirements.txt` (esisteva solo per il rilevamento Python di Nixpacks) rimosso.

**Alternative considerate**: mantenere Nixpacks aggiungendo un `nixpacks.toml` con pacchetto Nix
`nodejs` e comando `npm install -g` in fase di install — scartata, più fragile e meno
esplicita/debuggabile di un Dockerfile per un requisito runtime permanente (non temporaneo) del
motore agentico; cercare un modo per evitare del tutto il sottoprocesso Node.js — scartata, è
un requisito documentato e non aggirabile dell'SDK stesso.

**Conseguenze**: build leggermente più lenta (immagine Docker con Node.js+Python invece di
Nixpacks auto-ottimizzato); ogni futura modifica alla struttura di `codice/` o `.claude/` va
riflessa anche nei path `COPY` del Dockerfile, non più automatica come con Nixpacks.

---

## 2026-07-14 — Connettori: criterio di completezza "cosa fa un umano", non "tutta l'API"

**Contesto**: costruendo il connettore Gmail (Tappa 2), la prima versione copriva solo
cerca/bozza/invia - scelto in base ai soli requisiti del design, senza prima aver guardato
tutta la superficie dell'API Gmail. L'utente ha fatto notare che un connettore collegato a metà
rischia di far dire a un cliente reale "manca proprio QUESTO", e che l'obiettivo è dare
all'agente "tutte le dita di una mano", non solo alcune.

**Decisione**: prima di scegliere le capacità di un connettore, si fa sempre una rassegna
sistematica della superficie API completa (regola aggiunta in CLAUDE.md, "Completezza dei
connettori"). Il criterio di "completo" non è l'enumerazione tecnica dell'API (scartato:
include amministrazione account - S/MIME, delegati, vacation responder - che nessun cliente
PMI chiede in chat) ma "tutto quello che un essere umano fa normalmente" con quella capacità.
Per Gmail (Tappa 2) questo ha aggiunto: rispondere restando nel thread giusto (In-Reply-To/
References/threadId), inoltrare con allegati originali, segnare letta/non letta/archiviata/
importante, organizzare in etichette (creandole se mancano), leggere allegati, cestinare
(sposta nel cestino - l'eliminazione permanente richiederebbe lo scope sensibile
`https://mail.google.com/`, deliberatamente escluso), inviare una bozza già creata, CC/BCC nel
compose. Scope OAuth aggiornati da `gmail.readonly`+`gmail.send` a `gmail.modify`+
`gmail.labels` (copre tutto il sopra tranne l'eliminazione permanente).

**Distinzione azioni immediate vs con gate di conferma**: segnare letta/archiviare/etichettare
sono reversibili e a basso rischio, eseguono subito senza conferma. Rispondere/inoltrare/
inviare una bozza/cestinare sono trattate come `send_email`: creano un'azione in attesa,
eseguite solo dall'endpoint di conferma separato (mai dal modello) - vedi voce precedente sul
gate di conferma fuori dal controllo del modello.

**Alternative considerate**: implementare tutta la superficie API Gmail letteralmente, incluse
le impostazioni account - scartata, lavoro speso su capacità che nessun cliente PMI userà mai
tramite un assistente in chat, in tensione diretta col metodo walking skeleton; lasciare il
connettore limitato a cerca/bozza/invia e aggiungere il resto "quando serve" senza una rassegna
sistematica - scartata, rischia di far scoprire i buchi da un cliente pagante invece che da
una rassegna fatta a mente lucida.

**Conseguenze**: l'utente già collegato (il founder) deve ridare il consenso OAuth per il nuovo
scope (una volta, pre-lancio, nessun cliente reale coinvolto ancora); ogni prossimo connettore
(Tappa 4: Calendar, Storage) segue la stessa regola prima di scrivere codice.

---

## 2026-07-14 — Idea di prodotto "Eidos Mail" annotata, non costruita ora

**Contesto**: valutando la completezza del connettore Gmail, l'utente ha proposto un'idea di
prodotto: un piano/tier più economico dello stesso Eidos, senza agente conversazionale, solo
classificazione/organizzazione automatica della mail (riusa `classification.py` +
`organize_email`/`mark_email` già costruiti) - pensato per clienti che non vogliono
l'assistente completo.

**Decisione**: idea salvata in `notes/idee-prodotto-eidos2.md`, non costruita ora. Richiede
comunque Tappa 10 (trigger automatico, non on-demand) e Tappa 9 (gating per piano/tenant) prima
di essere fattibile, e va decisa formalmente con `saas-architect` quando arriva il momento
(è una decisione di mappa/pricing, non un dettaglio di modulo).

**Alternative considerate**: costruirla ora in parallelo a Tappa 2 - scartata, biforca
l'attenzione prima di aver validato lo scheletro base con l'unico utente reale attuale (il
founder), lo stesso errore metodologico che ha causato il reboot da Eidos v1; costruirla come
prodotto/codebase separato invece che come tier dello stesso Eidos - sconsigliata quando se ne
riparlerà (duplica onboarding/fatturazione/manutenzione), ma decisione non ancora presa.

**Conseguenze**: nessuna ora. Da riprendere quando Tappa 9/10 sono pronte e l'ipotesi di
segmento cliente è validata con conversazioni reali, non solo ipotizzata.

---

## 2026-07-14 — Verifica reale di `reply_email`: threading corretto lato destinatario

**Contesto**: test end-to-end reale (non mockato) di `reply_email` con mail vere. Un primo test
mittente=destinatario (`ghila97@gmail.com` verso se stesso) mostrava le due mail come righe
separate nonostante `threadId`/`In-Reply-To`/`References` risultassero corretti via API -
riconducibile a un comportamento noto di Gmail quando mittente e destinatario coincidono
(mittente e destinatario possono vedere thread diversi per lo stesso invio). Ripetuto con un
destinatario reale diverso (`riccardoghilardotti@gmail.com`).

**Risultato**: dal lato di chi riceve la risposta, il messaggio appare correttamente raggruppato
nello stesso thread dell'originale - il meccanismo (`threadId` + `In-Reply-To`/`References` +
oggetto, vedi `gmail_client.rispondi_messaggio`) funziona per l'uso reale (l'agente risponde a
un vero cliente/fornitore, è la loro casella quella che conta). Dal lato mittente
(`ghila97@gmail.com`, cartella Inviata) i due messaggi restano visivamente separati - stranezza
nota e diffusa della vista "Inviata" di Gmail (raggruppa le conversazioni in modo meno
affidabile della vista "Posta in arrivo"), non riconducibile al nostro codice.

**Decisione**: capacità considerata verificata e funzionante. La discrepanza sulla vista
"Inviata" del mittente si documenta come limite noto di Gmail stesso, non un difetto da
inseguire ulteriormente.

**Conseguenze**: nessuna azione di codice necessaria. Se un cliente futuro segnala "le mie
risposte non si vedono raggruppate nella cartella Inviata", si spiega come comportamento noto
di Gmail (vista Inviata), non un bug di Eidos.

---

## 2026-07-14 — Playbook riutilizzabili: si estraggono da un'implementazione reale, non a priori

**Contesto**: costruito il connettore Gmail (Tappa 2), l'utente ha chiesto di fissare le
linee guida seguite (completezza, gate di conferma, test, verifica reale, cursori
incrementali) in un documento, in modo che tra qualche mese un nuovo connettore (Calendar,
Storage — Tappa 4) segua lo stesso standard invece di reinventarlo o abbassare il livello.
Stessa esigenza si riproporrà per altre categorie di lavoro che si ripeteranno nel progetto.

**Decisione**: primo playbook creato in [playbook/connettori.md](playbook/connettori.md),
cartella dedicata `playbook/` (non `docs/`, che resta per le specifiche di modulo), distillato
da com'è stato costruito davvero Gmail (struttura codice, gate di conferma, sync incrementale,
pattern di test, cosa documentare) - non da teoria scritta a priori. Regola generale: quando
una categoria di lavoro si ripeterà **e un prossimo caso è già previsto**, si estrae un
playbook concreto in `playbook/<tema>.md` subito dopo la prima implementazione reale, non
prima e non per speculazione. I principi ("perché") restano in CLAUDE.md, che linka il
playbook; il playbook è il "come, concretamente", è vivo (si aggiorna quando un caso reale lo
smentisce) e le discrepanze si segnalano all'utente invece di forzare la conformità in
silenzio - criteri completi in CLAUDE.md, sezione "Playbook operativi".

**Alternative considerate**: scrivere playbook teorici in anticipo per ogni categoria
prevista - scartata, rischio di codificare principi mai verificati contro un caso reale
(stesso errore metodologico che ha causato il reboot di Eidos v1: costruire/decidere in
isolamento senza validazione reale); mettere la checklist operativa dentro CLAUDE.md invece di
un documento dedicato - scartata, CLAUDE.md deve restare la lettura d'apertura di ogni sessione
con le regole dure di progetto, non accumulare checklist operative per singola categoria di
lavoro.

**Conseguenze**: CLAUDE.md e PROJECT.md linkano il nuovo file invece di duplicarne il
contenuto; ogni prossimo connettore (Calendar/Storage, Tappa 4) parte da questo playbook;
quando emergerà un'altra categoria di lavoro ricorrente (es. subagent, automazioni) si
estrarrà un playbook analogo dopo la prima implementazione reale di quella categoria, non
prima.
