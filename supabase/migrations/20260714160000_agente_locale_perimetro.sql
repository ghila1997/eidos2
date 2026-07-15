-- Tappa 3, Ciclo B: Agente Locale - perimetro di cartelle/path autorizzate.
-- Il filesystem locale non ha un provider esterno che faccia da guardiano
-- (a differenza di Gmail, dove l'autorizzazione e' data dal consenso OAuth):
-- serve un perimetro esplicito, imposto nel codice (vedi ROADMAP.md, Tappa 3,
-- "Perimetro di accesso"; DECISIONS.md "Safety Supervisor: punto unico di
-- autorizzazione per ogni tool call").
--
-- Gestita solo dal comando CLI diretto (`cli_locale.py --autorizza`), mai
-- da un tool esposto al modello - stesso principio delle azioni distruttive
-- in CLAUDE.md: il perimetro stesso non deve essere ampliabile dal modello.

create table if not exists public.perimetro_locale (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    path text not null,
    created_at timestamptz not null default now(),
    unique (tenant_id, path)
);

alter table public.perimetro_locale enable row level security;

-- Nessuna policy per anon/authenticated in questa fase, stesso motivo delle
-- altre tabelle di Orchestratore: unico accesso e' locale con service role
-- key (vedi codice/common/supabase_rest.py), non client-side.
