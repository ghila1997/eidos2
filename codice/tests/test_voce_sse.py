"""Parser SSE incrementale lato client (Tappa 6): i chunk di rete possono
spezzare righe ed eventi in punti arbitrari — il parser deve ricomporli."""
from __future__ import annotations

from voce.sse import ParserSSE


def test_evento_intero_in_un_chunk():
    p = ParserSSE()
    eventi = p.aggiungi('event: delta\ndata: {"testo": "Ciao"}\n\n')
    assert eventi == [("delta", {"testo": "Ciao"})]


def test_evento_spezzato_tra_chunk():
    p = ParserSSE()
    assert p.aggiungi("event: del") == []
    assert p.aggiungi('ta\ndata: {"tes') == []
    eventi = p.aggiungi('to": "Ciao"}\n\n')
    assert eventi == [("delta", {"testo": "Ciao"})]


def test_piu_eventi_in_un_chunk():
    p = ParserSSE()
    chunk = (
        'event: tool_in_corso\ndata: {"tool": "search_memoria"}\n\n'
        'event: delta\ndata: {"testo": "Trovato"}\n\n'
    )
    assert p.aggiungi(chunk) == [
        ("tool_in_corso", {"tool": "search_memoria"}),
        ("delta", {"testo": "Trovato"}),
    ]


def test_ignora_righe_sconosciute_e_commenti():
    p = ParserSSE()
    eventi = p.aggiungi(': keepalive\nid: 7\nevent: fine\ndata: {"risposta": "ok", "azione_in_attesa": null}\n\n')
    assert eventi == [("fine", {"risposta": "ok", "azione_in_attesa": None})]
