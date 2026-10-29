"""Pflichtangaben werden lokal geprüft und nie automatisch versandt."""
from datetime import date

from belege.pruefung import pruefe
from belege.typen import Einordnung, Text


def _einordnung(betrag=119.0):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Lieferant GmbH", "Software", betrag, "EUR", "hoch", "", "regel", "Studio Beispiel")


def test_vollstaendige_rechnung_ist_ok(repo):
    text = Text("""Lieferant GmbH\nMusterstraße 1\n12345 Berlin\nRechnung an: Studio Beispiel
    Rechnungsnummer: RE-2026-001\nRechnungsdatum: 29.10.2026\nLeistung: Software, Menge 1
    USt-IdNr.: DE123456789\nUmsatzsteuer 19 % 19,00 EUR\nGesamt 119,00 EUR""", "klartext", 1)
    assert pruefe(_einordnung(300), text) == []


def test_fehler_und_kleinbetrag(repo):
    text = Text("Rechnung an: Studio Beispel\nRechnungsdatum: 29.10.2026\nLeistung: Porto", "klartext", 1)
    befund = pruefe(_einordnung(300), text)
    assert any("abweichend" in punkt for punkt in befund)
    assert any("Rechnungsnummer" in punkt for punkt in befund)
    klein = Text("Lieferant\nMusterweg 3\n12345 Bonn\nDatum: 29.10.2026\nLeistung: Kaffee\nGesamt 12,00\n19 %", "klartext", 1)
    assert pruefe(_einordnung(12), klein) == []


def test_reverse_charge_und_xml_felder(repo):
    text = Text("Rechnung an Studio Beispiel\nUSt-IdNr. DE123456789\nRechnungsnummer RE-22\nDatum: 29.10.2026\nLeistung: Beratung\nReverse Charge", "klartext", 1)
    assert pruefe(_einordnung(300), text) == []
    xml = {"kaeufer": "Studio Beispiel", "verkaeufer_ust": "DE123456789", "nummer": "R-1", "datum": date(2026, 10, 29), "positionen": [{"text": "Beratung"}], "steuer": True}
    assert pruefe(_einordnung(300), Text("", "xml", 1), xml=xml) == []
