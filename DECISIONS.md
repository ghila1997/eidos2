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
