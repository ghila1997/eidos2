"""Tool custom MCP di Agente Locale: solo le operazioni senza equivalente
nativo nell'SDK (lettura/scrittura di contenuto usano i tool nativi
Read/Write/Edit/Glob/Grep, gestiti da `hook.py` - vedi DECISIONS.md,
"Safety Supervisor: punto unico di autorizzazione per ogni tool call").

Stesso principio del Supervisor usato da `orchestratore/tools.py`: ogni
funzione verifica il perimetro e chiama `Supervisor.validate()` prima di
agire. La differenza rispetto a Gmail e' come si risolve `ask_user`: qui la
sessione e' locale e sincrona (un solo terminale), quindi si chiede
conferma subito con `conferma_terminale`, senza passare dalla coda
`azioni_pending` (pensata per conferme asincrone/multi-dispositivo, non
necessaria per un processo locale a singolo utente).
"""
from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from memoria.ingest_documento import ErroreIngestDocumento, importa_documento
from orchestratore.safety import supervisor

from . import perimetro
from .conferma_locale import conferma_terminale

SERVER_NAME = "eidos_agente_locale"


def _testo(contenuto: str) -> dict:
    return {"content": [{"type": "text", "text": contenuto}]}


async def _verifica_perimetro(tenant_id: str, nome_tool: str, path: str, categoria: str) -> dict:
    """Chiama il Supervisor per un singolo path, senza chiedere conferma -
    la conferma (se serve) la chiede il chiamante una sola volta, anche
    quando un'operazione tocca piu' di un path (es. move_file)."""
    dentro = await perimetro.is_path_allowed(tenant_id, path)
    return supervisor.validate(
        {"name": nome_tool, "category": categoria},
        {"tenant_id": tenant_id, "path_in_perimetro": dentro, "file_path": path},
    )


async def _list_directory(tenant_id: str, path: str) -> str:
    """Immediato, sola lettura: sostituisce il tool nativo Glob, il cui
    tool_input non espone un campo path verificabile in modo affidabile
    (vedi hook.py)."""
    verdetto = await _verifica_perimetro(tenant_id, "list_directory", path, supervisor.CATEGORIA_IMMEDIATA)
    if verdetto["verdict"] != supervisor.VERDICT_ALLOW:
        return f"Azione non consentita: {verdetto['message']}"
    cartella = Path(path)
    if not cartella.is_dir():
        return f"'{path}' non è una cartella valida."
    voci = sorted(cartella.iterdir())
    if not voci:
        return f"'{path}' è vuota."
    righe = [f"- {v.name}{'/' if v.is_dir() else ''}" for v in voci]
    return f"Contenuto di '{path}':\n" + "\n".join(righe)


async def _move_file(tenant_id: str, origine: str, destinazione: str) -> str:
    for path in (origine, destinazione):
        verdetto = await _verifica_perimetro(tenant_id, "move_file", path, supervisor.CATEGORIA_DISTRUTTIVA)
        if verdetto["verdict"] == supervisor.VERDICT_DENY:
            return f"Azione non consentita: {verdetto['message']} ({path})"
    if not conferma_terminale(f"move_file: sposta '{origine}' in '{destinazione}'."):
        return "Operazione annullata dall'utente."
    shutil.move(origine, destinazione)
    return f"Spostato: '{origine}' -> '{destinazione}'."


async def _delete_file(tenant_id: str, path: str) -> str:
    verdetto = await _verifica_perimetro(tenant_id, "delete_file", path, supervisor.CATEGORIA_DISTRUTTIVA)
    if verdetto["verdict"] == supervisor.VERDICT_DENY:
        return f"Azione non consentita: {verdetto['message']}"
    if not conferma_terminale(f"delete_file: elimina '{path}'."):
        return "Operazione annullata dall'utente."
    Path(path).unlink()
    return f"Eliminato: '{path}'."


async def _create_folder(tenant_id: str, path: str) -> str:
    verdetto = await _verifica_perimetro(tenant_id, "create_folder", path, supervisor.CATEGORIA_DISTRUTTIVA)
    if verdetto["verdict"] == supervisor.VERDICT_DENY:
        return f"Azione non consentita: {verdetto['message']}"
    if not conferma_terminale(f"create_folder: crea '{path}'."):
        return "Operazione annullata dall'utente."
    Path(path).mkdir(parents=True, exist_ok=True)
    return f"Cartella creata: '{path}'."


async def _import_document(tenant_id: str, path: str) -> str:
    """Ingest esplicito in Memoria di un file locale (vedi
    memoria/ingest_documento.py) - immediato, sola lettura del file dal
    lato Agente Locale (nessuna scrittura sul filesystem), ma sempre
    dentro il perimetro autorizzato come gli altri tool custom qui."""
    verdetto = await _verifica_perimetro(tenant_id, "import_document", path, supervisor.CATEGORIA_IMMEDIATA)
    if verdetto["verdict"] != supervisor.VERDICT_ALLOW:
        return f"Azione non consentita: {verdetto['message']}"
    file_path = Path(path)
    if not file_path.is_file():
        return f"'{path}' non è un file valido."
    contenuto = file_path.read_bytes()
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    try:
        return await importa_documento(tenant_id, "locale", path, file_path.name, contenuto, mime_type)
    except ErroreIngestDocumento as exc:
        return f"Non importato: {exc}"


def crea_server(tenant_id: str):
    @tool(
        "list_directory",
        "Elenca il contenuto di una cartella (dentro il perimetro autorizzato). Azione immediata, sola lettura.",
        {"path": str},
    )
    async def list_directory(args: dict) -> dict:
        return _testo(await _list_directory(tenant_id, args["path"]))

    @tool(
        "move_file",
        "Sposta o rinomina un file/cartella (origine e destinazione devono essere dentro il perimetro autorizzato). Richiede conferma esplicita dell'utente.",
        {"origine": str, "destinazione": str},
    )
    async def move_file(args: dict) -> dict:
        return _testo(await _move_file(tenant_id, args["origine"], args["destinazione"]))

    @tool(
        "delete_file",
        "Elimina un file (dentro il perimetro autorizzato). Richiede conferma esplicita dell'utente, non e' reversibile.",
        {"path": str},
    )
    async def delete_file(args: dict) -> dict:
        return _testo(await _delete_file(tenant_id, args["path"]))

    @tool(
        "create_folder",
        "Crea una cartella, incluse eventuali sottocartelle intermedie (dentro il perimetro autorizzato). Richiede conferma esplicita dell'utente.",
        {"path": str},
    )
    async def create_folder(args: dict) -> dict:
        return _testo(await _create_folder(tenant_id, args["path"]))

    @tool(
        "import_document",
        (
            "Importa in memoria permanente un documento locale (dentro il "
            "perimetro autorizzato) — PDF, Word, Excel, immagini/scansioni: "
            "lo rende cercabile semanticamente e, se riconosce chiaramente "
            "una controparte, ne salva anche i campi chiave come fatto "
            "collegato a quell'entità. USA SOLO quando l'utente chiede "
            "esplicitamente di ricordare/importare/salvare un documento — "
            "NON automaticamente durante una lettura normale con Read."
        ),
        {"path": str},
    )
    async def import_document(args: dict) -> dict:
        return _testo(await _import_document(tenant_id, args["path"]))

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[list_directory, move_file, delete_file, create_folder, import_document],
    )


ALLOWED_TOOLS = [
    f"mcp__{SERVER_NAME}__list_directory",
    f"mcp__{SERVER_NAME}__move_file",
    f"mcp__{SERVER_NAME}__delete_file",
    f"mcp__{SERVER_NAME}__create_folder",
    f"mcp__{SERVER_NAME}__import_document",
]

# Tool nativi SDK abilitati insieme ai custom sopra (vedi hook.py): Glob
# escluso, il suo tool_input non espone un path verificabile in modo
# affidabile (list_directory lo sostituisce).
NATIVE_ALLOWED_TOOLS = ["Read", "Write", "Edit", "Grep"]
