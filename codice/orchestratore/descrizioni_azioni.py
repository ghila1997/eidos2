"""Descrizione leggibile di un'azione pending - **fonte unica** per ogni
interfaccia (CLI e web), come richiesto dalla Tappa 7.2 (ROADMAP.md).

La logica "che aspetto ha un'azione da confermare" vive solo qui, sul server:
il CLI e la UI web non la ricalcolano, consumano il dict che il server mette
nel payload dell'azione esposta (endpoint /chat, evento WS `fine`/`azione_in_attesa`).
Cosi' se cambia il modo di descrivere un invio mail, cambia in un posto solo
e le due interfacce restano allineate (regola CLAUDE.md "ogni informazione
vive in un punto solo").

Ogni tipo di azione ha **una voce sola** in `_DESCRITTORI`, che tiene insieme
icona, titolo singolare, titolo di gruppo, righe della scheda e frasi di esito.
Il rendering (CLI e web) non sa cosa sia una mail o un evento: legge la
struttura e basta. Aggiungere un connettore = aggiungere una voce, senza
toccare le interfacce - stessa direzione degli MCP Apps, dove l'interfaccia la
porta il connettore (vedi notes/mcp-apps-interfacce-connettori.md).

Struttura restituita per una singola azione:

    {
      "icona": "✉",                 # emoji per l'intestazione della scheda
      "titolo": "Invio email",        # verbo dell'azione
      "riepilogo": "Invio a x@... : Oggetto",   # una riga (usata dal CLI/fallback)
      "dettagli": [{"etichetta": "A", "valore": "x@..."}, ...],  # righe chiave/valore
      "corpo": "Ciao Marco, ...",     # testo lungo (mail/impegno), o None
    }

`descrivi_gruppo` aggiunge `multipla`, `totale` e `voci` (una per azione) per
il caso di N azioni da confermare insieme.

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


def _quando(p: dict) -> str:
    return " – ".join(x for x in (p.get("inizio"), p.get("fine")) if x)


# --- schede: payload -> (riepilogo, righe, corpo) ---------------------------
# Le azioni che nel payload portano un'etichetta leggibile (mittente/oggetto di
# una mail, nome di un file, titolo di un evento) la usano; se manca - payload
# vecchi, creati prima che i tool la salvassero - si ricade sull'id tecnico.
# Meglio un id grezzo che un KeyError, ma un id grezzo da solo non e' una cosa
# che un umano possa confermare: e' il motivo per cui i tool ora la salvano.

def _scheda_send_email(p: dict) -> tuple:
    return (
        f"Invio a {p.get('destinatario', '?')}: {p.get('oggetto', '')}".strip(),
        [_riga("A", p.get("destinatario")), _riga("Cc", p.get("cc")),
         _riga("Ccn", p.get("bcc")), _riga("Oggetto", p.get("oggetto"))],
        p.get("corpo"),
    )


def _scheda_reply_email(p: dict) -> tuple:
    riferimento = p.get("oggetto") or p.get("message_id", "?")
    return (
        f"Risposta a {p.get('destinatario') or riferimento}",
        [_riga("A", p.get("destinatario")), _riga("Cc", p.get("cc")),
         _riga("In risposta a", p.get("oggetto") or p.get("message_id"))],
        p.get("corpo"),
    )


def _scheda_forward_email(p: dict) -> tuple:
    riferimento = p.get("oggetto") or p.get("message_id", "?")
    return (
        f"Inoltro di '{riferimento}' a {p.get('destinatario', '?')}",
        [_riga("A", p.get("destinatario")), _riga("Cc", p.get("cc")),
         _riga("Messaggio", p.get("oggetto") or p.get("message_id"))],
        p.get("testo_aggiuntivo"),
    )


def _scheda_send_draft(p: dict) -> tuple:
    riferimento = p.get("oggetto") or p.get("draft_id", "?")
    return (
        f"Invio della bozza '{riferimento}'",
        [_riga("A", p.get("destinatario")), _riga("Oggetto", p.get("oggetto")),
         _riga("Bozza", p.get("draft_id"))],
        None,
    )


def _scheda_trash_email(p: dict) -> tuple:
    mittente, oggetto = p.get("mittente"), p.get("oggetto")
    if not (mittente or oggetto):
        # Payload vecchio, senza metadati: resta l'id tecnico.
        message_id = p.get("message_id", "?")
        return f"Messaggio {message_id}", [_riga("Messaggio", p.get("message_id"))], None
    return (
        " · ".join(x for x in (mittente, oggetto) if x),
        [_riga("Da", mittente), _riga("Oggetto", oggetto), _riga("Data", p.get("data"))],
        None,
    )


def _scheda_create_event(p: dict) -> tuple:
    return (
        f"Creo l'evento '{p.get('titolo', '?')}'",
        [_riga("Titolo", p.get("titolo")), _riga("Quando", _quando(p)),
         _riga("Invitati", p.get("partecipanti"))],
        p.get("descrizione"),
    )


def _scheda_update_event(p: dict) -> tuple:
    riferimento = p.get("titolo") or p.get("event_id", "?")
    return (
        f"Modifico l'evento '{riferimento}'",
        [_riga("Evento", p.get("titolo") or p.get("event_id")), _riga("Quando", _quando(p))],
        None,
    )


def _scheda_delete_event(p: dict) -> tuple:
    riferimento = p.get("titolo") or p.get("event_id", "?")
    return (
        f"Cancello l'evento '{riferimento}'",
        [_riga("Evento", p.get("titolo") or p.get("event_id")), _riga("Quando", _quando(p))],
        None,
    )


def _scheda_share_file(p: dict) -> tuple:
    con = "chiunque abbia il link" if p.get("pubblico") else p.get("email")
    riferimento = p.get("nome") or p.get("file_id", "?")
    return (
        f"Condivido il file '{riferimento}'",
        [_riga("File", p.get("nome") or p.get("file_id")), _riga("Con", con),
         _riga("Ruolo", p.get("ruolo"))],
        None,
    )


def _scheda_trash_file(p: dict) -> tuple:
    riferimento = p.get("nome") or p.get("file_id", "?")
    return (
        f"Sposto nel cestino il file '{riferimento}'",
        [_riga("File", p.get("nome") or p.get("file_id"))],
        None,
    )


def _scheda_forget_document(p: dict) -> tuple:
    riferimento = p.get("nome") or p.get("documento_id", "?")
    return (
        f"Dimentico il documento '{riferimento}'",
        [_riga("Documento", p.get("nome") or p.get("documento_id"))],
        None,
    )


def _scheda_propose_commitment(p: dict) -> tuple:
    return (
        f"Impegno su {p.get('entity_nome', '?')} ({p.get('direzione', '?')}): "
        f"{p.get('descrizione', '')}".strip(),
        [_riga("Con", p.get("entity_nome")), _riga("Direzione", p.get("direzione")),
         _riga("Scadenza", p.get("scadenza"))],
        p.get("descrizione"),
    )


def _scheda_close_commitment(p: dict) -> tuple:
    return (
        f"Chiudo l'impegno {p.get('impegno_id', '?')}: {p.get('motivo', '')}".strip(),
        [_riga("Impegno", p.get("impegno_id")), _riga("Motivo", p.get("motivo"))],
        None,
    )


# --- registro: una voce per tipo di azione ----------------------------------
# `titolo` = scheda singola; `gruppo` = intestazione di N azioni insieme;
# `esito` = frase al passato di una sola; `esito_gruppo` = di N.
_CESTINO = "\U0001f5d1"

_DESCRITTORI: dict[str, dict[str, Any]] = {
    # Gmail
    azioni.TIPO_SEND_EMAIL: {
        "icona": "✉", "titolo": "Invio email", "gruppo": "{n} email da inviare",
        "scheda": _scheda_send_email,
        "esito": lambda p: f"Mail inviata a {p['destinatario']}" if p.get("destinatario") else "Mail inviata",
        "esito_gruppo": "{n} mail inviate",
    },
    azioni.TIPO_REPLY_EMAIL: {
        "icona": "↩", "titolo": "Risposta email", "gruppo": "{n} risposte da inviare",
        "scheda": _scheda_reply_email,
        "esito": lambda p: f"Risposta inviata a {p['destinatario']}" if p.get("destinatario") else "Risposta inviata",
        "esito_gruppo": "{n} risposte inviate",
    },
    azioni.TIPO_FORWARD_EMAIL: {
        "icona": "➦", "titolo": "Inoltro email", "gruppo": "{n} email da inoltrare",
        "scheda": _scheda_forward_email,
        "esito": lambda p: f"Mail inoltrata a {p['destinatario']}" if p.get("destinatario") else "Mail inoltrata",
        "esito_gruppo": "{n} mail inoltrate",
    },
    azioni.TIPO_SEND_DRAFT: {
        "icona": "✉", "titolo": "Invio bozza", "gruppo": "{n} bozze da inviare",
        "scheda": _scheda_send_draft,
        "esito": lambda p: "Bozza inviata",
        "esito_gruppo": "{n} bozze inviate",
    },
    azioni.TIPO_TRASH_EMAIL: {
        "icona": _CESTINO, "titolo": "Cestina email", "gruppo": "{n} mail nel cestino",
        "scheda": _scheda_trash_email,
        "esito": lambda p: "Mail spostata nel cestino",
        "esito_gruppo": "{n} mail spostate nel cestino",
    },
    # Calendar
    azioni.TIPO_CREATE_EVENT: {
        "icona": "\U0001f4c5", "titolo": "Nuovo evento", "gruppo": "{n} eventi da creare",
        "scheda": _scheda_create_event,
        "esito": lambda p: f"Evento creato: {p['titolo']}" if p.get("titolo") else "Evento creato",
        "esito_gruppo": "{n} eventi creati",
    },
    azioni.TIPO_UPDATE_EVENT: {
        "icona": "\U0001f4c5", "titolo": "Modifica evento", "gruppo": "{n} eventi da modificare",
        "scheda": _scheda_update_event,
        "esito": lambda p: "Evento aggiornato",
        "esito_gruppo": "{n} eventi aggiornati",
    },
    azioni.TIPO_DELETE_EVENT: {
        "icona": _CESTINO, "titolo": "Cancella evento", "gruppo": "{n} eventi da cancellare",
        "scheda": _scheda_delete_event,
        "esito": lambda p: "Evento cancellato",
        "esito_gruppo": "{n} eventi cancellati",
    },
    # Drive
    azioni.TIPO_SHARE_FILE: {
        "icona": "\U0001f517", "titolo": "Condividi file", "gruppo": "{n} file da condividere",
        "scheda": _scheda_share_file,
        "esito": lambda p: f"File condiviso con {p['email']}" if p.get("email") else "File condiviso",
        "esito_gruppo": "{n} file condivisi",
    },
    azioni.TIPO_TRASH_FILE: {
        "icona": _CESTINO, "titolo": "Cestina file", "gruppo": "{n} file nel cestino",
        "scheda": _scheda_trash_file,
        "esito": lambda p: "File spostato nel cestino",
        "esito_gruppo": "{n} file spostati nel cestino",
    },
    # Memoria
    azioni.TIPO_FORGET_DOCUMENT: {
        "icona": _CESTINO, "titolo": "Dimentica documento", "gruppo": "{n} documenti da dimenticare",
        "scheda": _scheda_forget_document,
        "esito": lambda p: "Documento dimenticato",
        "esito_gruppo": "{n} documenti dimenticati",
    },
    azioni.TIPO_PROPOSE_COMMITMENT: {
        "icona": "\U0001f4cc", "titolo": "Nuovo impegno", "gruppo": "{n} impegni da salvare",
        "scheda": _scheda_propose_commitment,
        "esito": lambda p: "Impegno salvato",
        "esito_gruppo": "{n} impegni salvati",
    },
    azioni.TIPO_CLOSE_COMMITMENT: {
        "icona": "✓", "titolo": "Chiudi impegno", "gruppo": "{n} impegni da chiudere",
        "scheda": _scheda_close_commitment,
        "esito": lambda p: "Impegno chiuso",
        "esito_gruppo": "{n} impegni chiusi",
    },
}


def descrivi_azione(azione: dict) -> dict:
    """Traduce un'azione pending (`{"tipo", "payload", ...}`) in una descrizione
    leggibile e strutturata. Non solleva mai su payload inatteso: i campi
    mancanti spariscono, un tipo sconosciuto ha un fallback dignitoso."""
    tipo = azione.get("tipo", "")
    p = azione.get("payload") or {}
    descrittore = _DESCRITTORI.get(tipo)
    if descrittore is None:
        return _componi("⚙", f"Azione '{tipo}'", f"Azione di tipo '{tipo}'", [])
    riepilogo, righe, corpo = descrittore["scheda"](p)
    return _componi(descrittore["icona"], descrittore["titolo"], riepilogo, righe, corpo)


def descrivi_gruppo(azioni_pendenti: list[dict]) -> dict | None:
    """Le N azioni in attesa di un turno come **una sola** scheda da confermare.

    Con una sola azione torna esattamente la scheda di prima (piu' `voci`, che
    contiene solo lei): il caso "manda questa mail" non deve cambiare aspetto
    solo perche' ora il gate sa contare.

    Con N azioni dello stesso tipo l'intestazione e' quella di gruppo ("21 mail
    nel cestino"); con tipi diversi si resta generici, perche' nessun titolo
    specifico sarebbe onesto per un insieme misto. In ogni caso `voci` porta
    una riga per azione, con il suo `id`: e' quello che permette all'utente di
    escluderne una senza rifiutare tutto il gruppo.
    """
    if not azioni_pendenti:
        return None

    voci = []
    for azione in azioni_pendenti:
        descrizione = descrivi_azione(azione)
        voci.append({
            "id": azione.get("id"),
            "icona": descrizione["icona"],
            "riepilogo": descrizione["riepilogo"],
            "dettagli": descrizione["dettagli"],
            "corpo": descrizione["corpo"],
        })

    if len(azioni_pendenti) == 1:
        return {**descrivi_azione(azioni_pendenti[0]), "multipla": False, "totale": 1, "voci": voci}

    totale = len(azioni_pendenti)
    tipi = {a.get("tipo", "") for a in azioni_pendenti}
    if len(tipi) == 1:
        descrittore = _DESCRITTORI.get(next(iter(tipi)))
        icona = descrittore["icona"] if descrittore else "⚙"
        titolo = descrittore["gruppo"].format(n=totale) if descrittore else f"{totale} azioni da confermare"
    else:
        icona, titolo = "⚙", f"{totale} azioni da confermare"

    return {
        "icona": icona,
        "titolo": titolo,
        "riepilogo": titolo,
        "dettagli": [],
        "corpo": None,
        "multipla": True,
        "totale": totale,
        "voci": voci,
    }


# Frase di **esito** (passato, cosa e' stato fatto) di un'azione eseguita, per
# la conferma dal vivo nella UI: distinta dalla descrizione della scheda pending
# (presente/futuro) - stessa casa perche' e' sempre "come si dice a parole
# un'azione", ma informazione diversa. Non persistita in cronologia (le azioni
# fatte non si tengono, vedi DECISIONS.md 2026-07-29).
def esito_azione(azione: dict) -> str:
    descrittore = _DESCRITTORI.get(azione.get("tipo", ""))
    if descrittore is None:
        return "Azione eseguita"
    return descrittore["esito"](azione.get("payload") or {})


def esito_gruppo(esiti: list[dict]) -> str:
    """Una riga sola per un gruppo risolto, contando per tipo: "20 mail
    spostate nel cestino, 1 esclusa". Dice anche quello che **non** e'
    andato - un fallimento silenzioso su 21 azioni e' esattamente il modo
    di far perdere fiducia in un assistente che agisce da solo."""
    if not esiti:
        return "Niente da fare"

    eseguite = [e for e in esiti if e.get("stato") == azioni.STATO_INVIATA]
    if len(esiti) == 1 and len(eseguite) == 1:
        return eseguite[0].get("esito") or "Azione eseguita"

    pezzi: list[str] = []
    per_tipo: dict[str, int] = {}
    for e in eseguite:
        per_tipo[e.get("tipo", "")] = per_tipo.get(e.get("tipo", ""), 0) + 1
    for tipo, quante in per_tipo.items():
        descrittore = _DESCRITTORI.get(tipo)
        pezzi.append(
            descrittore["esito_gruppo"].format(n=quante) if descrittore
            else f"{quante} azioni eseguite"
        )
    if not pezzi:
        pezzi.append("niente eseguito")

    def _conta(stato: str) -> int:
        return sum(1 for e in esiti if e.get("stato") == stato)

    escluse = _conta(azioni.STATO_RIFIUTATA)
    if escluse:
        pezzi.append(f"{escluse} esclusa" if escluse == 1 else f"{escluse} escluse")
    fallite = _conta(azioni.STATO_ERRORE)
    if fallite:
        pezzi.append(f"{fallite} non riuscita" if fallite == 1 else f"{fallite} non riuscite")
    scadute = _conta(azioni.STATO_SCADUTA)
    if scadute:
        pezzi.append(f"{scadute} scaduta" if scadute == 1 else f"{scadute} scadute")

    return ", ".join(pezzi)
