> **Bozza non ancora decisa** — da riprendere come spunto (non vincolante) al design
> della **Tappa 6 — Voce** in ROADMAP.md. Riconfermare o cambiare a quel punto, non dare
> per acquisita (vedi CLAUDE.md, "Idee non ancora decise → notes/").

# SPEC — Pipeline vocale (wake word, STT, TTS, latenza, interruzioni)

> Documento di specifica per l'implementazione della voce. Definisce l'intera
> catena audio: dall'ascolto continuo alla risposta parlata, con budget di
> latenza, gestione delle interruzioni e degli errori. Ogni regola è vincolante;
> in caso di dubbio implementativo, vince questo file.
>
> Documenti correlati: `PANELS_SPEC.md` (la sincronizzazione voce↔pannelli è al §7).

---

## 0. Obiettivo di esperienza

La voce deve sembrare una **conversazione**, non un walkie-talkie. Tre proprietà
non negoziabili:

1. **Prima parola della risposta entro ~1 s** dalla fine della frase dell'utente.
   Oltre 1,5 s la percezione passa da "dialogo" a "attesa di un computer".
2. **Nessuna parola persa**, mai — nemmeno al primo comando a freddo, nemmeno
   se l'utente parla tutto d'un fiato senza pausa dopo la wake word.
3. **Interrompibile**: se l'utente parla sopra la risposta, Jarvis tace e ascolta
   (barge-in). Un assistente che non si può interrompere è un registratore.

---

## 1. Architettura della catena

```
                    ┌─────────────────────────────────────────┐
 mic (sempre on) ──▶│ RING BUFFER 2s │──▶ wake word detector   │
                    │  (circolare)   │     (openWakeWord /     │
                    └───────┬────────┘      Porcupine, locale) │
                            │ trigger                          │
                            ▼                                  │
                    ┌──────────────────┐                       │
                    │ Deepgram STT     │  WebSocket SEMPRE     │
                    │ streaming        │  aperto (KeepAlive)   │
                    └───────┬──────────┘                       │
                            │ transcript (interim + final)     │
                            ▼                                  │
                    ┌──────────────────┐                       │
                    │ LLM streaming    │──▶ comandi pannello ──┼─▶ HUD (WebSocket)
                    │ + tool calling   │                       │
                    └───────┬──────────┘                       │
                            │ testo a frasi                    │
                            ▼                                  │
                    ┌──────────────────┐                       │
                    │ TTS streaming    │──▶ casse ◀── barge-in ┘
                    └──────────────────┘     (stop immediato se
                                              l'utente riparla)
```

Tutti gli stadi sono in **streaming e in parallelo**: nessuno aspetta che il
precedente abbia finito. È qui che si vince o si perde la latenza.

---

## 2. Cattura audio e ring buffer

### Regole

- Il microfono cattura **sempre**, in chunk da 32–64 ms (16 kHz, 16 bit, mono —
  il formato che wake word e Deepgram digeriscono nativamente).
- Ogni chunk finisce in un **buffer circolare da ~2 s** (`deque(maxlen=...)`),
  indipendentemente da tutto il resto. Il buffer esiste PRIMA e A PRESCINDERE
  dalla wake word.

### Perché è vincolante

La wake word viene riconosciuta con 200–500 ms di ritardo rispetto a quando è
stata pronunciata, e l'utente spesso non fa pausa: "Jarvis che tempo fa domani"
è un'unica emissione. Senza buffer, le prime parole del comando sono perse.

### Comportamento al trigger

```python
from collections import deque
ring = deque(maxlen=32)          # ~2 s di chunk da 64 ms

def on_audio_chunk(chunk):
    ring.append(chunk)
    if wake_detector.process(chunk):
        # invia PRIMA il pregresso: dall'audio ~0.5 s precedente al trigger
        for old in backfill(ring, seconds_before=0.5):
            stt_ws.send(old)
        session.streaming = True # da qui in poi: chunk live direttamente a STT
```

- `seconds_before=0.5` è il default; regolabile 0.3–0.8 in config.
- Il buffer NON si svuota mai del tutto: continua a riempirsi anche durante lo
  streaming (serve per il barge-in, §6).

---

## 3. Wake word

- **Locale, sempre** (openWakeWord o Porcupine). Mai in cloud: deve funzionare
  offline, senza latenza di rete, e senza inviare audio continuo a terzi.
- Soglia di confidenza configurabile. Default prudente: meglio un falso negativo
  (l'utente ripete) che falsi positivi (Jarvis si attiva da solo → erosione
  immediata della fiducia).
- **Feedback di attivazione obbligatorio e istantaneo** (< 100 ms dal trigger):
  il nucleo dell'HUD passa a stato `listening` + un chirp audio brevissimo e
  discreto. L'utente DEVE sapere di essere ascoltato prima di finire la frase.
- **Modalità conversazione** (follow-up senza wake word): dopo che Jarvis ha
  finito di rispondere, il microfono resta in ascolto attivo per una finestra
  di **6 s** (configurabile). Se l'utente riparla in quella finestra, è un
  follow-up: niente "Jarvis" richiesto. Il nucleo resta in un `listening`
  attenuato per segnalarlo. Scaduta la finestra → torna il requisito wake word.
  Comando "basta così / grazie" chiude la finestra subito.

---

## 4. STT (Deepgram) — connessione e parametri

### Connessione sempre calda

- Il WebSocket verso Deepgram si apre **all'avvio del sistema** e non si chiude
  mai volontariamente.
- Ogni **5 s** di inattività audio si invia `{"type": "KeepAlive"}` (il timeout
  Deepgram è 10 s). Deepgram fattura l'audio inviato, non il tempo di
  connessione: tenere il canale aperto costa zero.
- **Watchdog di riconnessione**: se la connessione cade, riconnessione con
  backoff (0.5 s, 1 s, 2 s, max 10 s). Durante la riconnessione il ring buffer
  continua ad accumulare: alla riapertura si fa backfill di quanto perso.
  Se un comando arriva a connessione caduta → l'audio va comunque nel buffer,
  e appena il canale torna vivo viene trascritto. Perdita parole: zero.

### Parametri obbligatori

```
model=nova-2 (o superiore)   language=it (o multi)
interim_results=true         endpointing=300
smart_format=true            vad_events=true
encoding=linear16            sample_rate=16000
```

- `interim_results=true`: trascrizioni parziali in tempo reale → alimentano la
  **trascrizione live sull'HUD** (l'utente vede che è stato capito mentre parla,
  e può correggersi).
- `endpointing=300`: Deepgram segnala la fine frase dopo ~300 ms di silenzio →
  è QUESTO evento (`speech_final`) che fa partire l'LLM, non timeout arbitrari.
  Con 300 ms si guadagnano 500–1000 ms percepiti rispetto a soglie ingenue.
- Taratura: 300 ms va bene per comandi; se l'utente detta testi lunghi con pause
  di pensiero, valutare 500 ms in un profilo "dettatura".

---

## 5. LLM e TTS in streaming

### LLM

- La richiesta parte **al `speech_final`**, con il transcript completo del turno.
- La risposta si consuma **in streaming**. Due flussi si separano dallo stream:
  - **testo** → spezzato a frasi (split su `. ! ? :` + lunghezza minima) e
    inviato frase per frase al TTS;
  - **comandi pannello** (tool call `show_panel`) → inoltrati all'HUD APPENA
    compaiono nello stream, senza aspettare la fine della generazione
    (sincronizzazione voce↔visual, §7).

### TTS

- **Streaming, a frasi**: la prima frase va in sintesi mentre l'LLM genera le
  successive. La coda audio si riempie dietro la riproduzione.
- Scelte: ElevenLabs (qualità massima, streaming websocket) o Piper (locale,
  gratuito, latenza minima; qualità inferiore ma accettabile). L'interfaccia
  del modulo TTS deve essere astratta: `speak_stream(sentences) / stop()` —
  cambiare motore non deve toccare il resto.
- Mentre il TTS suona: nucleo HUD in stato `speaking`.
- **Sanificazione del testo per il TTS**: rimuovere markdown, emoji, sigle da
  espandere (es. "km/h" → "chilometri orari"). Il testo mostrato a schermo e
  quello pronunciato POSSONO divergere: lo schermo mostra "21°C", la voce dice
  "ventuno gradi".

### Budget di latenza (fine frase utente → prima parola di Jarvis)

| Stadio | Target | Note |
|---|---|---|
| Endpointing Deepgram | ~300 ms | fisso, è il parametro |
| Primo token LLM | 200–400 ms | modello veloce per il routing vocale |
| Prima frase completa | 300–500 ms | dipende dalla lunghezza frase |
| TTS time-to-first-byte | 150–300 ms | ElevenLabs streaming / Piper locale |
| **Totale** | **~0.95–1.5 s** | target: sotto 1.2 s nel caso mediano |

Se un tool call lungo (ricerca web, mail) sfora il budget: Jarvis pronuncia un
**riempitivo breve** ("Un momento, controllo…") generato subito, POI la risposta
vera. Mai silenzio oltre ~1.5 s: il silenzio non segnalato è percepito come rottura.

---

## 6. Barge-in (interruzione) — vincolante

L'utente può parlare sopra Jarvis in qualunque momento, e Jarvis deve cedere.

### Meccanica

1. **Durante lo stato `speaking`**, il VAD (voice activity detection — quello di
   Deepgram via `vad_events`, o webrtcvad locale) resta attivo sul microfono.
2. Voce utente rilevata per > 250 ms continuativi (soglia anti-falsi-positivi:
   colpi di tosse, rumori) →
   - **stop TTS immediato** (fade-out 100 ms, non taglio secco),
   - flush della coda TTS e **annullo della generazione LLM** ancora in corso,
   - nucleo → `listening`,
   - l'audio utente (già nel ring buffer dal primo istante) va a Deepgram.
3. Il nuovo turno dell'utente viene processato normalmente. Nel contesto LLM si
   annota che la risposta precedente è stata interrotta a metà (il modello deve
   sapere cosa l'utente HA sentito e cosa no).

### Il problema dell'eco (critico, da risolvere subito)

Il microfono sente le casse: senza contromisure, Jarvis si interrompe da solo
sentendo la propria voce. Difese in ordine di preferenza:

1. **AEC (echo cancellation)**: usare l'AEC di sistema (PulseAudio/PipeWire
   `echo-cancel`, o il modulo AEC di WebRTC). È la soluzione giusta.
2. In aggiunta: durante `speaking`, alzare la soglia VAD e ignorare rilevazioni
   che correlano col segnale in uscita.
3. Fallback povero (solo per prototipo): half-duplex — barge-in disattivato,
   si accetta di non poter interrompere. Da segnare come debito tecnico.

### Comandi di corridoio

Alcune parole durante `speaking` sono comandi di controllo, non nuovi turni:
"stop / basta / zitto" → tace e basta, senza inviare nulla all'LLM.
Riconoscerli sul transcript interim con match diretto, latenza minima.

---

## 7. Sincronizzazione voce ↔ HUD

- Il comando `show_panel` parte verso l'HUD **appena il tool call compare nello
  stream LLM** — tipicamente questo fa apparire il pannello in coincidenza con
  l'inizio del parlato. Voce e visual percepiti come un gesto unico (regola del
  timing, `PANELS_SPEC.md`).
- Stati del nucleo comandati dalla pipeline, sempre coerenti con l'audio:

| Evento pipeline | Stato nucleo |
|---|---|
| Wake word trigger / finestra follow-up | `listening` |
| `speech_final` ricevuto | `processing` |
| Primo byte audio TTS in riproduzione | `speaking` |
| Coda TTS vuota + LLM chiuso | `idle` (o `listening` attenuato se finestra follow-up) |

- La **trascrizione live** sull'HUD usa gli interim results: si aggiorna a ogni
  parziale, si consolida al final. La risposta di Jarvis compare a schermo in
  streaming, sincronizzata a grandi linee col parlato (per frase, non per parola:
  la sincronizzazione per parola non vale la complessità).

---

## 8. Gestione errori — l'utente non vede mai uno stack trace

| Guasto | Comportamento |
|---|---|
| Deepgram irraggiungibile | Buffer continua ad accumulare; riconnessione con backoff; se > 5 s: "Ho un problema di connessione, un momento" + dot di stato HUD in ambra |
| LLM timeout / errore | "Non sono riuscito a elaborare, può ripetere?" — MAI silenzio |
| TTS giù | Fallback a TTS locale (Piper) se configurato; altrimenti la risposta appare almeno a schermo, con avviso |
| Trascrizione confidenza bassa | L'LLM riceve il transcript col flag low-confidence e può chiedere conferma ("Ha detto di spegnere TUTTE le luci?") per azioni con effetti |
| Wake word in loop (falsi trigger ripetuti) | Dopo 3 attivazioni senza speech nel giro di 1 min → alza soglia temporaneamente e logga |

Regola generale: **ogni guasto ha una voce**. Il silenzio non spiegato è il
peggior messaggio d'errore possibile.

---

## 9. Privacy e controllo

- Wake word e VAD girano **in locale**: nessun audio lascia la macchina finché
  la wake word non è scattata (più il backfill di 0.5 s).
- Comando vocale e fisico per il **mute totale** ("Jarvis, smetti di ascoltare"
  / tasto): microfono chiuso a livello di cattura, dot HUD spento, riattivazione
  SOLO fisica o da UI — non vocale, ovviamente.
- Log audio: di default NON si salvano le registrazioni; si salvano solo i
  transcript (servono alla memoria). Config esplicita per cambiare.

---

## 10. Criteri di accettazione (test manuali)

- [ ] A sistema appena avviato, "Jarvis che tempo fa" detto tutto d'un fiato →
      il transcript contiene la frase COMPLETA, incluse le prime parole
- [ ] Ripetere il test dopo 30 min di inattività → identico (KeepAlive funziona)
- [ ] Cronometro: fine frase → prima parola di Jarvis < 1.5 s (mediana < 1.2 s)
- [ ] Mentre Jarvis parla, dire "aspetta" → tace entro ~350 ms e ascolta
- [ ] Jarvis NON si interrompe mai da solo sentendo la propria voce dalle casse
      (test a volume alto)
- [ ] Risposta a domanda dopo risposta, senza ridire "Jarvis", entro 6 s → funziona
- [ ] Staccare la rete, dare un comando, riattaccarla → il comando viene
      processato, nessuna parola persa
- [ ] "Jarvis, smetti di ascoltare" → nessuna reazione a qualunque comando
      vocale successivo, finché non riattivato fisicamente
- [ ] La trascrizione live appare sull'HUD MENTRE si parla, non alla fine

---

## 11. Struttura moduli suggerita

```
voice/
├── capture.py        # mic loop, ring buffer, resampling
├── wakeword.py       # openWakeWord/Porcupine wrapper, soglie, cooldown
├── stt.py            # client Deepgram: WS persistente, KeepAlive, backfill,
│                     #   riconnessione, eventi interim/final/speech_final
├── llm.py            # streaming, split a frasi, estrazione tool call
├── tts.py            # interfaccia astratta speak_stream()/stop(),
│                     #   backend elevenlabs.py / piper.py, sanificazione testo
├── bargein.py        # VAD durante speaking, AEC hooks, comandi di corridoio
├── orchestrator.py   # macchina a stati (idle/listening/processing/speaking),
│                     #   budget latenza, riempitivi, finestra follow-up
└── config.yml        # soglie, timeout, modelli, profili (comandi/dettatura)
```

L'`orchestrator` è l'unico che conosce gli stati e parla con l'HUD; gli altri
moduli sono sostituibili singolarmente (cambiare STT o TTS non tocca nient'altro).
