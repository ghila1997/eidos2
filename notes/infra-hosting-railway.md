# Railway — limite noto per clienti enterprise B2B

> Nota tecnica non vincolante, da riconfermare quando/se diventa rilevante. Non è una
> decisione (vedi DECISIONS.md), solo un rischio da tenere a mente.

**Cosa**: Railway ospita l'app/orchestratore (Dockerfile → uvicorn), non i dati — quelli
sono su Supabase (Postgres, Auth, Storage, RLS), che è il vero perimetro di sicurezza dati.
Per lo stadio attuale (walking skeleton, singolo utente founder) Railway va bene: env var
cifrate, TLS di default verso Supabase, isolamento per servizio.

**Limite**: Railway non pubblicizza certificazioni formali tipo SOC2 o ISO 27001 (a differenza
di AWS/GCP/Azure). Un cliente enterprise B2B (azienda grande, procurement/IT che richiede
DPA, audit di sicurezza, questionari infrastruttura) probabilmente le chiederebbe prima di
firmare.

**Quando riconsiderare**: solo se la roadmap punta a clienti enterprise regolamentati
(non PMI/freelance, il target attuale). A quel punto rivalutare hosting (o verificare se
Railway ha nel frattempo preso certificazioni).

_Aggiunta 2026-07-14, durante Tappa 2 (Orchestratore), dopo domanda dell'utente su
sicurezza dati Railway._
