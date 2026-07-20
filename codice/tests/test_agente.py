"""Test di MotoreAgente: ciclo di vita del client persistente, opzioni di
configurazione, interruzione di un tentativo in corso (Tappa 6, incr.4)."""
from __future__ import annotations

import pytest

from orchestratore import agente

TENANT = "tenant-1"


class FakeSDKClient:
    """ClaudeSDKClient scriptato: ogni istanza consuma i turni del copione.
    Un turno e' una lista di messaggi SDK oppure un'eccezione da sollevare."""

    copione: list[list] = []
    istanze: list["FakeSDKClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.prompts: list[str] = []
        self._turni = iter(FakeSDKClient.copione[len(FakeSDKClient.istanze)])
        self.connesso = False
        self.interrotto = 0
        FakeSDKClient.istanze.append(self)

    async def connect(self):
        self.connesso = True

    async def disconnect(self):
        self.connesso = False

    async def query(self, prompt):
        self.prompts.append(prompt)
        self._corrente = next(self._turni)

    async def interrupt(self):
        self.interrotto += 1

    async def receive_response(self):
        if isinstance(self._corrente, Exception):
            raise self._corrente
        for messaggio in self._corrente:
            yield messaggio


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    import memoria.db as memoria_db

    async def fake_preferenze(tenant_id):
        return {}

    async def fake_set_sessione_agent(tenant_id, session_id):
        pass

    monkeypatch.setattr(agente, "ClaudeSDKClient", FakeSDKClient)
    monkeypatch.setattr(memoria_db, "get_preferenze", fake_preferenze)
    monkeypatch.setattr(memoria_db, "set_sessione_agent", fake_set_sessione_agent)
    agente._motori.clear()
    FakeSDKClient.copione = []
    FakeSDKClient.istanze = []


async def test_interrompi_su_motore_senza_client_non_fa_nulla():
    """Nessun turno mai partito: interrompi() è un no-op sicuro."""
    motore = await agente.motore_per(TENANT)
    await motore.interrompi()  # non deve sollevare


async def test_interrompi_chiama_interrupt_sul_client_connesso():
    from claude_agent_sdk.types import ResultMessage

    def _result(testo="ok"):
        return ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id="sess-1", result=testo,
        )

    FakeSDKClient.copione = [[[_result()]]]
    motore = await agente.motore_per(TENANT)
    async for _ in motore.turno("ciao", canale="voce"):
        pass  # il turno finisce, il client resta connesso e riusabile
    await motore.interrompi()
    assert FakeSDKClient.istanze[0].interrotto == 1
