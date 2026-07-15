# Modulo: Agente Locale

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Dà al founder la possibilità di chiedere in linguaggio naturale un'azione reale su
file/cartelle del suo PC (leggere, scrivere, cercare per contenuto, spostare/rinominare,
creare cartelle, eliminare), dentro un perimetro di cartelle esplicitamente autorizzato.
Sessione locale separata dall'Orchestratore server-side (Railway non ha accesso al
filesystem del founder). NON fa: terminale, browser (restano "pianificato" in PROJECT.md),
estrazione di contenuto da PDF/binari (Tappa 5), indicizzazione/ricerca semantica dei file
(Tappa 5 — vedi ROADMAP.md), sandboxing OS-level (mitigazione attuale resta la conferma
obbligatoria, vedi ROADMAP.md "Esplicitamente rimandato").

## Interfacce

- **Espone**: entrypoint locale `python -m agente_locale.cli_locale` (sessione
  interattiva) e `python -m agente_locale.cli_locale --autorizza "<path>"` (gestione
  perimetro, comando diretto non esposto al modello)
- **Consuma**: Claude Agent SDK (`ClaudeSDKClient`, sessione locale interattiva, non passa
  da `/chat`), Safety Supervisor (`codice/orchestratore/safety/`, via import diretto),
  Supabase Postgres (tabella `perimetro_locale`, stesso `eidos2` usato dal resto del
  prodotto)

## Come funziona

- `codice/agente_locale/perimetro.py` — tabella `perimetro_locale` (`tenant_id`, `path`);
  `is_path_allowed` normalizza il path (case-insensitive su Windows, blocca traversal e
  cartelle "sorelle" con lo stesso prefisso) e verifica se è dentro una radice autorizzata
- `codice/agente_locale/hook.py` — hook `PreToolUse` unico per i tool nativi dell'SDK
  (`Read`/`Write`/`Edit`/`Grep`): calcola il path coinvolto, chiama il Safety Supervisor,
  risolve `ask_user` con un prompt sincrono al terminale
- `codice/agente_locale/conferma_locale.py` — `conferma_terminale()`, condivisa da hook e
  tool custom
- `codice/agente_locale/tools.py` — tool custom MCP (`list_directory`, `move_file`,
  `delete_file`, `create_folder`): nessun equivalente nativo con un path verificabile (vedi
  DECISIONS.md, "Agente Locale (Ciclo B): Glob escluso dai tool nativi")
- `codice/agente_locale/cli_locale.py` — entrypoint: `EIDOS_TENANT_ID` da `.env` locale
  (nessuna sessione a cookie qui), `cwd` fissata sulla prima cartella autorizzata

Le scritture (`Write`/`Edit`/`move_file`/`delete_file`/`create_folder`) chiedono sempre
conferma sincrona al terminale — nessuna coda `azioni_pending` come Gmail: sessione locale
a singolo utente, la persona è già lì.

## Come si prova

1. `cd codice && .venv\Scripts\python.exe -m agente_locale.cli_locale --autorizza "C:\percorso\cartella"`
2. `.venv\Scripts\python.exe -m agente_locale.cli_locale`
3. "scrivi appunti.txt in \<cartella\> con scritto prova" → chiede conferma `[y/n]` → il file
   esiste davvero con quel contenuto
4. "leggi appunti.txt" → risposta immediata, nessuna conferma
5. "scrivi qualcosa in C:\Windows\test.txt" → bloccato subito, nessuna conferma chiesta

Test automatici: `codice/tests/test_perimetro.py`, `test_agente_locale_hook.py`,
`test_agente_locale_tools.py`.

## Decisioni rilevanti

- DECISIONS.md — "Safety Supervisor: punto unico di autorizzazione per ogni tool call"
- DECISIONS.md — "Agente Locale (Ciclo B): Glob escluso dai tool nativi, sostituito da list_directory custom"
- DECISIONS.md — "Autorizzazioni: niente modulo Autorizzazioni separato, resta dentro Orchestratore"
- ROADMAP.md — Tappa 3, "Perimetro di accesso"

## Trappole note / attenzioni

- **Non lanciare `cli_locale.py` dal terminale integrato di VSCode/Claude Code**: eredita
  variabili d'ambiente dell'estensione (auth source per le connessioni claude.ai) che
  confondono il sottoprocesso CLI Node.js dell'SDK, causando `ConnectionRefused` invece di
  usare la sessione claude.ai loggata. Usare un terminale Windows separato (verificato
  2026-07-15: stesso comando, stesso codice, funziona correttamente da lì)
- Path traversal (`..`, path assoluti fuori perimetro, cartelle "sorelle" con lo stesso
  prefisso) bloccato sia per i tool nativi (hook) che per i tool custom — coperto da
  `test_perimetro.py`
- Nessun tool espone la possibilità di ampliare il perimetro: solo `--autorizza` da riga di
  comando diretta, mai dal modello — anche se un file letto contiene istruzioni in tal senso
- `Grep` senza `paths` espliciti verifica solo la `cwd` della sessione (sempre dentro il
  perimetro per costruzione) — se in futuro si abilitano più cartelle autorizzate
  contemporaneamente, `Grep` implicito resta scoped alla prima, non a tutte
- Rifiuto (`n`) alla conferma → file non toccato, verificato confrontando esistenza/contenuto
  prima e dopo — coperto da `test_agente_locale_hook.py`/`test_agente_locale_tools.py`
- Richiede il CLI Node.js di Claude Code installato e loggato in locale (non solo nel
  container Docker di Railway, diverso da Orchestratore che gira server-side) — verificare
  con `claude auth status`
