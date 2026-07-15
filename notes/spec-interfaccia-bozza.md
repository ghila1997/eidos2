> **Bozza non ancora decisa** — da riprendere come spunto (non vincolante) al design
> della **Tappa 7 — Interfaccia Utente** in ROADMAP.md. Riconfermare o cambiare a quel
> punto, non dare per acquisita (vedi CLAUDE.md, "Idee non ancora decise → notes/").

# SPEC — Sistema pannelli HUD (nature, ciclo di vita, focus)

> Documento di specifica per l'implementazione. Definisce le tre nature dei pannelli,
> le regole di layout e la macchina a stati del focus. Ogni regola qui dentro è
> vincolante: in caso di dubbio implementativo, vince questo file.

---

## 0. Il test di necessità — quando NON mostrare nulla

**Questa regola viene PRIMA di tutte le altre.** La voce è il canale primario di
risposta. Il pannello è l'eccezione, e deve guadagnarsi il posto. Il default per
ogni interazione è: **risposta solo vocale, schermo intatto.**

Perché è vincolante: l'identità visiva dell'HUD è "vuoto finché non serve". Se ogni
frase produce un pannello, il vuoto sparisce, i pannelli importanti annegano tra
quelli inutili, e l'interfaccia degenera in una bacheca di notifiche. Un pannello
non necessario non è neutro: è un danno.

### Il test (una domanda sola)

> **"Il visual aggiunge qualcosa che la voce non può dare in modo efficiente?"**
>
> Se la risposta vocale è completa e memorizzabile da sola → NESSUN pannello.

### Criteri che GIUSTIFICANO un pannello

Un pannello nasce solo se la risposta ricade in almeno uno di questi casi:

1. **Densità** — più di 2-3 dati da confrontare o ricordare insieme.
   Il calendario della giornata letto a voce è una litania che si dimentica;
   a schermo è un colpo d'occhio.
2. **Andamento** — trend, serie, confronti nel tempo.
   "Meteo del weekend": tre giorni di temperature a voce evaporano, in un
   grafico restano.
3. **Persistenza temporale** — processi che vivono nel tempo (timer, download,
   render, musica). La voce non può "restare" a mostrare l'avanzamento.
4. **Contenuto intrinsecamente visivo** — immagini, video, documenti, modelli
   3D, stream di finestre. Non esiste versione vocale.
5. **Dati da trascrivere o riusare** — un indirizzo, un codice, un numero di
   telefono, un link. La voce li dà, il pannello li lascia copiare.

### Esempi vincolanti — SOLO VOCE

| Richiesta | Risposta | Perché niente pannello |
|---|---|---|
| "Che ore sono?" | "Sono le 15:20" | Un dato singolo, già consumato |
| "Accendi le luci del soggiorno" | "Fatto" | L'effetto si vede nella stanza; la conferma visiva è ridondante |
| "Quanto fa 340 per 12?" | "4.080" | Un numero si dice |
| "Che tempo fa domani?" | "Domani 21 gradi, nuvoloso" | 1-2 dati: la voce basta (≠ meteo settimana) |
| "Domani ho impegni la mattina?" | "Uno solo, alle 9:30" | Risposta sì/no + un dato |
| "Metti un promemoria per le 18" | "Promemoria alle 18, fatto" | Conferma di azione |
| Conversazione, opinioni, domande generiche | voce | Non c'è dato strutturato da mostrare |

### Esempi vincolanti — PANNELLO GIUSTIFICATO

| Richiesta | Criterio | Pannello |
|---|---|---|
| "Mostrami il calendario di oggi" | Densità (4+ eventi) | effimero calendar |
| "Meteo del weekend" | Andamento | effimero weather multi-giorno |
| "Timer 5 minuti" | Persistenza | persistente timer |
| "Metti musica" | Persistenza | persistente now-playing |
| "Fammi vedere quella mail" | Contenuto visivo | focus mail |
| "Che indirizzo ha il ristorante?" | Da trascrivere | effimero text (voce + pannello) |

### Casi borderline — come decidere

- **Meteo di domani**: solo voce. **Meteo della settimana**: pannello. La soglia
  è la densità, non l'argomento.
- **"Ho mail nuove?"** → "Due, da Marco e da Anna" = solo voce. **"Di cosa
  parlano?"** → anteprima a pannello (densità).
- **Conferme di azioni domotiche**: solo voce, SEMPRE — con un'eccezione: se
  l'azione è ambigua o rischiosa ("spegni tutto"), un effimero da 6 s che elenca
  cosa è stato spento ha valore di verifica.
- In dubbio → **solo voce**. Il costo dell'errore è asimmetrico: un pannello
  mancato si recupera in un secondo con l'override (sotto); un pannello inutile
  ha già sporcato lo schermo.

### L'override dell'utente (obbligatorio)

L'utente può sempre forzare la materializzazione: **"fammi vedere" / "mostramelo"**
detto dopo una risposta vocale genera il pannello di quel contenuto (l'LLM tiene
il contesto dell'ultimo turno, quindi sa cosa mostrare). Simmetricamente "chiudi" /
"non serve" congeda qualsiasi pannello.

Questo override è ciò che rende sicuro il default conservativo: sbagliare verso
il silenzio visivo costa un solo comando vocale.

### Implementazione

Il test vive nel **system prompt dell'LLM**, non in codice: si include questa
sezione (criteri + esempi) e si lascia decidere il modello caso per caso. Il tool
`show_panel` deve dichiarare nella sua descrizione: *"Usa SOLO se la risposta
supera il test di necessità (§0). Il default è rispondere senza pannello."*

---

## 1. Le tre nature — definizione

Ogni pannello ha esattamente una `nature`, dichiarata alla creazione e immutabile.

| | EFFIMERO | PERSISTENTE | FOCUS |
|---|---|---|---|
| **Cos'è** | Una risposta visiva a una domanda | Lo stato di un processo in corso | Il contenuto su cui l'utente sta lavorando |
| **Vita legata a** | Il tempo (timeout) | Il processo (finché è vivo) | L'attenzione dell'utente (finché non lo chiude) |
| **Chi lo chiude** | Timer automatico | La fine del processo | SOLO comando esplicito dell'utente |
| **Dimensione** | Piccolo (~320px) | Piccolo (~320px) | Grande (area centrale dominante) |
| **Zona** | Destra | Sinistra | Centro (o dock se retrocesso, v. §4) |
| **Max simultanei** | 2 | Illimitati (in pratica 2-3) | 1 al centro + N nel dock |
| **Può essere sfrattato** | Sì, dal più nuovo | MAI da un effimero | Mai chiuso, solo retrocesso |
| **Timeout default** | 10–20 s | Nessuno | Nessuno |

### Il test per classificare (da usare nel prompt dell'LLM)

Per decidere la natura, rispondere a UNA domanda:

- *"Tra 30 secondi questo pannello servirà ancora?"* → **NO** = effimero
- *"C'è un processo che sta ancora girando?"* → **SÌ** = persistente
- *"L'utente lo sta guardando/usando attivamente per lavorare?"* → **SÌ** = focus

---

## 2. Esempi concreti per natura

### EFFIMERI — "rispondi e sparisci"

| Richiesta utente | Pannello | Timeout |
|---|---|---|
| "Che tempo fa domani?" | Meteo con temperatura grande | 18 s |
| "Quanto fa 340 per 12?" | Risultato calcolo | 10 s |
| "Ho mail da Marco?" | Anteprima lista mail (3 righe) | 15 s |
| "Accendi le luci" | Conferma "Luci soggiorno: ON" | 6 s |
| "Che ore sono a Tokyo?" | Orologio fuso orario | 10 s |

Caratteristica chiave: **la voce ha già dato la risposta**. Il pannello è un rinforzo
visivo, non il canale primario. Se sparisce troppo presto non si perde nulla.

### PERSISTENTI — "vivo finché il processo è vivo"

| Richiesta utente | Pannello | Muore quando |
|---|---|---|
| "Timer 5 minuti" | Countdown live | Il timer scade (+5 s di "Completato") |
| "Metti musica" | Now playing + equalizzatore | La riproduzione si ferma |
| "Renderizza la scena" | Barra avanzamento render | Il render finisce (→ può promuoversi, v. §5) |
| "Scarica quel file" | Progress download | Download completo |
| Registrazione attiva | Indicatore REC + durata | Stop registrazione |

Caratteristica chiave: **rappresentano qualcosa che sta ANCORA accadendo**. Chiuderli
non ferma il processo (la musica continua), ma l'utente perde la visibilità — per
questo un effimero non può mai sfrattarli.

### FOCUS — "il mio lavoro, non toccarlo"

| Richiesta utente | Contenuto | Note |
|---|---|---|
| "Mostrami la scena di Blender" | Stream WebRTC della finestra | Livello 2 |
| "Apri il modello 3D" | glTF in Three.js, ruotabile | Livello 3, effetto ologramma |
| "Fammi vedere quella mail" | Mail completa, leggibile | — |
| "Mostrami il documento" | Testo/PDF scrollabile | — |
| "Apri la dashboard vendite" | Grafico grande interattivo | — |

Caratteristica chiave: **è il contenuto, non un riassunto del contenuto**. L'utente
ci interagisce (legge, ruota, osserva). Perderlo per un evento automatico è il bug
più grave possibile del sistema.

### Casi ambigui — come si risolvono

- **"Mostrami il calendario"** → effimero (lista compatta, 20 s). Ma **"apri il
  calendario, devo organizzare la settimana"** → focus. La differenza è l'intenzione
  di *lavorarci*. In dubbio: effimero, con possibilità di promozione (§5).
- **Notifica "nuova mail da Marco"** → effimero proattivo (zona avvisi, ambra).
  Se l'utente dice "aprila" → si promuove a focus.
- **Videochiamata in arrivo** → focus critico (scavalca tutto, v. §4.3).

---

## 3. Schema messaggio (LLM → server → HUD)

```json
{
  "action": "show",
  "nature": "ephemeral | persistent | focus",
  "type": "weather | calendar | timer | music | mail | media | stream | model3d | text",
  "id": "weather-tomorrow",
  "data": { },
  "ttl": 18,
  "priority": 1
}
```

Regole:
- `id` deterministico per tipo+soggetto: serve alla **deduplicazione** — se arriva
  uno `show` con `id` già vivo, si AGGIORNA il pannello esistente (animazione refresh
  di ~200ms), non se ne crea un secondo.
- `ttl` solo per effimeri. Se assente: default 15. Ignorato per le altre nature.
- `priority`: 0=decorativo, 1=contestuale, 2=richiesta esplicita, 3=critico.
- L'LLM può anche emettere `{"action": "dismiss", "id": "..."}` o
  `{"action": "dismiss", "nature": "ephemeral"}` quando il tema della conversazione
  cambia (congedo contestuale).

**Il layout manager (server) decide posizione, dimensione e sfratti. L'LLM non
controlla MAI il layout — solo natura, tipo, dati.**

---

## 4. Macchina a stati del FOCUS

Il punto centrale della spec: **un focus non muore quando perde il centro — si
sposta.** Retrocede in una posizione secondaria e resta vivo.

### 4.1 Stati

```
                promote()
   ┌──────────┐ ────────▶ ┌──────────┐
   │  CENTER   │           │  DOCKED  │   (miniatura PiP in basso a dx,
   │  grande,  │ ◀──────── │  viva e  │    oppure tab laterale dal 3° in poi)
   │ dominante │  demote() │aggiornata│
   └────┬─────┘           └────┬─────┘
        │                      │
        └──── close() ─────────┘──▶ CLOSED
              (SOLO esplicito: "chiudi il render",
               tocco sulla ✕, o fine naturale del processo)
```

### 4.2 Transizioni

| Evento | Effetto |
|---|---|
| Nuovo focus richiesto, centro libero | Nuovo → CENTER |
| Nuovo focus richiesto, centro occupato | Nuovo → CENTER, vecchio → DOCKED (chi parla per ultimo vince il centro) |
| 2 focus richiesti nello STESSO turno ("mostrami A e B") | Split view: centro diviso a metà. Limite: 2. |
| 3° focus in poi | DOCKED come tab con titolo |
| "Jarvis, scambia" | CENTER ↔ primo DOCKED |
| "Mostrami di nuovo X" (X è docked) | X → CENTER, l'attuale → DOCKED |
| Focus `priority: 3` (chiamata, allarme) | Scavalca: prende CENTER, tutti gli altri → DOCKED. Nessuno muore. |
| "Chiudi X" / ✕ / processo terminato | X → CLOSED, il DOCKED più recente può risalire a CENTER (chiedere se ambiguo) |

### 4.3 Regole ferree

1. `demote()` NON è `close()`. Mai distruggere un focus per far spazio.
2. Un focus DOCKED continua a ricevere aggiornamenti (lo stream resta connesso,
   il documento mantiene la posizione di scroll).
3. Durante uno split o con un focus a CENTER: gli effimeri si auto-limitano a
   max 1, gli avvisi proattivi sono SOSPESI (accodati, mostrati a focus chiuso).
4. Se la richiesta multipla è ambigua ("aprimi il progetto e le mail"), Jarvis
   CHIEDE: "Affiancati o uno alla volta?" — un turno di voce costa meno di un
   layout sbagliato.

---

## 5. Promozioni e retrocessioni tra nature

I pannelli possono cambiare ruolo seguendo l'intenzione dell'utente:

- **effimero → focus**: "aprila" detto su un'anteprima mail → il pannellino si
  espande animandosi verso il centro (non spawn di un pannello nuovo: è LO STESSO
  pannello che cresce — continuità visiva).
- **persistente → focus**: il render finisce → il pannello progress mostra
  l'anteprima; "fammela vedere" → si promuove a focus col PNG pieno.
- **focus → effimero di conferma**: alla chiusura di un focus con azione compiuta
  ("invia la mail" da un focus mail) → il focus si chiude e nasce un effimero
  di conferma da 6 s.

---

## 6. Criteri di accettazione (test manuali)

- [ ] "Che ore sono?" → risposta SOLO vocale, nessun pannello
- [ ] "Accendi le luci del soggiorno" → "Fatto" a voce, schermo intatto
- [ ] "Che tempo fa domani?" → solo voce; "meteo del weekend" → pannello
- [ ] Dopo una risposta solo vocale, "fammi vedere" → appare il pannello
      relativo a quel contenuto
- [ ] Chiedo il meteo due volte di fila → UN solo pannello, che si aggiorna
- [ ] Avvio un timer, poi chiedo meteo, calendario, una ricerca → il timer non
      viene MAI sfrattato
- [ ] Apro lo stream di Blender, poi dico "mostrami la mail di Marco" → la mail
      va al centro, Blender scala in PiP ancora live, nessuno dei due muore
- [ ] "Jarvis, scambia" → i due si invertono con animazione < 400 ms
- [ ] Chiudo la mail → Blender torna al centro
- [ ] Con un focus attivo arriva una notifica proattiva → NON appare; appare
      dopo la chiusura del focus
- [ ] Cambio argomento di conversazione → gli effimeri del tema precedente si
      congedano entro qualche secondo
- [ ] Nessuna combinazione di comandi porta a più di: 1 centro (o split da 2)
      + 2 laterali piccoli + dock

---

## 7. Note implementative

- Layout manager: ~50-80 righe. Struttura dati: lista pannelli vivi con
  `{id, nature, priority, created_at, state}` + funzioni `place()`, `evict()`,
  `dedupe()`, `promote()`, `demote()`.
- Le animazioni di promozione/retrocessione usano FLIP (First-Last-Invert-Play)
  così il pannello "vola" fisicamente dalla posizione vecchia alla nuova.
- Timing: entrata 300-400 ms ease-out; demote a PiP 350 ms; refresh dedupe 200 ms.
- Il dock PiP vive in basso a destra, sopra la trascrizione; le tab (3+ focus)
  sul bordo destro, verticali, solo titolo.
