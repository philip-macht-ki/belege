from datetime import date

from belege.aufraeumen import aktualisieren, liste
from belege.pruefung import hinweise, pruefe
from belege.typen import Einordnung, Text


def _e(betrag=300):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Muster GmbH", "Abo", betrag, "EUR", "hoch", "", "regel", "Studio Beispiel")


def _rechnung(extra="", steuer="MwSt 19 %"):
    return Text("Muster GmbH\nRechnung an: Studio Beispiel\nUSt-IdNr. DE123456789\nRechnung RE-100\n29.10.2026\nLeistung: Beratung\n" + steuer + "\n" + extra, "klartext", 1)


def test_mahnung_und_kuerzel_liste_bleiben_still_und_fliestext_nicht(repo):
    assert pruefe(_e(), Text("Muster GmbH\nMAHNUNG\nRechnung RE-1", "klartext", 1)) == []
    assert "Steuersatz" in " ".join(pruefe(_e(), _rechnung("Erinnerung: zahlbar bis morgen", "")))
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("[pruefung]\n", "[pruefung]\nnie_beleg = [\"report@example.test\", \"Wochenreport\"]\n"), encoding="utf-8")
    assert pruefe(_e(), Text("Wochenreport\nRechnung RE-1", "klartext", 1), absender="x@example.test") == []
    assert pruefe(_e(), _rechnung(), absender="report@example.test") == []


def test_eu_ohne_hinweis_nur_mit_eigener_ustid(repo):
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('ust_id = ""', 'ust_id = "DE111111111"').replace("an = false", "an = true"), encoding="utf-8")
    text = _rechnung("VAT number: FR12345678901\nIhre USt-IdNr.: DE 111 111 111", "")
    assert not any("Steuersatz" in p for p in pruefe(_e(), text))
    assert any("EU-Rechnung ohne" in p for p in hinweise(_e(), text))
    ohne_eigene = _rechnung("VAT number: FR12345678901", "")
    assert "Steuersatz" in " ".join(pruefe(_e(), ohne_eigene))
    assert not any("EU-Rechnung ohne" in p for p in hinweise(_e(), ohne_eigene))


def test_ocr_steuer_und_kleinbetrag_position_und_drittland(repo):
    assert not any("Steuersatz" in p for p in pruefe(_e(), _rechnung("MwSt\n\n\n19 %")))
    klein = Text("Rechnung\n4. September 2026\nBestellnummer: AB12CD\niCloud+ mit 50 GB (Monatlich)   2,99 €\nGesamt 2,99", "klartext", 1)
    assert not any("Leistungsbeschreibung" in p for p in pruefe(_e(2.99), klein))
    ausland = _rechnung("Canva Pty Ltd\nAustralia\nABN 123 456 789", "")
    assert not any("Steuersatz" in p for p in pruefe(_e(), ausland))


def test_liste_sortiert_blendet_aus_und_status_wird_bei_neuem_problem_geoeffnet():
    stand = {"erste_liste": None, "anbieter": {"alt": {"name": "Alt", "status": "ignorieren", "weg": "lieferant", "probleme": [], "rechnungen": 1}}}
    eintraege = [{"lieferant": "Meta GmbH", "punkte": ["Empfänger fehlt"], "hinweise": [], "datum": "2026-10-01", "betrag": 1},
                 {"lieferant": "Anders", "punkte": ["Steuer fehlt"], "hinweise": [], "datum": "2026-10-01", "betrag": 1},
                 {"lieferant": "Alt", "punkte": ["Steuer fehlt"], "hinweise": [], "datum": "2026-10-01", "betrag": 1}]
    _, text = liste(eintraege, stand)
    assert text.index("Meta") < text.index("Anders") and "- Alt" not in text
    daten = {"erste_liste": None, "anbieter": {"muster": {"name": "Muster", "status": "erledigt", "probleme": ["Empfänger fehlt"], "rechnungen": 1}}}
    neu, melden = aktualisieren({"lieferant": "Muster GmbH", "punkte": ["Steuer fehlt"], "hinweise": [], "datum": "2026-10-02"}, daten)
    assert neu["status"] == "offen" and melden


import pytest  # noqa: E402

from belege import verarbeiten  # noqa: E402
from belege.aufraeumen import befehl as aufraeumen_befehl, weg, zustand  # noqa: E402
from belege.pruefung import EU_OHNE_SATZ  # noqa: E402
from belege.typen import Fund  # noqa: E402


@pytest.mark.parametrize("kopf", [
    "Muster Anwälte\nAktenzeichen 12/26\n\n\nZAHLUNGSERINNERUNG\nRechnung RE-55 vom 01.08.2026",
    "Muster Insolvenzverwaltung\nAttraktive Veräußerungsmöglichkeit\nStaRUG-Verfahren Katalog",
    "Telekom Muster\nAnlage Rechnungskonten\nKundenkonto 1234",
    "Muster Inc.\nFor ACH delivery\nRouting 0000\nAccount 1111",
    "Getränke Muster GmbH\nLeergut- & Transportmittel-Abrechnung\nRücknahme 20.10.2026",
    "Receipt\nMuster SAS\nReceipt number RCPT-000001\nInvoice number INV-839346-001\nAmount paid 10,00",
])
def test_keine_rechnungen_bleiben_still(repo, kopf):
    assert pruefe(_e(), Text(kopf, "klartext", 1)) == []


def test_quittung_ohne_verweis_bleibt_pruefbar(repo):
    assert pruefe(_e(), Text("Quittung\nMuster Kiosk\nGetränk 3,00", "klartext", 1)) != []


def test_empfaenger_als_nachname_vorname(repo):
    text = Text("Muster Steuerberatung\nMusterweg 1\n12345 Musterstadt\nBeispiel, Mara\nRechnung RE-1\n29.10.2026\n"
                "Leistung: Beratung\nMwSt 19 %\nUSt-IdNr. DE123456789", "klartext", 1)
    assert not any("Empfänger" in p for p in pruefe(_e(), text))


def test_positionszeile_ohne_kopfwort_ist_leistung(repo):
    text = _rechnung().text.replace("Leistung: Beratung\n", "8x Kunstblumen schalen a32€\n256,00\n")
    assert not any("Leistungsbeschreibung" in p for p in pruefe(_e(), Text(text, "klartext", 1)))


def test_weg_hinweis_nur_bei_eu_ohne_satz():
    assert weg("Muster", [], ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]) == ("", "")
    assert weg("Muster", [], [EU_OHNE_SATZ])[0] == "hinweis"
    assert weg("Meta Platforms Ireland", ["Empfänger fehlt"], [])[0] == "selbst"
    assert weg("Unbekannt GmbH", ["Empfänger fehlt"], [])[0] == "lieferant"


def test_liste_ohne_entwurf_verspricht_keinen_und_zaehlt_rechnungen():
    eintraege = [{"lieferant": "Lieferant GmbH", "punkte": ["Steuer fehlt"], "hinweise": []}] * 3 + [
        {"lieferant": "Nur RC", "punkte": [], "hinweise": ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]}]
    betreff, text = liste(eintraege, {"anbieter": {}})
    assert betreff == "Rechnungsprüfung: einmal aufräumen (1 Anbieter)" and "€" not in betreff
    assert "(3 Rechnungen)" in text and "Entwurf liegt" not in text and "Nur RC" not in text


def test_vorschau_als_eml_sendet_nichts(repo, monkeypatch, tmp_path):
    monkeypatch.setattr("belege.senden.senden", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("gesendet")))
    ziel = tmp_path / "liste.eml"
    args = type("Args", (), {"monate": 3, "vorschau": str(ziel), "echt": False})()
    assert aufraeumen_befehl(args) == 0
    from email import message_from_bytes, policy
    mail = message_from_bytes(ziel.read_bytes(), policy=policy.default)
    assert mail["Subject"].startswith("Rechnungsprüfung: einmal aufräumen")
    assert not zustand().get("erste_liste")


def test_nur_ein_entwurf_je_anbieter(repo, monkeypatch):
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("an = false", "an = true"), encoding="utf-8")
    entwuerfe = []
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_, **__: _e())
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.pruefung.pruefe", lambda *_a, **_k: ["Rechnungsnummer fehlt"])
    monkeypatch.setattr("belege.kern.firma", lambda *_a, **_k: {"name": "Studio Beispiel", "ust_id": "DE111111111"})
    monkeypatch.setattr("belege.senden.entwurf", lambda *a, **_k: entwuerfe.append(a))
    for nummer in (1, 2):
        datei = repo / f"rechnung{nummer}.pdf"
        datei.write_bytes(b"%PDF" + bytes([nummer]))
        fund = Fund(datei, "postfach", datei.name, date(2026, 10, nummer), {"von": "rechnung@muster.test"})
        assert verarbeiten.verarbeite(fund, True).status == "befund"
    assert len(entwuerfe) == 1
    assert zustand()["anbieter"]["muster"]["rechnungen"] == 2


def test_review_schluessel_zustand_und_eigene_eu_firma(repo):
    from belege.aufraeumen import schluessel
    from belege import kern
    assert schluessel("Meta Platforms Ireland Ltd") == schluessel("Meta")
    assert schluessel("Metallbau Schmidt GmbH") != schluessel("Meta")
    kern.schreiben(kern.pfad("arbeit", "pruefung_anbieter.json"), {"anbieter": []})
    assert zustand() == {"anbieter": {}, "erste_liste": None}
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('ust_id = ""', 'ust_id = "FR12345678901"'), encoding="utf-8")
    text = Text("Muster BV\nRechnung RE-1\n29.10.2026\nLeistung: Beratung\nBTW NL123456789B01\n"
                "Klant: FR 12345678901\nTotal 100,00", "klartext", 1)
    assert not any("Steuersatz" in p for p in pruefe(_e(), text))


def test_mahnung_als_position_in_echter_rechnung_bleibt_pruefbar(repo):
    text = Text("Muster Inkasso GmbH\nRechnung\nRechnung Nr. RE-42\n29.10.2026\nMahnung\n12,00", "klartext", 1)
    assert pruefe(_e(), text) != []


def test_aufraeumliste_merkt_sich_fehlversand_nicht(repo, monkeypatch):
    from belege import kern
    kern.schreiben(kern.pfad("arbeit", "index.json"), {"a": {"lieferant": "Muster GmbH", "datum": date.today().isoformat(),
                                                           "pruefung": {"status": "befund", "punkte": ["Steuer fehlt"]}}})
    monkeypatch.setattr("belege.senden.senden", lambda *_a, **_k: kern.Ergebnis("befund", "Nicht gesendet"))
    monkeypatch.setattr("belege.bericht.empfaenger", lambda: "ich@example.test")
    args = type("Args", (), {"monate": 3, "vorschau": None, "echt": True})()
    assert aufraeumen_befehl(args) == 1
    assert not zustand().get("erste_liste")


def test_echtlauf_reste_leergut_anlage_canva_und_steuer_id(repo):
    assert pruefe(_e(), Text("Leergut- & Transportmittel-Abrechnung      Getränke Muster GmbH\nBeleg-Nr. 1", "klartext", 1)) == []
    assert pruefe(_e(), Text("\nAnlage Rechnungskonten     Details unter www.muster.de\nAufstellung Ihrer Rechnungskonten*\n5633472085",
                             "klartext", 1)) == []
    canva = Text("Muster Rechnung\nRechnung                  05018-44925970\nAusstellungsdatum 28.09.2026\nRechnungsadresse Germany\n"
                 "Artikel Betrag\nMuster Pro (Jahresabonnement) 107,88 €\nGesamtbetrag 107,88 €\n\n"
                 "Muster Pty Ltd, 1 Kippax St, NSW 2010, Australia · ABN 80 000 000 000", "klartext", 1)
    assert pruefe(_e(107.88), canva) == []
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('ust_id = ""', 'ust_id = "DE111111111"'), encoding="utf-8")
    mistral = Text("Anzahlungsrechnung\nRechnungsnummer MS-1\nAusgabedatum 10. Sep. 2026\nVon An\nMuster SAS Studio Beispiel\n"
                   "Musterweg 1\n12345 Musterstadt\n\n\n\n\nArtikel Menge Preis\nAPI Guthaben 1 €10,00\n\n\n"
                   "Steuer ID: DE111111111\nSteuer ID: FR12000000000\n€10,00",
                   "klartext", 1)
    assert pruefe(_e(), mistral) == []


def test_erinnerung_ohne_hinweise_quittung_mit(repo):
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("an = false", "an = true"), encoding="utf-8")
    quittung = Text("Receipt\nMuster SAS\nReceipt number RCPT-000001\nInvoice number INV-1\nVAT FR12000000000\nVAT 0 %", "klartext", 1)
    # Stripe-Belege sind oft der einzige Beleg mit Reverse-Charge-Angabe; Hinweise bleiben.
    assert hinweise(_e(), quittung) != []
    erinnerung = Text("Muster Verrechnungsstelle\nUSt-IdNr. DE123456789\n\nERINNERUNG\nRechnung RE-1", "klartext", 1)
    assert hinweise(_e(), erinnerung) == []


def test_liste_zaehlt_nur_rechnungen_mit_befund():
    eintraege = [{"lieferant": "Meta", "punkte": ["Empfänger fehlt"], "hinweise": []},
                 {"lieferant": "Meta", "punkte": [], "hinweise": ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]}]
    _, text = liste(eintraege, {"anbieter": {}})
    assert "Meta (1 Rechnung)" in text
