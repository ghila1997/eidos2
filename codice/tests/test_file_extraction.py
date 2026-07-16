import io
from types import SimpleNamespace

import openpyxl
import pypdf
from docx import Document

from memoria import file_extraction


def _pdf_senza_testo() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_senza_testo_non_ha_testo_digitale():
    assert file_extraction.pdf_ha_testo_digitale(_pdf_senza_testo()) is False


def test_pdf_con_testo_digitale_rilevato(monkeypatch):
    """Trappola: pdf_ha_testo_digitale deve riconoscere un PDF con testo
    reale (non solo il caso vuoto) - pypdf.PdfReader mockato per non
    dipendere da una libreria di generazione PDF con testo (reportlab)."""
    pagina_finta = SimpleNamespace(extract_text=lambda: "Fattura n. 123 del 16/07/2026 - Importo dovuto: 500 EUR")
    lettore_finto = SimpleNamespace(pages=[pagina_finta])
    monkeypatch.setattr(file_extraction.pypdf, "PdfReader", lambda _: lettore_finto)

    assert file_extraction.pdf_ha_testo_digitale(b"non importa, mockato") is True
    assert "Fattura n. 123" in file_extraction.estrai_testo_pdf(b"non importa, mockato")


def test_pdf_corrotto_trattato_come_senza_testo_non_crash():
    assert file_extraction.pdf_ha_testo_digitale(b"non sono affatto un PDF") is False


def test_numero_pagine_pdf():
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    assert file_extraction.numero_pagine_pdf(buffer.getvalue()) == 2


def test_estrai_testo_docx():
    documento = Document()
    documento.add_paragraph("Contratto di fornitura con Rossi Srl")
    buffer = io.BytesIO()
    documento.save(buffer)

    testo = file_extraction.estrai_testo_docx(buffer.getvalue())

    assert "Contratto di fornitura con Rossi Srl" in testo


def test_estrai_testo_xlsx():
    cartella = openpyxl.Workbook()
    foglio = cartella.active
    foglio.title = "Listino"
    foglio.append(["Prodotto", "Prezzo"])
    foglio.append(["Vite M6", 0.15])
    buffer = io.BytesIO()
    cartella.save(buffer)

    testo = file_extraction.estrai_testo_xlsx(buffer.getvalue())

    assert "Listino" in testo
    assert "Vite M6" in testo
