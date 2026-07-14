# Eidos 2.0

> Indice del progetto. Descrive lo stato attuale del sistema — non i piani.
> Ultimo allineamento: 2026-07-14

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
| Orchestratore | Agente conversazionale singolo (Claude Agent SDK), connettore Gmail completo (cerca/rispondi/inoltra/organizza/invia), decide azione diretta vs delega a subagente (non ancora servito) | costruito (v1, single-user) | [docs/orchestratore/README.md](docs/orchestratore/README.md) |
| Memoria | Un solo database Postgres con tre modi di ricordare: poche righe sempre caricate (preferenze minime, costruito), tabelle strutturate per fatti (schema pronto, vuoto finché l'agente non impara in conversazione), ricerca semantica (pgvector) su mail importate (costruito). Estrazione strutturata da documenti generici: Tappa 5 | costruito (v1, solo mail) | [docs/orchestratore/README.md](docs/orchestratore/README.md) |
| Connettori Cloud | Email/calendario/storage/messaggistica/ricerca web, OAuth per singola capacità | pianificato | — |
| Agente Locale | File/cartelle/terminale/browser sul PC del cliente, sessione isolata dalla macchina ospite | pianificato | — |
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
- `notes/idee-salvate-da-eidos-v1.md` — idee recuperate dal progetto precedente, non ancora decise per questo progetto
