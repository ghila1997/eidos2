"""Perimetro di cartelle/path autorizzate per Agente Locale (vedi
ROADMAP.md, Tappa 3, "Perimetro di accesso"): il filesystem locale non ha
un provider esterno che faccia da guardiano (a differenza di Gmail, dove
l'autorizzazione e' gia' data dal consenso OAuth), quindi il confine va
imposto qui nel codice.

`autorizza_cartella` va chiamato SOLO dal comando CLI diretto
(`cli_locale.py --autorizza`), mai da un tool esposto al modello - il
perimetro stesso non deve essere ampliabile dall'agente.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

from common.supabase_rest import rest_headers, supabase_settings


async def autorizza_cartella(tenant_id: str, path: str) -> str:
    percorso = str(Path(path).resolve())
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/perimetro_locale",
            headers={**rest_headers(key), "Prefer": "return=representation,resolution=merge-duplicates"},
            json={"tenant_id": tenant_id, "path": percorso},
        )
    resp.raise_for_status()
    return percorso


async def elenca_cartelle_autorizzate(tenant_id: str) -> list[str]:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/perimetro_locale",
            params={"tenant_id": f"eq.{tenant_id}", "select": "path"},
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    return [riga["path"] for riga in resp.json()]


def _dentro_radice(path_risolto: str, radice_risolta: str) -> bool:
    """Confronto case-insensitive su Windows (os.path.normcase), con
    controllo di confine esplicito: una cartella "sorella" con lo stesso
    prefisso (es. perimetro "C:\\Test", path "C:\\TestAltro") NON deve
    risultare dentro - trappola classica di un controllo fatto solo con
    startswith senza il separatore."""
    richiesto = os.path.normcase(path_risolto)
    radice = os.path.normcase(radice_risolta)
    return richiesto == radice or richiesto.startswith(radice + os.sep)


async def is_path_allowed(tenant_id: str, path: str) -> bool:
    if not path:
        return False
    try:
        path_risolto = str(Path(path).resolve())
    except OSError:
        return False
    radici = await elenca_cartelle_autorizzate(tenant_id)
    return any(
        _dentro_radice(path_risolto, str(Path(radice).resolve()))
        for radice in radici
    )
