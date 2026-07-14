"""Motore di policy del Safety Supervisor, isolato dall'SDK: riceve
un'azione e un contesto, deve sempre restituire un verdetto - mai eseguire
nulla, mai fallire aperto su un'azione sconosciuta (default deny)."""
import json

import pytest

from orchestratore.safety import supervisor

TENANT = "11111111-1111-1111-1111-111111111111"

# L'isolamento dell'audit log (nessun test scrive nel repo reale) e' un
# fixture autouse globale in conftest.py: vale anche per test_tools.py/
# test_azioni.py, che ora passano dal Supervisor pur non conoscendolo.


def _policy_reali():
    return supervisor.carica_policy()


@pytest.mark.asyncio
async def test_azione_immediata_permessa():
    verdetto = supervisor.validate(
        {"name": "mark_email", "category": supervisor.CATEGORIA_IMMEDIATA},
        {"tenant_id": TENANT},
        policies=_policy_reali(),
    )
    assert verdetto["verdict"] == supervisor.VERDICT_ALLOW


@pytest.mark.asyncio
async def test_azione_distruttiva_chiede_conferma_con_placeholder():
    verdetto = supervisor.validate(
        {"name": "send_email", "category": supervisor.CATEGORIA_DISTRUTTIVA},
        {"tenant_id": TENANT},
        policies=_policy_reali(),
    )
    assert verdetto["verdict"] == supervisor.VERDICT_ASK_USER
    assert verdetto["message"] == "Azione: send_email. Confermi?"


@pytest.mark.asyncio
async def test_azione_categoria_sconosciuta_negata_per_default():
    """Fail closed: un'azione senza categoria riconosciuta non deve mai
    passare per default - deve essere esplicitamente negata."""
    verdetto = supervisor.validate(
        {"name": "qualcosa_di_nuovo", "category": "categoria_mai_vista"},
        {"tenant_id": TENANT},
        policies=_policy_reali(),
    )
    assert verdetto["verdict"] == supervisor.VERDICT_DENY
    assert verdetto["matched_rule"] == "Default deny"


def test_priorita_vince_regola_con_priority_minore():
    policy = [
        {"name": "bassa priorita'", "priority": 50, "category": "x", "response": "deny"},
        {"name": "alta priorita'", "priority": 5, "category": "x", "response": "allow"},
    ]
    verdetto = supervisor.validate(
        {"name": "azione", "category": "x"}, {"tenant_id": TENANT}, policies=policy
    )
    assert verdetto["matched_rule"] == "alta priorita'"
    assert verdetto["verdict"] == "allow"


def test_condizione_soddisfatta_fa_match():
    policy = [
        {
            "name": "dentro perimetro",
            "priority": 10,
            "conditions": {"path_in_perimetro": True},
            "response": "allow",
        },
        {"name": "fallback", "priority": 20, "response": "deny"},
    ]
    verdetto = supervisor.validate(
        {"name": "read_file"}, {"tenant_id": TENANT, "path_in_perimetro": True}, policies=policy
    )
    assert verdetto["matched_rule"] == "dentro perimetro"


def test_condizione_mancante_nel_contesto_valutata_falsa():
    """Se il contesto non porta la chiave richiesta dalla condizione, la
    regola non deve poter matchare (sicurezza per default, non un crash)."""
    policy = [
        {
            "name": "dentro perimetro",
            "priority": 10,
            "conditions": {"path_in_perimetro": True},
            "response": "allow",
        },
        {"name": "fallback", "priority": 20, "response": "deny"},
    ]
    verdetto = supervisor.validate(
        {"name": "read_file"}, {"tenant_id": TENANT}, policies=policy  # niente path_in_perimetro
    )
    assert verdetto["matched_rule"] == "fallback"
    assert verdetto["verdict"] == "deny"


def test_audit_log_scrive_una_riga_json_con_tenant_id():
    supervisor.validate(
        {"name": "send_email", "category": supervisor.CATEGORIA_DISTRUTTIVA},
        {"tenant_id": TENANT},
        policies=_policy_reali(),
    )
    righe = supervisor._AUDIT_LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    assert len(righe) == 1
    riga = json.loads(righe[0])
    assert riga["tenant_id"] == TENANT
    assert riga["action"] == "send_email"
    assert riga["verdict"] == "ask_user"


def test_reload_policies_rilegge_il_file(tmp_path, monkeypatch):
    file_policy = tmp_path / "policies.yaml"
    file_policy.write_text(
        "policies:\n  - name: consenti tutto\n    priority: 10\n    response: allow\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor, "_POLICY_PATH", file_policy)
    monkeypatch.setattr(supervisor, "_policy_cache", None)

    supervisor.reload_policies()

    verdetto = supervisor.validate({"name": "qualsiasi"}, {"tenant_id": TENANT})
    assert verdetto["verdict"] == "allow"
    assert verdetto["matched_rule"] == "consenti tutto"
