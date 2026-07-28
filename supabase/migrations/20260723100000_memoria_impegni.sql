-- Cuneo "impegni impliciti": promesse/obblighi presi via mail o documenti
-- che non vivono in nessun calendario/todo-list (sessione 2026-07-23, vedi
-- DECISIONS.md). Tabella dedicata, non dentro memoria_fatti.data: uno stato
-- che cambia nel tempo (aperto/chiuso) va interrogato trasversalmente per
-- stato, scomodo su jsonb.

create table if not exists public.memoria_impegni (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    entity_key text not null,
    descrizione text not null,
    direzione text not null check (direzione in ('nostro', 'loro')),
    source_type text not null,
    source_id text not null,
    source_excerpt text not null,
    observed_at timestamptz not null,
    scadenza date,
    stato text not null default 'aperto' check (stato in ('aperto', 'chiuso')),
    confidence numeric not null check (confidence >= 0 and confidence <= 1),
    created_at timestamptz not null default now(),
    chiuso_il timestamptz
);

-- Lettura più frequente: "dammi gli impegni aperti", filtrata per tenant.
create index if not exists memoria_impegni_tenant_stato_idx
    on public.memoria_impegni (tenant_id, stato);

-- Deduplica e controllo automatico di chiusura all'ingest (mail/documenti):
-- entità + fonte già proposta.
create index if not exists memoria_impegni_entity_source_idx
    on public.memoria_impegni (tenant_id, entity_key, source_type, source_id);

alter table public.memoria_impegni enable row level security;

-- Nessuna policy per anon/authenticated, stesso pattern del resto di
-- Memoria: unico accesso è server-side con service role key.
