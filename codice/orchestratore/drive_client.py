"""Client Google Drive API: tutto quello che un essere umano fa normalmente
con un cloud storage (cercare, leggere, caricare/creare, organizzare in
cartelle, condividere, cestinare) - vedi design Tappa 4 (Drive), decisione
"completezza dei connettori" (stesso criterio di Gmail/Calendar).

Nessun SDK Google pesante - httpx puro, coerente con gmail_client.py/
calendar_client.py.

Lettura contenuto (`leggi_contenuto_file`): i Google Docs/Sheets/Slides
nativi non hanno byte scaricabili direttamente, servono `files.export` con
un mimeType esplicito (Docs/Slides -> text/plain, Sheets -> text/csv). File
normali: se `text/*` si scaricano e decodificano, altrimenti (PDF, immagini,
binari) si conferma solo l'esistenza/metadati - l'estrazione arriva con
Memoria: estensione documenti (Tappa 5), stesso pattern già usato per gli
allegati Gmail (`gmail_client.ottieni_messaggio`/tools.py `_get_attachment`).

Scope OAuth: `drive` pieno (vedi oauth_drive.py) - non gestisce
impostazioni/quota/Shared Drives (amministrazione, fuori scope).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from . import oauth_core, oauth_drive

_API_BASE = "https://www.googleapis.com/drive/v3"
_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

MIME_FOLDER = "application/vnd.google-apps.folder"

_MIME_EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

_CAMPI_FILE = "id,name,mimeType,parents,modifiedTime,size,trashed"


class DriveError(Exception):
    """Errore nella chiamata a Google Drive API."""


async def ottieni_access_token(tenant_id: str) -> str:
    # access_token_valido tiene una cache in-memory (~1,6s risparmiati a ogni
    # tool call oltre il primo, vedi oauth_core.py) - non rifà il giro
    # Supabase+Google se l'access token è ancora valido.
    token = await oauth_core.access_token_valido(tenant_id, oauth_drive.PROVIDER_DRIVE)
    if token is None:
        raise DriveError(
            "Nessuna credenziale Drive collegata per questo tenant: "
            "serve prima /oauth/google_drive/authorize"
        )
    return token


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _formatta_file(dati: dict) -> dict[str, Any]:
    return {
        "file_id": dati["id"],
        "nome": dati.get("name", ""),
        "mime_type": dati.get("mimeType", ""),
        "cartelle": dati.get("parents", []),
        "modificato": dati.get("modifiedTime"),
        "dimensione": dati.get("size"),
    }


def _costruisci_multipart(metadata: dict, contenuto: str, mime_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    corpo = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
        f"{contenuto}\r\n"
        f"--{boundary}--"
    )
    return corpo.encode("utf-8"), f"multipart/related; boundary={boundary}"


async def cerca_file(
    access_token: str,
    query: str | None = None,
    mime_type: str | None = None,
    cartella_id: str | None = None,
    include_trashed: bool = False,
) -> list[dict[str, Any]]:
    """Ricerca per nome + full-text (contenuto indicizzato da Google per
    Docs/Sheets/Slides/PDF/testo). Esclude il cestino di default -
    altrimenti i risultati includerebbero file "morti" (trappola vista con
    Gmail: mostrare per default cose che un umano non si aspetta)."""
    clausole = [] if include_trashed else ["trashed = false"]
    if query:
        query_escapata = query.replace("\\", "\\\\").replace("'", "\\'")
        clausole.append(f"(name contains '{query_escapata}' or fullText contains '{query_escapata}')")
    if mime_type:
        clausole.append(f"mimeType = '{mime_type}'")
    if cartella_id:
        clausole.append(f"'{cartella_id}' in parents")
    q = " and ".join(clausole) if clausole else "trashed = false"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/files",
            params={"q": q, "fields": f"files({_CAMPI_FILE})", "pageSize": "50"},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.list fallita: {resp.status_code}")
    return [_formatta_file(f) for f in resp.json().get("files", [])]


async def elenca_cartella(access_token: str, cartella_id: str = "root") -> list[dict[str, Any]]:
    return await cerca_file(access_token, cartella_id=cartella_id)


async def ottieni_metadata_file(access_token: str, file_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/files/{file_id}",
            params={"fields": _CAMPI_FILE},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.get fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def leggi_contenuto_file(access_token: str, file_id: str) -> dict[str, Any]:
    meta = await ottieni_metadata_file(access_token, file_id)
    mime = meta["mime_type"]

    if mime in _MIME_EXPORT:
        mime_export = _MIME_EXPORT[mime]
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_API_BASE}/files/{file_id}/export",
                params={"mimeType": mime_export},
                headers=_headers(access_token),
            )
        if resp.status_code != 200:
            raise DriveError(f"Drive files.export fallita: {resp.status_code}")
        return {**meta, "testo": resp.text, "binario": False}

    if mime.startswith("text/") or mime in ("application/json",):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_API_BASE}/files/{file_id}",
                params={"alt": "media"},
                headers=_headers(access_token),
            )
        if resp.status_code != 200:
            raise DriveError(f"Drive files.get(alt=media) fallita: {resp.status_code}")
        return {**meta, "testo": resp.text, "binario": False}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/files/{file_id}",
            params={"alt": "media"},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.get(alt=media) fallita: {resp.status_code}")
    return {**meta, "testo": None, "binario": True, "dati_binari": resp.content}


async def crea_cartella(access_token: str, nome: str, cartella_padre_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": nome, "mimeType": MIME_FOLDER}
    if cartella_padre_id:
        body["parents"] = [cartella_padre_id]
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/files", params={"fields": _CAMPI_FILE}, headers=_headers(access_token), json=body
        )
    if resp.status_code not in (200, 201):
        raise DriveError(f"Drive files.create(folder) fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def crea_file(
    access_token: str,
    nome: str,
    contenuto: str,
    mime_type: str = "text/plain",
    cartella_padre_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": nome, "mimeType": mime_type}
    if cartella_padre_id:
        metadata["parents"] = [cartella_padre_id]
    corpo, content_type = _costruisci_multipart(metadata, contenuto, mime_type)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_UPLOAD_BASE}/files",
            params={"uploadType": "multipart", "fields": _CAMPI_FILE},
            headers={**_headers(access_token), "Content-Type": content_type},
            content=corpo,
        )
    if resp.status_code not in (200, 201):
        raise DriveError(f"Drive files.create(upload) fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def aggiorna_contenuto_file(
    access_token: str, file_id: str, contenuto: str, mime_type: str = "text/plain"
) -> dict[str, Any]:
    """Sovrascrive il contenuto di un file esistente. Drive mantiene le
    revisioni precedenti nella cronologia (non distrugge nulla), coerente
    col trattarla come azione reversibile a basso rischio."""
    corpo, content_type = _costruisci_multipart({}, contenuto, mime_type)
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_UPLOAD_BASE}/files/{file_id}",
            params={"uploadType": "multipart", "fields": _CAMPI_FILE},
            headers={**_headers(access_token), "Content-Type": content_type},
            content=corpo,
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.update(upload) fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def rinomina_file(access_token: str, file_id: str, nuovo_nome: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_API_BASE}/files/{file_id}",
            params={"fields": _CAMPI_FILE},
            headers=_headers(access_token),
            json={"name": nuovo_nome},
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.update(rename) fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def sposta_file(access_token: str, file_id: str, cartella_destinazione_id: str) -> dict[str, Any]:
    """Drive tratta i genitori come un insieme (`addParents`/`removeParents`),
    non un campo singolo - serve leggere i genitori attuali prima, altrimenti
    il file finisce duplicato in due cartelle invece di spostato."""
    meta = await ottieni_metadata_file(access_token, file_id)
    vecchi_parents = ",".join(meta["cartelle"])
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_API_BASE}/files/{file_id}",
            params={
                "addParents": cartella_destinazione_id,
                "removeParents": vecchi_parents,
                "fields": _CAMPI_FILE,
            },
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.update(move) fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def copia_file(
    access_token: str, file_id: str, nuovo_nome: str | None = None, cartella_destinazione_id: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if nuovo_nome:
        body["name"] = nuovo_nome
    if cartella_destinazione_id:
        body["parents"] = [cartella_destinazione_id]
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/files/{file_id}/copy",
            params={"fields": _CAMPI_FILE},
            headers=_headers(access_token),
            json=body,
        )
    if resp.status_code not in (200, 201):
        raise DriveError(f"Drive files.copy fallita: {resp.status_code}")
    return _formatta_file(resp.json())


async def condividi_file(
    access_token: str, file_id: str, email: str | None = None, ruolo: str = "reader", pubblico: bool = False
) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "anyone", "role": ruolo} if pubblico else {
        "type": "user", "role": ruolo, "emailAddress": email,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/files/{file_id}/permissions",
            params={
                "fields": "id,type,role,emailAddress",
                "sendNotificationEmail": "false" if pubblico else "true",
            },
            headers=_headers(access_token),
            json=body,
        )
    if resp.status_code not in (200, 201):
        raise DriveError(f"Drive permissions.create fallita: {resp.status_code}")
    return resp.json()


async def lista_permessi(access_token: str, file_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/files/{file_id}/permissions",
            params={"fields": "permissions(id,type,role,emailAddress)"},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive permissions.list fallita: {resp.status_code}")
    return resp.json().get("permissions", [])


async def revoca_permesso(access_token: str, file_id: str, permission_id: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{_API_BASE}/files/{file_id}/permissions/{permission_id}", headers=_headers(access_token)
        )
    if resp.status_code not in (200, 204):
        raise DriveError(f"Drive permissions.delete fallita: {resp.status_code}")


async def cestina_file(access_token: str, file_id: str) -> dict[str, Any]:
    """Sposta nel cestino (reversibile) - non elimina in modo permanente,
    stessa scelta già fatta per `gmail_client.cestina_messaggio`."""
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_API_BASE}/files/{file_id}",
            params={"fields": _CAMPI_FILE},
            headers=_headers(access_token),
            json={"trashed": True},
        )
    if resp.status_code != 200:
        raise DriveError(f"Drive files.update(trash) fallita: {resp.status_code}")
    return _formatta_file(resp.json())
