"""Translator condiviso turno SDK -> eventi UI (orchestratore/streaming.py),
usato sia dalla voce sia dalla sessione web. Tappa 7.2 aggiunge `tool_finito`
(chiusura della riga di log) e l'arricchimento di `fine` con la descrizione
leggibile dell'azione pending per la scheda di conferma."""
import pytest
from claude_agent_sdk.types import ResultMessage, StreamEvent, ToolResultBlock, UserMessage

from orchestratore import azioni, streaming

pytestmark = pytest.mark.asyncio

TENANT = "11111111-1111-1111-1111-111111111111"


def _tool_start(tool_id: str, nome: str) -> StreamEvent:
    return StreamEvent(
        uuid="u", session_id="s",
        event={"type": "content_block_start", "index": 1,
               "content_block": {"type": "tool_use", "id": tool_id, "name": nome, "input": {}}},
    )


def _tool_result(tool_id: str, is_error: bool = False) -> UserMessage:
    return UserMessage(content=[ToolResultBlock(tool_use_id=tool_id, content="ok", is_error=is_error)])


def _result(testo="ok") -> ResultMessage:
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                         is_error=False, num_turns=1, session_id="s", result=testo)


class FakeMotore:
    def __init__(self, eventi):
        self._eventi = eventi

    async def turno(self, messaggio, canale):
        for e in self._eventi:
            yield e


async def _raccogli(eventi, monkeypatch, azioni_pendenti=()):
    async def fake_pendenti(tenant_id):
        return list(azioni_pendenti)

    monkeypatch.setattr(azioni, "ottieni_azioni_pendenti_tenant", fake_pendenti)
    out = []
    async for ev in streaming.traduci_turno(FakeMotore(eventi), "ciao", canale="testo", tenant_id=TENANT):
        out.append(ev)
    return out


async def test_tool_start_e_result_diventano_in_corso_e_finito_stesso_id(monkeypatch):
    eventi = [_tool_start("tu_1", "mcp__eidos__search_files"),
              _tool_result("tu_1"), _result("fatto")]
    out = await _raccogli(eventi, monkeypatch)

    in_corso = next(e for e in out if e["evento"] == "tool_in_corso")
    finito = next(e for e in out if e["evento"] == "tool_finito")
    assert in_corso["id"] == "tu_1" and in_corso["tool"] == "search_files"
    assert in_corso["etichetta"] == "Cerco tra i file"
    assert finito["id"] == "tu_1" and finito["esito"] == "ok"


async def test_tool_result_con_errore_da_esito_errore(monkeypatch):
    eventi = [_tool_start("tu_9", "mcp__eidos__read_file"),
              _tool_result("tu_9", is_error=True), _result("ops")]
    out = await _raccogli(eventi, monkeypatch)

    finito = next(e for e in out if e["evento"] == "tool_finito")
    assert finito == {"evento": "tool_finito", "id": "tu_9", "esito": "errore"}


async def test_fine_arricchisce_azione_con_descrizione(monkeypatch):
    azione = {"id": "az-1", "tipo": "send_email",
              "payload": {"destinatario": "x@y.it", "oggetto": "Ciao", "corpo": "Testo"}}
    out = await _raccogli([_result("pronto")], monkeypatch, azioni_pendenti=[azione])

    fine = out[-1]
    assert fine["evento"] == "fine"
    assert fine["azione_in_attesa"]["descrizione"]["titolo"] == "Invio email"
    # una sola azione: scheda identica a prima, non "1 azione da confermare"
    assert fine["azione_in_attesa"]["descrizione"]["multipla"] is False


async def test_fine_con_piu_azioni_le_raggruppa_in_una_scheda_sola(monkeypatch):
    """Il caso del bug: 21 trash_email in un turno davano 21 conferme, di cui
    l'utente ne vedeva UNA (le altre riemergevano un messaggio alla volta).
    Ora l'evento `fine` porta l'intero gruppo in una scheda."""
    pendenti = [
        {"id": f"az-{i}", "tipo": "trash_email",
         "payload": {"message_id": f"m{i}", "mittente": f"Tizio {i}", "oggetto": f"Oggetto {i}"}}
        for i in range(21)
    ]
    out = await _raccogli([_result("pronto")], monkeypatch, azioni_pendenti=pendenti)

    scheda = out[-1]["azione_in_attesa"]
    assert len(scheda["azioni"]) == 21
    descrizione = scheda["descrizione"]
    assert descrizione["multipla"] is True
    assert descrizione["titolo"] == "21 mail nel cestino"
    assert len(descrizione["voci"]) == 21
    # ogni voce porta il suo id (serve per escluderla) e testo leggibile
    assert descrizione["voci"][0]["id"] == "az-0"
    assert descrizione["voci"][0]["riepilogo"] == "Tizio 0 · Oggetto 0"


async def test_fine_senza_azione_non_ha_descrizione(monkeypatch):
    out = await _raccogli([_result("pronto")], monkeypatch, azioni_pendenti=[])
    assert out[-1] == {"evento": "fine", "risposta": "pronto", "azione_in_attesa": None}


async def test_etichetta_tool_sconosciuto_ricade_sul_nome_pulito():
    assert streaming.etichetta_tool("mcp__eidos__qualcosa_nuovo") == "qualcosa_nuovo"
    assert streaming.etichetta_tool("Read") == "Read"


async def test_etichetta_trash_email_non_dice_che_e_gia_fatto():
    """Trovato a STOP 2 (2026-07-30): "Cestino la mail" col ✓ leggeva come
    "fatto", ma a quel punto l'azione è solo proposta - parte alla conferma.
    Tutte le scritture gated devono stare al gerundio."""
    assert streaming.etichetta_tool("mcp__eidos__trash_email") == "Preparo il cestinamento"
    for tool in ("send_email", "reply_email", "forward_email", "send_draft",
                 "trash_email", "trash_file", "delete_event", "forget_document"):
        etichetta = streaming.etichetta_tool(f"mcp__eidos__{tool}")
        assert etichetta.startswith("Preparo"), f"{tool} non è al gerundio: {etichetta}"
