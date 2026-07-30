"""Traduzione condivisa: messaggi SDK di un turno del motore -> eventi UI.

Un solo posto per la mappa `StreamEvent`/`ResultMessage` -> eventi
(`delta`/`tool_in_corso`/`fine`), riusata da chi consuma un turno in
streaming: il turno vocale (`turno_vocale.py`, che ci monta sopra
ponte + speculativo) e la sessione web (`interfaccia_utente/sessione_web.py`,
che la usa nuda). Regola CLAUDE.md "ogni informazione vive in un punto solo":
la forma degli eventi non va duplicata tra i due canali.

Questa funzione NON cattura le eccezioni del motore né decide il testo di un
evento `errore`: il ciclo di vita (loggare, tradurre in `errore`, chiudere)
resta del chiamante, che ha il proprio contesto. Il testo dell'errore è però
qui (`MESSAGGIO_ERRORE`), così i due canali mostrano lo stesso messaggio.
"""
from __future__ import annotations

from typing import AsyncIterator

from claude_agent_sdk.types import ResultMessage, StreamEvent, ToolResultBlock, UserMessage

from . import azioni
from .descrizioni_azioni import descrivi_azione

MESSAGGIO_ERRORE = "Non sono riuscito a elaborare la richiesta, riprova."

# Etichette leggibili per il log azioni della UI (Tappa 7.2): cosa sta facendo
# l'assistente, non il nome tecnico del tool. Le scritture "fuori" sono al
# gerundio "Preparo ..." perché a quel punto l'azione è solo *proposta*: parte
# davvero solo dopo la conferma (vedi azioni.py). Un tool non in mappa (es. un
# tool nativo dell'SDK) ricade sul nome pulito - meglio grezzo che sbagliato.
_ETICHETTE_TOOL = {
    "search_memoria": "Cerco nella memoria",
    "search_email": "Cerco nella posta",
    "read_email": "Leggo l'email",
    "read_thread": "Leggo la conversazione",
    "remember_fact": "Salvo in memoria",
    "list_impegni_aperti": "Controllo gli impegni aperti",
    "propose_commitment": "Preparo un impegno",
    "close_commitment": "Chiudo un impegno",
    "draft_email": "Preparo una bozza",
    "send_email": "Preparo l'invio della mail",
    "reply_email": "Preparo la risposta",
    "forward_email": "Preparo l'inoltro",
    "send_draft": "Preparo l'invio della bozza",
    "trash_email": "Cestino la mail",
    "mark_email": "Segno la mail",
    "organize_email": "Organizzo la mail",
    "list_labels": "Guardo le etichette",
    "list_attachments": "Guardo gli allegati",
    "get_attachment": "Leggo un allegato",
    "import_document": "Importo il documento",
    "list_documents": "Elenco i documenti",
    "get_document": "Recupero il documento",
    "forget_document": "Preparo l'eliminazione del documento",
    "search_events": "Cerco nel calendario",
    "check_availability": "Controllo la disponibilità",
    "respond_to_invite": "Rispondo all'invito",
    "create_event": "Preparo l'evento",
    "update_event": "Preparo la modifica dell'evento",
    "delete_event": "Preparo la cancellazione dell'evento",
    "search_files": "Cerco tra i file",
    "read_file": "Leggo il file",
    "list_folder": "Sfoglio la cartella",
    "create_folder": "Creo la cartella",
    "create_file": "Creo il file",
    "update_file_content": "Aggiorno il file",
    "move_file": "Sposto il file",
    "copy_file": "Copio il file",
    "rename_file": "Rinomino il file",
    "revoke_permission": "Revoco un permesso",
    "list_permissions": "Controllo i permessi",
    "share_file": "Preparo la condivisione",
    "trash_file": "Preparo il cestinamento del file",
}


def nome_tool_pulito(nome: str) -> str:
    """`mcp__<server>__<tool>` -> `<tool>`; i tool nativi restano invariati."""
    if nome.startswith("mcp__"):
        return nome.split("__", 2)[2]
    return nome


def etichetta_tool(nome: str) -> str:
    """Frase leggibile per il log; fallback sul nome pulito se sconosciuto."""
    pulito = nome_tool_pulito(nome)
    return _ETICHETTE_TOOL.get(pulito, pulito)


async def traduci_turno(
    motore, testo: str, canale: str, tenant_id: str
) -> AsyncIterator[dict]:
    """Consuma `motore.turno(testo, canale)` e produce eventi UI man mano:

    - `{"evento": "delta", "testo": ...}` per ogni frammento di testo;
    - `{"evento": "tool_in_corso", "id": ..., "tool": ..., "etichetta": ...}`
      quando parte un tool;
    - `{"evento": "tool_finito", "id": ..., "esito": "ok"|"errore"}` quando il
      tool ritorna (accoppiato per `id` al `tool_in_corso`, così il log della UI
      chiude la riga invece di lasciarla "in corso" per sempre - Tappa 7.2);
    - un solo `{"evento": "fine", "risposta": ..., "azione_in_attesa": ...}`
      alla fine, con l'eventuale azione pending appena creata da un tool
      (arricchita di `descrizione` leggibile per la scheda di conferma).

    Un'eccezione del motore si propaga al chiamante (non tradotta qui)."""
    pezzi: list[str] = []
    async for messaggio in motore.turno(testo, canale=canale):
        if isinstance(messaggio, StreamEvent):
            evento = messaggio.event
            tipo_evento = evento.get("type")
            if tipo_evento == "content_block_delta":
                delta = evento.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"evento": "delta", "testo": delta["text"]}
            elif tipo_evento == "content_block_start":
                blocco = evento.get("content_block") or {}
                if blocco.get("type") == "tool_use":
                    nome = blocco.get("name", "")
                    yield {
                        "evento": "tool_in_corso",
                        "id": blocco.get("id", ""),
                        "tool": nome_tool_pulito(nome),
                        "etichetta": etichetta_tool(nome),
                    }
        elif isinstance(messaggio, UserMessage):
            # Il risultato di un tool torna come UserMessage con un
            # ToolResultBlock: è il segnale che il tool ha *finito* (diverso da
            # content_block_stop, che marca solo la fine della richiesta del
            # modello, non l'esecuzione).
            for blocco in messaggio.content or []:
                if isinstance(blocco, ToolResultBlock):
                    yield {
                        "evento": "tool_finito",
                        "id": blocco.tool_use_id,
                        "esito": "errore" if blocco.is_error else "ok",
                    }
        elif isinstance(messaggio, ResultMessage):
            if messaggio.subtype == "success" and messaggio.result:
                pezzi.append(messaggio.result)

    azione_appena_creata = await azioni.ottieni_azione_pendente_tenant(tenant_id)
    if azione_appena_creata is not None:
        azione_appena_creata["descrizione"] = descrivi_azione(azione_appena_creata)
    yield {"evento": "fine", "risposta": "\n".join(pezzi), "azione_in_attesa": azione_appena_creata}
