> **Bozza non ancora decisa** — da riprendere come spunto (non vincolante) al design
> della **Tappa 6 — Voce** / **Tappa 7 — Interfaccia Utente** in ROADMAP.md (satelliti voce,
> scoperta rete, instradamento HUD per stanza). Riconfermare o cambiare a quel punto, non dare
> per acquisita (vedi CLAUDE.md, "Idee non ancora decise → notes/"). Nota: cita `VOICE_SPEC.md`
> e `PANELS_SPEC.md` come documenti correlati — corrispondono a `notes/spec-voce-bozza.md` e
> `notes/spec-interfaccia-bozza.md` in questo progetto.

# SPEC — Hardware, scoperta rete e instradamento per stanza

> Documento di specifica per l'implementazione. Definisce i satelliti voce,
> il server centrale, la scoperta automatica dei dispositivi in rete
> (TV/Chromecast), il cast dell'HUD, e la regola di instradamento per stanza.
> Ogni regola è vincolante; in caso di dubbio implementativo, vince questo file.
>
> Documenti correlati: `VOICE_SPEC.md` (pipeline audio sul satellite),
> `PANELS_SPEC.md` (focus manager — qui si aggiunge SOLO il "su quale schermo").

---

## 0. Principio

**Niente Alexa, niente Echo, niente ecosistemi chiusi come punto d'ingresso
vocale.** Il microfono/altoparlante sono dispositivi satellite dedicati,
economici, sotto controllo diretto. Gli schermi (TV, tablet, monitor) sono
invece raggiungibili quasi sempre in automatico, tramite standard di rete
già esistenti — nessuna configurazione manuale di IP o dispositivi.

Regola di instradamento di base, che guida l'intera spec:
**la stanza in cui parli è la stanza in cui compare l'HUD.** Non serve una
tabella di preferenze: emerge dall'architettura, perché il server sa sempre
quale satellite ti ha sentito.

---

## 1. Perché non Alexa / Echo

| Aspetto | Realtà |
|---|---|
| Microfono | Chiuso, nessuna API di accesso al flusso audio grezzo. Non aggirabile. |
| Skill Alexa | Rovescerebbe il controllo: dovresti dire "Alexa, chiedi a Jarvis…", con Amazon in mezzo a ogni turno, wake word e latenza sue. |
| Altoparlante da solo | Utilizzabile SOLO come cassa Bluetooth in output. Il mic resta comunque escluso: serve comunque un satellite separato per l'input. |

**Decisione**: Echo esclusi dal percorso vocale. Riutilizzabili al massimo come
cassa Bluetooth accoppiata a un satellite, mai come punto d'ingresso.

---

## 2. Satellite voce — specifica hardware

Un satellite per stanza in cui si vuole poter parlare a Jarvis.

### 2.1 Componenti

| Componente | Scelta consigliata | Costo indicativo |
|---|---|---|
| Board | Raspberry Pi Zero 2W (minimo) o Pi 4 (se si vuole margine) | 15–35 € |
| Array microfonico | ReSpeaker 2-Mic HAT (essenziale) o 4-Mic (migliore per beamforming/rumore) | 10–25 € |
| Uscita audio | Jack/HAT audio verso cassa attiva della stanza, o Bluetooth verso cassa esistente (anche un Echo riusato, v. §1) | variabile |
| Alimentazione | USB-C 5V/3A | 8 € |
| Custodia | Qualsiasi, purché non copra i microfoni | 5–10 € |

**Costo totale per satellite: ~30–45 €.**

### 2.2 Software sul satellite

- Sistema minimo (Raspberry Pi OS Lite, no desktop).
- Processo unico: cattura audio → ring buffer → wake word locale
  (openWakeWord/Porcupine) → invio stream al server via WebSocket sulla rete
  locale. Tutta la logica pesante (STT/LLM/TTS) resta sul server: il satellite
  è un client leggero, sostituibile senza perdere nulla.
- **Identità obbligatoria**: ogni satellite si registra al server con un
  `room_id` configurato una tantum in un file locale (`room: "soggiorno"`).
  Questo è il dato che abilita tutto l'instradamento del §5 — senza `room_id`
  il satellite non deve poter connettersi (fail-safe: meglio un satellite
  fermo che uno che parla dalla stanza sbagliata).

```yaml
# satellite-config.yml
room_id: "soggiorno"
server_ws: "ws://192.168.1.10:8765/satellite"
wake_word: "jarvis"
mic_gain: auto
```

### 2.3 Quanti servirne

Uno per ogni stanza in cui si vuole attivazione vocale diretta. Non serve
copertura totale della casa al primo giro: si parte da 1, si aggiungono nel
tempo. Nessuna modifica al server richiesta per aggiungerne uno — si registra
da solo alla prima connessione (v. §4).

---

## 3. Server centrale — specifica hardware

| Requisito | Nota |
|---|---|
| Sempre acceso | È il cervello: se è spento, l'intero sistema è muto |
| CPU | Modesta: il carico pesante (LLM, STT, TTS) è quasi sempre in API cloud. Un Raspberry Pi 4/5 o un mini PC bastano se non si eseguono modelli locali |
| RAM | 4 GB minimo, 8 GB comodo se si aggiungono modelli locali (Whisper locale, TTS locale tipo Piper) |
| Rete | Ethernet preferita per il server (stabilità), WiFi accettabile per i satelliti |
| Storage | 32 GB+ per OS, log, memoria (SQLite/vector DB) |

Il server espone: WebSocket per i satelliti voce, WebSocket per i client HUD,
endpoint HTTP che serve la pagina dell'HUD stessa (così i client TV/browser
la caricano da un URL locale, es. `http://192.168.1.10:5000/hud`).

---

## 4. Scoperta automatica dei dispositivi (TV, Chromecast, smart device)

### 4.1 Principio

Gli schermi e i dispositivi smart **non richiedono configurazione manuale di
IP**. Si annunciano da soli sulla rete locale con protocolli standard, esattamente
come fa Netflix per trovare un Chromecast. Il server li scopre in automatico.

### 4.2 Protocolli e librerie

| Protocollo | Cosa copre | Libreria Python |
|---|---|---|
| mDNS/Bonjour | Dispositivi Apple, molti smart device generici | `zeroconf` |
| SSDP/UPnP | Chromecast, DLNA, molte smart TV | `pychromecast` (usa SSDP internamente) |
| Proprietario Cast | Google Cast / Chromecast built-in | `pychromecast` |
| CEC | TV non in rete ma su HDMI da un box collegato | `cec-client` (Linux) |

### 4.3 Comportamento del server

- Scansione periodica in background (es. ogni 5 minuti, più una scansione
  immediata all'avvio) che aggiorna la lista dei dispositivi visibili.
- Ogni dispositivo trovato viene registrato con: nome, tipo, indirizzo IP,
  capacità (accensione, cast, entrambe).
- **Non serve azione dell'utente** per far apparire un dispositivo nella
  lista, a meno che non sia un device "muto" in rete (v. §4.4).

```python
import pychromecast
chromecasts, browser = pychromecast.get_chromecasts()
# ogni oggetto in chromecasts: nome, uuid, capacità — già pronto da usare
```

### 4.4 Limite reale: dispositivi non in rete

- TV vecchie, non smart, non raggiungibili via WiFi/Ethernet: la scoperta
  automatica non le vede, per definizione. Serve un box fisico attaccato
  (Fire Stick/Android box/Raspberry Pi via HDMI) che parli **HDMI-CEC** per
  accensione/spegnimento e cambio sorgente, e che esponga il proprio Cast per
  il resto.
- Alexa/Echo: anche se compaiono nella scansione di rete come dispositivo
  presente, il protocollo interno resta chiuso — vedere il dispositivo non
  significa poterci comandare qualcosa (v. §1). Da escludere dalla lista utile.

---

## 5. Instradamento HUD — regola di default

### 5.1 La regola (nessuna tabella necessaria)

> **Lo schermo su cui appare l'HUD è quello della stanza da cui è arrivata
> la richiesta vocale.**

Emerge direttamente dall'architettura, senza bisogno di preferenze configurate:

```
Utente parla  →  Satellite "soggiorno" lo sente (ha room_id="soggiorno")
             →  Server sa: richiesta = stanza "soggiorno"
             →  Server cerca uno schermo registrato con room_id="soggiorno"
             →  Se esiste ed è raggiungibile → cast automatico dell'HUD lì
             →  Se non esiste → risposta solo vocale (nessun forzare
                su uno schermo di un'altra stanza)
```

### 5.2 Registrazione schermi per stanza

Ogni schermo (TV, tablet, monitor con browser) va abbinato a un `room_id`
esattamente come i satelliti voce, così l'accoppiamento stanza-satellite ↔
stanza-schermo è diretto:

```yaml
# screen-registry.yml (sul server, o auto-popolato alla prima scoperta + conferma)
- room_id: "soggiorno"
  name: "TV Soggiorno"
  type: "chromecast"
  cast_uuid: "xxxxx"
- room_id: "studio"
  name: "Monitor Studio"
  type: "browser-kiosk"
  url_target: "studio"   # canale WebSocket dedicato per instradare i pannelli
```

Per un dispositivo scoperto via rete (Chromecast) l'abbinamento a un
`room_id` va confermato una volta dall'utente ("questa è la TV del
soggiorno?"); per un browser in kiosk mode, il `room_id` si imposta nell'URL
o in un file locale, come per i satelliti.

### 5.3 Cast automatico

Se lo schermo della stanza è una TV/Chromecast (non un browser già aperto in
kiosk), il server la "sveglia" e ci apre l'HUD via cast, senza intervento
dell'utente:

```python
tv = get_cast_by_room("soggiorno")
tv.wait()
tv.media_controller.play_media(f"{HUD_BASE_URL}/hud?room=soggiorno", "text/html")
```

- Se la TV è già accesa su un altro contenuto (Netflix, TV via antenna):
  il cast prende il focus dello schermo. Da usare quindi solo per contenuto
  che giustifica l'interruzione (focus esplicitamente richiesto, non un
  pannello meteo — vedi test di necessità in `PANELS_SPEC.md` §0: vale anche
  qui, a maggior ragione, perché il costo di interruzione di una TV in uso è
  più alto di un pannello sullo schermo del PC).
- **"Richiudi" / fine del focus** → comando di stop cast: la TV torna alla
  sorgente precedente (non si spegne, semplicemente si esce dall'app cast).

### 5.4 Eccezione esplicita (rara, non di default)

Il default resta stanza-in-cui-parli = stanza-in-cui-appare. Solo se
l'utente lo richiede esplicitamente si forza un'altra destinazione:
"mostralo sulla TV" mentre si è in un'altra stanza → comando diretto,
bypassa la regola di stanza per quella singola richiesta. Non è una
preferenza permanente salvo che l'utente la renda tale ("i render vanno
sempre sulla TV, anche se chiedo dallo studio" → allora sì, da persistere
come regola in memoria, ma è un'aggiunta a valle, non il comportamento
iniziale).

---

## 6. Costi indicativi (sistema completo a 2 stanze)

| Voce | Costo |
|---|---|
| 2 satelliti voce (Pi Zero 2W + mic HAT) | ~70–90 € |
| Server centrale (Pi 4/5 o mini PC modesto) | ~60–100 € |
| Box TV per cast/CEC (se la TV non è già smart) | ~30–40 € |
| **Totale indicativo** | **~160–230 €** |

API cloud (Deepgram STT, TTS, LLM) sono a consumo, non incluse nell'hardware:
tipicamente pochi euro al mese per un uso domestico normale.

---

## 7. Criteri di accettazione (test manuali)

- [ ] Un nuovo satellite acceso in una stanza mai usata prima → compare al
      server senza modifiche di codice, solo grazie al suo `room_id`
- [ ] Un Chromecast nuovo in rete compare nella lista del server entro 5 min
      dall'accensione, senza inserire IP a mano
- [ ] Parlando dal satellite "soggiorno" con la TV del soggiorno registrata
      → l'HUD appare lì automaticamente, senza dire "sulla TV"
- [ ] Parlando dal satellite "studio" (nessuno schermo registrato lì) →
      risposta solo vocale, nessun tentativo di castare altrove
- [ ] "Mostralo sulla TV" detto dallo studio → forza il cast sul soggiorno
      per quella sola richiesta, senza diventare regola permanente
- [ ] La TV già accesa su un contenuto (es. Netflix) → il cast dell'HUD
      subentra solo per un focus richiesto esplicitamente, non per pannelli
      minori (meteo, conferme)
- [ ] "Richiudi" durante un contenuto castato → la TV torna alla sorgente
      precedente, non si spegne
- [ ] Un dispositivo Echo eventualmente presente in rete NON compare come
      target utilizzabile nella lista schermi/satelliti
