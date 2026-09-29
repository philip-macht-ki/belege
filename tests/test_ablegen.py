"""Tests für sichere, kollisionsfreie und trockene Ablage."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from belege.ablegen import ablegen, dateiname, sauber
from belege.typen import Einordnung, Fund, Text


def _einordnung(**werte):
    daten = {
        "ist_beleg": True,
        "art": "eingang",
        "bereich": "betrieb",
        "datum": date(2026, 9, 10),
        "lieferant": "Möwe & Söhne",
        "beschreibung": "Rechnung-Software-Abo",
        "betrag": 19.90,
        "waehrung": "EUR",
        "sicherheit": "hoch",
        "grund": "Test.",
        "quelle": "rueckfall",
    }
    daten.update(werte)
    return Einordnung(**daten)


def _fund(repo, name="beleg.pdf", inhalt=b"eins", verschieben=True):
    datei = repo / "handy" / name
    datei.write_bytes(inhalt)
    return Fund(datei, "handy", name, date(2026, 9, 10), verschieben=verschieben)


def test_namensschema_erhaelt_umlaute():
    assert sauber("Möwe & Söhne") == "Möwe-Söhne"
    assert dateiname(_einordnung(), ".pdf") == "2026-09-10_Möwe-Söhne_Rechnung-Software-Abo.pdf"


def test_trocken_dann_echt_verschiebt_nur_echt(repo):
    fund = _fund(repo)
    trocken = ablegen(fund, _einordnung(), Text("", "leer"), False)
    assert trocken.status == "nichts"
    assert fund.datei.exists()
    assert not list((repo / "ablage").rglob("*.pdf"))
    echt = ablegen(fund, _einordnung(), Text("", "leer"), True)
    assert echt.status == "ok"
    assert not fund.datei.exists()
    assert Path(echt.daten["pfad"]).exists()


def test_kollision_bekommt_anhang_2_und_ueberschreibt_nicht(repo):
    erster = _fund(repo, "eins.pdf", b"eins")
    ablegen(erster, _einordnung(), Text("", "leer"), True)
    zweiter = _fund(repo, "zwei.pdf", b"zwei")
    ergebnis = ablegen(zweiter, _einordnung(), Text("", "leer"), True)
    assert ergebnis.daten["pfad"].endswith("_2.pdf")
    assert Path(ergebnis.daten["pfad"]).read_bytes() == b"zwei"


def test_unsortiert_nie_ueberschrieben_wird(repo):
    erster = _fund(repo, "unklar.pdf", b"eins")
    einordnung = _einordnung(sicherheit="niedrig")
    ablegen(erster, einordnung, Text("", "leer"), True)
    zweiter = _fund(repo, "unklar.pdf", b"zwei")
    ergebnis = ablegen(zweiter, einordnung, Text("", "leer"), True)
    assert "/Unsortiert/" in ergebnis.daten["pfad"]
    assert ergebnis.daten["pfad"].endswith("_2.pdf")


def test_erechnung_legt_xml_und_sicht_pdf_mit_gleichem_stamm_ab(repo):
    xml = (
        b'<?xml version="1.0"?><Invoice><ID>R-1</ID><IssueDate>2026-09-10</IssueDate>'
        b'<AccountingSupplierParty><Party><PartyName><Name>Lieferant Beispiel</Name>'
        b'</PartyName></Party></AccountingSupplierParty><AccountingCustomerParty><Party>'
        b'<PartyName><Name>Studio Beispiel</Name></PartyName></Party>'
        b'</AccountingCustomerParty><LegalMonetaryTotal><PayableAmount currencyID="EUR">'
        b'19.90</PayableAmount></LegalMonetaryTotal></Invoice>'
    )
    fund = _fund(repo, "rechnung.xml", xml)
    ergebnis = ablegen(fund, _einordnung(), Text("", "xml"), True)
    xml_pfad = Path(ergebnis.daten["pfad"])
    pdf_pfad = xml_pfad.with_suffix(".pdf")
    assert xml_pfad.exists()
    assert pdf_pfad.exists()
    assert xml_pfad.stem == pdf_pfad.stem


def test_sonderzeichen_bleiben_im_namen():
    from belege.ablegen import sauber

    assert sauber("Café Morgenrot") == "Café-Morgenrot"
    assert sauber("Blatt & Bogen / Druck") == "Blatt-Bogen-Druck"
