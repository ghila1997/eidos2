"""Hook PreToolUse unico per i tool nativi dell'SDK usati da Agente Locale
(vedi DECISIONS.md, "Safety Supervisor: punto unico di autorizzazione per
ogni tool call"): calcola se il/i path coinvolti sono dentro il perimetro
autorizzato e chiama il Safety Supervisor. Un verdetto `ask_user` si risolve
qui stesso con un prompt sincrono al terminale, fuori dal controllo del
modello.

Nota su `Glob`: verificato sulla documentazione ufficiale live che il suo
`tool_input` espone solo `pattern`, non un campo path esplicito da poter
validare in modo affidabile qui - per non lasciare un varco (fail open su
un tool che enumera il filesystem), `Glob` NON e' tra i tool nativi
abilitati in questo ciclo; la stessa capacita' (elencare una cartella) e'
coperta dal tool custom `list_directory` in `tools.py`, dove il path e'
sempre esplicito e verificabile (vedi DECISIONS.md per la nota completa).
"""
from __future__ import annotations

from claude_agent_sdk import HookMatcher

from orchestratore.safety import supervisor

from . import perimetro
from .conferma_locale import conferma_terminale

# Read/Write/Edit hanno sempre un file_path esplicito (campo obbligatorio
# nel loro schema). Grep ha "paths" (lista, opzionale: se assente cerca
# nella cwd - per questo il chiamante DEVE impostare cwd su una cartella
# del perimetro, vedi cli_locale.py).
_CAMPO_PATH = {"Read": "file_path", "Write": "file_path", "Edit": "file_path"}

_CATEGORIA_PER_TOOL = {
    "Read": supervisor.CATEGORIA_IMMEDIATA,
    "Grep": supervisor.CATEGORIA_IMMEDIATA,
    "Write": supervisor.CATEGORIA_DISTRUTTIVA,
    "Edit": supervisor.CATEGORIA_DISTRUTTIVA,
}


def _nega(motivo: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": motivo,
        }
    }


async def _path_da_verificare(tool_name: str, tool_input: dict, cwd: str) -> list[str] | None:
    """None = tool senza path da verificare (nessun controllo qui)."""
    if tool_name in _CAMPO_PATH:
        path = tool_input.get(_CAMPO_PATH[tool_name])
        return [path] if path else []  # manca il campo obbligatorio -> fail closed (lista vuota = nessun path valido)
    if tool_name == "Grep":
        paths = tool_input.get("paths") or [cwd]  # nessun path esplicito -> ricade sulla cwd (sempre nel perimetro)
        return list(paths)
    return None


def crea_hook_perimetro(tenant_id: str, cwd: str) -> HookMatcher:
    async def hook_perimetro(input_data: dict, tool_use_id, context) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        path_da_verificare = await _path_da_verificare(tool_name, tool_input, cwd)
        if path_da_verificare is None:
            return {}
        if not path_da_verificare:
            return _nega(f"{tool_name}: percorso mancante o non valido.")

        categoria = _CATEGORIA_PER_TOOL.get(tool_name, supervisor.CATEGORIA_DISTRUTTIVA)

        for path in path_da_verificare:
            dentro = await perimetro.is_path_allowed(tenant_id, path)
            verdetto = supervisor.validate(
                {"name": tool_name, "category": categoria},
                {"tenant_id": tenant_id, "path_in_perimetro": dentro, "file_path": path},
            )
            if verdetto["verdict"] == supervisor.VERDICT_DENY:
                return _nega(verdetto["message"])
            if verdetto["verdict"] == supervisor.VERDICT_ASK_USER:
                if not conferma_terminale(f"{tool_name} su '{path}'."):
                    return _nega("Operazione annullata dall'utente.")

        return {}

    return HookMatcher(matcher="Read|Write|Edit|Grep", hooks=[hook_perimetro])
