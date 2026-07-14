"""Trappole di gmail_client: risposta nel thread giusto, inoltro con
allegati originali, creazione etichetta solo se manca davvero,
incrementale via history.list."""
import httpx
import pytest

from orchestratore import gmail_client

_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

ORIGINALE = {
    "message_id": "msg-orig",
    "thread_id": "thread-1",
    "rfc822_message_id": "<abc@mail.gmail.com>",
    "mittente": "cliente@example.com",
    "destinatari": "founder@example.com",
    "oggetto": "Richiesta preventivo",
    "corpo": "Vorrei un preventivo",
    "allegati": [],
}


@pytest.mark.asyncio
async def test_rispondi_messaggio_usa_thread_e_in_reply_to(monkeypatch):
    """Trappola: senza thread_id/In-Reply-To, la risposta arriva come mail
    slegata invece che nello stesso thread Gmail."""
    async def fake_ottieni_messaggio(access_token, message_id):
        assert message_id == "msg-orig"
        return ORIGINALE

    chiamata = {}

    async def fake_invia(access_token, destinatario, oggetto, corpo, cc=None, bcc=None,
                          allegati=None, thread_id=None, in_reply_to=None, references=None):
        chiamata.update(locals())
        return {"id": "msg-reply"}

    monkeypatch.setattr(gmail_client, "ottieni_messaggio", fake_ottieni_messaggio)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    await gmail_client.rispondi_messaggio("token", "msg-orig", "Ecco il preventivo")

    assert chiamata["thread_id"] == "thread-1"
    assert chiamata["in_reply_to"] == "<abc@mail.gmail.com>"
    assert chiamata["references"] == "<abc@mail.gmail.com>"
    assert chiamata["destinatario"] == "cliente@example.com"  # risponde al mittente originale
    assert chiamata["oggetto"] == "Re: Richiesta preventivo"


@pytest.mark.asyncio
async def test_rispondi_messaggio_non_raddoppia_prefisso_re(monkeypatch):
    originale_gia_re = {**ORIGINALE, "oggetto": "Re: Richiesta preventivo"}

    async def fake_ottieni_messaggio(access_token, message_id):
        return originale_gia_re

    chiamata = {}

    async def fake_invia(access_token, destinatario, oggetto, corpo, **kwargs):
        chiamata["oggetto"] = oggetto
        return {"id": "msg-reply"}

    monkeypatch.setattr(gmail_client, "ottieni_messaggio", fake_ottieni_messaggio)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    await gmail_client.rispondi_messaggio("token", "msg-orig", "Corpo")

    assert chiamata["oggetto"] == "Re: Richiesta preventivo"


@pytest.mark.asyncio
async def test_inoltra_messaggio_riporta_corpo_e_scarica_allegati(monkeypatch):
    originale_con_allegato = {
        **ORIGINALE,
        "allegati": [{"attachment_id": "att-1", "filename": "fattura.pdf", "mime_type": "application/pdf", "size": 100}],
    }

    async def fake_ottieni_messaggio(access_token, message_id):
        return originale_con_allegato

    async def fake_scarica(access_token, message_id, attachment_id):
        assert attachment_id == "att-1"
        return b"contenuto-pdf-finto"

    chiamata = {}

    async def fake_invia(access_token, destinatario, oggetto, corpo, cc=None, bcc=None, allegati=None, **kwargs):
        chiamata["oggetto"] = oggetto
        chiamata["corpo"] = corpo
        chiamata["allegati"] = allegati
        return {"id": "msg-fwd"}

    monkeypatch.setattr(gmail_client, "ottieni_messaggio", fake_ottieni_messaggio)
    monkeypatch.setattr(gmail_client, "scarica_allegato", fake_scarica)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    await gmail_client.inoltra_messaggio("token", "msg-orig", "collega@example.com", testo_aggiuntivo="Guarda qui")

    assert chiamata["oggetto"] == "Fwd: Richiesta preventivo"
    assert "Guarda qui" in chiamata["corpo"]
    assert "Vorrei un preventivo" in chiamata["corpo"]  # corpo originale riportato
    assert chiamata["allegati"] == [{"filename": "fattura.pdf", "contenuto": b"contenuto-pdf-finto"}]


@pytest.mark.asyncio
async def test_trova_o_crea_etichetta_riusa_esistente_senza_duplicare(monkeypatch):
    async def fake_lista(access_token):
        return [{"id": "label-1", "name": "Clienti"}]

    crea_chiamato = False

    async def fake_crea(access_token, nome):
        nonlocal crea_chiamato
        crea_chiamato = True
        return {"id": "label-nuovo"}

    monkeypatch.setattr(gmail_client, "lista_etichette", fake_lista)
    monkeypatch.setattr(gmail_client, "crea_etichetta", fake_crea)

    etichetta_id = await gmail_client.trova_o_crea_etichetta("token", "clienti")  # case-insensitive

    assert etichetta_id == "label-1"
    assert crea_chiamato is False


@pytest.mark.asyncio
async def test_trova_o_crea_etichetta_crea_se_mancante(monkeypatch):
    async def fake_lista(access_token):
        return [{"id": "label-1", "name": "Clienti"}]

    async def fake_crea(access_token, nome):
        assert nome == "Fornitori"
        return {"id": "label-nuovo"}

    monkeypatch.setattr(gmail_client, "lista_etichette", fake_lista)
    monkeypatch.setattr(gmail_client, "crea_etichetta", fake_crea)

    etichetta_id = await gmail_client.trova_o_crea_etichetta("token", "Fornitori")

    assert etichetta_id == "label-nuovo"


@pytest.mark.asyncio
async def test_lista_messaggi_nuovi_con_cursore_usa_history_list(respx_mock):
    """Con un cursore (historyId) esistente, l'incrementale passa da
    history.list, non da un fetch pieno."""
    route = respx_mock.get(f"{_API_BASE}/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "history": [
                    {"messagesAdded": [{"message": {"id": "msg-1"}}]},
                    {"messagesAdded": [{"message": {"id": "msg-2"}}]},
                ],
                "historyId": "54321",
            },
        )
    )

    ids, nuovo_cursore = await gmail_client.lista_messaggi_nuovi("token", "12345")

    assert route.calls.last.request.url.params["startHistoryId"] == "12345"
    assert ids == ["msg-1", "msg-2"]
    assert nuovo_cursore == "54321"


@pytest.mark.asyncio
async def test_lista_messaggi_nuovi_senza_cursore_fa_fetch_pieno(respx_mock):
    """Primo import (nessun cursore): fetch pieno via messages.list, nuovo
    cursore preso da getProfile, non da history.list."""
    respx_mock.get(f"{_API_BASE}/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "msg-1"}, {"id": "msg-2"}]})
    )
    respx_mock.get(f"{_API_BASE}/profile").mock(
        return_value=httpx.Response(200, json={"historyId": "99999"})
    )

    ids, nuovo_cursore = await gmail_client.lista_messaggi_nuovi("token", None)

    assert ids == ["msg-1", "msg-2"]
    assert nuovo_cursore == "99999"


@pytest.mark.asyncio
async def test_lista_messaggi_nuovi_con_cursore_scaduto_fa_fallback_a_fetch_pieno(respx_mock):
    """Trappola: se Gmail scarta il cursore (historyId troppo vecchio,
    404), non deve esplodere - deve ripiegare su un fetch pieno."""
    respx_mock.get(f"{_API_BASE}/history").mock(return_value=httpx.Response(404))
    respx_mock.get(f"{_API_BASE}/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "msg-3"}]})
    )
    respx_mock.get(f"{_API_BASE}/profile").mock(
        return_value=httpx.Response(200, json={"historyId": "11111"})
    )

    ids, nuovo_cursore = await gmail_client.lista_messaggi_nuovi("token", "cursore-vecchio")

    assert ids == ["msg-3"]
    assert nuovo_cursore == "11111"
