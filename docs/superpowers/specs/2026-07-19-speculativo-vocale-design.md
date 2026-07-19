# Design — Tappa 6, incremento 4: generazione speculativa vocale

> Approvato dall'utente in chat il 2026-07-19. Riferimento: ROADMAP.md Tappa 6,
> ordine degli incrementi concordato dopo l'incremento 3 (ponte + fix latenza).

## Obiettivo

Ridurre ulteriormente il tempo tra la fine del parlato dell'utente e la prima
parola udibile di Eidos, partendo con la generazione **prima** che scada
l'endpointing di Deepgram (300ms), scommettendo su un transcript parziale
quando sembra stabile. Guadagno atteso: ~0,3-0,5s per turno.

## Perché serve un cambio di protocollo (non solo un timer lato client)

Se il tentativo speculativo si rivela sbagliato (l'utente continua a
parlare), va **interrotto** — non solo ignorato: lasciare che il modello
finisca di generare in background sprecherebbe token e, soprattutto,
lascerebbe una risposta "fantasma" nella cronologia conversazionale del
motore persistente (`orchestratore/agente.py`), confondendo i turni
successivi.

Il futuro barge-in (Tappa 6, incremento successivo non ancora pianificato in
dettaglio: interrompere Eidos mentre parla) ha lo stesso identico bisogno.
Questo incremento costruisce il meccanismo di interruzione in modo generico,
riusabile da entrambi — ma **implementa solo lo speculativo**: il barge-in
vero (rilevare la voce dell'utente sopra l'audio in uscita) resta un
incremento a parte, deciso esplicitamente con l'utente (vedi "Fuori ambito").

## Verifica preliminare (obbligatoria prima del design, CLAUDE.md)

Il Claude Agent SDK documenta `ClaudeSDKClient.interrupt()` solo in un
pattern sequenziale (stesso task: query → sleep → interrupt → drain →
query). Nessuna doc ufficiale conferma o esclude esplicitamente l'uso da un
task concorrente diverso da quello che sta consumando `receive_response()`.

Verificato con un **esperimento reale isolato** (non simulato, API vera,
2026-07-19, script in `C:\Users\ghila\AppData\Local\Temp\claude\...\scratchpad\esperimento_interrupt.py`,
non nel repo):

- Task A: `query()` + itera `receive_response()` di un turno lungo
  ("conta da 1 a 200").
- Task B: dopo un ritardo (verificato sia prima che l'output cominciasse,
  sia a metà streaming attivo con decine di token già arrivati), chiama
  `client.interrupt()` sulla STESSA istanza, in concorrenza.
- Risultato in **entrambi i casi**: nessuna eccezione né in A né in B; Task A
  riceve pulito un `ResultMessage(subtype="error_during_execution",
  is_error=True)` e la sua iterazione termina da sola; il client resta
  **immediatamente riusabile** per un turno successivo pulito.

**Conclusione**: il pattern "task in background genera, un secondo pezzo di
codice lo interrompe da fuori quando serve" è sicuro. Non serve una macchina
a stati con tutto sequenziale in un solo task — si riusa lo stesso schema
già in produzione per la corsa ponte/agente in `router.py` (`chat_stream`),
aggiungendo solo la capacità di chiamare `interrupt()` sul task in corso.

## Protocollo

`/chat/stream` passa da richiesta HTTP singola (POST, SSE in risposta) a
**connessione WebSocket**, una per sessione vocale (aperta quando parte
`python -m voce`, chiusa all'uscita — non una per turno: evita il costo di
riconnessione a ogni scambio).

**Client → server**, un messaggio per ogni aggiornamento della trascrizione:
```json
{"tipo": "parziale", "testo": "che impegni ho domani"}
{"tipo": "finale", "testo": "che impegni ho domani"}
```

**Server → client**, stessi eventi di oggi più uno nuovo:
```json
{"evento": "ponte", "testo": "..."}
{"evento": "tool_in_corso", "tool": "..."}
{"evento": "delta", "testo": "..."}
{"evento": "fine", "risposta": "...", "azione_in_attesa": null}
{"evento": "errore", "messaggio": "..."}
{"evento": "annullato"}
```

`annullato`: il tentativo in corso (quello a cui il client sta forse già
dando voce) non conta più — il client deve fermare immediatamente qualunque
audio/TTS per quel tentativo, senza pronunciarne altro.

## Euristica "sembra completa" (lato client)

Puro timer, nessuna dipendenza da comportamenti non verificati di Deepgram
(es. punteggiatura sugli interim, non garantita): se il transcript ricevuto
da Deepgram **non cambia per ~300-400ms**, si manda come `parziale` al
server — è il segnale che innesca la scommessa. Criterio prudente (deciso
con l'utente, 2026-07-19): non punteggiatura, non euristiche testuali
aggressive — solo stabilità nel tempo, testabile in modo puro (mock del
tempo, nessuna dipendenza da audio reale).

## Logica server per un turno (orchestratore/router.py, endpoint WS)

1. Primo `parziale` ricevuto (e nessun tentativo già in corso) → parte un
   task in background che esegue `motore.turno(testo, canale="voce")`,
   inoltrando `ponte`/`tool_in_corso`/`delta` al client come già avviene
   oggi (stesso schema a coda di `chat_stream`).
2. Il server continua ad ascoltare nuovi messaggi dal client MENTRE il
   tentativo gira (`asyncio.wait` su: prossimo messaggio WS in arrivo,
   prossimo evento dal task del motore).
3. Se arriva un `parziale` o un `finale` con testo che **aggiunge parole
   nuove** rispetto a quello su cui gira il tentativo corrente → si chiama
   `interrupt()` sul client del motore (sicuro, verificato sopra), si manda
   `annullato` al client, si scarta ogni output residuo del tentativo
   vecchio, si riparte dal punto 1 con il nuovo testo.
4. Se arriva `finale` e il confronto **normalizzato** (minuscolo, senza
   punteggiatura finale, spazi collassati) ha la stessa sequenza di parole
   del testo su cui il tentativo in corso sta già generando → nessun
   riavvio: si lascia proseguire, si manda `fine` a completamento. È qui
   che si guadagna il tempo (l'endpointing di Deepgram e la generazione si
   sono sovrapposti). Il confronto **non è stringa esatta**: Deepgram
   spesso "ripulisce" il transcript finale (maiuscole, punteggiatura,
   formattazione numeri) anche senza che l'utente abbia aggiunto parole —
   uno stringa-per-stringa esatto butterebbe via quasi ogni tentativo per
   differenze cosmetiche, vanificando il guadagno.
5. Se arriva `finale` senza che nessun tentativo sia mai partito (frase
   troppo corta per il timer di stabilità) → parte ora, comportamento
   identico a oggi.

Il gate di conferma sulle azioni distruttive, il ponte, il vincolo di
brevità in voce: **invariati**, si applicano al tentativo qualunque esso sia
(speculativo o no) — nessuna eccezione per i tentativi "scommessa".

## Client (voce/client.py, voce/stt.py)

- La connessione WS si apre una volta, resta aperta per tutta la sessione
  vocale (non più un POST per turno).
- `stt.py` espone gli interim al chiamante (già lo fa per la trascrizione
  live); il client li inoltra al WS come `parziale` non appena stabili per
  il tempo soglia, e come `finale` a `speech_final`.
- Su `ponte`/`delta`/`tool_in_corso`: comportamento identico a oggi
  (pronuncia via `tts.py`, cronometro `(tempi: ...)`).
- Su `annullato`: ferma immediatamente la sessione TTS del tentativo
  corrente (se ha già iniziato a suonare qualcosa, taglia — non dovrebbe
  succedere quasi mai col criterio prudente, ma va gestito), resta in
  ascolto in silenzio del tentativo successivo.

## Cosa NON cambia

- `/chat` testuale resta un POST semplice, non tocca il WebSocket.
- Motore persistente, ponte, cache OAuth/HTTP, thinking adaptive: invariati.
- Gate di conferma sulle azioni distruttive: invariato, si applica a valle
  di qualunque tentativo (speculativo o no).

## Fuori ambito (esplicitamente rimandato)

- Barge-in vero (rilevare la voce dell'utente sopra l'audio in uscita di
  Eidos): il meccanismo di interruzione costruito qui è generico e
  riusabile, ma il rilevamento "l'utente sta parlando mentre Eidos parla"
  (VAD durante `speaking`, gestione eco/AEC) è un incremento a parte, non
  ancora disegnato in dettaglio.
- Riempitivi locali: restano dietro il flag `EIDOS_VOCE_RIEMPITIVI` (off di
  default, deciso il 2026-07-17), non toccati da questo incremento.
- Ottimizzazione ulteriore della soglia di stabilità (300-400ms): il valore
  iniziale è una scelta prudente, si ritara con l'uso reale se necessario.

## Test da coprire

- Server (fake SDK client, stesso schema di `test_chat_stream.py`):
  - `parziale` stabile avvia un tentativo in background
  - `parziale`/`finale` con parole nuove durante un tentativo → interrupt +
    `annullato` + riavvio con nuovo testo
  - `finale` che combacia (confronto normalizzato, non stringa esatta) col
    tentativo in corso → nessun riavvio, `fine` regolare
  - `finale` con sola differenza cosmetica (maiuscole/punteggiatura) →
    nessun riavvio (trappola esplicita: senza questo test un fix futuro
    potrebbe reintrodurre il confronto a stringa esatta per errore)
  - `finale` senza tentativo precedente → parte normalmente
  - azione pendente/errori: stesso comportamento di oggi, applicato al
    tentativo attivo qualunque esso sia
- Client: euristica di stabilità (timer puro, mock del tempo), gestione
  `annullato` (ferma TTS, non pronuncia nulla del tentativo scartato)
- STOP 2 (prova reale): frase detta tutta d'un fiato (guadagno atteso),
  frase con ripensamento a metà ("che impegni ho doma— anzi dopodomani",
  verifica che non si senta mai la risposta sbagliata)
