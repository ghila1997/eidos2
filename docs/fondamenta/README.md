# Modulo: Fondamenta

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Scheletro del repo, deploy automatico in produzione, autenticazione del founder come
singolo utente su Supabase, schema dati con `tenant_id` presente da subito (un solo
tenant valorizzato). NON fa: ruoli multipli/permessi granulari (Grant), audit log,
limite dispositivi, invito membri — tutto rimandato a Tappa 8 (multi-tenant).

## Interfacce

- **Espone**: `GET /health` (pubblico), `POST /login` (email+password → cookie di
  sessione), `GET /me` (identità + `tenant_id` del founder, richiede sessione valida)
- **Consuma**: Supabase Auth (REST `/auth/v1/token`, `/auth/v1/user`, `/auth/v1/admin/users`)
  e PostgREST (`/rest/v1/tenant_members`) via service role key

## Come funziona

Backend FastAPI (`codice/app.py`, `codice/fondamenta/`). Login: il backend passa le
credenziali a Supabase Auth (`sign_in_with_password`) e mette `access_token`/
`refresh_token` in cookie httpOnly+secure. `/me` verifica il token chiamando
`GET /auth/v1/user` su Supabase (nessun JWT verificato localmente), poi legge
`tenant_members` con la service role key (bypassa RLS, chiamata server-side).
Schema (`supabase/migrations/20260713153000_fondamenta_tenants.sql`): tabelle
`tenants` e `tenant_members` (`user_id`, `tenant_id`, `role`, default `owner`).
Deploy: Railway, servizio collegato al repo GitHub (branch `main`), build via
`Dockerfile` alla root (non più Nixpacks dalla Tappa 2: il Claude Agent SDK
richiede il CLI Node.js di Claude Code come sottoprocesso runtime, che
Nixpacks-solo-Python non installava - vedi DECISIONS.md). Il Dockerfile
installa Node.js+npm, il CLI Claude Code, le dipendenze Python da
`codice/requirements.txt`, e avvia `uvicorn app:app` da dentro `codice/`.

## Come si prova

1. `GET https://eidos2-api-production.up.railway.app/health` → `{"status":"ok","message":"hello world"}`
2. Login:
   ```
   curl -X POST https://eidos2-api-production.up.railway.app/login \
     -H "Content-Type: application/json" \
     -d "{\"email\":\"<founder>\",\"password\":\"<password>\"}" -c cookies.txt
   ```
   → `{"status":"ok"}`
3. `curl https://eidos2-api-production.up.railway.app/me -b cookies.txt` →
   `user_id`, `email`, `tenant_id`, `role: owner`
4. Push su `main` → Railway rideploya da solo entro un paio di minuti (verificabile
   da `railway deployment list --service eidos2-api`)

Test automatici: `codice/tests/` (pytest, Supabase mockato con `respx`) coprono le
trappole sotto.

## Decisioni rilevanti

- DECISIONS.md — "Reboot completo del progetto precedente (Eidos v1)"
- DECISIONS.md — "Metodo di costruzione: walking skeleton"
- DECISIONS.md — "Multi-tenancy: shared schema + tenant_id da subito"
- DECISIONS.md — "Auth: Supabase Auth + RLS come piattaforma, flusso di sessione da riprogettare"
- DECISIONS.md — "Fondamenta: nuovo progetto Supabase pulito invece di riusare EIDOS v1"

## Trappole note / attenzioni

- `/me` senza cookie o con token invalido/scaduto deve rispondere 401, mai 200 con
  dati vuoti — coperto da `test_auth.py`
- Un utente Supabase creato con "Invite" (non "Create new user" con password
  diretta) risulta confermato ma **senza password funzionante** — il login fallisce
  con "credenziali non valide" finché non gli si imposta una password esplicita da
  Supabase Studio. Non ovvio dal messaggio d'errore.
- `tenant_members.user_id` senza riga corrispondente → `/me` deve rispondere 404,
  non un tenant vuoto/finto — coperto da `test_auth.py`
- La service role key bypassa RLS: usata solo server-side in `supabase_client.py`,
  mai esposta al client. Nessuna policy RLS per `anon`/`authenticated` è ancora
  definita su `tenants`/`tenant_members` — da fare quando un modulo avrà bisogno di
  accesso diretto client-side (non prima).
- Build via `Dockerfile` (non più Nixpacks): se si sposta `codice/`, aggiornare
  i path `COPY` nel `Dockerfile` alla root.
