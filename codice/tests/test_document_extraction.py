from types import SimpleNamespace

import pytest

from memoria import document_extraction


class _FakeStream:
    """Il percorso visione usa client.messages.stream(...) (trascrizioni
    lunghe, vedi document_extraction.py) - il fake espone lo stesso
    contratto: async context manager + get_final_message()."""

    def __init__(self, message):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, content, stop_reason="tool_use"):
        self._content = content
        self._stop_reason = stop_reason
        self.ultima_chiamata: dict | None = None

    async def create(self, **kwargs):
        self.ultima_chiamata = kwargs
        return SimpleNamespace(content=self._content, stop_reason=self._stop_reason)

    def stream(self, **kwargs):
        self.ultima_chiamata = kwargs
        return _FakeStream(SimpleNamespace(content=self._content, stop_reason=self._stop_reason))


class _FakeAnthropic:
    def __init__(self, content, stop_reason="tool_use"):
        self.messages = _FakeMessages(content, stop_reason)


def _blocco_tool_use(input_dict):
    return SimpleNamespace(type="tool_use", name=document_extraction._TOOL_NAME, input=input_dict)


@pytest.mark.asyncio
async def test_estrai_da_testo_usa_haiku_e_delimita_contenuto_non_fidato(monkeypatch):
    fake = _FakeAnthropic([_blocco_tool_use({
        "tipo_documento": "fattura", "entity_nome": "Rossi Srl",
        "campi": {"importo": "500.00"},
    })])
    monkeypatch.setattr(document_extraction.anthropic, "AsyncAnthropic", lambda: fake)

    risultato = await document_extraction.estrai_da_testo("Fattura di Rossi Srl, importo 500 euro")

    assert risultato["entity_nome"] == "Rossi Srl"
    chiamata = fake.messages.ultima_chiamata
    assert chiamata["model"] == document_extraction.MODEL_TESTO
    assert "<documento_non_fidato>" in chiamata["messages"][0]["content"]
    assert chiamata["tool_choice"] == {"type": "tool", "name": document_extraction._TOOL_NAME}


@pytest.mark.asyncio
async def test_estrai_da_testo_senza_entita_chiara_omette_entity_nome(monkeypatch):
    fake = _FakeAnthropic([_blocco_tool_use({"tipo_documento": "altro", "campi": {}})])
    monkeypatch.setattr(document_extraction.anthropic, "AsyncAnthropic", lambda: fake)

    risultato = await document_extraction.estrai_da_testo("appunti generici senza controparte")

    assert "entity_nome" not in risultato


@pytest.mark.asyncio
async def test_estrai_da_documento_visivo_usa_sonnet_e_content_block_pdf(monkeypatch):
    fake = _FakeAnthropic([_blocco_tool_use({
        "tipo_documento": "ricevuta", "campi": {}, "testo_completo": "Scontrino trascritto",
    })])
    monkeypatch.setattr(document_extraction.anthropic, "AsyncAnthropic", lambda: fake)

    risultato = await document_extraction.estrai_da_documento_visivo(b"%PDF-bytes-finti", "application/pdf")

    assert risultato["testo_completo"] == "Scontrino trascritto"
    chiamata = fake.messages.ultima_chiamata
    assert chiamata["model"] == document_extraction.MODEL_VISIONE
    blocco_documento = chiamata["messages"][0]["content"][0]
    assert blocco_documento["type"] == "document"
    assert blocco_documento["source"]["media_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_estrai_da_documento_visivo_immagine_usa_content_block_image(monkeypatch):
    fake = _FakeAnthropic([_blocco_tool_use({"tipo_documento": "altro", "campi": {}, "testo_completo": ""})])
    monkeypatch.setattr(document_extraction.anthropic, "AsyncAnthropic", lambda: fake)

    await document_extraction.estrai_da_documento_visivo(b"immagine-finta", "image/jpeg")

    blocco_documento = fake.messages.ultima_chiamata["messages"][0]["content"][0]
    assert blocco_documento["type"] == "image"
    assert blocco_documento["source"]["media_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_senza_tool_use_solleva_errore(monkeypatch):
    fake = _FakeAnthropic([SimpleNamespace(type="text", text="risposta senza tool")])
    monkeypatch.setattr(document_extraction.anthropic, "AsyncAnthropic", lambda: fake)

    with pytest.raises(RuntimeError):
        await document_extraction.estrai_da_testo("qualcosa")


@pytest.mark.asyncio
async def test_visione_troncata_solleva_errore_esplicito(monkeypatch):
    """Se la trascrizione sfonda max_tokens il JSON del tool è mutilato:
    meglio un errore esplicito che indicizzare una trascrizione a metà
    spacciandola per completa."""
    fake = _FakeAnthropic(
        [_blocco_tool_use({"tipo_documento": "contratto", "campi": {}, "testo_completo": "troncat"})],
        stop_reason="max_tokens",
    )
    monkeypatch.setattr(document_extraction.anthropic, "AsyncAnthropic", lambda: fake)

    with pytest.raises(RuntimeError, match="tronc"):
        await document_extraction.estrai_da_documento_visivo(b"%PDF-finto", "application/pdf")
