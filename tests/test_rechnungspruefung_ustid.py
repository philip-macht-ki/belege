"""Eine fehlende USt-IdNr. oder Steuernummer des Lieferanten fällt auf (1.14.2).

Bis 1.14.1 galt jedes lange Wort als EU-USt-IdNr. („Druckerei“), die Zeile nach
„USt-IdNr.“ als Wert („24103 Kiel“) und eine Gläubiger-ID als USt-IdNr. Eine
Rechnung über 480 € ganz ohne Steuernummer ergab damit „OK“.
"""
from datetime import date

from belege.pruefung import _hat_lieferantensteuer, pruefe
from belege.typen import Einordnung, Text

FEHLT = "USt-IdNr. oder Steuernummer des Lieferanten fehlt"
KOPF = "Druckerei Lindenau GmbH\nHafenstraße 4\n24103 Kiel\nRechnung an: Studio Beispiel\nMusterstraße 1\n12345 Musterstadt\n"
REST = "Rechnungsnummer: 2026-0402\nRechnungsdatum: 25.10.2026\nLeistung: Flyer A5, 1.000 Stück\nNetto 403,36 EUR\nUmsatzsteuer 19 % 76,64 EUR\nGesamt 480,00 EUR\n"


def _einordnung(betrag=480.0):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 25), "Druckerei Lindenau GmbH", "Druck", betrag, "EUR", "hoch", "", "regel", "Studio Beispiel")


def test_rechnung_ohne_steuernummer_hat_befund(repo):
    for fuss in ["", "Gläubiger-ID DE98ZZZ09999999999\nMandatsreferenz 4711\n", "USt-IdNr.\n24103 Kiel\n",
                 "Bankverbindung Sparkasse Kiel\nIBAN DE12 2105 0170 0012 3456 78\nBIC NOLADE21KIE\n"]:
        befund = pruefe(_einordnung(), Text(KOPF + REST + fuss, "klartext", 1))
        assert FEHLT in befund, fuss


def test_rechnung_mit_steuernummer_ohne_befund(repo):
    for fuss in ["USt-IdNr.: DE123456789\n", "USt-IdNr. DE 123 456 789\n", "VAT ID: IE3668997OH\n",
                 "Steuernummer: 19/295/12345\n", "St.-Nr. 2929512345\n", "Steuer-Nr.\n19/295/12345\n",
                 "Druckerei Lindenau GmbH · DE123456789 · Amtsgericht Kiel HRB 1234\n", "ATU12345678\n",
                 "VAT ID: GB123456789\n", "MWST-Nr. / VAT: CHE-123.456.789\n",
                 "www.lieferant.example USt.-IDNr. DE123456789 BIC: DEUTDEDBDUE\n"]:
        befund = pruefe(_einordnung(), Text(KOPF + REST + fuss, "klartext", 1))
        assert FEHLT not in befund, fuss


def test_lange_woerter_und_folgezeilen_zaehlen_nicht():
    assert not _hat_lieferantensteuer("Druckerei Lindenau GmbH\nGeschäftsführung Maria Lindenau", None)
    assert not _hat_lieferantensteuer("USt-IdNr.\n24103 Kiel", None)
    assert not _hat_lieferantensteuer("Gläubiger-Identifikationsnummer DE98ZZZ09999999999", None)
    assert _hat_lieferantensteuer("", {"verkaeufer_ust": "DE123456789"})


def test_eigene_ust_id_ist_keine_lieferanten_ust_id():
    firma = {"ust_id": "DE111111111"}
    assert not _hat_lieferantensteuer("Ihre USt-IdNr.: DE111111111", None, firma)
    assert not _hat_lieferantensteuer("Kunde Studio Beispiel DE 111 111 111", None, firma)
    assert _hat_lieferantensteuer("Ihre USt-IdNr.: DE111111111\nUnsere USt-IdNr.: DE123456789", None, firma)
