"""Trappole di drive_client: ricerca esclude il cestino di default, lettura
sceglie export/alt=media/nessuna-estrazione in base al tipo di file, spostare
usa addParents/removeParents (non duplica), condivisione pubblica vs per
email passano campi diversi a permissions.create."""
import json

import httpx
import pytest

from orchestratore import drive_client

_API_BASE = "https://www.googleapis.com/drive/v3"
_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"


@pytest.mark.asyncio
async def test_cerca_file_esclude_cestino_di_default(respx_mock):
    route = respx_mock.get(f"{_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )

    await drive_client.cerca_file("token", query="contratto")

    q = route.calls.last.request.url.params["q"]
    assert "trashed = false" in q
    assert "contratto" in q


@pytest.mark.asyncio
async def test_cerca_file_con_include_trashed_non_filtra(respx_mock):
    route = respx_mock.get(f"{_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )

    await drive_client.cerca_file("token", query="contratto", include_trashed=True)

    q = route.calls.last.request.url.params["q"]
    assert "trashed = false" not in q


@pytest.mark.asyncio
async def test_leggi_contenuto_google_doc_usa_export_text_plain(respx_mock):
    respx_mock.get(f"{_API_BASE}/files/doc-1").mock(
        return_value=httpx.Response(200, json={
            "id": "doc-1", "name": "Contratto", "mimeType": "application/vnd.google-apps.document",
        })
    )
    route_export = respx_mock.get(f"{_API_BASE}/files/doc-1/export").mock(
        return_value=httpx.Response(200, text="contenuto del contratto")
    )

    risultato = await drive_client.leggi_contenuto_file("token", "doc-1")

    assert route_export.calls.last.request.url.params["mimeType"] == "text/plain"
    assert risultato["testo"] == "contenuto del contratto"
    assert risultato["binario"] is False


@pytest.mark.asyncio
async def test_leggi_contenuto_google_sheet_usa_export_csv(respx_mock):
    respx_mock.get(f"{_API_BASE}/files/sheet-1").mock(
        return_value=httpx.Response(200, json={
            "id": "sheet-1", "name": "Budget", "mimeType": "application/vnd.google-apps.spreadsheet",
        })
    )
    route_export = respx_mock.get(f"{_API_BASE}/files/sheet-1/export").mock(
        return_value=httpx.Response(200, text="a,b,c")
    )

    await drive_client.leggi_contenuto_file("token", "sheet-1")

    assert route_export.calls.last.request.url.params["mimeType"] == "text/csv"


@pytest.mark.asyncio
async def test_leggi_contenuto_file_testuale_normale_usa_alt_media(respx_mock):
    route_media = respx_mock.get(f"{_API_BASE}/files/txt-1", params={"alt": "media"}).mock(
        return_value=httpx.Response(200, text="ciao mondo")
    )
    respx_mock.get(f"{_API_BASE}/files/txt-1").mock(
        return_value=httpx.Response(200, json={"id": "txt-1", "name": "note.txt", "mimeType": "text/plain"})
    )

    risultato = await drive_client.leggi_contenuto_file("token", "txt-1")

    assert route_media.called
    assert risultato["testo"] == "ciao mondo"


@pytest.mark.asyncio
async def test_leggi_contenuto_file_binario_non_estrae_testo(respx_mock):
    """Trappola centrale (vedi CLAUDE.md): un PDF/immagine non è testo -
    l'estrazione arriva con Tappa 5, qui si conferma solo l'esistenza."""
    respx_mock.get(f"{_API_BASE}/files/pdf-1").mock(
        return_value=httpx.Response(200, json={
            "id": "pdf-1", "name": "scansione.pdf", "mimeType": "application/pdf", "size": "12345",
        })
    )

    risultato = await drive_client.leggi_contenuto_file("token", "pdf-1")

    assert risultato["testo"] is None
    assert risultato["binario"] is True
    assert risultato["nome"] == "scansione.pdf"


@pytest.mark.asyncio
async def test_sposta_file_rimuove_i_vecchi_genitori(respx_mock):
    respx_mock.get(f"{_API_BASE}/files/f-1").mock(
        return_value=httpx.Response(200, json={
            "id": "f-1", "name": "Report", "mimeType": "text/plain", "parents": ["cartella-vecchia"],
        })
    )
    route_patch = respx_mock.patch(f"{_API_BASE}/files/f-1").mock(
        return_value=httpx.Response(200, json={
            "id": "f-1", "name": "Report", "mimeType": "text/plain", "parents": ["cartella-nuova"],
        })
    )

    risultato = await drive_client.sposta_file("token", "f-1", "cartella-nuova")

    params = route_patch.calls.last.request.url.params
    assert params["addParents"] == "cartella-nuova"
    assert params["removeParents"] == "cartella-vecchia"
    assert risultato["cartelle"] == ["cartella-nuova"]


@pytest.mark.asyncio
async def test_condividi_file_per_email_passa_type_user(respx_mock):
    route = respx_mock.post(f"{_API_BASE}/files/f-1/permissions").mock(
        return_value=httpx.Response(200, json={"id": "perm-1", "type": "user", "role": "reader"})
    )

    await drive_client.condividi_file("token", "f-1", email="cliente@example.com", ruolo="reader")

    corpo = json.loads(route.calls.last.request.content)
    assert corpo == {"type": "user", "role": "reader", "emailAddress": "cliente@example.com"}


@pytest.mark.asyncio
async def test_condividi_file_pubblico_passa_type_anyone_senza_email(respx_mock):
    route = respx_mock.post(f"{_API_BASE}/files/f-1/permissions").mock(
        return_value=httpx.Response(200, json={"id": "perm-2", "type": "anyone", "role": "reader"})
    )

    await drive_client.condividi_file("token", "f-1", ruolo="reader", pubblico=True)

    corpo = json.loads(route.calls.last.request.content)
    assert corpo == {"type": "anyone", "role": "reader"}
    assert "emailAddress" not in corpo


@pytest.mark.asyncio
async def test_cestina_file_non_elimina_in_modo_permanente(respx_mock):
    route = respx_mock.patch(f"{_API_BASE}/files/f-1").mock(
        return_value=httpx.Response(200, json={"id": "f-1", "name": "X", "mimeType": "text/plain"})
    )

    await drive_client.cestina_file("token", "f-1")

    corpo = json.loads(route.calls.last.request.content)
    assert corpo == {"trashed": True}


@pytest.mark.asyncio
async def test_crea_file_invia_multipart_con_metadata_e_contenuto(respx_mock):
    route = respx_mock.post(f"{_UPLOAD_BASE}/files").mock(
        return_value=httpx.Response(200, json={"id": "new-1", "name": "Note", "mimeType": "text/plain"})
    )

    risultato = await drive_client.crea_file("token", "Note", "contenuto testuale", cartella_padre_id="cartella-1")

    richiesta = route.calls.last.request
    assert richiesta.url.params["uploadType"] == "multipart"
    assert richiesta.headers["Content-Type"].startswith("multipart/related")
    corpo = richiesta.content.decode("utf-8")
    assert '"name": "Note"' in corpo
    assert '"parents": ["cartella-1"]' in corpo
    assert "contenuto testuale" in corpo
    assert risultato["file_id"] == "new-1"


@pytest.mark.asyncio
async def test_ottieni_access_token_senza_credenziale_solleva_errore_chiaro(monkeypatch):
    from orchestratore import oauth_core

    async def fake_get_credenziale(tenant_id, provider):
        return None

    monkeypatch.setattr(oauth_core, "get_credenziale", fake_get_credenziale)

    with pytest.raises(drive_client.DriveError, match="oauth/google_drive/authorize"):
        await drive_client.ottieni_access_token("11111111-1111-1111-1111-111111111111")
