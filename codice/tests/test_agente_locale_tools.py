"""Trappola centrale: le operazioni che toccano davvero il filesystem
(move/delete/create_folder) non devono mai avvenire senza conferma esplicita
dell'utente, e mai fuori dal perimetro autorizzato - a prescindere da cosa
"pensa" il modello di dover fare."""
import pytest

from agente_locale import perimetro, tools

TENANT = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_move_file_dentro_perimetro_con_conferma_sposta(tmp_path, monkeypatch):
    origine = tmp_path / "appunti.txt"
    origine.write_text("prova")
    destinazione = tmp_path / "archivio" / "appunti.txt"
    destinazione.parent.mkdir()

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())
    monkeypatch.setattr(tools, "conferma_terminale", lambda messaggio: True)

    risultato = await tools._move_file(TENANT, str(origine), str(destinazione))

    assert destinazione.exists()
    assert not origine.exists()
    assert "Spostato" in risultato


@pytest.mark.asyncio
async def test_move_file_rifiuto_conferma_non_sposta(tmp_path, monkeypatch):
    origine = tmp_path / "appunti.txt"
    origine.write_text("prova")
    destinazione = tmp_path / "appunti-spostato.txt"

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())
    monkeypatch.setattr(tools, "conferma_terminale", lambda messaggio: False)

    risultato = await tools._move_file(TENANT, str(origine), str(destinazione))

    assert origine.exists()
    assert not destinazione.exists()
    assert "annullata" in risultato


@pytest.mark.asyncio
async def test_move_file_destinazione_fuori_perimetro_negato_senza_conferma(tmp_path, monkeypatch):
    origine = tmp_path / "appunti.txt"
    origine.write_text("prova")
    destinazione = tmp_path / "fuori" / "appunti.txt"

    async def fake_is_allowed(tenant_id, path):
        return path == str(origine)  # solo l'origine e' dentro il perimetro

    conferma_chiamata = False

    def fake_conferma(messaggio):
        nonlocal conferma_chiamata
        conferma_chiamata = True
        return True

    monkeypatch.setattr(perimetro, "is_path_allowed", fake_is_allowed)
    monkeypatch.setattr(tools, "conferma_terminale", fake_conferma)

    risultato = await tools._move_file(TENANT, str(origine), str(destinazione))

    assert origine.exists()
    assert conferma_chiamata is False, "non deve chiedere conferma se gia' negato dal perimetro"
    assert "non consentita" in risultato


@pytest.mark.asyncio
async def test_delete_file_conferma_elimina(tmp_path, monkeypatch):
    file = tmp_path / "da-eliminare.txt"
    file.write_text("prova")

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())
    monkeypatch.setattr(tools, "conferma_terminale", lambda messaggio: True)

    risultato = await tools._delete_file(TENANT, str(file))

    assert not file.exists()
    assert "Eliminato" in risultato


@pytest.mark.asyncio
async def test_delete_file_rifiuto_conferma_non_elimina(tmp_path, monkeypatch):
    file = tmp_path / "da-non-eliminare.txt"
    file.write_text("prova")

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())
    monkeypatch.setattr(tools, "conferma_terminale", lambda messaggio: False)

    risultato = await tools._delete_file(TENANT, str(file))

    assert file.exists()
    assert "annullata" in risultato


@pytest.mark.asyncio
async def test_delete_file_fuori_perimetro_negato(tmp_path, monkeypatch):
    file = tmp_path / "protetto.txt"
    file.write_text("prova")

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _false())
    monkeypatch.setattr(tools, "conferma_terminale", lambda messaggio: True)

    risultato = await tools._delete_file(TENANT, str(file))

    assert file.exists()
    assert "non consentita" in risultato


@pytest.mark.asyncio
async def test_create_folder_con_conferma_crea_sottocartelle(tmp_path, monkeypatch):
    nuova = tmp_path / "livello1" / "livello2"

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())
    monkeypatch.setattr(tools, "conferma_terminale", lambda messaggio: True)

    risultato = await tools._create_folder(TENANT, str(nuova))

    assert nuova.is_dir()
    assert "creata" in risultato


@pytest.mark.asyncio
async def test_import_document_fuori_perimetro_negato_senza_chiamare_ingest(tmp_path, monkeypatch):
    file = tmp_path / "fattura.pdf"
    file.write_bytes(b"contenuto")

    chiamato = False

    async def fake_importa(*args, **kwargs):
        nonlocal chiamato
        chiamato = True
        return "non dovrebbe arrivare qui"

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _false())
    monkeypatch.setattr(tools, "importa_documento", fake_importa)

    risultato = await tools._import_document(TENANT, str(file))

    assert chiamato is False
    assert "non consentita" in risultato


@pytest.mark.asyncio
async def test_import_document_dentro_perimetro_chiama_ingest(tmp_path, monkeypatch):
    file = tmp_path / "note.txt"
    file.write_bytes(b"contenuto di prova")

    ricevuto = {}

    async def fake_importa(tenant_id, fonte, source_id, nome_file, contenuto, mime_type):
        ricevuto.update(
            tenant_id=tenant_id, fonte=fonte, source_id=source_id,
            nome_file=nome_file, contenuto=contenuto, mime_type=mime_type,
        )
        return "Documento importato (id doc-1, tipo altro): ricercabile in memoria."

    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())
    monkeypatch.setattr(tools, "importa_documento", fake_importa)

    risultato = await tools._import_document(TENANT, str(file))

    assert ricevuto["fonte"] == "locale"
    assert ricevuto["source_id"] == str(file)
    assert ricevuto["contenuto"] == b"contenuto di prova"
    assert "importato" in risultato


@pytest.mark.asyncio
async def test_import_document_file_inesistente(tmp_path, monkeypatch):
    monkeypatch.setattr(perimetro, "is_path_allowed", lambda tenant_id, path: _true())

    risultato = await tools._import_document(TENANT, str(tmp_path / "non-esiste.pdf"))

    assert "non è un file valido" in risultato


async def _true(*args, **kwargs) -> bool:
    return True


async def _false(*args, **kwargs) -> bool:
    return False
