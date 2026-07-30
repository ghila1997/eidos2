# MCP Apps: l'interfaccia la porta il connettore

**Stato: idea decisa come direzione, non da fare ora.** Non è in ROADMAP.md di
proposito: manca il caso reale che la giustifica (vedi "Quando diventa vera").

## Cos'è

Prima estensione ufficiale del protocollo MCP (SEP-1865, proposta nov 2025,
rilasciata **26 gennaio 2026**). Un server MCP pubblica una pagina HTML come
risorsa `ui://`, la lega a un tool via `_meta.ui.resourceUri`, e il client la
rende in un iframe sandboxed dentro la conversazione. Il pannello comunica col
client via postMessage/JSON-RPC (metodi `ui/*` più `tools/call`) e può
richiamare i tool del server. La CSP dell'iframe blocca le richieste di rete
esterne: la pagina dev'essere autoconsistente.

Supporto host al 2026-07: Claude (web e desktop), VS Code Copilot, Microsoft
365 Copilot, Goose, Postman, MCPJam, Archestra. SDK client `@mcp-ui/client` o
il modulo AppBridge — entrambi npm.

- Annuncio: https://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/
- Overview + modello di sicurezza: https://modelcontextprotocol.io/extensions/apps/overview
- SEP-1865: https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp

## Perché ci interessa

È il principio che vogliamo per le schede dei connettori: **chi scrive il
connettore Gmail scrive anche la scheda che lo rappresenta**, e l'interfaccia
non sa cosa sia una mail. Oggi `descrizioni_azioni.py` ci arriva a metà: è già
fonte unica lato server (CLI e web la consumano senza ricalcolarla) e dal fix
delle conferme multiple ha un registro con **una voce per tipo di azione** —
icona, titolo, titolo di gruppo, righe della scheda, frasi di esito. Aggiungere
un connettore è aggiungere una voce.

Quello che manca per essere davvero MCP Apps: la scheda è **dati strutturati**
resi dalla UI, non **HTML servito dal connettore**.

## Perché non adesso

1. **Eidos è insieme server e client.** `tools.py` crea un server MCP
   in-process e la UI web è nostra. Il protocollo esiste per rendere
   l'interfaccia di un server che il client *non ha scritto* e di cui *non si
   fida* — da lì iframe, sandbox, CSP. Adottarlo ora significa costruire il
   lato host (AppBridge, npm, build step su un frontend oggi vanilla senza
   build) per isolare noi da noi stessi.
2. **Tensione col gate di sicurezza.** La regola di CLAUDE.md è che la conferma
   di un'azione distruttiva avvenga fuori dal controllo del modello: la scheda
   chiama `POST /azioni/conferma-gruppo`, endpoint che il modello non può
   invocare. Dentro un iframe MCP App la CSP blocca le chiamate di rete: il
   "Sì, cestina" dovrebbe rientrare dal canale dei tool, cioè **dentro** il
   perimetro del modello. Va risolto prima di adottare il protocollo per le
   schede di conferma — non è un dettaglio implementativo.

## Quando diventa vera

Uno di questi due, che sono casi concreti e non ipotesi:

- **Un cliente collega un suo server MCP.** Lì l'isolamento serve davvero: è
  codice di terzi, e la sandbox è esattamente la garanzia che vogliamo.
- **I connettori Eidos girano dentro Claude.ai** (o altro host), non solo
  dentro Eidos. Lì il protocollo è l'unico modo per portarci l'interfaccia.

In entrambi i casi si cambia il renderer, non i connettori — a patto di tenere
il registro di `descrizioni_azioni.py` mappabile su quello che servirebbe a un
`ui://` (una voce per tipo, dati strutturati, nessuna conoscenza di dominio
nella UI).

## Da verificare prima di scrivere codice

Regola dura di CLAUDE.md: delegare a `claude-code-guide`, non fidarsi della
memoria.

- Il decorator `@tool` del Claude Agent SDK **Python** accetta `_meta`? (l'SDK
  degli MCP Apps oggi è npm — se Python non lo espone, il server MCP in-process
  non può dichiarare risorse `ui://`)
- `create_sdk_mcp_server` permette di registrare risorse oltre ai tool?
- Come si comporta un host che **non** supporta l'estensione: il tool degrada a
  risultato testuale o fallisce?
