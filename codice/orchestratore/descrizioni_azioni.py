"""Descrizione leggibile di un'azione pending - **fonte unica** per ogni
interfaccia (CLI e web), come richiesto dalla Tappa 7.2 (ROADMAP.md).

La logica "che aspetto ha un'azione da confermare" vive solo qui, sul server:
il CLI e la UI web non la ricalcolano, consumano il dict che il server mette
nel payload dell'azione esposta (endpoint /chat, evento WS `fine`/`azione_in_attesa`).
Cosi' se cambia il modo di descrivere un invio mail, cambia in un posto solo
e le due interfacce restano allineate (regola CLAUDE.md "ogni informazione
vive in un punto solo").

Struttura restituita (generica su tutti i tipi, non solo Gmail):

    {
      "icona": "✉",                 # emoji per l'intestazione della scheda
      "titolo": "Invio email",        # verbo dell'azione
      "riepilogo": "Invio a x@... : Oggetto",   # una riga (usata dal CLI/fallback)
      "dettagli": [{"etichetta": "A", "valore": "x@..."}, ...],  # righe chiave/valore
      "corpo": "Ciao Marco, ...",     # testo lungo (mail/impegno), o None
    }

La UI web rende `dettagli` come righe e `corpo` come blocco di testo: per una
mail viene naturalmente "formato mail" senza codice ad hoc per tipo. I payload
sono diversi tra Gmail/Calendar/Drive/Memoria: qui si legge solo cio' che
c'e', mai una chiave data per scontata (trappola reale Tappa 4: un payload
Calendar mandava in KeyError la descrizione pensata per Gmail).
"""
from __future__ import annotations

from typing import Any

from . import azioni


def _riga(etichetta: str, valore: Any) -> dict[str, str] | None:
    """Una riga dettaglio, o None se il valore e' assente/vuoto (cosi' i campi
    opzionali - cc, bcc, invitati - non lasciano righe vuote nella scheda)."""
    if valore is None:
        return None
    if isinstance(valore, (list, tuple)):
        valore = ", ".join(str(v) for v in valore if v)
    testo = str(valore).strip()
    if not testo:
        return None
    return {"etichetta": etichetta, "valore": testo}


def _componi(icona: str, titolo: str, riepilogo: str, righe: list, corpo: str | None = None) -> dict:
    return {
        "icona": icona,
        "titolo": titolo,
        "riepilogo": riepilogo,
        "dettagli": [r for r in righe if r is not None],
        "corpo": (corpo.strip() if isinstance(corpo, str) and corpo.strip() else None),
    }


def descrivi_azione(azione: dict) -> dict:
    """Traduce un'azione pending (`{"tipo", "payload", ...}`) in una descrizione
    leggibile e strutturata. Non solleva mai su payload inatteso: i campi
    mancanti spariscono, un tipo sconosciuto ha un fallback dignitoso."""
    tipo = azione.get("tipo", "")
    p = azione.get("payload") or {}

    if tipo == azioni.TIPO_SEND_EMAIL:
        return _componi(
            "✉", "Invio email",
            f"Invio a {p.get('destinatario', '?')}: {p.get('oggetto', '')}".strip(),
            [_riga("A", p.get("destinatario")), _riga("Cc", p.get("cc")),
             _riga("Ccn", p.get("bcc")), _riga("Oggetto", p.get("oggetto"))],
            corpo=p.get("corpo"),
        )
    if tipo == azioni.TIPO_REPLY_EMAIL:
        return _componi(
            "↩", "Risposta email",
            f"Risposta al messaggio {p.get('message_id', '?')}",
            [_riga("A", p.get("destinatario")), _riga("Cc", p.get("cc")),
             _riga("In risposta a", p.get("message_id"))],
            corpo=p.get("corpo"),
        )
    if tipo == azioni.TIPO_FORWARD_EMAIL:
        return _componi(
            "➦", "Inoltro email",
            f"Inoltro di {p.get('message_id', '?')} a {p.get('destinatario', '?')}",
            [_riga("A", p.get("destinatario")), _riga("Cc", p.get("cc")),
             _riga("Messaggio", p.get("message_id"))],
            corpo=p.get("testo_aggiuntivo"),
        )
    if tipo == azioni.TIPO_SEND_DRAFT:
        return _componi(
            "✉", "Invio bozza",
            f"Invio della bozza {p.get('draft_id', '?')}",
            [_riga("Bozza", p.get("draft_id"))],
        )
    if tipo == azioni.TIPO_TRASH_EMAIL:
        return _componi(
            "\U0001f5d1", "Cestina email",
            f"Sposto nel cestino il messaggio {p.get('message_id', '?')}",
            [_riga("Messaggio", p.get("message_id"))],
        )
    if tipo == azioni.TIPO_CREATE_EVENT:
        quando = " – ".join(x for x in (p.get("inizio"), p.get("fine")) if x)
        return _componi(
            "\U0001f4c5", "Nuovo evento",
            f"Creo l'evento '{p.get('titolo', '?')}'",
            [_riga("Titolo", p.get("titolo")), _riga("Quando", quando),
             _riga("Invitati", p.get("partecipanti"))],
            corpo=p.get("descrizione"),
        )
    if tipo == azioni.TIPO_UPDATE_EVENT:
        quando = " – ".join(x for x in (p.get("inizio"), p.get("fine")) if x)
        return _componi(
            "\U0001f4c5", "Modifica evento",
            f"Modifico l'evento {p.get('event_id', '?')}",
            [_riga("Evento", p.get("event_id")), _riga("Titolo", p.get("titolo")),
             _riga("Quando", quando)],
        )
    if tipo == azioni.TIPO_DELETE_EVENT:
        return _componi(
            "\U0001f5d1", "Cancella evento",
            f"Cancello l'evento {p.get('event_id', '?')}",
            [_riga("Evento", p.get("event_id"))],
        )
    if tipo == azioni.TIPO_SHARE_FILE:
        con = "chiunque abbia il link" if p.get("pubblico") else p.get("email")
        return _componi(
            "\U0001f517", "Condividi file",
            f"Condivido il file {p.get('file_id', '?')}",
            [_riga("File", p.get("file_id")), _riga("Con", con), _riga("Ruolo", p.get("ruolo"))],
        )
    if tipo == azioni.TIPO_TRASH_FILE:
        return _componi(
            "\U0001f5d1", "Cestina file",
            f"Sposto nel cestino il file {p.get('file_id', '?')}",
            [_riga("File", p.get("file_id"))],
        )
    if tipo == azioni.TIPO_FORGET_DOCUMENT:
        return _componi(
            "\U0001f5d1", "Dimentica documento",
            f"Dimentico il documento {p.get('documento_id', '?')}",
            [_riga("Documento", p.get("documento_id"))],
        )
    if tipo == azioni.TIPO_PROPOSE_COMMITMENT:
        return _componi(
            "\U0001f4cc", "Nuovo impegno",
            f"Impegno su {p.get('entity_nome', '?')} ({p.get('direzione', '?')}): "
            f"{p.get('descrizione', '')}".strip(),
            [_riga("Con", p.get("entity_nome")), _riga("Direzione", p.get("direzione")),
             _riga("Scadenza", p.get("scadenza"))],
            corpo=p.get("descrizione"),
        )
    if tipo == azioni.TIPO_CLOSE_COMMITMENT:
        return _componi(
            "✓", "Chiudi impegno",
            f"Chiudo l'impegno {p.get('impegno_id', '?')}: {p.get('motivo', '')}".strip(),
            [_riga("Impegno", p.get("impegno_id")), _riga("Motivo", p.get("motivo"))],
        )

    return _componi("⚙", f"Azione '{tipo}'", f"Azione di tipo '{tipo}'", [])
