"""Il blocco su azione pendente (endpoint /chat) allega la descrizione
leggibile che il CLI/web mostrano, così la fonte della descrizione è una sola
(server) - Tappa 7.2."""
import pytest
from fastapi import HTTPException

from orchestratore import azioni, router

pytestmark = pytest.mark.asyncio


async def test_blocco_azione_pendente_espone_descrizione(monkeypatch):
    async def azione_bloccante(tenant_id):
        return {"id": "az-1", "tipo": "send_email",
                "payload": {"destinatario": "x@y.it", "oggetto": "Ciao", "corpo": "Testo"}}

    monkeypatch.setattr(azioni, "azione_bloccante", azione_bloccante)

    with pytest.raises(HTTPException) as exc:
        await router._blocca_se_azione_pendente("t1")

    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["azione_id"] == "az-1"
    assert detail["descrizione"]["titolo"] == "Invio email"


async def test_nessun_blocco_se_non_c_e_azione(monkeypatch):
    async def niente(tenant_id):
        return None

    monkeypatch.setattr(azioni, "azione_bloccante", niente)

    await router._blocca_se_azione_pendente("t1")  # non solleva
