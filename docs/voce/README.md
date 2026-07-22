# Modulo: Voce

> Descrive lo stato attuale del modulo, com'è davvero. Si aggiorna insieme al codice.

## Responsabilità

Dà al founder una conversazione vocale completa (domanda parlata → azione reale → risposta
parlata) sopra l'Orchestratore esistente: nessuna logica agentica propria, solo I/O audio
(STT/TTS) e la sessione WebSocket che porta i transcript al server e riporta indietro testo/
eventi da pronunciare. Client CLI (push-to-talk, Invio per parlare), non ancora interfaccia
grafica (Tappa 7). Progettato da zero, nessuna decisione ereditata da Eidos v1.

## Interfacce

- **Espone**: entrypoint `python -m voce` (richiede login CLI esistente, stesso cookie di
  `cli.py`)
- **Consuma**: `/voice/token` (token effimeri Deepgram grant-JWT 30s + ElevenLabs single-use
  15min — le key permanenti restano solo nell'env server, l'audio non attraversa mai il
  backend), `/chat/stream` via WebSocket persistente (`orchestratore/turno_vocale.py`, stessa
  sessione agente e stesso Safety Supervisor di `/chat` testuale), Deepgram STT WS, ElevenLabs
  TTS WS (`stream-input`)

## Come funziona

- `codice/voce/stt.py` — un turno = WS Deepgram con token effimero, blocchi mic in streaming,
  chiude a `speech_final` (endpointing 300ms — timer fisso, non un modello di turn-taking; il
  pezzo mancante è annotato in ROADMAP.md Tappa 7)
- `codice/voce/tts.py` — `SessioneTTS`: un WS ElevenLabs per turno (token single-use, il
  protocollo si chiude quando riceve testo vuoto), `invia(frase)` con `flush` per sintetizzare
  subito, `chiudi()` aspetta l'audio residuo e chiude WS+casse
- `codice/voce/frasi.py` — `SpezzaFrasi`: spezza i delta di testo a confine di frase così la
  prima frase va in sintesi mentre il modello genera le successive
- `codice/voce/sanificazione.py` — quello che si pronuncia non è quello che si mostra
  (markdown/emoji via, pausa tra intestazioni e voci di lista)
- `codice/voce/conferme.py` — elenco chiuso e deterministico per le risposte sì/no vocali
  (stessa fonte di `cli.py`, mai interpretazione del modello)
- `codice/voce/sessione_ws.py` — wrapper della connessione WebSocket persistente verso
  `/chat/stream`; la logica di decisione (quando interrompere un tentativo) vive server-side in
  `orchestratore/turno_vocale.py`
- `codice/voce/rilevatore_frase.py` — euristica "sembra completa" per lo speculativo
  (**infrastruttura presente ma non collegata**, vedi sotto)
- `codice/voce/client.py` — loop principale: ascolta, manda il transcript finale, consuma gli
  eventi del turno (`ponte`/`delta`/`tool_in_corso`/`fine`/`errore`/`annullato`) pronunciandoli
  via TTS, gestisce la conferma di un'azione in attesa
- `orchestratore/voce_token.py` — emette i token effimeri
- `orchestratore/ponte.py` — frase di presa in carico generata da Haiku puro in parallelo al
  turno di Sonnet (copre il silenzio iniziale, si astiene su chiacchiera pura — eval
  `orchestratore/eval/eval_ponte.py`)
- `orchestratore/turno_vocale.py` — macchina a stati del turno lato server (avvio/interrompi/
  prosegui in base ai transcript ricevuti)

**Speculativo vocale (mandare un transcript "parziale" prima della fine frase) costruito
completo in TDD ma disattivato lato client** dopo STOP 2 con voce vera: scattava anche su pause
di respiro normali, non solo su frasi complete, percepito come innaturale. L'infrastruttura
(`rilevatore_frase.py`, `SessioneVoce.manda_parziale`, l'interrupt server-side in
`turno_vocale.py`) resta intatta per una riattivazione futura con un'euristica diversa — vedi
DECISIONS.md 2026-07-22.

## Come si prova

```
cd codice
$env:EIDOS_API_BASE_URL = "http://127.0.0.1:8123"   # o l'URL di produzione
.venv\Scripts\python -m voce
```

Login riusa il cookie di `cli.py` se presente, altrimenti chiede email/password. Premi Invio,
parla, il turno risponde a voce. Casi critici da riverificare a ogni modifica sostanziale:

1. Frase intera senza pause
2. Ripensamento a metà frase ("che impegni ho doma— anzi dopodomani") — nessun accenno alla
   risposta sbagliata
3. Frase corta senza pause ("grazie")

Test automatici: `codice/tests/` (logica pura — frasi, sanificazione, conferme, rilevatore,
turno_vocale server-side). I wrapper I/O reali (`audio.py`, `stt.py`, `tts.py`,
`sessione_ws.py`, `client.py`) sono verificati con voce vera allo STOP 2, non da unit test
(stessa convenzione dichiarata in `voce/__init__.py`).

## Decisioni rilevanti

- DECISIONS.md 2026-07-22 — "Tappa 6 (Voce): STT/TTS da zero, ponte vocale, speculativo
  tentato e ritirato" (fondamenta, ponte, sei bug di latenza server-side, speculativo
  costruito e disattivato, token Deepgram scaduto a metà sessione, handshake TTS sul percorso
  critico → prefetch, latenza Orchestratore trovata ma fuori perimetro)
- ROADMAP.md — Tappa 6

## Trappole note / attenzioni

- **Token TTS/STT sempre presi appena prima di servire, mai in anticipo**: sono effimeri
  (Deepgram 30s, ElevenLabs single-use) — prenderli all'avvio della sessione invece che a ogni
  turno li fa scadere a metà conversazione (bug reale trovato a STOP 2, corretto).
- **`SessioneTTS` non è riusabile tra turni**: il protocollo ElevenLabs usato qui
  (`stream-input` single-context) si chiude quando riceve testo vuoto — un nuovo turno richiede
  sempre un nuovo token+WS. La latenza dell'handshake è overlappata (prefetch all'inizio del
  turno), non eliminata: una vera connessione persistente cross-turno richiederebbe ridisegnare
  il contratto di `SessioneTTS`/`Casse` (oggi "fine turno" = chiusura WS = unico segnale di
  "audio finito di suonare") — scartato finché il prefetch basta a nascondere l'handshake
  dentro l'attesa, più lunga, del primo token LLM.
- **Latenza al primo token LLM è il fattore dominante e resta variabile** (2,4-4,8s su turni
  semplici, oltre 10s con una tool call reale) — è latenza Orchestratore, non di questo modulo;
  il `ponte` la maschera quando scatta ma non la risolve. Non affrontato qui per scelta
  esplicita, da riprendere in una sessione dedicata all'Orchestratore se resta un problema.
- **Endpointing Deepgram è un timer fisso (300ms)**, non un modello di turn-taking — stesso
  limite concettuale dello speculativo disattivato. Annotato come lavoro di Tappa 7
  (Interfaccia), non di questo modulo.
- **Riempitivi locali disattivati** (`EIDOS_VOCE_RIEMPITIVI=0` di default, STOP 2 2026-07-17):
  resta solo l'apertura contestuale del `ponte` lato server.
