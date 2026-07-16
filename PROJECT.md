# Eidos 2.0

> Indice del progetto. Descrive lo stato attuale del sistema — non i piani.
> Ultimo allineamento: 2026-07-16

## Cos'è

Eidos è un assistente operativo AI per imprenditori, PMI e freelance: non un chatbot che
risponde a domande, ma un agente che capisce l'intento (voce o testo) e lo trasforma in
azione reale — file organizzati, email scritte, dati recuperati, task eseguiti. Obiettivo
finale: prodotto SaaS multi-tenant vendibile, in abbonamento flat con soglia di consumo.
La v1 si valida prima su un solo utente (il founder), poi si apre a clienti reali.

> Perché queste scelte: vedi [`DECISIONS.md`](DECISIONS.md).
> Come si lavora qui: vedi [`CLAUDE.md`](CLAUDE.md).

## Scala e vincoli

- Team: 1 persona (founder)
- Scala attuale: micro-SaaS — v1 validata dal founder come singolo utente prima di aprire a clienti
- Stack: Claude Agent SDK (Python), PostgreSQL + pgvector via Supabase (Auth + DB + Storage + RLS unificati), Gmail API, Stripe Checkout

## Architettura in breve

Monolite Python. Un agente orchestratore (Claude Agent SDK) con subagent via `AgentDefinition`
introdotti solo quando serve davvero delega parallela — non uno per dominio fin da subito.
DB Postgres+pgvector (Supabase), shared schema con `tenant_id` fin dall'inizio anche in fase
single-user. Metodo di costruzione: walking skeleton — si costruisce prima il percorso più
sottile ma vero end-to-end, si ispessisce un pezzo alla volta (dettagli in ROADMAP.md).

## Moduli

| Modulo | Responsabilità | Stato | Docs |
|---|---|---|---|
| Fondamenta | Autentica il founder (single-user) su Supabase, schema con `tenant_id` da subito. Ruoli/permessi granulari (Grant), audit log, dispositivi: Tappa 8 | costruito (v1 minima) | [docs/fondamenta/README.md](docs/fondamenta/README.md) |
| Orchestratore | Agente conversazionale singolo (Claude Agent SDK), connettori Gmail, Google Calendar e Google Drive completi (cerca/rispondi/inoltra/organizza/invia mail; cerca/crea/modifica/cancella/rispondi a inviti/controlla disponibilità su calendario; cerca/legge/crea/organizza/condivide/cestina file e cartelle su Drive), Safety Supervisor (autorizzazione centralizzata per ogni tool call), decide azione diretta vs delega a subagente (non ancora servito) | costruito (v1, single-user) | [docs/orchestratore/README.md](docs/orchestratore/README.md) |
| Memoria | Un solo database Postgres con tre modi di ricordare: poche righe sempre caricate (preferenze minime, costruito), tabelle strutturate per fatti per entità (upsert, scrittura sempre esplicita via `remember_fact`, costruito), ricerca semantica (pgvector) unificata su mail importate + eventi calendario conclusi + fatti salvati (`search_memoria`, costruito). Estrazione strutturata/indicizzazione documenti generici (inclusi file locali e file Drive): Tappa 5 | costruito (v1, mail+calendario+fatti) | [docs/orchestratore/README.md](docs/orchestratore/README.md) |
| Connettori Cloud | Suite Google completa: Google Calendar + Google Drive (vedi riga Orchestratore); messaggistica, ricerca web non ancora coperti; Suite Microsoft (Outlook Mail/Calendar, OneDrive) dopo validazione della Suite Google | in parte pianificato | — |
| Agente Locale | File/cartelle: leggere/scrivere/cercare/spostare/eliminare dentro un perimetro autorizzato, sessione locale separata dall'Orchestratore server-side. Terminale/browser: non ancora costruiti | costruito (v1, solo file) | [docs/agente_locale/README.md](docs/agente_locale/README.md) |
| Voce | STT/TTS (da riprogettare da zero, nessuna decisione ereditata) | pianificato | — |
| Interfaccia Utente | Riceve voce/testo, mostra risposte, log azioni, conferme | pianificato | — |
| Consumi | Traccia uso per tenant, applica soglia/avvisi del piano in abbonamento | pianificato | — |
| Automazioni | Automazioni create dall'utente (schedulate o su trigger di eventi): scheduler, ricezione webhook/polling sui Connettori Cloud, storage delle definizioni per tenant, esecuzione tramite invocazione dell'Orchestratore | pianificato | — |

I README di modulo (`docs/{{modulo}}/README.md`) si scrivono quando il modulo viene costruito.

## Documenti

- [DECISIONS.md](DECISIONS.md) — log delle decisioni architetturali (append-only)
- [ROADMAP.md](ROADMAP.md) — ordine di implementazione dei moduli (walking skeleton)
- [playbook/connettori.md](playbook/connettori.md) — checklist operativa per implementare un
  connettore, estratta da Gmail (Tappa 2); vedi CLAUDE.md, "Playbook operativi", per
  quando/come si scrive un playbook
- [playbook/system-prompt-agenti.md](playbook/system-prompt-agenti.md) — checklist operativa
  per scrivere/modificare il system prompt di un agente (struttura, best practice da
  verificare online prima di ogni modifica), estratta da Orchestratore e Agente Locale; si
  applica anche ai futuri subagenti specializzati
- `notes/idee-salvate-da-eidos-v1.md` — idee recuperate dal progetto precedente, non ancora decise per questo progetto
