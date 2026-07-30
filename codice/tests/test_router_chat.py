"""Il blocco su azione pendente (endpoint /chat) allega la descrizione
leggibile che il CLI/web mostrano, così la fonte della descrizione è una sola
(server) - Tappa 7.2. Il blocco vale per l'intero gruppo di azioni del turno,
non per una sola: erano N conferme e se ne vedeva una."""
import pytest
from fastapi import HTTPException

from orchestratore import azioni, router

pytestmark = pytest.mark.asyncio


async def test_blocco_azione_pendente_espone_descrizione(monkeypatch):
    async def bloccanti(tenant_id):
        return [{"id": "az-1", "tipo": "send_email",
                 "payload": {"destinatario": "x@y.it", "oggetto": "Ciao", "corpo": "Testo"}}]

    monkeypatch.setattr(azioni, "azioni_bloccanti", bloccanti)

    with pytest.raises(HTTPException) as exc:
        await router._blocca_se_azione_pendente("t1")

    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert [a["id"] for a in detail["azioni"]] == ["az-1"]
    assert detail["descrizione"]["titolo"] == "Invio email"


async def test_blocco_espone_tutto_il_gruppo_non_solo_la_prima(monkeypatch):
    async def bloccanti(tenant_id):
        return [{"id": f"az-{i}", "tipo": "trash_email",
                 "payload": {"message_id": f"m{i}", "mittente": "Tizio", "oggetto": f"Ogg {i}"}}
                for i in range(21)]

    monkeypatch.setattr(azioni, "azioni_bloccanti", bloccanti)

    with pytest.raises(HTTPException) as exc:
        await router._blocca_se_azione_pendente("t1")

    detail = exc.value.detail
    assert len(detail["azioni"]) == 21
    assert detail["descrizione"]["titolo"] == "21 mail nel cestino"


async def test_nessun_blocco_se_non_c_e_azione(monkeypatch):
    async def niente(tenant_id):
        return []

    monkeypatch.setattr(azioni, "azioni_bloccanti", niente)

    await router._blocca_se_azione_pendente("t1")  # non solleva
