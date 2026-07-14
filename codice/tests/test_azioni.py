"""Trappola centrale della Tappa 2: send_email non deve mai inviare senza
conferma esplicita, e la conferma deve restare scoped al tenant giusto."""
import httpx
import pytest

from orchestratore import azioni, gmail_client

SUPABASE_URL = "https://fake.supabase.co"
TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
AZIONE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

PAYLOAD = {"destinatario": "x@example.com", "oggetto": "Ciao", "corpo": "Testo"}


def _mock_azione(respx_mock, tenant_id: str, stato: str = azioni.STATO_IN_ATTESA):
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": AZIONE_ID,
                    "tenant_id": tenant_id,
                    "tipo": azioni.TIPO_SEND_EMAIL,
                    "payload": PAYLOAD,
                    "stato": stato,
                }
            ],
        )
    )


@pytest.mark.asyncio
async def test_crea_azione_pending_scrive_e_ritorna_id(respx_mock):
    respx_mock.post(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(201, json=[{"id": AZIONE_ID}])
    )
    azione_id = await azioni.crea_azione_pending(TENANT_A, azioni.TIPO_SEND_EMAIL, PAYLOAD)
    assert azione_id == AZIONE_ID


@pytest.mark.asyncio
async def test_conferma_no_non_invia_mail(respx_mock, monkeypatch):
    _mock_azione(respx_mock, TENANT_A)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[])
    )

    invio_chiamato = False

    async def fake_invia(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=False)

    assert risultato["stato"] == azioni.STATO_RIFIUTATA
    assert invio_chiamato is False


@pytest.mark.asyncio
async def test_conferma_si_invia_mail_una_sola_volta(respx_mock, monkeypatch):
    _mock_azione(respx_mock, TENANT_A)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[])
    )

    chiamate = []

    async def fake_ottieni_token(tenant_id):
        return "fake-access-token"

    async def fake_invia(access_token, destinatario, oggetto, corpo):
        chiamate.append((destinatario, oggetto, corpo))
        return {"id": "msg-1"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_ottieni_token)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == [(PAYLOAD["destinatario"], PAYLOAD["oggetto"], PAYLOAD["corpo"])]


@pytest.mark.asyncio
async def test_conferma_azione_di_altro_tenant_non_trovata(respx_mock):
    """Anti-leak: un'azione del tenant A non deve essere confermabile
    passando il tenant B, anche conoscendo l'id esatto."""
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[])
    )

    with pytest.raises(azioni.AzioneNonTrovata):
        await azioni.conferma_azione(TENANT_B, AZIONE_ID, conferma=True)


@pytest.mark.asyncio
async def test_conferma_azione_gia_risolta_solleva_errore(respx_mock):
    _mock_azione(respx_mock, TENANT_A, stato=azioni.STATO_INVIATA)

    with pytest.raises(azioni.AzioneGiaRisolta):
        await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)
