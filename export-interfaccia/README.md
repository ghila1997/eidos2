# Interfaccia Eidos — pacchetto esportabile

Copia **così com'è** (nessuna modifica) dei file statici serviti in produzione da
`codice/interfaccia_utente/static/` (il server FastAPI li monta su `/`). Utile come
riferimento/punto di partenza per un'altra interfaccia — ma **non è un pacchetto
plug-and-play**: metà di quello che vedi qui parla con un backend Eidos vero (login,
WebSocket, conferme...) e senza quel backend non funziona. Sotto trovi cosa è
puramente visivo (portabile) e cosa no.

## Contenuto

```
export-interfaccia/
  README.md                        questa guida
  index.html                       pagina unica dell'app (login + schermata principale)
  style.css                        tutti gli stili (identità visiva, layout, pannelli)
  app.js                           tutta la logica client (WebSocket, audio, UI, PWA)
  pcm-worklet.js                   AudioWorklet: cattura microfono in PCM grezzo
  manifest.json, sw.js, icons/     installabilità PWA (nessuna cache offline reale)
  essere_vivente_component.html    copia di riferimento del componente Essere Vivente
                                    (vedi anche export-essere-vivente/, più completo)
  vendor/
    three.min.js                   Three.js (per il componente Essere Vivente)
    qrcode.js, qrcode_utf8.js      generatore QR (pairing companion), MIT, di Kazuhiko Arase
```

## Cosa è SOLO visivo — portabile senza backend

Questa è la parte riusabile in un altro progetto senza scrivere nessun server:

- **Identità visiva** (`style.css`): fondo quasi nero (`#04040c`), testo lavanda chiaro
  (`#eef1ff`), pannelli in vetro scuro (`rgba(18,20,42,0.46)`, bordo
  `rgba(150,165,255,0.12)`), accento `#8aa0ff`, font "Space Grotesk" (Google Fonts).
- **Sfondo condiviso** (`app.js`, funzione `initBackground()`): canvas 2D con una
  griglia di puntini stile carta millimetrata (passo 30px), più luminosi al centro,
  variazione casuale ma stabile (stesso seme), parallasse leggero al puntatore,
  rispetta `prefers-reduced-motion`. Nessuna dipendenza da rete.
- **Layout della schermata principale**: Essere Vivente al centro a piena
  dimensione, barra voce/risposta in alto (monospace, una riga, auto-fade),
  chat in basso al centro, modalità in basso a destra, log azioni sopra la chat,
  cronologia a linguetta sul bordo destro, consumi in basso a sinistra. Tutto
  in CSS puro (`style.css`), riorganizzabile senza toccare la logica di rete.
- **Schede grafiche flottanti**: finestre trascinabili che si posano da sole
  nello spazio libero attorno all'essere (stessa logica generica, la sola
  dipendenza dal backend è *da dove arrivano i dati*, non da come si disegnano).
- **Essere Vivente**: componente a parte, vedi `export-essere-vivente/` (più
  completo e aggiornato di questa copia di riferimento).

## Cosa NON funziona senza il backend Eidos vero

Tutto quello che passa dalla rete. `app.js` chiama direttamente questi endpoint —
senza un server compatibile che risponde a queste rotte, le funzioni corrispondenti
falliscono silenziosamente o restano bloccate:

| Cosa | Endpoint | Serve per |
|---|---|---|
| Login | `POST /login`, `GET /auth-config` | Autenticazione (Supabase Auth OAuth/email) |
| Conversazione | `WS /ws/session` | **Il canale principale**: testo, audio, stato, log azioni, tutto passa da qui |
| Dispositivi | `GET/POST /devices*` | Limite dispositivi, pairing companion |
| Account collegati | `GET/POST /connections*`, `/oauth/*` | Email/calendario/storage/messaggistica collegati |
| Pairing | `POST /pairing/*` | QR per aggiungere un companion (telefono/tablet) |
| Consumi | `GET /usage` | Indicatore spesa del mese |

La specifica completa di questi endpoint (formati messaggio, stati, regole) è in
[`docs/modules/08-interfaccia-utente.md`](../docs/modules/08-interfaccia-utente.md)
di questo stesso progetto — è lì che si trova la logica lato server da replicare se
si vuole portare l'interfaccia *funzionante* altrove, non solo l'aspetto.

## Attenzione: percorsi assoluti, non apribile così com'è

`index.html` referenzia tutto con percorsi **assoluti** (`/static/style.css`,
`/static/app.js`, `/static/vendor/...`, `/assets/essere_vivente_component.html`,
`/manifest.json`) — sono quelli che il server Eidos monta (`config.STATIC_DIR` su
`/static`, una rotta dedicata per `/assets/essere_vivente_component.html`). Aperto
da un server generico messo in questa cartella (es. `python -m http.server`),
questi percorsi puntano alla radice del server e **non trovano i file** (CSS/JS non
si caricano, pagina non stilizzata) — non è un problema di rete/backend, è proprio
il routing.

Per guardare **solo l'aspetto** senza backend, prima di aprirlo:
1. sposta `style.css`, `app.js`, `pcm-worklet.js`, `manifest.json`, `sw.js`,
   `vendor/`, `icons/` dentro una cartella `static/` (nome a piacere, basta
   aggiornare i percorsi di conseguenza) accanto a `index.html`;
2. metti `essere_vivente_component.html` (+ la sua `vendor/three.min.js`) dove
   punta `/assets/essere_vivente_component.html`, oppure riscrivi quel percorso
   a relativo (`essere_vivente_component.html`);
3. servi la cartella con un server locale qualsiasi.

Anche sistemati i percorsi, resta vero quanto sopra: ogni azione che tocca la
rete (login vero, mandare un messaggio, vedere lo stato cambiare dal server)
non farà nulla senza un backend compatibile dall'altra parte — utile solo per
giudicare aspetto/layout, non funzionalità.
