"""Trappole del percorso immagini (Tappa 5.1): l'API Claude accetta solo
JPEG/PNG/GIF/WebP entro 10MB base64 e lavora al meglio fino a 2576px di
lato lungo (tier alta risoluzione, verificato sulla doc ufficiale
2026-07-16). Una foto HEIC da iPhone o un TIFF da scanner passavano il
gate dei 20MB e esplodevano con un errore API grezzo - la normalizzazione
locale li converte prima, senza toccare l'originale archiviato.
"""
import io

import pytest
from PIL import Image

from memoria import image_normalization


def _png(dimensione: tuple[int, int] = (100, 100), mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, dimensione, color=None).save(buffer, format="PNG")
    return buffer.getvalue()


def _tiff() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buffer, format="TIFF")
    return buffer.getvalue()


def _heic() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buffer, format="HEIF")
    return buffer.getvalue()


def test_png_piccola_resta_invariata():
    contenuto = _png()
    normalizzato, mime = image_normalization.normalizza_per_visione(contenuto, "image/png")
    assert normalizzato == contenuto
    assert mime == "image/png"


def test_tiff_convertito_in_jpeg():
    normalizzato, mime = image_normalization.normalizza_per_visione(_tiff(), "image/tiff")
    assert mime == "image/jpeg"
    assert Image.open(io.BytesIO(normalizzato)).format == "JPEG"


def test_heic_convertito_in_jpeg():
    """HEIC è il default delle foto iPhone: il caso più comune di 'foto di
    un documento cartaceo' per un utente reale."""
    normalizzato, mime = image_normalization.normalizza_per_visione(_heic(), "image/heic")
    assert mime == "image/jpeg"
    assert Image.open(io.BytesIO(normalizzato)).format == "JPEG"


def test_immagine_oltre_lato_massimo_ridimensionata():
    normalizzato, mime = image_normalization.normalizza_per_visione(
        _png((4000, 2000)), "image/png"
    )
    assert mime == "image/jpeg"
    immagine = Image.open(io.BytesIO(normalizzato))
    assert max(immagine.size) <= image_normalization.LATO_MASSIMO
    # proporzioni preservate (4000x2000 -> 2576x1288)
    assert abs(immagine.size[0] / immagine.size[1] - 2.0) < 0.01


def test_png_con_trasparenza_convertita_senza_crash():
    normalizzato, mime = image_normalization.normalizza_per_visione(
        _png((3000, 3000), mode="RGBA"), "image/png"
    )
    assert mime == "image/jpeg"


def test_bytes_corrotti_errore_esplicito():
    with pytest.raises(image_normalization.ErroreImmagineNonLeggibile):
        image_normalization.normalizza_per_visione(b"non sono un'immagine", "image/jpeg")
