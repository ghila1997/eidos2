# Interfaccia — composizione del prodotto finito (registro "niente si perde")

> Stella polare dell'interfaccia Eidos. Elenca **ogni** pezzo dell'interfaccia finita e a quale
> tappa appartiene, così rimandare non vuol dire perdere (principio scope-guard: si lavora a pezzi,
> non si taglia in silenzio). Fonti: export dell'interfaccia v1 (`export-interfaccia/`, riferimento
> visivo consegnato dall'utente) + roadmap Eidos 2.0 + buchi individuati per un prodotto vendibile.
> Decisioni relative: DECISIONS.md 2026-07-28 "Tappa 7 (Interfaccia Utente)".
>
> Legenda: ✅ = presente nell'export v1 · 🆕 = buco non presente in v1, da non dimenticare.
> "Tappa" = dove la funzione diventa reale (l'**aspetto** può comparire prima, mai con dati finti).

## A · Ingresso e identità
- Login email/password + **Google/Microsoft** (Supabase Auth), logout, sessione ✅ · Tappa 8
  (in Tappa 7: schermata login attiva su auth cookie esistente, provider nascosti)
- Pairing claim (entrare come companion da link scansionato) ✅ · Tappa 8
- 🆕 Recupero password / account · Tappa 8
- 🆕 Registrazione self-service (nuovo cliente si iscrive da solo) · Tappa 8

## B · Baricentro: Essere Vivente
- Entità 3D centrale ruotabile, stati idle/listening/thinking/speaking, reattività audio, palette,
  sfondo+vignetta+griglia ✅ · **Tappa 7** (config prod: `nebulaCosmo`, zoom 0.85)

## C · Conversazione testo
- Input + invio, risposta in streaming, barra trascrizione in alto, storico messaggi ✅ · **Tappa 7**
- 🆕 Rendering markdown delle risposte · Tappa 7.6
- 🆕 Copia/rigenera risposta (minori) · Tappa 7+

## D · Conversazione voce (nel browser)
- Pulsante mic, cattura PCM, listen_state, TTS + allineamento parole sulla barra, sblocco audio ✅
  · Tappa 7.5
- Modalità Normale / Silenziosa / Spenta ✅ · Tappa 7.5
- 🆕 Barge-in (interrompere l'assistente parlando) · Tappa 7.5

## E · Trasparenza operativa
- Log azioni dal vivo (step), conferme (gate Sì/No con descrizione), blocco su azione pendente ✅
  · **Tappa 7.2**
- Storico azioni con esito ✅ (parziale) · Tappa 7.2/7.3

## F · Schede grafiche flottanti (parte del prodotto finito)
- `data_presented`: lista, tabella, evento, luogo, grafico, scheda; trascinabili, auto-posizionate,
  chiudibili ✅ · **Tappa 7.4** (renderer completo; i tipi si riempiono su dati reali, protocollo
  progettato per tutti)

## G · Cronologia (unificata con la barra — vedi DECISIONS.md)
- La barra di trascrizione si espande in cronologia (colonna sfumata, non un pannello separato) ·
  **Tappa 7.3**
- 🆕 Persistenza cross-sessione (sopravvive al refresh, salvata per tenant) · Tappa 7.3
- 🆕 Ricerca nello storico (minore) · dopo

## H · Account collegati (connettori)
- Lista account per capacità (email/calendario/storage/messaggi), collega (OAuth), scollega/revoca,
  toggle sincronizzazione per account, stato/errori ✅ · Tappa 8

## I · Dispositivi
- Lista dispositivi attivi, limite, pairing companion via QR, rimozione ✅ · Tappa 8

## J · Consumi e abbonamento
- Indicatore spesa mese + barra budget, avvisi 80/100% ✅ · Tappa 9
- 🆕 Gestione abbonamento (piano, metodo di pagamento, fatture — Stripe) · Tappa 9

## K · 🆕 Le Procedure (superficie assente in v1)
- Catalogo **Assistenze** ("cosa può fare Eidos per me" — la scoperta) · Tappa 10
- **Automazioni**: lista, creazione a voce, osservabilità (timeline passi, passo fallito, rilancio) · Tappa 10
- **Attese**: lista "cose che Eidos sta aspettando", chiudi/prolunga · Tappa 10
- **Risorse/Modelli**: libreria (template, glossari, tono, regole) · Tappa 10

## L · 🆕 Memoria — vederla e correggerla
- Vista di cosa Eidos ricorda: fatti su clienti/progetti, impegni aperti (`list_impegni_aperti`
  esiste già), documenti; correggere/dimenticare. È il cuore del prodotto: il cliente deve poterlo
  ispezionare · Tappa 8+ (superficie nuova)

## M · 🆕 Notifiche
- Come arriva all'utente un'Attesa che scatta, un'approvazione richiesta, il risultato di
  un'automazione: notifiche in-app + push PWA · Tappa 10

## N · 🆕 Stato di sistema e casi limite
- Indicatore connessione WS (online/riconnessione/offline) — v1 falliva in silenzio · Tappa 7.2
- Errori come toast/schede, empty state (prima esecuzione, nessun account, storico vuoto) · Tappa 7+

## O · 🆕 Impostazioni e preferenze
- Profilo, tono/stile, regole, lingua, notifiche · Tappa 8+

## P · Multi-formato e installabilità
- PWA (manifest, service worker, installabile) ✅ · Tappa 7.6
- Responsive desktop/mobile, companion più leggero su telefono ✅ (parziale) · Tappa 8

## Q · Accessibilità
- prefers-reduced-motion (sfondo lo rispetta), focus/tastiera, aria-live ✅ (parziale) · trasversale

---

## Da rivedere quando si arriva alle Tappe 8/9/10
Gli 🆕 sopra non sono ancora slottati in dettaglio nelle rispettive tappe di ROADMAP.md: vanno
formalizzati (via `saas-architect`) quando si apre la Tappa 8/9/10, non prima. Questo file è il
promemoria che esistono e da dove vengono, così non si "dimenticano silenziosamente" — l'errore di
Eidos v1 sull'onboarding OAuth (vedi ROADMAP Tappa 8).
