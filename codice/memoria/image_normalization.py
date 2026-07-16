"""Normalizzazione locale delle immagini prima del percorso visione
(document_extraction.estrai_da_documento_visivo). L'API Claude accetta
solo JPEG/PNG/GIF/WebP, max 10MB in base64, max 8000x8000px, e i modelli
ad alta risoluzione (Sonnet 5) lavorano nativamente fino a 2576px di lato
lungo - oltre, il server ridimensiona comunque (verificato sulla doc
ufficiale Vision, 2026-07-16).

Senza questa normalizzazione i casi più comuni del mondo reale falliscono
con un errore API grezzo: foto HEIC da iPhone (il default), TIFF da
scanner, foto da 8-12MB. La conversione avviene solo per la chiamata di
visione - l'originale dell'utente resta intatto (hash, dedup e archivio
su Storage usano sempre i byte originali, vedi ingest_documento.py).
"""
from __future__ import annotations

import io

import pillow_heif
from PIL import Image

# Abilita lettura (e scrittura, usata nei test) di HEIC/HEIF in Pillow.
pillow_heif.register_heif_opener()

# Formati che l'API accetta cosi' come sono (formato Pillow -> media type).
_FORMATI_API = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}

# Lato lungo massimo processato nativamente dal tier alta risoluzione
# (Sonnet 5): ridimensionare oltre non aggiunge fedelta', solo byte.
LATO_MASSIMO = 2576

# Byte grezzi oltre i quali si ricomprime comunque: ~7MB grezzi diventano
# ~9.3MB in base64, vicini al limite API di 10MB.
DIMENSIONE_MASSIMA = 7_000_000

_QUALITA_JPEG = 85


class ErroreImmagineNonLeggibile(Exception):
    """I byte non sono un'immagine decodificabile - errore atteso, non un bug."""


def normalizza_per_visione(contenuto: bytes, mime_type: str) -> tuple[bytes, str]:
    """Ritorna (byte, media_type) pronti per il content block `image`
    dell'API. Se l'immagine e' gia' in un formato/dimensione accettati la
    ritorna invariata; altrimenti converte in JPEG ridimensionando al
    LATO_MASSIMO. `mime_type` dichiarato dal chiamante non e' fidato: fa
    fede il formato reale rilevato da Pillow."""
    try:
        immagine = Image.open(io.BytesIO(contenuto))
        immagine.load()
    except Exception as exc:
        raise ErroreImmagineNonLeggibile(
            f"il file non è un'immagine leggibile ({exc.__class__.__name__})"
        ) from exc

    formato_reale = immagine.format
    if (
        formato_reale in _FORMATI_API
        and max(immagine.size) <= LATO_MASSIMO
        and len(contenuto) <= DIMENSIONE_MASSIMA
    ):
        return contenuto, _FORMATI_API[formato_reale]

    if max(immagine.size) > LATO_MASSIMO:
        immagine.thumbnail((LATO_MASSIMO, LATO_MASSIMO), Image.LANCZOS)
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    buffer = io.BytesIO()
    immagine.save(buffer, format="JPEG", quality=_QUALITA_JPEG)
    return buffer.getvalue(), "image/jpeg"
