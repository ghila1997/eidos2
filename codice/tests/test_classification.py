from types import SimpleNamespace

import pytest

from orchestratore import classification


class _FakeMessages:
    def __init__(self, content):
        self._content = content

    async def create(self, **kwargs):
        return SimpleNamespace(content=self._content)


class _FakeAnthropic:
    def __init__(self, content):
        self.messages = _FakeMessages(content)


@pytest.mark.asyncio
async def test_classifica_mail_estrae_tool_use(monkeypatch):
    blocco = SimpleNamespace(
        type="tool_use",
        name=classification._TOOL_NAME,
        input={"ingest": True, "categoria": "cliente", "priorita": "alta"},
    )
    monkeypatch.setattr(
        classification.anthropic, "AsyncAnthropic", lambda: _FakeAnthropic([blocco])
    )

    risultato = await classification.classifica_mail("x@example.com", "Oggetto", "Corpo")

    assert risultato == {"ingest": True, "categoria": "cliente", "priorita": "alta"}


@pytest.mark.asyncio
async def test_classifica_mail_senza_tool_use_solleva_errore(monkeypatch):
    blocco = SimpleNamespace(type="text", text="risposta senza tool")
    monkeypatch.setattr(
        classification.anthropic, "AsyncAnthropic", lambda: _FakeAnthropic([blocco])
    )

    with pytest.raises(RuntimeError):
        await classification.classifica_mail("x@example.com", "Oggetto", "Corpo")
