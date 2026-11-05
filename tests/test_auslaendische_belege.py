"""Übernommen aus Philips Belegcheck (05.11.2026): Fremdwährung im Buchungstext, ausländische Rechnungstitel."""
from __future__ import annotations

from belege import monat
from belege.pruefung import _rechnungsnummer_vorhanden


def test_originalbetrag_aus_dem_buchungstext(tmp_path):
    datei = tmp_path / "konto.csv"
    datei.write_text("Datum;Betrag;Name;Verwendungszweck\n"
                     "07.10.2026;-23,41;BUNNYCDN;Originalbetrag: -25,00 USD Kurs 1,068\n"
                     "08.10.2026;-12,00;Bäckerei;Kartenzahlung\n", encoding="utf-8")
    usd, eur = monat.buchungen(datei, "2026-10")
    assert usd["originalbetrag"] == -25.0
    assert eur["originalbetrag"] is None


def test_originalbetrag_in_euro_zaehlt_nicht():
    assert monat._originalbetrag_aus_text("Originalbetrag: 12,00 EUR") is None
    assert monat._originalbetrag_aus_text("Original amount 1.234,50 CHF") == 1234.5


def test_litauische_rechnungsnummer_wird_erkannt():
    assert _rechnungsnummer_vorhanden("UAB Proton\nSąskaita PVM-2026-10455\nVilnius", None)
    assert _rechnungsnummer_vorhanden("Faktura\n2026/10/0187\nWarszawa", None)


def test_datum_hinter_dem_titel_bleibt_keine_nummer():
    assert not _rechnungsnummer_vorhanden("Sąskaita 2026-10-05\nVilnius", None)
