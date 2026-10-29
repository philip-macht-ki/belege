"""Konservative Regressionen aus dem trockenen Echtlauf."""
from datetime import date

import pytest

from belege.pruefung import hinweise, pruefe
from belege.typen import Einordnung, Text


def _e(*, betrag=300, firma="Studio Beispiel"):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Lieferant", "Leistung", betrag,
                       "EUR", "hoch", "", "regel", firma)


@pytest.fixture(autouse=True)
def _alle_pruefregeln(repo, monkeypatch):
    from belege import kern
    cfg = {"ablage": {"bereich_betrieb": "Betrieb"}, "betrieb": {"name": "Studio Beispiel", "namen": ["Studio Beispiel"], "anschrift": {"strasse": "Musterstraße 1", "plz": "12345", "ort": "Musterstadt"}}, "pruefung": {"an": True, "regeln": ["empfaenger", "anschrift", "ust_id_lieferant", "rechnungsnummer", "datum", "steuer", "leistung"], "kleinbetrag": 250}}
    monkeypatch.setattr(kern, "konfig", lambda _name: cfg)


def _voll(text="", *, nummer="Rechnungsnummer: RE-2026-100", datum="Rechnungsdatum: 29.10.2026", leistung="Leistung: Beratung", steuer="MwSt. 19 %"):
    return Text("Lieferant GmbH\nMusterweg 1\n12345 Berlin\nRechnung an: Studio Beispiel\n"
                f"USt-IdNr.: DE123456789\n{nummer}\n{datum}\n{leistung}\n{steuer}\n" + text, "klartext", 1)


def test_spaltenlayout_wird_vor_pruefung_verdichtet(repo):
    text = _voll("Description" + " " * 82 + "Qty       Unit price      Amount\nCloud Hosting Plan   1   $39.20   $39.20")
    assert pruefe(_e(), text) == []
    assert "Leistungsbeschreibung oder Leistungszeitraum fehlt" in pruefe(_e(), _voll("ohne Angaben", leistung=""))


@pytest.mark.parametrize("steuer", [
    "* MwSt ist verrechnet durch „Reverse-Charge“", "Gemäß Artikel 196, EC Direktive 2006/112/EC obliegt die Umsatzsteuer dem Leistungsempfänger",
    "subject to reverse charge under Article 196", "zzgl. 19 % USt € : 23,88", "Zuzüglich 19% MwSt. : 52,88 €",
    "194-6 Pfandsystem 0,25 EUR 19% MwSt", "VAT 0% 0,00 €", "Nettobetrag VAT Umsatzsteuer Gesamtsumme\n0% 2.074,80 0,00",
])
def test_steuerhinweise_und_prozent_varianten(repo, steuer):
    assert "Steuersatz und Steuerbetrag oder Steuerhinweis fehlt" not in pruefe(_e(), _voll(steuer))
    assert hinweise(_e(), _voll("subject to reverse charge under Article 196")) == ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]


def test_steuer_ohne_hinweis_bleibt_befund(repo):
    assert "Steuersatz und Steuerbetrag oder Steuerhinweis fehlt" in pruefe(_e(), _voll("ohne Steuer", steuer=""))


def test_usa_rechnung_ohne_lieferanten_ust_bleibt_bei_den_deutschen_steuerpflichten_still(repo):
    text = Text("Invoice\nInvoice number AB12CD-0001\nDate of issue July 3, 2026\nExample Tech Inc. Bill to\n"
                "12 Main Street Studio Beispiel\nLos Angeles, California 90094 Musterstraße 1\nUnited States 12345 Musterstadt\n"
                "DE VAT DE123456789\n$15.00 USD due July 3, 2026\nDescription Qty Unit price Amount\nAPI credits 15 $1.00 $15.00\nTotal $15.00", "klartext", 1)
    befund = pruefe(_e(), text)
    assert not any("Steuersatz" in x or "USt-IdNr." in x for x in befund)
    deutsch = _voll("ohne Steuer", nummer="Beleg: X-100", steuer="")
    assert any("Steuersatz" in x for x in pruefe(_e(), deutsch))


@pytest.mark.parametrize("text", [
    "Canva Pty Ltd\n110 Example St, NSW 2010, Australia\nABN 80 000 000 000\nRechnung 202610069\n29.10.2026\nLeistung: Design\nGesamt 25,00 EUR",
    "INVOICE\nBill to: Studio Beispiel, Musterstraße 1, 12345 Musterstadt\nInvoice number AB-00007\nInvoice date Sep 25, 2026\nDescription: Service\n$25.00",
])
def test_drittland_allgemein_ohne_eu_ust_bleibt_still(repo, text):
    befund = pruefe(_e(), Text(text, "klartext", 1))
    assert not any("Steuersatz" in punkt or "USt-IdNr." in punkt for punkt in befund)


def test_eu_lieferant_ohne_steuerhinweis_bleibt_befund(repo):
    text = Text("Rechnung\nLieferant SARL\nFrance\nRechnung an: Studio Beispiel\nMusterstraße 1\n12345 Musterstadt\n"
                "Rechnung 202610069\n29.10.2026\nLeistung: Beratung\nSteuer ID: FR95", "klartext", 1)
    befund = pruefe(_e(), text)
    assert "Steuersatz und Steuerbetrag oder Steuerhinweis fehlt" in befund


def test_gekuerzter_text_prueft_nur_empfaenger_und_anschrift(repo):
    text = Text("Rechnung an: Studio Beispiel\nMusterstraße 1\n12345 Musterstadt\n" + "Kopf\n" * 1200, "klartext", 1)
    assert pruefe(_e(), text) == []
    falsch = Text("Rechnung an: Falsche GmbH\n" + "Kopf\n" * 1200, "klartext", 1)
    assert any("Empfänger fehlt" in x or "abweichend" in x for x in pruefe(_e(), falsch))


def test_dritte_pdf_seite_prueft_nur_empfaenger_und_anschrift(repo):
    # pdftotext hält absichtlich nur zwei Seiten vor; Angaben auf Seite drei sind unbekannt.
    text = Text("Rechnung an: Studio Beispiel\nMusterstraße 1\n12345 Musterstadt", "klartext", 3)
    assert pruefe(_e(), text) == []
    falsch = Text("Rechnung an: Falsche GmbH\nMusterstraße 1\n12345 Musterstadt", "klartext", 3)
    assert any("Empfänger" in punkt for punkt in pruefe(_e(), falsch))


def test_unlesbarer_glyphensalat_ist_still(repo):
    salat = Text("/gB8/gC5/gC3/gC8/gCE/gD5\n" * 3 + "Rechnung\n", "klartext", 1)
    assert pruefe(_e(), salat) == []
    assert hinweise(_e(), salat) == []


@pytest.mark.parametrize("titel", ["Gutschrift", "Credit Note", "Erstattung", "Refund", "Zahlungserinnerung", "Mahnung", "Auftragsbestätigung", "Order Confirmation", "Pro-forma", "Angebot", "Kontoauszug", "Jahreskonto", "Auszahlungsübersicht", "Auszahlungsbericht", "Zahlungsbericht", "Bescheid", "Lohnabrechnung", "Vertrag"])
def test_keine_rechnungsdokumente_bleiben_still(repo, titel):
    assert pruefe(_e(), Text(titel + "\nRechnung\n", "klartext", 1)) == []


def test_gutschrift_im_fliesstext_ist_keine_titel_entscheidung(repo):
    text = _voll("\n".join(["Kopf"] * 16) + "\nGutschrift erfolgt auf Ihr Konto", steuer="").text.replace("USt-IdNr.: DE123456789\n", "")
    assert pruefe(_e(), Text(text, "klartext", 1)) != []


@pytest.mark.parametrize("nummer", ["Rechnung  202610069", "Rechnung\n202610069", "Invoice 4711-22", "Quittung 12345", "Rechnung 202610069", "Rechnung 000000046", "Ausgangsrechnung #01FVUEB26-03715/b", "Invoice #INV-2041", "Beleg-Nr.\nKd.-Nr.\nDatum\n260799\n10875\n31.07.2026", "Bei Zahlung angeben Datum NUMMER\n25-08-2026 2608329", "Credit Note Number:\n1072"])
def test_rechnungsnummer_auch_in_spalten_und_folgezeilen(repo, nummer):
    assert "Rechnungsnummer fehlt" not in pruefe(_e(), _voll(nummer))


def test_ohne_rechnungsnummer_bleibt_befund(repo):
    assert "Rechnungsnummer fehlt" in pruefe(_e(), _voll("Leistung vorhanden", nummer=""))


def test_artikel_196_trotz_ocr_verlust_ist_steuer_und_reverse_charge_hinweis(repo):
    text = _voll("Gema Artikel 196, EC Direktive 2006/112/EC obliegt die Umsatzsteuer dem Leistungsempfanger", steuer="")
    assert "Steuersatz und Steuerbetrag oder Steuerhinweis fehlt" not in pruefe(_e(), text)
    assert hinweise(_e(), text) == ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]
    assert "Steuersatz und Steuerbetrag oder Steuerhinweis fehlt" in pruefe(_e(), _voll("Artikel 196", steuer=""))


@pytest.mark.parametrize("titel", ["Darlehensvertrag", "Steuerbescheid", "Zahlungsbeleg", "Payment receipt", "Landesjustizkasse"])
def test_weitere_keine_rechnungsdokumente_bleiben_still(repo, titel):
    text = titel + ("\n" if titel == "Payment receipt" else "\nRechnung\n")
    assert pruefe(_e(), Text(text, "klartext", 1)) == []


def test_kein_rechnungsdokument_ohne_titelwort_und_ausdruecklicher_ausschluss(repo):
    assert pruefe(_e(), Text("SEO-Wochenreport\nSichtbarkeit und Links", "klartext", 1)) == []
    assert pruefe(_e(), Text("Das ist keine Rechnung\nRechnung 202610069", "klartext", 1)) == []
    # Eine Rechnung ohne Steuerangabe muss trotz Erwähnung einer Zahlungserinnerung weiter auffallen.
    text = _voll("\n".join(["Fließtext"] * 21 + ["Zahlungserinnerung zu einer alten Forderung"]), steuer="")
    assert "Steuersatz und Steuerbetrag oder Steuerhinweis fehlt" in pruefe(_e(), text)


@pytest.mark.parametrize("absender", ["Finanzamt Berlin", "Landesjustizkasse NRW", "Amtsgericht Köln"])
def test_behoerden_im_kopf_bleiben_still(repo, absender):
    assert pruefe(_e(), Text(absender + "\nRechnung\n", "klartext", 1)) == []


@pytest.mark.parametrize("datum", ["31. Aug. 2026", "Rechnungsdatum\n31. Aug. 2026", "25.06.26", "Jul 21, 2026", "Sep. 3, 2026"])
def test_datumsvarianten_werden_erkannt(repo, datum):
    assert "Rechnungsdatum fehlt" not in pruefe(_e(), _voll(datum))


def test_ohne_datum_bleibt_befund(repo):
    assert "Rechnungsdatum fehlt" in pruefe(_e(), _voll("ohne Datum", datum=""))


@pytest.mark.parametrize("adresse", ["Example Ireland Unlimited Company, 5 Wilton Park, Dublin 2, Ireland", "Block 8, Harcourt Centre, Dublin D02 K580, Irland", "15 rue des Exemples, 75009 Paris, France", "12 Example Road, London SW1A 1AA"])
def test_kleinbetrag_akzeptiert_auslaendische_lieferantenanschriften(repo, adresse):
    assert "Name und Anschrift des Lieferanten fehlt" not in pruefe(_e(betrag=20), Text(adresse + "\n19%", "klartext", 1))


def test_kleinbetrag_ohne_adresshinweis_bleibt_befund(repo):
    # Ohne Rechnungswort ist das Dokument seit der zweiten Echtlaufrunde bewusst still.
    assert "Name und Anschrift des Lieferanten fehlt" in pruefe(_e(betrag=20), Text("Quittung\nLieferant\n19%", "klartext", 1))


def test_mehrspaltenkopf_findet_erwartete_anschrift_global(repo):
    text = _voll("Lieferant GmbH, Lieferweg 3, 79111 Freiburg\nStudio Beispiel\nMusterstraße 1\n12345 Musterstadt")
    assert not any("Anschrift" in x for x in pruefe(_e(), text))


def test_firma_kann_pruefung_abschalten(repo, monkeypatch):
    monkeypatch.setattr("belege.pruefung._firma", lambda _e: {"pruefung": False})
    assert pruefe(_e(firma="Ausland UAB"), Text("Rechnung", "klartext", 1)) == []
    assert hinweise(_e(firma="Ausland UAB"), Text("Reverse-Charge", "klartext", 1)) == []
