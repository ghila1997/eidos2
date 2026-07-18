"""Client Gmail API: fetch mail per l'ingest, e tutte le azioni che un
essere umano fa normalmente con la posta (cercare, rispondere nel thread
giusto, inoltrare, segnare letta/archiviare/etichettare, cestinare, leggere
allegati) - vedi design Tappa 2, decisione "completezza dei connettori".
Nessun SDK Google pesante - httpx puro, coerente con
codice/fondamenta/supabase_client.py.

Scope OAuth richiesti (vedi oauth.py): gmail.modify (lettura, composizione,
invio, etichette-su-messaggio, cestino - non elimina in modo permanente) +
gmail.labels (creare/elencare etichette come oggetti). L'eliminazione
permanente (bypassa il cestino) richiederebbe lo scope sensibile
`https://mail.google.com/`, deliberatamente escluso: "cancella" per un
assistente si traduce in cestinare, non distruggere subito - stesso
comportamento di un umano che cancella da Gmail.
"""
from __future__ import annotations

import base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from . import oauth

_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

LABEL_UNREAD = "UNREAD"
LABEL_INBOX = "INBOX"
LABEL_STARRED = "STARRED"


class GmailError(Exception):
    """Errore nella chiamata a Gmail API."""


async def ottieni_access_token(tenant_id: str) -> str:
    # access_token_valido tiene una cache in-memory (~1,6s risparmiati a ogni
    # tool call oltre il primo, vedi oauth_core.py) - non rifà il giro
    # Supabase+Google se l'access token è ancora valido.
    token = await oauth.access_token_valido(tenant_id, oauth.PROVIDER_GMAIL)
    if token is None:
        raise GmailError(
            "Nessuna credenziale Gmail collegata per questo tenant: "
            "serve prima /oauth/google/authorize"
        )
    return token


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def lista_messaggi_nuovi(
    access_token: str, cursore: str | None
) -> tuple[list[str], str]:
    """Ritorna (id messaggi nuovi, nuovo cursore). Cursore = historyId Gmail
    dell'ultimo import; usa `users.history.list` per l'incrementale (preciso
    a livello di singolo evento, non a giorno come la vecchia ricerca
    "after:").

    Se manca un cursore, o Gmail lo rifiuta con 404 (historyId troppo vecchio:
    Gmail conserva la storia solo per un periodo limitato), si fa un fetch
    pieno via `messages.list` e si riparte da un nuovo historyId preso da
    `users.getProfile` - dedup a valle (import_mail.py) copre gli eventuali
    messaggi già importati ripescati da un fetch pieno."""
    if cursore:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_API_BASE}/history",
                params={
                    "startHistoryId": cursore,
                    "historyTypes": "messageAdded",
                    "maxResults": "50",
                },
                headers=_headers(access_token),
            )
        if resp.status_code == 200:
            body = resp.json()
            ids = [
                aggiunta["message"]["id"]
                for voce in body.get("history", [])
                for aggiunta in voce.get("messagesAdded", [])
            ]
            return ids, str(body.get("historyId", cursore))
        if resp.status_code != 404:
            raise GmailError(f"Gmail history.list fallita: {resp.status_code}")
        # 404: historyId scaduto lato Gmail - fallback a fetch pieno sotto

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/messages",
            params={"maxResults": "50"},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.list fallita: {resp.status_code}")
    ids = [m["id"] for m in resp.json().get("messages", [])]

    async with httpx.AsyncClient() as client:
        profilo = await client.get(f"{_API_BASE}/profile", headers=_headers(access_token))
    if profilo.status_code != 200:
        raise GmailError(f"Gmail getProfile fallita: {profilo.status_code}")
    return ids, str(profilo.json()["historyId"])


def _estrai_corpo(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode(
            "utf-8", errors="replace"
        )
    for parte in payload.get("parts", []):
        corpo = _estrai_corpo(parte)
        if corpo:
            return corpo
    return ""


def _estrai_allegati(payload: dict) -> list[dict[str, Any]]:
    risultato = []
    if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
        risultato.append(
            {
                "attachment_id": payload["body"]["attachmentId"],
                "filename": payload["filename"],
                "mime_type": payload.get("mimeType", "application/octet-stream"),
                "size": payload.get("body", {}).get("size", 0),
            }
        )
    for parte in payload.get("parts", []):
        risultato.extend(_estrai_allegati(parte))
    return risultato


async def ottieni_messaggio(access_token: str, message_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/messages/{message_id}",
            params={"format": "full"},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.get fallita: {resp.status_code}")
    body = resp.json()
    headers = {h["name"].lower(): h["value"] for h in body["payload"].get("headers", [])}
    corpo = _estrai_corpo(body["payload"]) or body.get("snippet", "")
    return {
        "message_id": message_id,
        "thread_id": body.get("threadId"),
        "rfc822_message_id": headers.get("message-id", ""),
        "mittente": headers.get("from", ""),
        "destinatari": headers.get("to", ""),
        "oggetto": headers.get("subject", ""),
        "corpo": corpo,
        "allegati": _estrai_allegati(body["payload"]),
    }


async def scarica_allegato(access_token: str, message_id: str, attachment_id: str) -> bytes:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/messages/{message_id}/attachments/{attachment_id}",
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.attachments.get fallita: {resp.status_code}")
    dati = resp.json()["data"]
    padding = "=" * (-len(dati) % 4)
    return base64.urlsafe_b64decode(dati + padding)


def _costruisci_mime(
    destinatario: str,
    oggetto: str,
    corpo: str,
    cc: str | None = None,
    bcc: str | None = None,
    allegati: list[dict[str, Any]] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    if allegati:
        msg = MIMEMultipart()
        msg.attach(MIMEText(corpo))
        for allegato in allegati:
            parte = MIMEApplication(allegato["contenuto"], Name=allegato["filename"])
            parte["Content-Disposition"] = f'attachment; filename="{allegato["filename"]}"'
            msg.attach(parte)
    else:
        msg = MIMEText(corpo)

    msg["to"] = destinatario
    msg["subject"] = oggetto
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


async def invia_messaggio(
    access_token: str,
    destinatario: str,
    oggetto: str,
    corpo: str,
    cc: str | None = None,
    bcc: str | None = None,
    allegati: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "raw": _costruisci_mime(
            destinatario, oggetto, corpo, cc=cc, bcc=bcc, allegati=allegati,
            in_reply_to=in_reply_to, references=references,
        )
    }
    if thread_id:
        payload["threadId"] = thread_id
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/messages/send", headers=_headers(access_token), json=payload
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.send fallita: {resp.status_code}")
    return resp.json()


async def rispondi_messaggio(
    access_token: str,
    message_id_originale: str,
    corpo: str,
    destinatario: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    """Risposta con threading corretto: stesso thread Gmail (threadId) e
    header In-Reply-To/References verso il Message-ID originale - senza
    questo, Gmail mostra la risposta come mail slegata, non nel thread."""
    originale = await ottieni_messaggio(access_token, message_id_originale)
    oggetto = originale["oggetto"]
    if not oggetto.lower().startswith("re:"):
        oggetto = f"Re: {oggetto}"
    return await invia_messaggio(
        access_token,
        destinatario or originale["mittente"],
        oggetto,
        corpo,
        cc=cc,
        bcc=bcc,
        thread_id=originale["thread_id"],
        in_reply_to=originale["rfc822_message_id"],
        references=originale["rfc822_message_id"],
    )


async def inoltra_messaggio(
    access_token: str,
    message_id_originale: str,
    destinatario: str,
    testo_aggiuntivo: str = "",
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    """Inoltro: corpo e allegati originali riportati nel nuovo messaggio."""
    originale = await ottieni_messaggio(access_token, message_id_originale)
    oggetto = originale["oggetto"]
    if not oggetto.lower().startswith(("fwd:", "fw:")):
        oggetto = f"Fwd: {oggetto}"
    corpo = (
        f"{testo_aggiuntivo}\n\n"
        "---------- Messaggio inoltrato ----------\n"
        f"Da: {originale['mittente']}\n"
        f"Oggetto: {originale['oggetto']}\n"
        f"A: {originale['destinatari']}\n\n"
        f"{originale['corpo']}"
    )
    allegati = []
    for meta in originale["allegati"]:
        contenuto = await scarica_allegato(access_token, message_id_originale, meta["attachment_id"])
        allegati.append({"filename": meta["filename"], "contenuto": contenuto})
    return await invia_messaggio(
        access_token, destinatario, oggetto, corpo, cc=cc, bcc=bcc, allegati=allegati or None
    )


async def crea_bozza(
    access_token: str,
    destinatario: str,
    oggetto: str,
    corpo: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/drafts",
            headers=_headers(access_token),
            json={"message": {"raw": _costruisci_mime(destinatario, oggetto, corpo, cc=cc, bcc=bcc)}},
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail drafts.create fallita: {resp.status_code}")
    return resp.json()


async def invia_bozza(access_token: str, draft_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/drafts/send", headers=_headers(access_token), json={"id": draft_id}
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail drafts.send fallita: {resp.status_code}")
    return resp.json()


async def modifica_messaggio(
    access_token: str,
    message_id: str,
    aggiungi_label: list[str] | None = None,
    rimuovi_label: list[str] | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if aggiungi_label:
        body["addLabelIds"] = aggiungi_label
    if rimuovi_label:
        body["removeLabelIds"] = rimuovi_label
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/messages/{message_id}/modify", headers=_headers(access_token), json=body
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.modify fallita: {resp.status_code}")
    return resp.json()


async def cestina_messaggio(access_token: str, message_id: str) -> dict:
    """Sposta nel cestino (reversibile) - non elimina in modo permanente,
    coerente con lo scope gmail.modify e con cosa fa davvero un umano
    quando "cancella" una mail da Gmail."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/messages/{message_id}/trash", headers=_headers(access_token)
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.trash fallita: {resp.status_code}")
    return resp.json()


async def lista_etichette(access_token: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_API_BASE}/labels", headers=_headers(access_token))
    if resp.status_code != 200:
        raise GmailError(f"Gmail labels.list fallita: {resp.status_code}")
    return resp.json().get("labels", [])


async def crea_etichetta(access_token: str, nome: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/labels",
            headers=_headers(access_token),
            json={"name": nome, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail labels.create fallita: {resp.status_code}")
    return resp.json()


async def trova_o_crea_etichetta(access_token: str, nome: str) -> str:
    """'Sposta in una cartella X' su Gmail = applica un'etichetta X,
    creandola se non esiste ancora - un solo passaggio per l'agente."""
    for etichetta in await lista_etichette(access_token):
        if etichetta["name"].lower() == nome.lower():
            return etichetta["id"]
    nuova = await crea_etichetta(access_token, nome)
    return nuova["id"]
