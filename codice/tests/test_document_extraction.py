from types import SimpleNamespace

import pytest

from memoria import document_extraction


class _FakeMessages:
    def __init__(self, content):
        self._content = content
        self.ultima_chiamata: dict | None = None

    async def create(self, **kwargs):
        self.ultima_chiamata = kwargs
        return SimpleNamespace(content=self._content)


class _FakeAnthropic:
    def __init__(self, content):
        self.messages = _FakeMessages(content)


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
