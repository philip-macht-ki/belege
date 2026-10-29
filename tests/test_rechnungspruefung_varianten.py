"""Realistische Schreibweisen der Pflichtangaben auf Rechnungen."""
from datetime import date

import pytest

from belege.pruefung import pruefe
from belege.typen import Einordnung, Text


def _einordnung():
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Lieferant GmbH",
                       "Beratung", 300.0, "EUR", "hoch", "", "regel", "Studio Beispiel")


def _rechnung(*, steuer: str = "MwSt. 19 %", steuer_id: str = "USt-IdNr.: DE123456789",
              nummer: str = "Rechnungsnummer: RE-2026-100", datum: str = "Rechnungsdatum: 29.10.2026",
              leistung: str = "Leistungszeitraum: Oktober 2026") -> Text:
    return Text(f"Lieferant GmbH\nMusterstraße 1\n12345 Berlin\nRechnung an: Studio Beispiel\n"
                f"{steuer_id}\n{nummer}\n{datum}\n{leistung}\n{steuer}\nGesamt 300,00 EUR", "klartext", 1)


@pytest.mark.parametrize("steuer_id", [
    "Steuernummer: 12/345/67890", "Steuer-Nr.: 12/345/67890", "St.-Nr. 12/345/67890",
    "StNr: 1234567890", "Steuer Nr. 12/345/67890", "UStIdNr: DE123456789",
    "USt-ID: DE123456789", "Umsatzsteuer-Identifikationsnummer: DE123456789",
    "VAT ID: GB123456789", "VAT No. FR12345678901", "ATU12345678",
])
def test_lieferantensteuer_varianten(repo, steuer_id):
    assert pruefe(_einordnung(), _rechnung(steuer_id=steuer_id)) == []


@pytest.mark.parametrize("nummer", [
    "Rechnungsnummer: RE-2026-100", "Rechnungs-Nr.: RE-2026-100", "Rg.-Nr. RG-2026-100",
    "Re.-Nr. RE-2026-100", "Belegnummer: B-2026-100", "Invoice No. INV-2026-100",
    "Invoice Number: INV-2026-100", "Rechnung\nNr. RE-2026-100",
])
def test_rechnungsnummer_varianten(repo, nummer):
    assert pruefe(_einordnung(), _rechnung(nummer=nummer)) == []


@pytest.mark.parametrize("datum", [
    "Rechnungsdatum: 29.10.2026", "Datum: 2026-10-29", "Invoice date: 10/29/2026",
    "Invoice date: October 29, 2026",
])
def test_datum_varianten(repo, datum):
    assert pruefe(_einordnung(), _rechnung(datum=datum)) == []


@pytest.mark.parametrize("leistung", [
    "Leistung: Beratung", "Leistungsdatum: 29.10.2026", "Leistungszeitraum: Oktober 2026",
    "Leistungsdatum entspricht Rechnungsdatum", "Service: Consulting October 2026",
])
def test_leistungs_varianten(repo, leistung):
    assert pruefe(_einordnung(), _rechnung(leistung=leistung)) == []


@pytest.mark.parametrize("steuer", [
    "Steuersatz: 19 %", "MwSt. 19 %", "USt 19 %", "Reverse Charge",
    "Steuerschuldnerschaft des Leistungsempfängers", "§ 13b UStG", "Kleinunternehmer gemäß § 19 UStG",
    "steuerfrei", "innergemeinschaftliche Lieferung",
])
def test_steuer_varianten(repo, steuer):
    assert pruefe(_einordnung(), _rechnung(steuer=steuer)) == []
