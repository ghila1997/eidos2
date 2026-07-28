# Mockup Tappa 7 — riferimento di *feel* (usa-e-getta)

Prototipo throwaway usato per **validare look & interazione** dell'interfaccia (Tappa 7) prima di
costruirla — preferenza registrata "prototipo UX prima del TDD". **Non è il modulo**: logica finta
e scriptata, dati inventati, nessun backend. Il modulo vero si costruisce in `codice/interfaccia_utente/`
seguendo ROADMAP.md (Tappa 7.1–7.6).

**Cosa fissa** (vedi DECISIONS.md 2026-07-28):
- Essere vivente al centro, palette `nebulaCosmo`, zoom 0.85, sfondo con griglia visibile + vignetta
- Barra di trascrizione che si **espande in cronologia** (colonna sfumata, non un pannello separato)
- Schede grafiche flottanti, log azioni dal vivo, gate di conferma, controlli in basso, modalità voce

**Come guardarlo**: serve un server locale (l'essere vivente è un iframe).
```
cd notes/mockup-tappa7
python -m http.server 8777 --bind 127.0.0.1
```
poi apri http://127.0.0.1:8777 — scrivi un messaggio e premi Invia per vedere la scena finta;
clicca la barra in alto per espandere la cronologia.
