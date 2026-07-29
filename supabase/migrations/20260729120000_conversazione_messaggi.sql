-- Cronologia conversazione (Tappa 7.3): il record della conversazione (UI web,
-- e domani voce/altre interfacce) sopravvive cross-sessione per tenant, cosi'
-- dopo un refresh la cronologia c'e' ancora. Dato del *motore* (Orchestratore),
-- non solo della UI: anche il flusso di conferma di un'azione ci scrive l'esito
-- ("Mail inviata a ...") - quindi vive in orchestratore/conversazione.py, non
-- nell'interfaccia.
--
-- Log **per-messaggio** (non una riga per turno): un turno = messaggio utente
-- + messaggio assistente; l'esito di un'azione e' un messaggio a se', aggiunto
-- quando l'azione parte davvero (anche minuti dopo, anche da un altro
-- dispositivo). I passi "fatti in mezzo" al turno (i tool eseguiti) stanno in
-- `passi` sul messaggio assistente, mostrati a richiesta nella UI. Questa forma
-- regge gia' per la Tappa 7.4 (le schede su dati reali diventano messaggi con
-- un payload nello stesso log).
--
-- Nuovo posto dove vivono dati cliente -> da coprire nella cancellazione/GDPR
-- della Tappa 11 (l'on delete cascade copre la cancellazione del tenant).

-- Forma precedente della stessa fetta (una riga per turno), mai spedita: si
-- rimuove per non lasciare una tabella vuota inutilizzata.
drop table if exists public.conversazione_turni;

create table if not exists public.conversazione_messaggi (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    ruolo text not null check (ruolo in ('utente', 'assistente', 'esito')),
    contenuto text not null default '',
    -- solo su 'assistente': [{"etichetta": "...", "esito": "ok"|"errore"}] dei
    -- tool eseguiti nel turno. null se il turno non ha fatto nulla.
    passi jsonb,
    created_at timestamptz not null default now()
);

-- Lettura unica: "ultimi N messaggi di questo tenant, in ordine di tempo".
create index if not exists conversazione_messaggi_tenant_created_idx
    on public.conversazione_messaggi (tenant_id, created_at);

alter table public.conversazione_messaggi enable row level security;

-- Nessuna policy per anon/authenticated, stesso pattern del resto: unico
-- accesso e' server-side con service role key.
