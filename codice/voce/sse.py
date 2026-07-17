"""Parser SSE incrementale per /chat/stream: i chunk TCP spezzano gli eventi
in punti arbitrari, si ricompone sul separatore di evento (riga vuota)."""
from __future__ import annotations

import json


class ParserSSE:
    def __init__(self) -> None:
        self._buffer = ""

    def aggiungi(self, testo: str) -> list[tuple[str, dict | None]]:
        self._buffer += testo
        eventi: list[tuple[str, dict | None]] = []
        while "\n\n" in self._buffer:
            blocco, self._buffer = self._buffer.split("\n\n", 1)
            nome, data = None, None
            for riga in blocco.split("\n"):
                if riga.startswith("event:"):
                    nome = riga.removeprefix("event:").strip()
                elif riga.startswith("data:"):
                    data = json.loads(riga.removeprefix("data:").strip())
            if nome is not None:
                eventi.append((nome, data))
        return eventi
