"""Tests für den sicheren Einzelablauf eines Funds."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

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


def test_fehlendes_rechnungsdatum_bekommt_befund_und_eingangsmonat(repo, monkeypatch):
    """Ohne Ausstellungsdatum bleibt die Rechnung prüfbar und nachvollziehbar."""
    datei = repo / "ohne-datum.pdf"
    datei.write_bytes(b"%PDF ohne Datum")
    fund = Fund(datei, "postfach", datei.name, date(2026, 9, 10), {"von": "lieferant@example.test"})
    e = _einordnung(fund, Text("", "klartext", 1))
    e.datum = None
    e.firma = "Studio Beispiel"
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("an = false", "an = true"), encoding="utf-8")
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_, **__: e)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text(
        "Lieferant GmbH\nMusterstraße 1\n12345 Berlin\nRechnung an: Studio Beispiel\n"
        "USt-IdNr. DE123456789\nRechnungsnummer RE-100\nLeistung: Beratung\nMwSt 19 %\nGesamt 300,00 EUR", "klartext", 1))
    ergebnis = verarbeiten.verarbeite(fund, True)
    assert ergebnis.status == "befund"
    befund = next((repo / "ablage").rglob("*.befund.txt"))
    assert "Rechnungsdatum fehlt" in befund.read_text(encoding="utf-8")
    assert "Eingangsdatum 10.09.2026" in befund.read_text(encoding="utf-8")
    index = json.loads((repo / "arbeit" / "index.json").read_text(encoding="utf-8"))
    eintrag = next(iter(index.values()))
    assert eintrag["datum"] is None and eintrag["befund"].endswith(".befund.txt")
    assert "/Manuell prüfen/2026/09/" in eintrag["pfad"]


def test_unklare_firma_wird_nicht_geprueft_und_erzeugt_keinen_entwurf(repo, monkeypatch):
    """Mehrfirmen-Funde ohne eindeutige Firma bleiben im Unsortiert-Weg."""
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text('[ablage]\nordner = "ablage"\nprivat = true\nbereich_betrieb = "Betrieb"\n'
                   '[[firma]]\nname = "Alpha GmbH"\nbereich = "Alpha"\n'
                   '[[firma]]\nname = "Beta GmbH"\nbereich = "Beta"\n'
                   '[pruefung]\nan = true\n', encoding="utf-8")
    datei = repo / "unklar.pdf"; datei.write_bytes(b"%PDF")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 1), {"von": "lieferant@example.test"})
    unklar = _einordnung(fund, Text("", "klartext", 1)); unklar.firma = "unklar"
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_, **__: unklar)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.senden.entwurf", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Entwurf")))
    ergebnis = verarbeiten.verarbeite(fund, True)
    assert ergebnis.status == "befund" and "/Unsortiert/" in ergebnis.daten["pfad"]
    assert not (repo / "arbeit" / "index.json").exists() or "pruefung" not in (repo / "arbeit" / "index.json").read_text(encoding="utf-8")


def test_beanstandete_xml_rechnung_hat_sicht_pdf(repo):
    """Auch im Ordner Manuell prüfen ist die E-Rechnung lesbar sichtbar."""
    from belege.ablegen import ablegen_befund
    xml = repo / "beanstandet.xml"
    xml.write_text("<Invoice><ID>RE-1</ID><IssueDate>2026-09-10</IssueDate><LegalMonetaryTotal>"
                   '<PayableAmount currencyID="EUR">300.00</PayableAmount></LegalMonetaryTotal></Invoice>', encoding="utf-8")
    e = _einordnung(Fund(xml, "handy", xml.name, date(2026, 9, 10)), Text("", "xml", 1)); e.firma = "Studio Beispiel"
    ergebnis = ablegen_befund(Fund(xml, "handy", xml.name, date(2026, 9, 10)), e, ["Rechnungsnummer fehlt"], True)
    assert Path(ergebnis.daten["pfad"]).with_suffix(".pdf").exists()


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


def _beleg_einordnung(lieferant="Taxi Müller", *, datum=date(2026, 10, 3), betrag=23.4, waehrung="EUR",
                      beschreibung="Fahrt"):
    """Baut eine sichere Einordnung für Dubletten- und ZUGFeRD-Verhaltenstests."""
    from belege.typen import Einordnung

    return Einordnung(True, "eingang", "betrieb", datum, lieferant, beschreibung, betrag,
                      waehrung, "hoch", "Testregel.", "regel")


def _normaler_pdf_fund(repo, name, inhalt=b"%PDF normal"):
    """Legt einen einfachen PDF-Fund für den normalen Einordnungsweg an."""
    datei = repo / name
    datei.write_bytes(inhalt)
    return Fund(datei, "handy", name, date(2026, 10, 3))


def test_zugferd_namensnennung_ohne_xml_wird_normal_abgelegt(repo, monkeypatch):
    """Ein bloßer Factur-X-Dateiname im PDF darf keinen dauerhaften Fehler auslösen."""
    fund = _normaler_pdf_fund(repo, "scheinbar-zugferd.pdf", b"%PDF factur-x.xml")
    logs = []
    monkeypatch.setattr("belege.verarbeiten.get_xml_from_pdf", lambda *_a, **_k: None)
    monkeypatch.setattr("belege.verarbeiten.kern.log", logs.append)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("normale Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: _beleg_einordnung())
    assert verarbeiten.verarbeite(fund, True).status == "ok"
    assert verarbeiten.verarbeite(fund, True).status == "nichts"
    assert "nennt eine E-Rechnung, enthält aber keine lesbare" in logs[0]


def test_zugferd_namensnennung_mit_lesefehler_wird_normal_abgelegt(repo, monkeypatch):
    """Eine Ausnahme der Factur-X-Bibliothek fällt auf die normale Einordnung zurück."""
    fund = _normaler_pdf_fund(repo, "fehler-zugferd.pdf", b"%PDF factur-x.xml")
    monkeypatch.setattr("belege.verarbeiten.get_xml_from_pdf", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kaputt")))
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("normale Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: _beleg_einordnung())
    assert verarbeiten.verarbeite(fund, True).status == "ok"


def test_zugferd_namensnennung_mit_kaputter_xml_wird_normal_abgelegt(repo, monkeypatch):
    """Eine nicht lesbare angehängte XML ist ebenfalls kein ZUGFeRD-Erfolg."""
    fund = _normaler_pdf_fund(repo, "kaputte-xml.pdf", b"%PDF factur-x.xml")
    monkeypatch.setattr("belege.verarbeiten.get_xml_from_pdf", lambda *_a, **_k: b"<kaputt")
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("normale Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: _beleg_einordnung())
    assert verarbeiten.verarbeite(fund, True).status == "ok"


def test_echte_eingebettete_zugferd_rechnung_bleibt_xml_quelle(repo):
    """Eine tatsächlich eingebettete, lesbare XML nutzt weiter den XML-Weg."""
    from facturx import generate_from_file
    from pypdf import PdfWriter

    xml = b"""<rsm:CrossIndustryInvoice xmlns:rsm=\"urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100\"
    xmlns:ram=\"urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100\"
    xmlns:udt=\"urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100\">
    <rsm:ExchangedDocument><ram:ID>RE-7</ram:ID><ram:TypeCode>380</ram:TypeCode><ram:IssueDateTime><udt:DateTimeString>20261003</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>
    <rsm:SupplyChainTradeTransaction><ram:ApplicableHeaderTradeAgreement><ram:SellerTradeParty><ram:Name>Taxi Mueller</ram:Name></ram:SellerTradeParty><ram:BuyerTradeParty><ram:Name>Studio Beispiel</ram:Name></ram:BuyerTradeParty></ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement><ram:SpecifiedTradeSettlementHeaderMonetarySummation><ram:GrandTotalAmount currencyID=\"EUR\">23.40</ram:GrandTotalAmount></ram:SpecifiedTradeSettlementHeaderMonetarySummation></ram:ApplicableHeaderTradeSettlement>
    <ram:IncludedSupplyChainTradeLineItem><ram:SpecifiedTradeProduct><ram:Name>Fahrt</ram:Name></ram:SpecifiedTradeProduct><ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>23.40</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement></ram:IncludedSupplyChainTradeLineItem></rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>"""
    basis = repo / "sicht.pdf"
    datei = repo / "echt-zugferd.pdf"
    writer = PdfWriter(); writer.add_blank_page(100, 100); writer.add_attachment("factur-x.xml", xml)
    with basis.open("wb") as offen:
        writer.write(offen)
    generate_from_file(str(basis), xml, flavor="factur-x", level="basic", check_xsd=False, output_pdf_file=str(datei))
    # Der Generator maskiert PDF-Namen; die vorhandene Schnellprüfung sucht den
    # unmaskierten Dateinamen, wie er bei den Kunden-PDFs vorkommt.
    datei.write_bytes(datei.read_bytes() + b"\n% factur-x.xml\n")
    fund = Fund(datei, "handy", datei.name, date(2026, 10, 3))
    assert verarbeiten._zugferd(fund)[0].quelle == "xml"
    ergebnis = verarbeiten.verarbeite(fund, True)
    assert ergebnis.status == "ok"


def _zwei_belege(repo, monkeypatch, *, zweiter_lieferant="FREE NOW", zweiter_text="Taxi Müller",
                 zweiter_betrag=23.4, zweites_datum=date(2026, 10, 3), zweite_waehrung="EUR",
                 zweite_beschreibung="Fahrt"):
    """Legt zwei absichtlich verschiedene Dateien mit gezielt gepatchter Einordnung ab."""
    erster = _normaler_pdf_fund(repo, "taxi.pdf", b"%PDF Taxi")
    zweiter = _normaler_pdf_fund(repo, "freedom.pdf", b"%PDF Free Now")
    einordnungen = iter((
        _beleg_einordnung(),
        _beleg_einordnung(zweiter_lieferant, datum=zweites_datum, betrag=zweiter_betrag,
                           waehrung=zweite_waehrung, beschreibung=zweite_beschreibung),
    ))
    texte = iter((Text("Taxi Müller", "klartext", 1), Text(zweiter_text, "klartext", 1)))
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: next(einordnungen))
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: next(texte))
    assert verarbeiten.verarbeite(erster, True).status == "ok"
    assert verarbeiten.verarbeite(zweiter, True).status == "ok"


def test_dublettenhinweis_bei_namensbezug(repo, monkeypatch):
    """Zwei Taxibelege mit Namensbezug bekommen genau einen vorsichtigen Hinweis."""
    from belege import kern

    _zwei_belege(repo, monkeypatch)
    eintraege = list(json.loads((repo / "arbeit" / "index.json").read_text()).values())
    neuer = next(e for e in eintraege if e["lieferant"] == "FREE NOW")
    assert "Taxi-Müller_Fahrt.pdf" in neuer["moegliche_dublette"]
    zweifel = [e for e in kern.ereignisse() if e["art"] == "zweifel"]
    assert len(zweifel) == 1
    assert "Möglicherweise doppelt" in zweifel[0]["text"] and "23,40 €" in zweifel[0]["text"]


def test_dublettenhinweis_ohne_namensbezug_bleibt_aus(repo, monkeypatch):
    _zwei_belege(repo, monkeypatch, zweiter_text="Fahrt mit unbekanntem Anbieter")
    assert "moegliche_dublette" not in next(e for e in json.loads((repo / "arbeit" / "index.json").read_text()).values()
                                            if e["lieferant"] == "FREE NOW")


def test_dublettenhinweis_bei_abweichendem_betrag_oder_datum_bleibt_aus(repo, monkeypatch):
    _zwei_belege(repo, monkeypatch, zweiter_lieferant="Taxi Müller", zweiter_betrag=23.9)
    assert not any("moegliche_dublette" in e for e in json.loads((repo / "arbeit" / "index.json").read_text()).values())


def test_dublettenhinweis_bei_abweichendem_datum_bleibt_aus(repo, monkeypatch):
    _zwei_belege(repo, monkeypatch, zweiter_lieferant="Taxi Müller", zweites_datum=date(2026, 10, 4))
    assert not any("moegliche_dublette" in e for e in json.loads((repo / "arbeit" / "index.json").read_text()).values())


def test_dublettenhinweis_bei_abweichender_waehrung_bleibt_aus(repo, monkeypatch):
    _zwei_belege(repo, monkeypatch, zweiter_lieferant="Taxi Müller", zweite_waehrung="USD")
    assert not any("moegliche_dublette" in e for e in json.loads((repo / "arbeit" / "index.json").read_text()).values())


def test_dublettenhinweis_rechnung_und_quittung_bleibt_aus(repo, monkeypatch):
    _zwei_belege(repo, monkeypatch, zweiter_lieferant="Taxi Müller", zweite_beschreibung="Zahlungsquittung")
    assert not any("moegliche_dublette" in e for e in json.loads((repo / "arbeit" / "index.json").read_text()).values())


def test_dublettenhinweis_schalter_und_trockenlauf(repo, monkeypatch):
    from belege import kern

    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("dublettenhinweis = true", "dublettenhinweis = false"), encoding="utf-8")
    _zwei_belege(repo, monkeypatch)
    assert not any("moegliche_dublette" in e for e in json.loads((repo / "arbeit" / "index.json").read_text()).values())

    trocken = _normaler_pdf_fund(repo, "trocken.pdf", b"%PDF trocken")
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: _beleg_einordnung())
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Taxi Müller", "klartext", 1))
    assert verarbeiten.verarbeite(trocken, False).status == "nichts"
    assert not any(e["art"] == "zweifel" and "trocken.pdf" in e["text"] for e in kern.ereignisse())


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
