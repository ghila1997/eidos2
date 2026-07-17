"""Contratto SSE di POST /chat/stream + motore agente persistente (Tappa 6).

Il motore (orchestratore/agente.py) tiene un ClaudeSDKClient vivo per tenant:
niente avvio di sottoprocesso a ogni turno (misurato ~6,4s a turno, trovato a
STOP 2). Qui il client SDK è un fake scriptato: si testa il contratto
dell'endpoint e il ciclo di vita del motore (riuso, ricrea su crash, resume).
"""
from __future__ import annotations

import json

import pytest
from claude_agent_sdk import ProcessError
from claude_agent_sdk.types import ResultMessage, StreamEvent
from starlette.testclient import TestClient

import memoria.db as memoria_db
from app import app
from orchestratore import agente, azioni
from orchestratore import router as router_mod

TENANT = "tenant-1"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _delta(testo: str) -> StreamEvent:
    return StreamEvent(
        uuid="u1",
        session_id="sess-nuova",
        event={
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": testo},
        },
    )


def _tool_start(nome_mcp: str) -> StreamEvent:
    return StreamEvent(
        uuid="u2",
        session_id="sess-nuova",
        event={
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": nome_mcp, "input": {}},
        },
    )


def _result(testo: str = "Ciao mondo", session_id: str = "sess-nuova") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        result=testo,
    )


def _eventi_sse(corpo: str) -> list[tuple[str, dict]]:
    eventi = []
    for blocco in corpo.strip().split("\n\n"):
        nome, data = None, None
        for riga in blocco.splitlines():
            if riga.startswith("event:"):
                nome = riga.removeprefix("event:").strip()
            elif riga.startswith("data:"):
                data = json.loads(riga.removeprefix("data:").strip())
        if nome is not None:
            eventi.append((nome, data))
    return eventi


class FakeSDKClient:
    """ClaudeSDKClient scriptato: ogni istanza consuma i turni del copione.
    Un turno è una lista di messaggi SDK oppure un'eccezione da sollevare."""

    copione: list[list] = []  # un elemento per istanza: lista di turni
    istanze: list["FakeSDKClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.prompts: list[str] = []
        self._turni = iter(FakeSDKClient.copione[len(FakeSDKClient.istanze)])
        self.connesso = False
        FakeSDKClient.istanze.append(self)

    async def connect(self):
        self.connesso = True

    async def disconnect(self):
        self.connesso = False

    async def query(self, prompt):
        self.prompts.append(prompt)
        self._corrente = next(self._turni)

    async def receive_response(self):
        if isinstance(self._corrente, Exception):
            raise self._corrente
        for messaggio in self._corrente:
            yield messaggio


@pytest.fixture()
def base(monkeypatch):
    """Auth, memoria e azioni finte; motore resettato; SDK fake."""

    async def fake_sessione(request):
        return {"tenant_id": TENANT, "user_id": "user-1", "role": "owner"}

    async def nessuna_azione(tenant_id):
        return None

    async def fake_preferenze(tenant_id):
        return {}

    async def fake_get_sessione(tenant_id):
        return "sess-vecchia"

    salvate: list[str] = []

    async def fake_set_sessione(tenant_id, session_id):
        salvate.append(session_id)

    monkeypatch.setattr(router_mod, "get_sessione_corrente", fake_sessione)
    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", nessuna_azione)
    monkeypatch.setattr(memoria_db, "get_preferenze", fake_preferenze)
    monkeypatch.setattr(memoria_db, "get_sessione_agent", fake_get_sessione)
    monkeypatch.setattr(memoria_db, "set_sessione_agent", fake_set_sessione)
    monkeypatch.setattr(agente, "ClaudeSDKClient", FakeSDKClient)
    agente._motori.clear()
    FakeSDKClient.copione = []
    FakeSDKClient.istanze = []
    return {"salvate": salvate, "monkeypatch": monkeypatch}


def test_stream_emette_delta_e_fine(base):
    FakeSDKClient.copione = [[[_delta("Ciao "), _delta("mondo"), _result("Ciao mondo")]]]
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    eventi = _eventi_sse(resp.text)
    assert ("delta", {"testo": "Ciao "}) == eventi[0]
    assert ("delta", {"testo": "mondo"}) == eventi[1]
    assert eventi[-1] == ("fine", {"risposta": "Ciao mondo", "azione_in_attesa": None})

    istanza = FakeSDKClient.istanze[0]
    assert istanza.options.include_partial_messages is True
    # niente resume all'avvio: riprendere uno storico vecchio di giorni
    # rallentava ogni turno (~+2,5s misurati) e costava token per sempre;
    # il resume serve solo al recupero della conversazione viva (crash)
    assert istanza.options.resume is None


def test_prefisso_turno_porta_data_e_canale(base):
    """La data non può più vivere nel system prompt (fisso alla connessione
    del client persistente): viaggia nel prefisso di ogni turno, costruito
    dal server — la trappola del 'oggi indovinato' non deve tornare."""
    FakeSDKClient.copione = [[[_result("ok")]]]
    _client().post("/chat/stream", json={"messaggio": "ciao"})
    prompt = FakeSDKClient.istanze[0].prompts[0]
    assert "[adesso:" in prompt
    assert "[canale: voce]" in prompt
    assert prompt.endswith("ciao")
    from datetime import datetime, timezone

    assert str(datetime.now(timezone.utc).year) in prompt


def test_chat_testuale_usa_lo_stesso_motore_con_canale_testo(base):
    FakeSDKClient.copione = [[[_result("risposta testo")]]]
    resp = _client().post("/chat", json={"messaggio": "ciao"})
    assert resp.status_code == 200
    assert resp.json()["risposta"] == "risposta testo"
    assert "[canale: testo]" in FakeSDKClient.istanze[0].prompts[0]


def test_motore_riusa_lo_stesso_processo_tra_turni(base):
    """Il punto del refactor: un solo sottoprocesso per tenant, i turni
    successivi non pagano l'avvio (~6,4s misurati)."""
    FakeSDKClient.copione = [[[_result("uno")], [_result("due")]]]
    c = _client()
    c.post("/chat/stream", json={"messaggio": "primo"})
    c.post("/chat/stream", json={"messaggio": "secondo"})
    assert len(FakeSDKClient.istanze) == 1
    assert len(FakeSDKClient.istanze[0].prompts) == 2


def test_stream_emette_tool_in_corso_senza_prefisso_mcp(base):
    FakeSDKClient.copione = [
        [[_tool_start("mcp__eidos__search_memoria"), _delta("Trovato."), _result("Trovato.")]]
    ]
    resp = _client().post("/chat/stream", json={"messaggio": "cerca x"})
    assert ("tool_in_corso", {"tool": "search_memoria"}) in _eventi_sse(resp.text)


def test_stream_409_se_azione_gia_pendente(base):
    async def azione_pendente(tenant_id):
        return {"id": "az-1", "tipo": "send_email", "payload": {}}

    base["monkeypatch"].setattr(azioni, "ottieni_azione_pendente_tenant", azione_pendente)
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["azione_id"] == "az-1"


def test_stream_azione_creata_arriva_nello_stream(base):
    azione = {"id": "az-9", "tipo": "send_email", "payload": {"destinatario": "x@y.it"}}
    esiti = iter([None, azione])

    async def azione_poi_creata(tenant_id):
        return next(esiti)

    base["monkeypatch"].setattr(azioni, "ottieni_azione_pendente_tenant", azione_poi_creata)
    FakeSDKClient.copione = [[[_delta("Preparo."), _result("Preparo.")]]]
    resp = _client().post("/chat/stream", json={"messaggio": "manda mail"})
    eventi = _eventi_sse(resp.text)
    assert eventi[-1] == ("fine", {"risposta": "Preparo.", "azione_in_attesa": azione})


def test_stream_salva_session_id_nuovo(base):
    FakeSDKClient.copione = [[[_result(session_id="sess-nuova")]]]
    _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert base["salvate"] == ["sess-nuova"]


def test_crash_del_processo_ricrea_il_client_con_resume_della_sessione_viva(base):
    """Sottoprocesso morto (ProcessError) senza nulla emesso: il motore
    ricrea il client riprendendo la sessione creata da QUESTO processo —
    la conversazione in corso non si perde per un crash del sottoprocesso."""
    FakeSDKClient.copione = [
        [[_result("ok", session_id="sess-viva")], ProcessError("processo morto")],
        [[_delta("Eccomi."), _result("Eccomi.")]],
    ]
    c = _client()
    c.post("/chat/stream", json={"messaggio": "primo"})
    resp = c.post("/chat/stream", json={"messaggio": "secondo"})
    eventi = _eventi_sse(resp.text)
    assert ("delta", {"testo": "Eccomi."}) in eventi
    assert "errore" not in [n for n, _ in eventi]
    assert len(FakeSDKClient.istanze) == 2
    assert FakeSDKClient.istanze[1].options.resume == "sess-viva"


def test_doppio_crash_riparte_senza_resume(base):
    """Se anche il retry con resume fallisce, l'ultima carta è una sessione
    pulita (il file di sessione può essere sparito col container)."""
    FakeSDKClient.copione = [
        [[_result("ok", session_id="sess-viva")], ProcessError("morto")],
        [ProcessError("resume rotto")],
        [[_delta("Ripartito."), _result("Ripartito.")]],
    ]
    c = _client()
    c.post("/chat/stream", json={"messaggio": "primo"})
    resp = c.post("/chat/stream", json={"messaggio": "secondo"})
    assert ("delta", {"testo": "Ripartito."}) in _eventi_sse(resp.text)
    assert FakeSDKClient.istanze[1].options.resume == "sess-viva"
    assert FakeSDKClient.istanze[2].options.resume is None


async def test_prescalda_apre_il_client_in_anticipo(base):
    """Il primo turno dopo un riavvio pagava ~10s di connessione: all'avvio
    del server il motore del founder si prepara in anticipo (se
    EIDOS_TENANT_ID è configurato)."""
    FakeSDKClient.copione = [[[_result("ok")]]]
    await agente.prescalda(TENANT)
    assert len(FakeSDKClient.istanze) == 1
    assert FakeSDKClient.istanze[0].connesso is True
    # il turno successivo riusa il client già caldo
    motore = await agente.motore_per(TENANT)
    async for _ in motore.turno("ciao", canale="testo"):
        pass
    assert len(FakeSDKClient.istanze) == 1


async def test_prescalda_senza_tenant_non_fa_nulla(base):
    await agente.prescalda(None)
    assert FakeSDKClient.istanze == []


def test_stream_errore_persistente_da_evento_pulito(base):
    FakeSDKClient.copione = [
        [Exception("529")],
        [Exception("529 ancora")],
        [Exception("529 sempre")],
    ]
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert [n for n, _ in _eventi_sse(resp.text)] == ["errore"]
    assert "529" not in resp.text
    assert "Traceback" not in resp.text
