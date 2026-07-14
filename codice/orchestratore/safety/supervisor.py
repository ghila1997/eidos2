"""Safety Supervisor: punto unico di autorizzazione per ogni tool call,
nativo o custom (vedi DECISIONS.md, "Safety Supervisor: punto unico di
autorizzazione per ogni tool call"). Non esegue nulla, decide soltanto
allow/deny/ask_user in base a policy dichiarative (`policies.yaml`).
Stateless: riceve un'azione e un contesto, restituisce subito un verdetto
piu' un audit log immutabile (JSON Lines).

Chi chiama `validate()` resta responsabile di eseguire l'azione (se
`allow`), di crearne una pendente in attesa di conferma umana (se
`ask_user`, per Gmail via `azioni.py`; per Agente Locale con un prompt
sincrono al terminale) o di rifiutarla (se `deny`) - il Supervisor stesso
non parla mai con l'utente.
"""
from __future__ import annotations

import json
import operator
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CATEGORIA_IMMEDIATA = "immediata"
CATEGORIA_DISTRUTTIVA = "distruttiva"

VERDICT_ALLOW = "allow"
VERDICT_DENY = "deny"
VERDICT_ASK_USER = "ask_user"

_POLICY_PATH = Path(__file__).parent / "policies.yaml"
_AUDIT_LOG_PATH = Path(__file__).parent / "audit.log"

_OPERATORI = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
}

_policy_cache: list[dict] | None = None


def carica_policy(path: Path | None = None) -> list[dict]:
    """Legge e ordina le regole per priorita' crescente (vince il primo match)."""
    percorso = path or _POLICY_PATH
    with open(percorso, encoding="utf-8") as f:
        dati = yaml.safe_load(f)
    regole = dati.get("policies", [])
    return sorted(regole, key=lambda r: r["priority"])


def reload_policies() -> None:
    """Rilegge il file di policy senza riavviare il processo."""
    global _policy_cache
    _policy_cache = carica_policy()


def _policy_attive() -> list[dict]:
    global _policy_cache
    if _policy_cache is None:
        _policy_cache = carica_policy()
    return _policy_cache


def _valuta_condizione(valore_reale: Any, valore_atteso: Any) -> bool:
    if isinstance(valore_atteso, str):
        for simbolo, funzione in _OPERATORI.items():
            if valore_atteso.startswith(simbolo + " "):
                confronto: Any = valore_atteso[len(simbolo):].strip()
                try:
                    confronto = float(confronto)
                    valore_reale = float(valore_reale)
                except (TypeError, ValueError):
                    pass
                return funzione(valore_reale, confronto)
        if valore_atteso.startswith("in ["):
            opzioni = [v.strip() for v in valore_atteso[4:-1].split(",")]
            return str(valore_reale) in opzioni
        if valore_atteso.startswith("matches "):
            pattern = valore_atteso[len("matches "):].strip()
            return re.search(pattern, str(valore_reale)) is not None
    return valore_reale == valore_atteso


def _condizioni_soddisfatte(condizioni: dict, context: dict) -> bool:
    for chiave, valore_atteso in condizioni.items():
        if chiave not in context:
            return False  # condizione mancante nel contesto = non soddisfatta
        if not _valuta_condizione(context[chiave], valore_atteso):
            return False
    return True


def _sostituisci_placeholder(messaggio: str | None, dati: dict) -> str | None:
    if messaggio is None:
        return None

    def _sostituisci(match: re.Match) -> str:
        chiave = match.group(1)
        return str(dati[chiave]) if chiave in dati else match.group(0)

    return re.sub(r"\{(\w+)\}", _sostituisci, messaggio)


def _registra_audit(action: dict, context: dict, verdict: str, matched_rule: str) -> None:
    riga = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": context.get("tenant_id"),
        "action": action.get("name"),
        "category": action.get("category"),
        "context": {k: v for k, v in context.items() if k != "tenant_id"},
        "verdict": verdict,
        "rule": matched_rule,
    }
    with open(_AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(riga, ensure_ascii=False) + "\n")


def validate(action: dict, context: dict, *, policies: list[dict] | None = None) -> dict:
    """`action = {"name": ..., "category": ..., "params": {...}}` (params
    opzionale). `context` porta sempre `tenant_id` piu' i campi rilevanti per
    le condizioni delle regole. Ritorna `{"verdict", "message", "matched_rule"}`.
    """
    regole = policies if policies is not None else _policy_attive()
    regole = sorted(regole, key=lambda r: r["priority"])
    params = action.get("params", {})

    for regola in regole:
        if "action" in regola and action.get("name") != regola["action"]:
            continue
        if "category" in regola and action.get("category") != regola["category"]:
            continue
        if not _condizioni_soddisfatte(regola.get("conditions", {}), context):
            continue

        dati_messaggio = {**params, **context, "tool_name": action.get("name")}
        messaggio = _sostituisci_placeholder(regola.get("message"), dati_messaggio)
        _registra_audit(action, context, regola["response"], regola["name"])
        return {"verdict": regola["response"], "message": messaggio, "matched_rule": regola["name"]}

    # Nessuna regola applicabile: fallisce chiuso, mai aperto per default -
    # rete di sicurezza nel caso un file di policy personalizzato dimentichi
    # una regola di default deny esplicita.
    _registra_audit(action, context, VERDICT_DENY, "default_deny")
    return {
        "verdict": VERDICT_DENY,
        "message": "Azione non autorizzata: nessuna policy applicabile.",
        "matched_rule": "default_deny",
    }
