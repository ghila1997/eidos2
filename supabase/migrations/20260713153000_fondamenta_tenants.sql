-- Fondamenta (Tappa 1): tenants + tenant_members.
-- Un solo tenant valorizzato in questa fase; ruoli multipli/Grant restano
-- fuori scope fino a Tappa 8 (vedi ROADMAP.md), la colonna `role` esiste già
-- per non dover rifare lo schema.

create table if not exists public.tenants (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz not null default now()
);

create table if not exists public.tenant_members (
    user_id uuid primary key references auth.users (id) on delete cascade,
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    role text not null default 'owner',
    created_at timestamptz not null default now()
);

create index if not exists tenant_members_tenant_id_idx
    on public.tenant_members (tenant_id);

alter table public.tenants enable row level security;
alter table public.tenant_members enable row level security;

-- Nessuna policy per anon/authenticated in questa fase: l'unico accesso
-- server-side passa dalla service role key (bypassa RLS), coerente col
-- flusso auth di Fondamenta (vedi codice/fondamenta/supabase_client.py).
-- Le policy per accesso diretto client-side arrivano quando servirà davvero
-- (es. con Connettori Cloud o Interfaccia Utente).
