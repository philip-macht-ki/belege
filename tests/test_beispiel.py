import csv
import email.policy
import os
from email.parser import BytesParser

import pytest

from belege import text
from belege.beispiel import befehl, vorschau
from belege.text import auslesen


def test_beispiel_erzeugt_musterbetrieb(repo):
    assert befehl(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    assert len(list((basis / "postfach").glob("*.eml"))) == 10
    assert (basis / "handy" / "bon-cafe.jpg").exists()
    assert (basis / "downloads" / "rechnung.pdf.crdownload").exists()
    duplikat = (basis / "downloads" / "pixelwerk-duplicate.pdf").read_bytes()
    assert duplikat == (basis / "pixelwerk.pdf").read_bytes()
    erwartete_spalten = [
        "Buchungstag", "Valutadatum", "Beguenstigter/Zahlungspflichtiger",
        "Verwendungszweck", "Betrag", "Waehrung",
    ]
    with open(basis / "kontoauszug.csv", encoding="utf-8") as f:
        assert next(csv.reader(f, delimiter=";")) == erwartete_spalten


def test_kontoauszug_betraege_entsprechen_brutto_der_belege(repo):
    """Jeder Betrag im Kontoauszug muss zum Brutto der zugehoerigen Rechnung passen."""
    assert befehl(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    erwartet = {
        "Pixelwerk Software GmbH": "59,50",
        "Netzfunk": "29,99",
        "Schriftwerk Fonts": "19,00",
        "Hostingwerk": "9,90",
        "Zahnarztpraxis Beispiel": "80,00",
        "Café Morgenrot": "238,00",
    }
    with open(basis / "kontoauszug.csv", encoding="utf-8") as f:
        zeilen = list(csv.reader(f, delimiter=";"))[1:]
    betraege = {zeile[2]: zeile[4].lstrip("-") for zeile in zeilen}
    for lieferant, betrag in erwartet.items():
        assert betraege[lieferant] == betrag


def test_pixelwerk_duplikat_ist_bytegleich_inklusive_mailanhang(repo):
    """Original, Downloads-Duplikat und Mailanhang muessen exakt dieselben Bytes tragen."""
    assert befehl(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    original = (basis / "pixelwerk.pdf").read_bytes()
    assert (basis / "downloads" / "pixelwerk-duplicate.pdf").read_bytes() == original
    with open(basis / "postfach" / "01-pixelwerk.eml", "rb") as f:
        nachricht = BytesParser(policy=email.policy.default).parse(f)
    anhang = next(nachricht.iter_attachments())
    assert anhang.get_payload(decode=True) == original


def test_kein_beleg_braucht_die_claude_stufe(repo, monkeypatch):
    """Der ganze Musterbetrieb muss ohne Modellaufruf lesbar sein."""
    assert befehl(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    def _kein_claude(_datei):
        pytest.fail("Claude darf im Musterbetrieb nicht noetig sein")

    monkeypatch.setattr(text, "_claude", _kein_claude)
    dateien = [
        p for p in basis.rglob("*")
        if p.is_file()
        and "vorschau" not in p.relative_to(basis).parts
        and "postfach" not in p.relative_to(basis).parts
    ]
    ergebnisse = {p.relative_to(basis).as_posix(): auslesen(p) for p in dateien}
    assert ergebnisse["xrechnung.xml"].stufe == "xml"
    assert ergebnisse["downloads/urlaub.jpg"].stufe == "leer"
    for name, erwartete_stufe in (
        ("ausgang.pdf", "pdftotext"), ("netzfunk.pdf", "pdftotext"), ("zahlfix.pdf", "pdftotext"),
        ("privat.pdf", "pdftotext"), ("newsletter.pdf", "pdftotext"),
        ("downloads/anleitung.pdf", "pdftotext"), ("downloads/hostingwerk.pdf", "pdftotext"),
    ):
        assert ergebnisse[name].stufe == erwartete_stufe, name


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Vision gibt es nur unter macOS")
def test_bons_sind_per_vision_mit_summe_lesbar(repo):
    pytest.importorskip("Vision")
    assert befehl(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    for name, summe in (("bon-cafe.jpg", "18.40"), ("bon-papeterie.jpg", "12.49")):
        erkannt = auslesen(basis / "handy" / name)
        assert erkannt.stufe == "vision"
        assert summe in erkannt.text


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="Vision gibt es nur unter macOS")
def test_pixelwerk_scan_ist_per_vision_lesbar(repo):
    pytest.importorskip("Vision")
    assert befehl(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    erkannt = auslesen(basis / "pixelwerk.pdf")
    assert erkannt.stufe == "vision"
    assert "Pixelwerk" in erkannt.text


def test_vorschau_erzeugt_ein_png_je_beleg(repo):
    assert befehl(object()) == 0
    assert vorschau(object()) == 0
    basis = repo / "beispiel" / "erzeugt"
    pngs = list((basis / "vorschau").glob("*.png"))
    assert len(pngs) >= 10
    assert (basis / "vorschau" / "pixelwerk.png").exists()
