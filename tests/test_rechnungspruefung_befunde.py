"""Regressionen für Befunde der Rechnungsprüfung."""
from datetime import date

import pytest

from belege import verarbeiten
from belege.pruefung import pruefe
from belege.typen import Einordnung, Fund, Text


def _einordnung(*, firma="Studio Beispiel"):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Lieferant GmbH",
                       "Beratung", 300.0, "EUR", "hoch", "", "regel", firma)


def _rechnung(*, datum="Rechnungsdatum: 29.10.2026", leistung="Leistung: Beratung"):
    return Text("Lieferant GmbH\nMusterstraße 1\n12345 Berlin\nRechnung an: Studio Beispiel\n"
                "USt-IdNr.: DE123456789\nRechnungsnummer: RE-2026-100\n"
                f"{datum}\n{leistung}\nMwSt. 19 %\nGesamt 300,00 EUR", "klartext", 1)


@pytest.mark.parametrize("datum", [
    "Rechnungsdatum: 29. Oktober 2026",
    "Ausgestellt am: 29. Oktober 2026",
    "Invoice date: Oct 29, 2026",
])
def test_datumsformen_mit_monatsnamen_werden_erkannt(repo, datum):
    assert pruefe(_einordnung(), _rechnung(datum=datum)) == []


@pytest.mark.parametrize("leistung", [
    "Bezeichnung: Beratung", "Beschreibung: Beratung", "Artikel: Beratung",
    "Position: Beratung", "Pos.: Beratung", "Description: Consulting", "Item: Consulting",
    "Leistung: Beratung", "Leistungszeitraum: Oktober 2026",
])
def test_positionsbezeichnungen_werden_als_leistung_erkannt(repo, leistung):
    assert pruefe(_einordnung(), _rechnung(leistung=leistung)) == []


def test_unklare_einzelfirma_wird_nicht_geprueft_und_erzeugt_keinen_entwurf(repo, monkeypatch):
    datei = repo / "unklar-einzelfirma.pdf"
    datei.write_bytes(b"%PDF")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 1), {"von": "lieferant@example.test"})
    einordnung = _einordnung(firma="unklar")
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("an = false", "an = true"), encoding="utf-8")
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_, **__: einordnung)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.pruefung.pruefe", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Prüfung")))
    monkeypatch.setattr("belege.senden.entwurf", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Entwurf")))
    ergebnis = verarbeiten.verarbeite(fund, True)
    assert ergebnis.status == "befund" and "/Unsortiert/" in ergebnis.daten["pfad"]


def test_entwurf_ohne_eigene_empfaengerdaten_wird_nicht_angelegt(repo, monkeypatch):
    datei = repo / "ohne-empfaengerdaten.pdf"
    datei.write_bytes(b"%PDF")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 1), {"von": "lieferant@example.test"})
    einordnung = _einordnung()
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("an = false", "an = true"), encoding="utf-8")
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_, **__: einordnung)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung", "klartext", 1))
    monkeypatch.setattr("belege.pruefung.pruefe", lambda *_a, **_k: ["Rechnungsnummer fehlt"])
    monkeypatch.setattr("belege.kern.firma", lambda *_a, **_k: {"name": "", "ust_id": ""})
    monkeypatch.setattr("belege.senden.entwurf", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Entwurf")))
    assert verarbeiten.verarbeite(fund, True).status == "befund"


def test_befehl_ueberspringt_unklare_firma(repo, monkeypatch, capsys):
    from belege import pruefung

    datei = repo / "unklar.txt"
    datei.write_text("Rechnung", encoding="utf-8")
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: _einordnung(firma="unklar"))
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung", "klartext", 1))
    monkeypatch.setattr(pruefung, "pruefe", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Prüfung")))
    assert pruefung.befehl(type("Args", (), {"ziel": [str(datei)]})()) == 0
    assert capsys.readouterr().out.strip() == "Firma unklar – wird nicht geprüft, landet in Unsortiert"
