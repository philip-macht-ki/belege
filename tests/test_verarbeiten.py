"""Tests für den sicheren Einzelablauf eines Funds."""

from __future__ import annotations

import json
from datetime import date

from belege import verarbeiten
from belege.typen import Fund, Text


def _einordnung(fund, text, **_):
    from belege.typen import Einordnung

    return Einordnung(
        True,
        "eingang",
        "betrieb",
        date(2026, 9, 10),
        "Pixelwerk",
        "Software-Abo",
        59.5,
        "EUR",
        "hoch",
        "Regel erkannt.",
        "regel",
    )


def test_dublette_wird_nicht_zweimal_abgelegt(repo, monkeypatch):
    """Eine bereits indexierte Datei wird ohne zweite Kopie übersprungen."""
    datei = repo / "rechnung.pdf"
    datei.write_bytes(b"gleich")
    fund = Fund(datei, "handy", datei.name, date(2026, 9, 10))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnung)
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _, **__: Text("Rechnung", "klartext", 1)
    )
    assert verarbeiten.verarbeite(fund, False).status == "nichts"
    assert not (repo / "ablage").exists() or not list((repo / "ablage").rglob("*"))
    assert verarbeiten.verarbeite(fund, True).status == "ok"
    erneut = verarbeiten.verarbeite(fund, True)
    assert erneut.status == "nichts"


def test_index_wird_nach_echter_ablage_geschrieben(repo, monkeypatch):
    """Der Index enthält nach einer echten Ablage die wichtigen Suchfelder."""
    datei = repo / "rechnung.pdf"
    datei.write_bytes(b"neu")
    fund = Fund(datei, "postfach", datei.name, date(2026, 9, 10))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnung)
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _, **__: Text("Rechnung", "klartext", 1)
    )
    assert verarbeiten.verarbeite(fund, True).status == "ok"
    index = json.loads((repo / "arbeit" / "index.json").read_text())
    eintrag = next(iter(index.values()))
    assert eintrag["lieferant"] == "Pixelwerk"
    assert eintrag["status"] == "abgelegt"


def test_downloads_zweifel_bleibt_liegen(repo, monkeypatch):
    """Ein unsicherer Download wird weder verschoben noch indexiert."""
    from belege.typen import Einordnung

    datei = repo / "downloads" / "unbekannt.pdf"
    datei.write_bytes(b"unsicher")
    fund = Fund(datei, "downloads", datei.name, date(2026, 9, 10), verschieben=True)
    unsicher = Einordnung(
        True,
        "eingang",
        "betrieb",
        date(2026, 9, 10),
        "Unbekannt",
        "Rechnung",
        None,
        "EUR",
        "niedrig",
        "Nur vorsichtig erkannt.",
        "rueckfall",
    )
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_, **__: unsicher)
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _, **__: Text("Rechnung", "klartext", 1)
    )
    assert verarbeiten.verarbeite(fund, False).status == "befund"
    assert datei.exists()
    assert verarbeiten.verarbeite(fund, True).status == "befund"
    assert datei.exists()


def test_erechnung_legt_xml_und_sicht_pdf_ab(repo):
    """Eine XML-Rechnung erhält neben dem Original eine lesbare Sicht-PDF."""
    xml = repo / "rechnung.xml"
    xml.write_text(
        """<Invoice><ID>RE-1</ID><IssueDate>2026-09-10</IssueDate>
        <AccountingSupplierParty><Party><PartyName><Name>Druckerei Blatt</Name></PartyName>
        </Party></AccountingSupplierParty><AccountingCustomerParty><Party><PartyName>
        <Name>Studio Beispiel</Name></PartyName></Party></AccountingCustomerParty>
        <LegalMonetaryTotal><PayableAmount currencyID=\"EUR\">47.60</PayableAmount>
        </LegalMonetaryTotal><InvoiceLine><Item><Name>Flyer</Name></Item>
        <LineExtensionAmount>40.00</LineExtensionAmount></InvoiceLine></Invoice>""",
        encoding="utf-8",
    )
    fund = Fund(xml, "postfach", xml.name, date(2026, 9, 10))
    trocken = verarbeiten.verarbeite(fund, False)
    assert trocken.status == "nichts"
    assert not list((repo / "ablage").rglob("*.xml"))
    assert verarbeiten.verarbeite(fund, True).status == "ok"
    abgelegt = list((repo / "ablage").rglob("*.xml"))
    assert len(abgelegt) == 1
    assert abgelegt[0].with_suffix(".pdf").exists()


def test_freier_name_ueberschreibt_nie(tmp_path):
    from belege.kern import freier_name

    (tmp_path / "bon.jpg").write_bytes(b"1")
    (tmp_path / "bon_2.jpg").write_bytes(b"2")
    assert freier_name(tmp_path / "bon.jpg").name == "bon_3.jpg"
    assert freier_name(tmp_path / "neu.jpg").name == "neu.jpg"


def test_downloads_duplikat_trocken_meldet_nichts(repo):
    from datetime import date

    from belege import kern as k
    from belege.typen import Fund
    from belege.verarbeiten import _sha, verarbeite

    datei = repo / "downloads" / "kopie.pdf"
    datei.write_bytes(b"%PDF gleich")
    k.schreiben(repo / "arbeit" / "index.json", {_sha(datei): {"pfad": "Betrieb/x.pdf", "firma": "Studio Beispiel"}})
    fund = Fund(datei, "downloads", datei.name, date.today(), verschieben=True)
    assert verarbeite(fund, False).status == "nichts"
    assert not (repo / "arbeit" / "ereignisse").exists()
    assert not (repo / "arbeit" / "gesehen.json").exists()
    verarbeite(fund, True)
    verarbeite(fund, True)
    zeilen = "".join(p.read_text() for p in (repo / "arbeit" / "ereignisse").glob("*.jsonl"))
    assert zeilen.count('"doppelt"') == 1
    assert "Studio Beispiel" in zeilen
    assert datei.exists()


def test_abofalle_wird_getrennt_abgelegt(repo, monkeypatch):
    datei = repo / "offerte.pdf"
    datei.write_bytes(b"%PDF harmlos")
    fund = Fund(datei, "handy", datei.name, date(2026, 10, 27), verschieben=True)
    monkeypatch.setattr("belege.text.auslesen", lambda _, **__: Text(
        "Offerte Branchenbuch Rheinland-Pfalz\\nEintragungsart\\nServicefax 0041 615 684 400", "klartext", 1))
    ergebnis = verarbeiten.verarbeite(fund, True)
    assert ergebnis.status == "befund"
    assert "Vorsicht Abofalle" in ergebnis.daten["pfad"]
    assert not datei.exists()


def test_einzelwort_offerte_ist_keine_abofalle():
    from belege.abofalle import erkennen
    assert erkennen("Ihre Offerte für Software", name="angebot.pdf") == (False, "")


def test_e_rechnung_mit_xml_geht_durch(tmp_path):
    from pypdf import PdfWriter
    from belege.abofalle import aktive_pdf_inhalte
    w = PdfWriter(); w.add_blank_page(100, 100)
    w.add_attachment("factur-x.xml", b"<rsm:CrossIndustryInvoice/>")
    datei = tmp_path / "zugferd.pdf"
    with datei.open("wb") as f: w.write(f)
    assert not aktive_pdf_inhalte(datei)[0]


def test_fremder_anhang_im_pdf_wird_angehalten(tmp_path):
    from pypdf import PdfWriter
    from belege.abofalle import aktive_pdf_inhalte
    w = PdfWriter(); w.add_blank_page(100, 100)
    w.add_attachment("tool.exe", b"MZ")
    datei = tmp_path / "anhang.pdf"
    with datei.open("wb") as f: w.write(f)
    assert aktive_pdf_inhalte(datei)[0]


def test_bestellte_verzeichnis_rechnung_ist_keine_abofalle():
    from belege.abofalle import erkennen
    assert not erkennen("Gelbe Seiten Branchenbuch\nRechnung Nr. 4711\nEintragungsart: Premium")[0]


def test_javascript_beim_oeffnen_wird_erkannt(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject
    from belege.abofalle import aktive_pdf_inhalte
    w = PdfWriter(); w.add_blank_page(100, 100)
    w._root_object[NameObject("/OpenAction")] = DictionaryObject({
        NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert(1)")})
    w.compress_identical_objects()
    datei = tmp_path / "oeffnen.pdf"
    with datei.open("wb") as f: w.write(f)
    assert aktive_pdf_inhalte(datei)[0]


def test_aktive_pdf_aus_downloads_wird_verschoben(tmp_path, monkeypatch):
    from belege import ablegen
    from belege.typen import Fund
    monkeypatch.setattr(ablegen, "ablage_ordner", lambda: tmp_path / "Ablage")
    quelle = tmp_path / "Downloads" / "x.pdf"; quelle.parent.mkdir(); quelle.write_bytes(b"%PDF")
    fund = Fund.__new__(Fund)
    for k, v in {"datei": quelle, "name": "x.pdf", "verschieben": True}.items(): object.__setattr__(fund, k, v)
    from datetime import datetime
    object.__setattr__(fund, "eingang", datetime(2026, 10, 27))
    erg = ablegen.abofalle_ablegen(fund, "JS", True, ordner="Vorsicht Datei prüfen", status="aktiv", hinweis="h")
    assert not quelle.exists() and "Vorsicht Datei prüfen" in erg.daten["pfad"]
