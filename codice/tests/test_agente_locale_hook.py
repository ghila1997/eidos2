"""Hook PreToolUse di Agente Locale: trappola centrale e' che un tool nativo
(Read/Write/Edit/Grep) non deve mai poter toccare un path fuori dal
perimetro, e le scritture dentro il perimetro devono sempre passare da una
conferma esplicita risolta PRIMA che il tool nativo esegua davvero."""
import pytest

from agente_locale import hook, perimetro

TENANT = "11111111-1111-1111-1111-111111111111"
CWD = "C:\\EidosTest"


def _input(tool_name: str, tool_input: dict) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input}


@pytest.mark.asyncio
async def test_read_fuori_perimetro_negato(monkeypatch):
    async def fake_allowed(tenant_id, path):
        return False

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](
        _input("Read", {"file_path": "C:\\Windows\\segreto.txt"}), None, None
    )

    assert risultato["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.asyncio
async def test_read_dentro_perimetro_permesso(monkeypatch):
    async def fake_allowed(tenant_id, path):
        return True

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](
        _input("Read", {"file_path": f"{CWD}\\appunti.txt"}), None, None
    )

    assert risultato == {}


@pytest.mark.asyncio
async def test_write_dentro_perimetro_con_conferma_permesso(monkeypatch):
    async def fake_allowed(tenant_id, path):
        return True

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)
    monkeypatch.setattr(hook, "conferma_terminale", lambda messaggio: True)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](
        _input("Write", {"file_path": f"{CWD}\\nuovo.txt", "file_text": "ciao"}), None, None
    )

    assert risultato == {}


@pytest.mark.asyncio
async def test_write_dentro_perimetro_rifiuto_conferma_negato(monkeypatch):
    async def fake_allowed(tenant_id, path):
        return True

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)
    monkeypatch.setattr(hook, "conferma_terminale", lambda messaggio: False)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](
        _input("Write", {"file_path": f"{CWD}\\nuovo.txt", "file_text": "ciao"}), None, None
    )

    assert risultato["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.asyncio
async def test_edit_fuori_perimetro_negato_senza_chiedere_conferma(monkeypatch):
    async def fake_allowed(tenant_id, path):
        return False

    conferma_chiamata = False

    def fake_conferma(messaggio):
        nonlocal conferma_chiamata
        conferma_chiamata = True
        return True

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)
    monkeypatch.setattr(hook, "conferma_terminale", fake_conferma)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](
        _input("Edit", {"file_path": "C:\\Windows\\config.ini", "edits": []}), None, None
    )

    assert risultato["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert conferma_chiamata is False


@pytest.mark.asyncio
async def test_grep_con_un_path_fuori_perimetro_negato(monkeypatch):
    async def fake_allowed(tenant_id, path):
        return path == f"{CWD}\\dentro"

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](
        _input("Grep", {"pattern": "prova", "paths": [f"{CWD}\\dentro", "C:\\Fuori"]}), None, None
    )

    assert risultato["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.asyncio
async def test_grep_senza_paths_usa_cwd(monkeypatch):
    path_verificati = []

    async def fake_allowed(tenant_id, path):
        path_verificati.append(path)
        return path == CWD

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_allowed)

    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](_input("Grep", {"pattern": "prova"}), None, None)

    assert risultato == {}
    assert path_verificati == [CWD]


@pytest.mark.asyncio
async def test_tool_senza_path_non_verificato(monkeypatch):
    """Un tool non mappato (es. futuro tool senza dimensione path) non deve
    bloccare l'esecuzione qui - non e' compito di questo hook."""
    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](_input("AskUserQuestion", {}), None, None)

    assert risultato == {}


@pytest.mark.asyncio
async def test_write_senza_file_path_negato_fail_closed(monkeypatch):
    matcher = hook.crea_hook_perimetro(TENANT, CWD)
    risultato = await matcher.hooks[0](_input("Write", {"file_text": "ciao"}), None, None)

    assert risultato["hookSpecificOutput"]["permissionDecision"] == "deny"
