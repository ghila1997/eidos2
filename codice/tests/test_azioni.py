"""Trappola centrale della Tappa 2: send_email non deve mai inviare senza
conferma esplicita, e la conferma deve restare scoped al tenant giusto."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from orchestratore import azioni, calendar_client, conversazione, drive_client, gmail_client

SUPABASE_URL = "https://fake.supabase.co"
TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
AZIONE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

PAYLOAD = {"destinatario": "x@example.com", "oggetto": "Ciao", "corpo": "Testo"}


def _mock_azione(
    respx_mock, tenant_id: str, stato: str = azioni.STATO_IN_ATTESA,
    tipo: str = azioni.TIPO_SEND_EMAIL, payload: dict | None = None,
    created_at: str | None = None,
):
    riga = {
        "id": AZIONE_ID,
        "tenant_id": tenant_id,
        "tipo": tipo,
        "payload": payload if payload is not None else PAYLOAD,
        "stato": stato,
    }
    if created_at is not None:
        riga["created_at"] = created_at
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[riga])
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

    async def fake_invia(access_token, destinatario, oggetto, corpo, cc=None, bcc=None):
        chiamate.append((destinatario, oggetto, corpo))
        return {"id": "msg-1"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_ottieni_token)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == [(PAYLOAD["destinatario"], PAYLOAD["oggetto"], PAYLOAD["corpo"])]


@pytest.mark.asyncio
async def test_conferma_ritorna_esito_dal_vivo_ma_non_lo_persiste(respx_mock, monkeypatch):
    """Tappa 7.3 (rivisto 2026-07-29): l'esito ("Mail inviata a X") torna nel
    payload per la conferma DAL VIVO nella UI, ma NON si scrive in cronologia -
    le azioni fatte non si tengono (la verità è in Gmail). `conversazione` non
    deve nemmeno essere toccato da conferma_azione."""
    _mock_azione(respx_mock, TENANT_A)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[])
    )

    async def fake_ottieni_token(tenant_id):
        return "fake-access-token"

    async def fake_invia(*a, **k):
        return {"id": "msg-1"}

    scritture = []

    async def esplodi_se_scrive(*a, **k):
        scritture.append(a)

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_ottieni_token)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)
    monkeypatch.setattr(conversazione, "salva_turno", esplodi_se_scrive)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["esito"] == f"Mail inviata a {PAYLOAD['destinatario']}"
    assert scritture == []  # niente scrittura in cronologia
    assert not hasattr(conversazione, "salva_esito")  # rimossa: non si persiste più


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


@pytest.mark.asyncio
async def test_conferma_reply_email_chiama_rispondi_messaggio(respx_mock, monkeypatch):
    payload = {"message_id": "msg-orig", "corpo": "Grazie!", "destinatario": None, "cc": None, "bcc": None}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_REPLY_EMAIL, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_rispondi(access_token, message_id, corpo, destinatario=None, cc=None, bcc=None):
        chiamate.append(message_id)
        return {"id": "msg-2"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "rispondi_messaggio", fake_rispondi)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == ["msg-orig"]


@pytest.mark.asyncio
async def test_conferma_forward_email_chiama_inoltra_messaggio(respx_mock, monkeypatch):
    payload = {"message_id": "msg-orig", "destinatario": "collega@example.com", "testo_aggiuntivo": "", "cc": None, "bcc": None}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_FORWARD_EMAIL, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_inoltra(access_token, message_id, destinatario, testo_aggiuntivo="", cc=None, bcc=None):
        chiamate.append((message_id, destinatario))
        return {"id": "msg-2"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "inoltra_messaggio", fake_inoltra)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == [("msg-orig", "collega@example.com")]


@pytest.mark.asyncio
async def test_conferma_send_draft_chiama_invia_bozza(respx_mock, monkeypatch):
    payload = {"draft_id": "draft-1"}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_SEND_DRAFT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_invia_bozza(access_token, draft_id):
        chiamate.append(draft_id)
        return {"id": "msg-2"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "invia_bozza", fake_invia_bozza)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == ["draft-1"]


@pytest.mark.asyncio
async def test_conferma_create_event_chiama_crea_evento(respx_mock, monkeypatch):
    payload = {"titolo": "Riunione", "inizio": "2026-07-20T10:00:00Z", "fine": "2026-07-20T11:00:00Z", "partecipanti": ["cliente@example.com"]}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_CREATE_EVENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_crea_evento(access_token, **kwargs):
        chiamate.append(kwargs["titolo"])
        return {"id": "evt-1"}

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "crea_evento", fake_crea_evento)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == ["Riunione"]


@pytest.mark.asyncio
async def test_conferma_delete_event_chiama_elimina_evento_con_notifica(respx_mock, monkeypatch):
    payload = {"event_id": "evt-1", "notifica": True, "calendario": None}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_DELETE_EVENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_elimina(access_token, event_id, *, notifica, calendario=None):
        chiamate.append((event_id, notifica))

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "elimina_evento", fake_elimina)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == [("evt-1", True)]


@pytest.mark.asyncio
async def test_conferma_no_su_create_event_non_crea_nulla(respx_mock, monkeypatch):
    payload = {"titolo": "Riunione", "inizio": "x", "fine": "y", "partecipanti": ["cliente@example.com"]}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_CREATE_EVENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamato = False

    async def fake_crea_evento(*args, **kwargs):
        nonlocal chiamato
        chiamato = True

    monkeypatch.setattr(calendar_client, "crea_evento", fake_crea_evento)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=False)

    assert risultato["stato"] == azioni.STATO_RIFIUTATA
    assert chiamato is False


@pytest.mark.asyncio
async def test_conferma_trash_email_chiama_cestina_messaggio(respx_mock, monkeypatch):
    payload = {"message_id": "msg-1"}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_TRASH_EMAIL, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_cestina(access_token, message_id):
        chiamate.append(message_id)
        return {"id": message_id}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "cestina_messaggio", fake_cestina)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == ["msg-1"]


@pytest.mark.asyncio
async def test_conferma_share_file_chiama_condividi_file(respx_mock, monkeypatch):
    payload = {"file_id": "f-1", "email": "cliente@example.com", "ruolo": "reader", "pubblico": False}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_SHARE_FILE, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_condividi(access_token, file_id, email=None, ruolo="reader", pubblico=False):
        chiamate.append((file_id, email, ruolo, pubblico))
        return {"id": "perm-1"}

    monkeypatch.setattr(drive_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(drive_client, "condividi_file", fake_condividi)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == [("f-1", "cliente@example.com", "reader", False)]


@pytest.mark.asyncio
async def test_conferma_no_su_share_file_non_condivide_nulla(respx_mock, monkeypatch):
    payload = {"file_id": "f-1", "email": "cliente@example.com", "ruolo": "reader", "pubblico": False}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_SHARE_FILE, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamato = False

    async def fake_condividi(*args, **kwargs):
        nonlocal chiamato
        chiamato = True

    monkeypatch.setattr(drive_client, "condividi_file", fake_condividi)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=False)

    assert risultato["stato"] == azioni.STATO_RIFIUTATA
    assert chiamato is False


@pytest.mark.asyncio
async def test_conferma_trash_file_chiama_cestina_file(respx_mock, monkeypatch):
    payload = {"file_id": "f-1"}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_TRASH_FILE, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_cestina(access_token, file_id):
        chiamate.append(file_id)
        return {"file_id": file_id}

    monkeypatch.setattr(drive_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(drive_client, "cestina_file", fake_cestina)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == ["f-1"]


@pytest.mark.asyncio
async def test_conferma_forget_document_chiama_dimentica(respx_mock, monkeypatch):
    """Tappa 5.1: dimenticare un documento passa dallo stesso gate delle
    altre azioni distruttive - solo la conferma esplicita dell'utente
    esegue la cancellazione vera."""
    payload = {"documento_id": "doc-9"}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_FORGET_DOCUMENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamate = []

    async def fake_dimentica(tenant_id, documento_id):
        chiamate.append((tenant_id, documento_id))
        return "dimenticato"

    monkeypatch.setattr(azioni.gestione_documenti, "dimentica_documento", fake_dimentica)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamate == [(TENANT_A, "doc-9")]


@pytest.mark.asyncio
async def test_conferma_no_su_forget_document_non_elimina(respx_mock, monkeypatch):
    payload = {"documento_id": "doc-9"}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_FORGET_DOCUMENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiamato = {"si": False}

    async def fake_dimentica(*args):
        chiamato["si"] = True

    monkeypatch.setattr(azioni.gestione_documenti, "dimentica_documento", fake_dimentica)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=False)

    assert risultato["stato"] == azioni.STATO_RIFIUTATA
    assert chiamato["si"] is False


@pytest.mark.asyncio
async def test_conferma_propose_commitment_scrive_impegno_aperto(respx_mock, monkeypatch):
    """Solo alla conferma esplicita l'impegno viene davvero scritto - mai
    prima (vedi tools._propose_commitment, che crea solo l'azione pending)."""
    payload = {
        "entity_nome": "Isagro",
        "descrizione": "Restituire pagamento doppio fattura 725FE",
        "direzione": "nostro",
        "source_type": "gmail",
        "source_id": "msg-1",
        "source_excerpt": "si richiede risarcimento doppio pagamento",
        "observed_at": "2026-07-21T09:53:31+00:00",
        "scadenza": None,
        "confidence": 0.9,
    }
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_PROPOSE_COMMITMENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    async def fake_trova_simile(tenant_id, entity_key, source_type, source_id):
        return None

    scritti = []

    async def fake_upsert_impegno(tenant_id, **kwargs):
        scritti.append((tenant_id, kwargs))
        return "impegno-1"

    monkeypatch.setattr(azioni.memoria_db, "trova_impegno_simile", fake_trova_simile)
    monkeypatch.setattr(azioni.memoria_db, "upsert_impegno", fake_upsert_impegno)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert len(scritti) == 1
    tenant_scritto, campi = scritti[0]
    assert tenant_scritto == TENANT_A
    assert campi["entity_key"] == "isagro"
    assert campi["descrizione"] == "Restituire pagamento doppio fattura 725FE"
    assert campi["direzione"] == "nostro"
    assert campi["source_type"] == "gmail"
    assert campi["source_id"] == "msg-1"
    assert campi["source_excerpt"] == "si richiede risarcimento doppio pagamento"
    assert campi["observed_at"] == "2026-07-21T09:53:31+00:00"
    assert campi["scadenza"] is None
    assert 0 <= campi["confidence"] <= 1


@pytest.mark.asyncio
async def test_conferma_propose_commitment_duplicato_non_riscrive(respx_mock, monkeypatch):
    """Deduplica: stessa entità+fonte già proposta in precedenza -> non
    crea un secondo impegno (vedi contratto STOP 1, punto 8)."""
    payload = {
        "entity_nome": "Isagro",
        "descrizione": "Restituire pagamento doppio fattura 725FE",
        "direzione": "nostro",
        "source_type": "gmail",
        "source_id": "msg-1",
        "source_excerpt": "si richiede risarcimento doppio pagamento",
        "observed_at": "2026-07-21T09:53:31+00:00",
        "scadenza": None,
        "confidence": 0.9,
    }
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_PROPOSE_COMMITMENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    async def fake_trova_simile(tenant_id, entity_key, source_type, source_id):
        return {"id": "impegno-esistente"}

    chiamato = {"si": False}

    async def fake_upsert_impegno(*args, **kwargs):
        chiamato["si"] = True

    monkeypatch.setattr(azioni.memoria_db, "trova_impegno_simile", fake_trova_simile)
    monkeypatch.setattr(azioni.memoria_db, "upsert_impegno", fake_upsert_impegno)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiamato["si"] is False


def _ts(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def test_azione_scaduta_vera_solo_oltre_ttl():
    fresca = {"created_at": _ts(-timedelta(minutes=30))}
    vecchia = {"created_at": _ts(-timedelta(hours=2))}
    assert azioni.azione_scaduta(fresca) is False
    assert azioni.azione_scaduta(vecchia) is True


def test_azione_scaduta_senza_created_at_non_scade():
    """Un payload di test senza timestamp non deve mai risultare scaduto -
    la scadenza è una rete di sicurezza, non un default aggressivo."""
    assert azioni.azione_scaduta({}) is False


@pytest.mark.asyncio
async def test_conferma_si_su_azione_scaduta_non_invia(respx_mock, monkeypatch):
    """Un 'Sì' su una scheda più vecchia di un'ora non spedisce nulla: torna
    stato 'scaduta' e va richiesta di nuovo (decisione STOP 1, Tappa 7.2)."""
    _mock_azione(respx_mock, TENANT_A, created_at=_ts(-timedelta(hours=2)))
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[]))

    invio_chiamato = False

    async def fake_invia(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_SCADUTA
    assert invio_chiamato is False


@pytest.mark.asyncio
async def test_azione_bloccante_ignora_e_marca_una_pendente_scaduta(respx_mock):
    """Scadenza pigra: una pendente scaduta viene marcata 'scaduta' e non
    blocca più - la nuova richiesta può procedere."""
    _mock_azione(respx_mock, TENANT_A, created_at=_ts(-timedelta(hours=3)))
    patch = respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[]))

    bloccante = await azioni.azione_bloccante(TENANT_A)

    assert bloccante is None
    assert patch.called  # marcata scaduta


@pytest.mark.asyncio
async def test_azione_bloccante_ritorna_una_pendente_fresca(respx_mock):
    _mock_azione(respx_mock, TENANT_A, created_at=_ts(-timedelta(minutes=5)))

    bloccante = await azioni.azione_bloccante(TENANT_A)

    assert bloccante is not None
    assert bloccante["id"] == AZIONE_ID


@pytest.mark.asyncio
async def test_conferma_close_commitment_chiude_impegno(respx_mock, monkeypatch):
    payload = {"impegno_id": "impegno-1", "motivo": "bonifico restituito il 22/07"}
    _mock_azione(respx_mock, TENANT_A, tipo=azioni.TIPO_CLOSE_COMMITMENT, payload=payload)
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(return_value=httpx.Response(200, json=[]))

    chiusi = []

    async def fake_chiudi_impegno(tenant_id, impegno_id):
        chiusi.append((tenant_id, impegno_id))

    monkeypatch.setattr(azioni.memoria_db, "chiudi_impegno", fake_chiudi_impegno)

    risultato = await azioni.conferma_azione(TENANT_A, AZIONE_ID, conferma=True)

    assert risultato["stato"] == azioni.STATO_INVIATA
    assert chiusi == [(TENANT_A, "impegno-1")]
