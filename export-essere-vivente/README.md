# Essere Vivente — pacchetto esportabile

Componente visivo autonomo: entità di particelle 3D, struttura a **vene radiali** che nascono
da un nucleo centrale sempre acceso e disegnano la forma stessa. Nessuna dipendenza esterna
oltre a Three.js (incluso in `vendor/`).

## Contenuto

```
export-essere-vivente/
  README.md                        questa guida
  essere_vivente_component.html    IL COMPONENTE (unico file da incorporare)
  essere_vivente_sfondo_lab.html   banco di prova: sfondo/zoom/posizione
  essere_vivente_lab.html          banco di prova: stato/palette/audio
  vendor/
    three.min.js                   Three.js (richiesto dal componente)
```

I due lab servono solo a guardare e tarare: nel progetto di destinazione basta
il componente (+ `vendor/`). Il percorso `vendor/three.min.js` è relativo:
mantieni la stessa struttura di cartelle accanto al componente.

## Come si prova

Apri `essere_vivente_lab.html` nel browser. Meglio da un piccolo server
locale (`python -m http.server` o estensione Live Server) — da `file://`
alcuni browser limitano iframe/localStorage.

## Come si incorpora

```html
<iframe id="essere" src="essere_vivente_component.html"
        style="border:0;background:transparent"></iframe>
```

Lo sfondo del componente è trasparente e **non dipinge né scurisce nulla attorno a
sé** (niente più ombra/alone o bagliore propri — tolti apposta): il buio/luce
dell'ambiente, se li vuoi, sono a carico della pagina ospite.

## API (postMessage verso l'iframe)

```js
const ev = document.getElementById('essere').contentWindow;

// stato dell'essere
ev.postMessage({type:'state', value:'idle'|'listening'|'thinking'|'speaking'}, '*');

// livello audio in tempo reale (0..1), per la reazione vocale in "speaking"
ev.postMessage({type:'level', value:v, bass:b, treble:t}, '*');

// impulso di inizio parola
ev.postMessage({type:'pulse'}, '*');

// palette colori (default 'complementare' se non specificata)
ev.postMessage({type:'config', palette:'complementare'}, '*');

// leve di taratura (tutte opzionali, canale 'lab'):
ev.postMessage({type:'lab',
  zoom: 1.0,              // dimensione complessiva (default 1)
  offsetY: 0.19,          // posizione verticale (default 0.19, + = più in alto)
  brightness: 0.4,        // luminosità generale (default 0.4)
  sizeBoost: 0.5,         // dimensione particelle (default 0.5)
  density: 1.0,           // densità particelle, 0..1 (default 1.0)
  reactMode: 0,           // reazione vocale in "speaking": 0-3 (default 0)
}, '*');
```

Valori di produzione già fissati come default nel componente: luminosità 0.4,
dimensione 0.5, densità 1.0, posizione verticale 0.19. Se non mandi nulla,
l'essere parte già giusto.

**Palette disponibili** (13): `mono`, `neutro`, `complementare` (default),
`prisma`, `ossidiana`, `neonUrbano`, `forestaBrace`, `acquamarina`,
`prismaIbrido`, `nebulaOrione`, `nebulaCarena`, `nebulaVelo`, `nebulaCosmo`.

## Cosa serve d'altro (checklist per il progetto di destinazione)

- **Sfondo/ambiente**: il componente non porta più con sé buio o luce propri —
  se vuoi un alone/vignetta attorno all'essere, va dipinto nella pagina ospite.
- **Polvere di stelle** (opzionale): vive nella pagina ospite, non nel
  componente — rada e tenue (si intuisce, non si vede), 3 strati con
  parallasse al puntatore e un luccichio raro quasi impercettibile; rispetta
  prefers-reduced-motion (tutto statico). Il codice di riferimento è in
  `essere_vivente_sfondo_lab.html`, funzione `initBackground()` (canvas 2D).
  Copialo se la vuoi.
- **Vignetta ai bordi** (opzionale): overlay CSS `.void` (vedi i lab).
- **Font**: i lab usano "Space Grotesk" da Google Fonts (serve internet, ma
  degradano con grazia al font di sistema). Il componente non usa font.
- Connessione internet NON richiesta dal componente: Three.js è locale.
