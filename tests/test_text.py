from pathlib import Path
import os

from fpdf import FPDF
from PIL import Image, ImageDraw
import pytest

from belege import text
from belege.text import auslesen, fehlerquote


def _pdf(p: Path, text: str):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, text)
    pdf.output(str(p))


def test_pdftotext_liest_und_kuerzt(repo):
    p = repo / "rechnung.pdf"
    satz = "Rechnung fuer Studio Beispiel mit vielen klaren Woertern und einem Betrag. "
    _pdf(p, satz * 150)
    t = auslesen(p)
    assert t.stufe == "pdftotext"
    assert 100 <= len(t.text) <= 6000


def test_fehlerquote_erkennt_zeichensalat():
    assert fehlerquote("Eine normale Rechnung mit klaren Worten und Betrag 12,50 EUR.") == 0
    assert fehlerquote("RecHnung Re5hnung ### normale Worte") > .10


def test_klartext_wird_auf_6000_zeichen_gekuerzt(repo):
    p = repo / "lang.txt"
    p.write_text("abc " * 2000)
    assert len(auslesen(p).text) == 6000


def test_xml_wird_ohne_modell_als_erechnung_gelesen(repo, monkeypatch):
    p = repo / "rechnung.xml"
    p.write_text("<Invoice><ID>X-1</ID><IssueDate>2026-09-10</IssueDate>"
                 "<AccountingSupplierParty><Name>Blatt</Name></AccountingSupplierParty>"
                 "<AccountingCustomerParty><Name>Studio Beispiel</Name></AccountingCustomerParty>"
                 "<LegalMonetaryTotal><PayableAmount>12.50</PayableAmount></LegalMonetaryTotal>"
                 "<InvoiceLine><Name>Papier</Name><LineExtensionAmount>10</LineExtensionAmount>"
                 "</InvoiceLine></Invoice>")
    monkeypatch.setattr(text, "_claude", lambda _: pytest.fail("Claude darf XML nicht lesen"))
    erkannt = auslesen(p)
    assert erkannt.stufe == "xml"
    assert "Verkäufer: Blatt" in erkannt.text


def test_metaantwort_von_claude_wird_verworfen(repo, monkeypatch):
    p = repo / "scan.pdf"
    p.write_bytes(b"kein echtes PDF")
    monkeypatch.setattr(text, "_pdftotext", lambda _: "")
    monkeypatch.setattr(text, "_vision", lambda _: "")
    monkeypatch.setattr(text, "_tesseract", lambda _: "")
    monkeypatch.setattr(text, "_claude", lambda _: "Ich benötige den Pfad zur Datei.")
    assert auslesen(p).stufe == "leer"


def test_farbverlauf_bleibt_leer_ohne_claude(repo, monkeypatch):
    p = repo / "urlaub.jpg"
    Image.linear_gradient("L").convert("RGB").resize((640, 400)).save(p)
    monkeypatch.setattr(text, "_vision", lambda _: "")
    monkeypatch.setattr(text, "_tesseract", lambda _: "")
    monkeypatch.setattr(text, "_claude", lambda _: pytest.fail("Claude darf nicht starten"))
    assert auslesen(p).stufe == "leer"


def test_unbekannte_endung_erreicht_claude_nicht(repo, monkeypatch):
    p = repo / "rechnung.pdf.crdownload"
    p.write_bytes(b"noch nicht fertig")
    def _kein_claude(_datei):
        pytest.fail("Claude darf bei unbekannter Endung nicht starten")

    monkeypatch.setattr(text, "_claude", _kein_claude)
    assert auslesen(p).stufe == "leer"


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Vision gibt es nur unter macOS")
def test_scan_nimmt_vision_wenn_verfuegbar(repo):
    pytest.importorskip("Vision")
    bild = repo / "scan.png"
    im = Image.new("RGB", (1200, 1200), "white")
    zeichner = ImageDraw.Draw(im)
    for y in range(30, 1100, 55):
        zeichner.text((30, y), "Rechnung Studio Beispiel Betrag 23,80 EUR", fill="black", font_size=32)
    im.save(bild)
    pdf = repo / "scan.pdf"
    doc = FPDF()
    doc.add_page()
    doc.image(str(bild), x=10, y=10, w=190)
    doc.output(str(pdf))
    assert auslesen(pdf).stufe == "vision"
