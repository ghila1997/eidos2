"""Canali aperti verso l'utente: servono a mandare eventi che NON nascono da
un messaggio del client (l'avanzamento di un gruppo di azioni confermate parte
da una POST, non dal ciclo della sessione)."""
import asyncio

import pytest

from orchestratore import canali

pytestmark = pytest.mark.asyncio

TENANT = "11111111-1111-1111-1111-111111111111"
ALTRO = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _pulisci():
    canali._canali_per_tenant.clear()
    canali._da_recapitare.clear()
    yield
    canali._canali_per_tenant.clear()
    canali._da_recapitare.clear()


async def test_annuncia_raggiunge_i_canali_del_tenant():
    ricevuti = []

    async def canale(evento):
        ricevuti.append(evento)

    canali.registra(TENANT, canale)
    await canali.annuncia(TENANT, {"evento": "azione_progresso", "fatte": 3, "totale": 10})

    assert ricevuti == [{"evento": "azione_progresso", "fatte": 3, "totale": 10}]


async def test_annuncia_non_perde_tenant():
    """Anti-leak: l'avanzamento delle azioni di un tenant non deve finire sullo
    schermo di un altro."""
    ricevuti = []

    async def canale(evento):
        ricevuti.append(evento)

    canali.registra(TENANT, canale)
    await canali.annuncia(ALTRO, {"evento": "azione_fine"})

    assert ricevuti == []


async def test_due_schede_aperte_ricevono_entrambe():
    a, b = [], []

    async def canale_a(evento):
        a.append(evento)

    async def canale_b(evento):
        b.append(evento)

    canali.registra(TENANT, canale_a)
    canali.registra(TENANT, canale_b)
    await canali.annuncia(TENANT, {"evento": "azione_fine"})

    assert len(a) == 1 and len(b) == 1


async def test_un_canale_morto_non_blocca_gli_altri():
    """Trappola: se una scheda è stata chiusa, il suo invio esplode - non deve
    impedire alle altre di ricevere né far fallire chi annuncia (l'esecuzione
    delle azioni è la cosa che conta, l'avanzamento è un di più)."""
    vivi = []

    async def canale_morto(evento):
        raise RuntimeError("socket chiuso")

    async def canale_vivo(evento):
        vivi.append(evento)

    canali.registra(TENANT, canale_morto)
    canali.registra(TENANT, canale_vivo)

    await canali.annuncia(TENANT, {"evento": "azione_fine"})   # non solleva

    assert len(vivi) == 1


async def test_deregistra_smette_di_ricevere():
    ricevuti = []

    async def canale(evento):
        ricevuti.append(evento)

    canali.registra(TENANT, canale)
    canali.deregistra(TENANT, canale)
    await canali.annuncia(TENANT, {"evento": "azione_fine"})

    assert ricevuti == []
    assert TENANT not in canali._canali_per_tenant   # niente tenant vuoti accumulati


async def test_esito_senza_canali_viene_recapitato_al_prossimo():
    """Il difetto grave trovato a STOP 2: se il socket e' morto (sessione
    scaduta, rete caduta) l'esito di un'azione GIA' AVVENUTA finiva nel nulla e
    l'utente non sapeva che 30 mail erano state cestinate. Ora aspetta il primo
    canale che si apre."""
    await canali.annuncia(TENANT, {"evento": "azione_fine", "esito": "30 mail spostate nel cestino"})

    ricevuti = []

    async def canale(evento):
        ricevuti.append(evento)

    canali.registra(TENANT, canale)
    await asyncio.sleep(0)   # il recapito parte come task
    await asyncio.sleep(0)

    assert ricevuti == [{
        "evento": "azione_fine",
        "esito": "30 mail spostate nel cestino",
        "differito": True,   # cosa avvenuta prima, non adesso
    }]


async def test_esito_arretrato_si_recapita_una_volta_sola():
    await canali.annuncia(TENANT, {"evento": "azione_fine", "esito": "3 mail spostate nel cestino"})

    primi, secondi = [], []

    async def canale_a(evento):
        primi.append(evento)

    async def canale_b(evento):
        secondi.append(evento)

    canali.registra(TENANT, canale_a)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    canali.registra(TENANT, canale_b)
    await asyncio.sleep(0)

    assert len(primi) == 1
    assert secondi == []   # gia' recapitato, non si ripete


async def test_esito_arretrato_troppo_vecchio_non_si_recapita(monkeypatch):
    """Un'ora dopo non e' una notizia, e' cronaca: mostrarla come esito fresco
    confonderebbe e basta."""
    await canali.annuncia(TENANT, {"evento": "azione_fine", "esito": "vecchio"})
    # invecchia artificialmente l'arretrato
    canali._da_recapitare[TENANT] = [
        (t - canali.VALIDITA_RECAPITO - 1, e) for t, e in canali._da_recapitare[TENANT]
    ]

    ricevuti = []

    async def canale(evento):
        ricevuti.append(evento)

    canali.registra(TENANT, canale)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert ricevuti == []


async def test_progresso_non_si_mette_da_parte():
    """Un avanzamento perso e' irrilevante (dice cosa stava succedendo, non
    cosa e' successo): solo l'esito finale merita il recapito differito."""
    await canali.annuncia(TENANT, {"evento": "azione_progresso", "fatte": 2, "totale": 5})
    assert TENANT not in canali._da_recapitare
