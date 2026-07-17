"""Riempitivi vocali: mai silenzio non segnalato durante un tool lungo
(deciso a STOP 1, Tappa 6). Elenco chiuso locale — non generati dal modello:
zero latenza, zero costo, zero rischio di anticipare contenuti sbagliati.

Regole anti-fastidio:
- un riempitivo per finestra di silenzio (una catena di tool non fa spam);
- mai sopra l'audio della risposta già in corso;
- un solo "ancora un momento" se l'attesa si prolunga;
- si riarma a ogni turno nuovo.
"""
from __future__ import annotations

import random

# Frasi volutamente non troppo corte: i testi cortissimi con flush escono
# con prosodia frettolosa dai modelli turbo (trovato a STOP 2)
_FRASI = {
    "ricerca": ["Dammi un attimo, controllo subito.", "Un momento, faccio una ricerca."],
    "mail": ["Dammi un attimo, preparo la mail.", "Un momento, la scrivo subito."],
    "calendario": ["Un attimo, guardo il calendario.", "Dammi un momento, sistemo il calendario."],
    "default": ["Dammi un secondo, ci penso subito.", "Un attimo che ci guardo."],
    "attesa": ["Ancora un momento, ci sto lavorando.", "Quasi fatto, un altro attimo."],
}

_CATEGORIA_PER_TOOL = {
    "ricerca": {
        "search_memoria", "search_events", "search_files", "check_availability",
        "list_documents", "get_document", "list_folder", "list_labels",
        "list_attachments", "get_attachment", "read_file", "list_permissions",
        "Read", "Grep", "Glob",
    },
    "mail": {"draft_email", "send_email", "reply_email", "forward_email", "send_draft"},
    "calendario": {"create_event", "update_event", "delete_event", "respond_to_invite"},
}


def _categoria(tool: str) -> str:
    for categoria, tools in _CATEGORIA_PER_TOOL.items():
        if tool in tools:
            return categoria
    return "default"


class GestoreRiempitivi:
    def __init__(self) -> None:
        self.nuovo_turno()

    def nuovo_turno(self) -> None:
        self._parlato = False
        self._audio_in_corso = False
        self._attesa_usata = False

    def su_tool(self, tool: str) -> str | None:
        if self._parlato or self._audio_in_corso:
            return None
        self._parlato = True
        return random.choice(_FRASI[_categoria(tool)])

    def su_audio_risposta(self) -> None:
        """La risposta vera sta suonando: da qui in poi nessun riempitivo."""
        self._audio_in_corso = True

    def su_attesa_lunga(self) -> str | None:
        """Silenzio che si prolunga (~10s) dopo il primo riempitivo."""
        if self._audio_in_corso or self._attesa_usata or not self._parlato:
            return None
        self._attesa_usata = True
        return random.choice(_FRASI["attesa"])
