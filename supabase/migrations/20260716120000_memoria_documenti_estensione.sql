-- Tappa 5: Memoria - estensione documenti (PDF, DOCX, XLSX, immagini/scan
-- via OCR). Aggiunge l'archiviazione del file originale (Supabase Storage)
-- a memoria_documenti, gia' esistente da Tappa 2 (vedi DECISIONS.md
-- "Memoria: un solo database, tre modi di ricordare").

alter table public.memoria_documenti
    add column if not exists storage_path text;

-- Bucket privato: unico accesso e' server-side con service role key,
-- stesso pattern delle tabelle (nessuna policy anon/authenticated).
insert into storage.buckets (id, name, public)
values ('documenti', 'documenti', false)
on conflict (id) do nothing;
