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

---

## 2026-07-14 — Ambienti: supera la voce precedente — niente secondo Supabase prima di Tappa 8

**Contesto**: la voce precedente ("Ambienti: nessuno staging per ora, un solo Supabase fino a
Tappa 3") imponeva l'apertura di un secondo progetto Supabase dedicato a sviluppo/test prima di
iniziare Tappa 3, per proteggere i dati reali del founder in uso permanente. Alla vigilia di
Tappa 3 sono emersi due fatti che ne cambiano la premessa: (1) vincolo di piano — l'utente ha
già 2 progetti Supabase sul piano gratuito (il vecchio "EIDOS" v1, ref
`nnnbtbmiaqkgylllwufw`, mai cancellato nonostante fosse già segnato "da archiviare" il
2026-07-13, e "eidos2", ref `ivuywauiqywlmxjxdppk`, quello attivo) e non può aprirne un terzo
gratis prima di avere ricavi; (2) natura dei dati — l'utente ha chiarito che considera i dati
attuali in `eidos2` (mail importate, memoria) materiale di costruzione/test, non uso
quotidiano reale da proteggere: prevede di creare un account pulito quando lancerà davvero il
prodotto. Questo toglie la base alla premessa originale ("proteggere l'unico uso reale del
founder").

**Decisione**: si resta su un solo progetto Supabase (`eidos2`) anche per Tappa 3 e oltre,
finché non si verifica una di queste due condizioni: il founder inizia a usare `eidos2` come
assistente reale quotidiano (non più solo materiale di test), oppure si arriva a Tappa 8
(primo cliente reale, dove comunque serve infrastruttura multi-tenant più solida). Mitigazione
a costo zero per le sessioni di test più rischiose (Tappa 3: azioni su file/cartelle reali che
possono scrivere fatti/audit log): backup manuale (`pg_dump`) di `eidos2` prima della sessione,
invece di un ambiente separato permanente.

**Alternative considerate**: cancellare il vecchio progetto "EIDOS" v1 per liberare uno slot
gratuito e aprire comunque un secondo Supabase dedicato a dev/test — scartata per ora: avrebbe
comunque prodotto un ambiente "dev" trattato come test, la stessa natura dei dati attuali in
`eidos2`, quindi 15 minuti spesi senza un rischio reale da mitigare. Restare per sempre su un
solo Supabase anche dopo Tappa 8 — scartata, il rischio cambia natura quando entrano dati di
clienti reali non-founder.

**Conseguenze**: ROADMAP.md, prerequisito di Tappa 3, aggiornato per rimuovere l'apertura del
secondo Supabase come blocco. Il vecchio progetto "EIDOS" v1 resta comunque candidato a
cancellazione a costo zero (libera uno slot per quando servirà, es. se l'uso di `eidos2`
diventa reale prima di Tappa 8), ma non è più legato a nessuna tappa: azione facoltativa
dell'utente, non un prerequisito di roadmap.

---

## 2026-07-14 — Autorizzazioni: niente modulo "Autorizzazioni" separato, resta dentro Orchestratore

**Contesto**: preparando il design di Tappa 3 (Agente Locale), è emerso che il filesystem
locale — a differenza dei connettori cloud (Gmail oggi, Calendar/Storage in Tappa 4), dove
l'autorizzazione alla lettura è già data una volta per tutte dal consenso OAuth — non ha un
provider esterno che faccia da guardiano: senza un perimetro esplicito, un agente locale
vedrebbe di default tutto ciò che vede l'utente del PC, non solo cartelle di lavoro. Si è
valutato se questo giustificasse un nuovo modulo di piattaforma dedicato ("Autorizzazioni":
credenziali esterne, gate di conferma azioni distruttive, perimetri di accesso locali).

**Decisione**: nessun nuovo modulo/cartella. Il meccanismo di gate delle azioni distruttive
(`codice/orchestratore/azioni.py`, dispatch generico per `tipo`, già usato da Gmail) e la
storage delle credenziali (`codice/orchestratore/oauth.py`, già generica per `tenant_id`+
`provider`) restano dentro Orchestratore, che per CLAUDE.md ("un solo motore agentico") è già
per design il substrato condiviso a cui ogni capacità si aggancia come tool — non un modulo di
dominio come un altro da cui l'Agente Locale dovrebbe tenersi separato. L'Agente Locale (Tappa
3) consuma questi meccanismi via import, aggiungendo solo ciò che è realmente nuovo: il
perimetro di cartelle/path autorizzato (vedi ROADMAP.md, Tappa 3). Esplicitamente escluso da
questo perimetro concettuale: i ruoli/permessi tra membri dello stesso tenant (owner/
operatore/lettore, Tappa 8) — asse diverso (chi tra gli umani del tenant può fare cosa, non
cosa può toccare l'agente nel mondo esterno), non va confuso nello stesso modulo.

**Alternative considerate**: modulo "Autorizzazioni" separato in `codice/` con propria riga in
PROJECT.md — scartata: Python non impone lo spostamento (l'import cross-modulo funziona
identico), e i 2 meccanismi esistenti sono già generici dove serve; l'unico problema reale
individuato (costanti Gmail-specifiche mescolate con la parte generica di credential storage in
`oauth.py`) non causa ancora danno con un solo provider — rimandato a Tappa 4, quando arriva il
secondo provider OAuth (vedi ROADMAP.md). Spostare comunque il codice ora "per pulizia" —
scartata, avrebbe toccato senza necessità funzionale codice di Tappa 2 già validato con dati
Gmail reali (STOP 2 già passato).

**Conseguenze**: ROADMAP.md aggiornato — Tappa 3 include il requisito esplicito di perimetro
filesystem imposto nel codice; Tappa 4 include il refactor di `oauth.py` (split generico/
Gmail-specifico) come lavoro da fare quando arriva il secondo provider, non prima; Tappa 11
include ora il caso specifico dell'eval su istruzione ostile in un'email letta dall'agente
(identificato in questa stessa discussione, non ancora coperto), rimandato lì su richiesta
esplicita dell'utente invece che anticipato a prima di Tappa 4.

---

## 2026-07-14 — Safety Supervisor: punto unico di autorizzazione per ogni tool call

**Contesto**: progettando Tappa 3 (Agente Locale), il primo tentativo teneva tre meccaniche di
enforcement diverse in parallelo — controllo Python scritto a mano dentro ogni tool custom (come
già fa Gmail), un hook `PreToolUse` per i tool nativi dell'SDK filesystem, e l'idea di negare
sempre i tool nativi per poi rifare l'azione a mano. L'utente ha fatto notare il rischio concreto:
ogni nuovo connettore/capacità avrebbe rischiato di reinventare a modo suo sia il controllo di
autorizzazione sia il gate di conferma, con logica sempre più sparsa e incoerente man mano che il
prodotto cresce (Calendar/Storage in Tappa 4, Automazioni in Tappa 10). L'utente ha anche chiesto
esplicitamente di poter usare i tool nativi dell'SDK (`Read`/`Write`/`Edit`/`Glob`/`Grep`) per
sfruttarne la potenza reale (es. `Grep` cerca nel contenuto dei file, non solo nei nomi) invece di
riscrivere equivalenti custom più poveri.

**Decisione**: introdotto un **Safety Supervisor** (`codice/orchestratore/safety/supervisor.py`,
`policies.yaml`) come punto unico di decisione per ogni tool call, nativo o custom: riceve
un'azione (nome, una o più categorie di rischio: `destructive`/`privacy`/`costly`/`network`/
`read_only`) e un contesto (incluso sempre `tenant_id`), valuta una lista di regole dichiarative
ordinate per priorità con condizioni (es. `path_in_perimetro: true`), e restituisce
`allow`/`deny`/`ask_user` più un audit log JSONL immutabile. Non esegue nulla e non parla con
l'utente: è puro motore di policy, stateless. Due punti di aggancio, stesso Supervisor:

- **Tool nativi SDK** (Agente Locale: `Read`/`Write`/`Edit`/`Glob`/`Grep`, sessione locale
  interattiva): un hook `PreToolUse` unico calcola il contesto (es. perimetro cartelle) e chiama
  `Supervisor.validate()`. Essendo la sessione locale e sincrona, un verdetto `ask_user` viene
  risolto dall'hook stesso chiedendo conferma al terminale, fuori dal controllo del modello.
- **Tool custom MCP**: la funzione tool chiama `Supervisor.validate()` in testa. Per Gmail
  (sessione server-side, richiesta HTTP la cui conferma può arrivare più tardi da un altro
  dispositivo), un verdetto `ask_user` crea un'azione pendente con il meccanismo esistente
  (`azioni.py`, invariato) — comportamento identico a oggi, ma la regola "quali azioni chiedono
  conferma" ora vive nel file di policy, non in if/else nel codice del connettore. Per
  `move_file`/`delete_file`/`create_folder` (Agente Locale, sessione locale sincrona, senza
  equivalente nativo SDK), un verdetto `ask_user` si risolve subito con lo stesso prompt
  sincrono al terminale usato dall'hook per i tool nativi (funzione di conferma condivisa) —
  nessuna azione pendente su Supabase, non necessaria per un processo locale a singolo utente;
  l'audit resta comunque coperto dal log del Supervisor stesso.

**Cosa NON si costruisce ora (rimandato)**: nessun consenso persistente per categoria (il
Supervisor chiede sempre, non memorizza "ok per sempre" — idea salvata in
`notes/idee-prodotto-eidos2.md` con vincolo esplicito: categorie come pagamenti/bancarie non
devono MAI ammettere consenso persistente, anche quando/se costruito); nessuna modalità di
controllo selezionabile dal cliente stile Claude Code (`bypassPermissions` e simili) — sconsigliata
esplicitamente per il pubblico PMI/freelance non tecnico di Eidos, vedi stessa nota.

**Alternative considerate**: mantenere il controllo scritto a mano dentro ogni tool (lo status quo
di Gmail) e ripeterlo per Agente Locale — scartata, è la causa diretta del problema segnalato
dall'utente; usare solo tool custom anche per il filesystem, evitando del tutto i tool nativi
dell'SDK — scartata su richiesta esplicita dell'utente, rinuncerebbe a capacità reali (es. `Grep`)
senza necessità, ora che l'enforcement non vive più dentro il tool ma nel Supervisor.

**Rischio tecnico aperto, da verificare scrivendo il codice** (non blocca l'architettura): se un
hook `PreToolUse` (o una funzione tool custom) può davvero bloccare in modo sincrono in attesa di
input da terminale dentro il loop dell'agente, senza un timeout imposto dall'SDK che lo interrompa
prima che il founder finisca di rispondere. Se non funziona in pratica, fallback: la conferma
locale passa comunque dalla stessa coda `azioni_pending` usata da Gmail invece che da un prompt
sincrono — cambia solo il "backend" che raccoglie il sì/no, non il Supervisor né le policy.

**Conseguenze**: questa voce supera parzialmente "Autorizzazioni: niente modulo Autorizzazioni
separato" (14/7) sul dettaglio dell'enforcement (ora centralizzato nel Supervisor invece che
duplicato per tool), ma ne conferma il principio di fondo (resta dentro Orchestratore, nessun
modulo di dominio a sé, nessuna riga propria in PROJECT.md). Gmail (Tappa 2, già validato) non
cambia comportamento visibile, ma le sue funzioni tool andranno aggiornate per chiamare il
Supervisor invece di if/else propri — piccola modifica meccanica, da fare come parte della
costruzione di Tappa 3. Il design dettagliato del Safety Supervisor e di Agente Locale prosegue
in `saas-module-builder`.

---

## 2026-07-14 — Agente Locale (Ciclo B): `Glob` escluso dai tool nativi, sostituito da `list_directory` custom

**Contesto**: costruendo il Ciclo B di Tappa 3 (Agente Locale) sopra il Safety Supervisor già
validato (vedi voce precedente), la verifica sulla documentazione ufficiale live del Claude Agent
SDK (regola CLAUDE.md, "Verifica delle capacità del Claude Agent SDK") ha confermato la sintassi
esatta di `ClaudeSDKClient`/hook `PreToolUse`, ma ha anche mostrato che il `tool_input` del tool
nativo `Glob` espone solo `pattern`, nessun campo path esplicito - a differenza di `Read`/`Write`/
`Edit` (`file_path`) e `Grep` (`paths`, lista). Il design approvato a STOP 1 includeva `Glob` tra i
tool nativi abilitati per l'elenco cartelle.

**Decisione**: `Glob` escluso dai tool nativi abilitati per Agente Locale. Il perimetro si applica
validando path espliciti nel `tool_input`: senza un campo del genere, l'hook non avrebbe modo di
verificare cosa `Glob` sta davvero enumerando (rischio di fail-open su un tool che elenca il
filesystem). La stessa capacità (elencare una cartella) resta coperta da un nuovo tool custom
`list_directory` (immediato, sola lettura, stesso pattern di verifica perimetro degli altri tool
custom di `agente_locale/tools.py`), dove il path è sempre esplicito e verificabile. Stesso
principio applicato a `Grep`: se il modello lo chiama senza `paths` esplicito, l'hook verifica la
sola `cwd` della sessione (sempre una cartella del perimetro, mai un default non verificato).

**Alternative considerate**: abilitare `Glob` comunque, fidandosi che operi solo sotto `cwd` per
default - scartata, non verificato con certezza sulla documentazione e un'assunzione sbagliata qui
avrebbe un costo alto (enumerazione di file fuori perimetro); bloccare `Glob` del tutto senza un
sostituto - scartata, avrebbe tolto una capacità già validata a STOP 1 senza necessità, quando un
tool custom equivalente costa poco.

**Conseguenze**: tool nativi abilitati per Agente Locale: `Read`, `Write`, `Edit`, `Grep`. Tool
custom MCP: `list_directory`, `move_file`, `delete_file`, `create_folder`. Micro-deviazione dal
design di STOP 1 (che elencava `Glob`), segnalata qui invece di lasciarla silenziosa - nessun
impatto sulla capacità finale offerta all'utente.

---

## 2026-07-15 — Agente Locale (Ciclo B): verifica reale, causa di un blocco apparente

**Contesto**: primo test manuale a STOP 2 (`cli_locale.py` lanciato dal terminale integrato di
VSCode): la sessione restava bloccata dopo il primo messaggio, senza errore visibile - sospettato
inizialmente il rischio tecnico già annotato ("hook che blocca in modo sincrono in attesa di
input"). Riprodotto con successo lanciando lo stesso comando con input pilotato (non interattivo):
gate, conferma e scrittura reale funzionavano correttamente, escludendo un bug nella logica.
Ripetuto poi dall'utente da un terminale Windows separato (non VSCode): stesso comando, stesso
codice, funziona correttamente end-to-end (scrittura con conferma, lettura immediata, blocco fuori
perimetro senza conferma).

**Causa reale**: non il meccanismo di conferma sincrona (il rischio tecnico annotato in
precedenza non si è verificato), ma l'ambiente del terminale integrato di VSCode/Claude Code, che
eredita variabili d'ambiente dell'estensione (auth source per le connessioni claude.ai) e confonde
il sottoprocesso CLI Node.js lanciato dall'SDK, portandolo a un `ConnectionRefused` invece di usare
la sessione claude.ai già loggata sulla macchina.

**Decisione**: capacità considerata verificata e funzionante. Nessuna modifica al meccanismo di
conferma sincrona (confermato che funziona anche in un terminale interattivo reale, non solo con
input pilotato). Registrata come trappola nota in `docs/agente_locale/README.md`: `cli_locale.py`
va sempre lanciato da un terminale Windows separato, mai dal terminale integrato di VSCode.

**Conseguenze**: nessuna azione di codice necessaria. Il "rischio tecnico aperto" annotato nella
voce "Safety Supervisor" di questo file (conferma sincrona nell'hook) è chiuso: verificato che
funziona, fallback ad `azioni_pending` non necessario.

---

## 2026-07-15 — Autenticazione Anthropic per i clienti: solo API key di Eidos, mai l'abbonamento personale del cliente

**Contesto**: verificando perché `cli_locale.py` in locale funziona con il login claude.ai del
founder (Pro, senza costo a consumo) invece che con una `ANTHROPIC_API_KEY`, l'utente ha chiesto se
per i clienti reali si potesse collegare tutto tramite un eventuale abbonamento Claude posseduto
dal cliente stesso, invece che tramite una `ANTHROPIC_API_KEY` di Eidos - varrebbe a dire meno costo
a consumo per Eidos sui clienti che già pagano un abbonamento Claude proprio.

**Decisione**: scartata. Per l'Orchestratore (server-side, Railway) non è tecnicamente praticabile -
un abbonamento claude.ai è un login personale interattivo legato a macchina/sessione, non esiste un
meccanismo per delegarlo a un processo backend remoto. Per Agente Locale (che gira davvero sul PC
del cliente) sarebbe tecnicamente plausibile, ma resta un rischio di violazione dei termini di
servizio di Anthropic non verificato (un abbonamento personale usato per alimentare le funzionalità
di un SaaS di terzi a pagamento) - non decidibile per comodità implementativa senza leggere i termini
reali. Anche se fosse permesso, risolverebbe il costo solo per il sottoinsieme di clienti che già
paga un abbonamento Claude proprio, verosimilmente pochi nel pubblico PMI/freelance target (vedi
PROJECT.md) - non sostituisce la soluzione generale già pianificata.

**Alternative considerate**: abbonamento del cliente per Agente Locale (solo) - scartata per il
rischio ToS non verificato più il beneficio limitato a un sottoinsieme di clienti.

**Conseguenze**: nessun cambiamento alla roadmap - resta valida la Tappa 9 così come già descritta
(Eidos usa una propria `ANTHROPIC_API_KEY`, il modulo Consumi misura l'uso per tenant, il prezzo
dell'abbonamento flat deve coprire quel costo). Resta aperto, e va risolto quando si progetta la
distribuzione reale di Agente Locale a un cliente non tecnico (vedi nota in
`notes/idee-prodotto-eidos2.md`), come consegnare in modo sicuro l'`ANTHROPIC_API_KEY` di Eidos al
processo locale sul PC del cliente senza che il cliente debba gestire credenziali Anthropic a mano.
