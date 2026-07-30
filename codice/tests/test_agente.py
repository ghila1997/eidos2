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


async def test_opzioni_motore_isola_i_tool_nativi_e_le_skill():
    """tools=None (default) esporrebbe TUTTI i nativi (Bash/Read/
    ToolSearch) al modello - trovato in reale (STOP 2, 2026-07-19): il
    modello ha chiamato ToolSearch su un turno vocale."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.tools == []
    assert opzioni.skills == ["redazione-email"]


async def test_opzioni_motore_thinking_adaptive_low():
    """Verificato in reale: 3,34s con thinking di default -> 1,52s su un
    saluto identico con adaptive+low (STOP 2, 2026-07-19)."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.thinking == {"type": "adaptive"}
    assert opzioni.effort == "low"


async def test_opzioni_motore_niente_config_utente():
    """MAI 'user': caricherebbe la config personale di Claude Code di chi
    ospita il server dentro l'agente del prodotto (trovato in reale, STOP 2
    2026-07-18)."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.setting_sources == ["project"]


async def test_opzioni_motore_niente_resume_di_sessioni_vecchie():
    """Niente resume all'avvio: riprendere uno storico vecchio rallentava
    ogni turno (~+2,5s misurati) e costava token per sempre."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.resume is None
    opzioni_con_resume = await motore._opzioni(resume="sess-viva")
    assert opzioni_con_resume.resume == "sess-viva"


# --- il modello deve sapere cosa è stato confermato (STOP 2, 2026-07-30) ----
# Il gate sta fuori dal turno, quindi nulla tornava al modello: alla domanda
# "l'hai fatto?" rispondeva "non ancora" su azioni già eseguite, e a "fallo di
# nuovo" le ricreava. Su 11 cestinamenti reali sono diventate 22 azioni.

def test_prefisso_turno_senza_esiti_resta_come_prima():
    prefisso = agente._prefisso_turno("testo")
    assert "[canale: testo]" in prefisso
    assert "eseguito dopo la tua conferma" not in prefisso


def test_prefisso_turno_riporta_gli_esiti_confermati():
    prefisso = agente._prefisso_turno("testo", ["11 mail spostate nel cestino"])
    assert "[eseguito dopo la tua conferma: 11 mail spostate nel cestino]" in prefisso


def test_annota_esito_viene_consumato_una_volta_sola():
    """Una nota si dà una volta: al turno dopo vive già nel contesto della
    sessione, ripeterla farebbe credere al modello che sia successo di nuovo."""
    tenant = "tenant-test-esiti"
    agente.annota_esito(tenant, "Mail inviata a x@y.it")
    agente.annota_esito(tenant, "Evento creato: Riunione")

    assert agente._consuma_esiti(tenant) == ["Mail inviata a x@y.it", "Evento creato: Riunione"]
    assert agente._consuma_esiti(tenant) == []


def test_annota_esito_e_per_tenant():
    agente.annota_esito("tenant-a", "Mail inviata")
    assert agente._consuma_esiti("tenant-b") == []
    assert agente._consuma_esiti("tenant-a") == ["Mail inviata"]


def test_annota_esito_ignora_stringa_vuota():
    """Un rifiuto non produce esito: non deve lasciare una nota vuota che il
    modello leggerebbe come 'è stato eseguito qualcosa'."""
    agente.annota_esito("tenant-vuoto", "")
    assert agente._consuma_esiti("tenant-vuoto") == []


def test_system_prompt_vieta_di_dire_che_non_e_stato_fatto():
    prompt = agente._costruisci_system_prompt({})
    assert "eseguito dopo la tua conferma" in prompt
    assert "Non riproporre MAI la stessa azione" in prompt
