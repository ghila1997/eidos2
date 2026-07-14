-- Tappa 2: Orchestratore minimo + Memoria (prima istanza).
-- Tre modi di ricordare (vedi DECISIONS.md "Memoria: un solo database..."):
-- preferenze (poche righe sempre caricate), fatti strutturati per entità
-- (upsert per entity_key), ricerca semantica su documenti (pgvector).
-- Tutte le tabelle con tenant_id da subito, RLS abilitata senza policy
-- per anon/authenticated (stesso pattern di Fondamenta: solo service role
-- server-side finché non serve accesso diretto client-side).

create extension if not exists vector;

-- (1) Poche righe sempre caricate in system prompt a inizio sessione.
create table if not exists public.memoria_preferenze (
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    chiave text not null,
    valore text not null,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, chiave)
);

-- (2) Fatti strutturati per entità nominata, upsert per entity_key.
-- Resta perlopiù vuota finché l'agente non impara qualcosa in conversazione
-- (estrazione automatica da documenti arriva in Tappa 5).
create table if not exists public.memoria_fatti (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    entity_key text not null,
    entity_type text not null,
    data jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    unique (tenant_id, entity_key)
);

-- (3a) Metadati del documento sorgente (es. una mail). Dedup per hash
-- contenuto e per (source_type, source_id) cross-import.
create table if not exists public.memoria_documenti (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    source_type text not null,
    source_id text not null,
    content_hash text not null,
    categoria text,
    priorita text,
    created_at timestamptz not null default now(),
    unique (tenant_id, source_type, source_id),
    unique (tenant_id, content_hash)
);

-- (3b) Chunk di testo + embedding per ricerca semantica (pgvector).
-- Dimensione 1024 = voyage-3 (vedi codice/orchestratore/embeddings.py).
create table if not exists public.memoria_chunk_embedding (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    documento_id uuid not null references public.memoria_documenti (id) on delete cascade,
    chunk_index int not null,
    chunk_text text not null,
    embedding vector(1024) not null,
    created_at timestamptz not null default now()
);

create index if not exists memoria_chunk_embedding_tenant_idx
    on public.memoria_chunk_embedding (tenant_id);

-- Indice IVFFlat per ricerca approssimata; con pochi dati (v1 single-tenant)
-- l'index scan degrada a seq scan senza problemi, si ottimizza quando serve.
create index if not exists memoria_chunk_embedding_vector_idx
    on public.memoria_chunk_embedding using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- Cursore di import incrementale per fonte (es. Gmail): evita di rileggere
-- da capo tutta la casella a ogni ingest.
create table if not exists public.memoria_import_cursore (
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    source_type text not null,
    cursore text,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, source_type)
);

-- Credenziali OAuth per capacità esterna (es. Gmail lettura+invio).
-- refresh_token_cifrato è cifrato con EIDOS_CREDENTIAL_ENCRYPTION_KEY
-- (Fernet, vedi codice/orchestratore/oauth.py) - mai in chiaro nel DB.
create table if not exists public.oauth_credenziali (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    provider text not null,
    scope text not null,
    refresh_token_cifrato text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, provider)
);

-- Azioni distruttive in attesa di conferma umana esplicita, fuori dal
-- controllo del modello (vedi CLAUDE.md). Il modello scrive qui, solo
-- l'endpoint di conferma (codice/orchestratore/azioni.py) esegue l'azione
-- vera dopo un "y" esplicito dell'utente.
create table if not exists public.azioni_pending (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    tipo text not null,
    payload jsonb not null,
    stato text not null default 'in_attesa',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Session id dell'Agent SDK da riprendere tra richieste HTTP separate
-- (ogni richiesta ricrea il client Python, deve continuare la stessa
-- conversazione). Un solo record per tenant: v1 è un utente, una sessione.
create table if not exists public.orchestratore_sessione (
    tenant_id uuid primary key references public.tenants (id) on delete cascade,
    session_id text not null,
    updated_at timestamptz not null default now()
);

create or replace function public.match_chunks(
    query_embedding vector(1024),
    p_tenant_id uuid,
    match_count int default 5
)
returns table (
    documento_id uuid,
    chunk_text text,
    source_type text,
    source_id text,
    similarity float
)
language sql stable
as $$
    select
        c.documento_id,
        c.chunk_text,
        d.source_type,
        d.source_id,
        1 - (c.embedding <=> query_embedding) as similarity
    from public.memoria_chunk_embedding c
    join public.memoria_documenti d on d.id = c.documento_id
    where c.tenant_id = p_tenant_id
    order by c.embedding <=> query_embedding
    limit match_count
$$;

alter table public.memoria_preferenze enable row level security;
alter table public.memoria_fatti enable row level security;
alter table public.memoria_documenti enable row level security;
alter table public.memoria_chunk_embedding enable row level security;
alter table public.memoria_import_cursore enable row level security;
alter table public.oauth_credenziali enable row level security;
alter table public.azioni_pending enable row level security;
alter table public.orchestratore_sessione enable row level security;

-- Nessuna policy per anon/authenticated in questa fase, stesso motivo di
-- Fondamenta: unico accesso è server-side con service role key.
