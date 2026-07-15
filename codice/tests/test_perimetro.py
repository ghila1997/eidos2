"""Perimetro filesystem di Agente Locale: trappola centrale e' il path
traversal - una cartella fuori dal perimetro autorizzato (o solo "sorella"
con lo stesso prefisso) non deve mai risultare dentro."""
import httpx
import pytest

from agente_locale import perimetro

SUPABASE_URL = "https://fake.supabase.co"
TENANT = "11111111-1111-1111-1111-111111111111"


def _mock_radici(respx_mock, radici: list[str]):
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/perimetro_locale").mock(
        return_value=httpx.Response(200, json=[{"path": r} for r in radici])
    )


@pytest.mark.asyncio
async def test_path_dentro_perimetro_permesso(respx_mock, tmp_path):
    radice = tmp_path / "EidosTest"
    radice.mkdir()
    file_dentro = radice / "appunti.txt"
    file_dentro.write_text("prova")

    _mock_radici(respx_mock, [str(radice)])

    assert await perimetro.is_path_allowed(TENANT, str(file_dentro)) is True


@pytest.mark.asyncio
async def test_path_fuori_perimetro_negato(respx_mock, tmp_path):
    radice = tmp_path / "EidosTest"
    radice.mkdir()
    fuori = tmp_path / "Altro" / "segreto.txt"

    _mock_radici(respx_mock, [str(radice)])

    assert await perimetro.is_path_allowed(TENANT, str(fuori)) is False


@pytest.mark.asyncio
async def test_cartella_sorella_con_stesso_prefisso_non_e_dentro(respx_mock, tmp_path):
    """Trappola: 'C:\\EidosTestAltro' non deve risultare dentro al perimetro
    'C:\\EidosTest' solo perche' inizia con la stessa stringa."""
    radice = tmp_path / "EidosTest"
    radice.mkdir()
    sorella = tmp_path / "EidosTestAltro" / "file.txt"

    _mock_radici(respx_mock, [str(radice)])

    assert await perimetro.is_path_allowed(TENANT, str(sorella)) is False


@pytest.mark.asyncio
async def test_path_traversal_con_dotdot_bloccato(respx_mock, tmp_path):
    radice = tmp_path / "EidosTest"
    radice.mkdir()
    (tmp_path / "fuori.txt").write_text("segreto")
    traversal = str(radice / ".." / "fuori.txt")

    _mock_radici(respx_mock, [str(radice)])

    assert await perimetro.is_path_allowed(TENANT, traversal) is False


@pytest.mark.asyncio
async def test_nessun_perimetro_autorizzato_nega_tutto(respx_mock, tmp_path):
    _mock_radici(respx_mock, [])
    assert await perimetro.is_path_allowed(TENANT, str(tmp_path / "qualsiasi.txt")) is False


@pytest.mark.asyncio
async def test_path_vuoto_negato(respx_mock, tmp_path):
    _mock_radici(respx_mock, [str(tmp_path)])
    assert await perimetro.is_path_allowed(TENANT, "") is False


@pytest.mark.asyncio
async def test_autorizza_cartella_scrive_path_risolto(respx_mock, tmp_path):
    cartella = tmp_path / "NuovaCartella"
    cartella.mkdir()
    respx_mock.post(f"{SUPABASE_URL}/rest/v1/perimetro_locale").mock(
        return_value=httpx.Response(201, json=[{"id": "x"}])
    )

    percorso = await perimetro.autorizza_cartella(TENANT, str(cartella))

    assert percorso == str(cartella.resolve())
