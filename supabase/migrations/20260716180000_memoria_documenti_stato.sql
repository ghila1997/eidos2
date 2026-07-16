-- Tappa 5.1: atomicità dell'ingest documenti.
-- Un crash tra insert_documento e i chunk lasciava una riga con hash
-- valorizzato ma zero chunk: ogni re-import successivo diceva "già
-- presente" mentre niente era ricercabile (perdita silenziosa, successa
-- davvero durante i test della Tappa 5). L'ingest ora inserisce con
-- stato='in_corso' e marca 'completo' solo a fine pipeline; il dedup per
-- hash considera solo i documenti completi (vedi memoria/ingest_documento.py).
-- Default 'completo': le righe esistenti (mail/eventi/fatti e documenti
-- già importati con successo) restano valide senza backfill.
alter table public.memoria_documenti
    add column if not exists stato text not null default 'completo';
