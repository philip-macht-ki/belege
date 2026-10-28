"""Regressionsfälle für die getrennte Firmenablage ohne Modellaufruf."""
from datetime import date

from belege import kern
from belege.ablegen import ziel
from belege.einordnen import _firma_aus_text
from belege.typen import Einordnung
from belege import bericht, monat


def _mehrere(tmp_path, monkeypatch):
    (tmp_path / "konfig").mkdir()
    (tmp_path / "konfig" / "belege.toml").write_text(
        '[ablage]\nordner = "ablage"\nprivat = true\nbereich_betrieb = "Betrieb"\n'
        '[[firma]]\nname = "Alpha GmbH"\nnamen = ["Alpha", "Alpha Gesellschaft"]\nust_id = "DE111111111"\nbereich = "Alpha"\n'
        '[[firma]]\nname = "Beta GmbH"\nnamen = ["Beta"]\nust_id = "DE222222222"\nbereich = "Beta"\n', encoding="utf-8")
    (tmp_path / "konfig" / "regeln.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)


def test_firma_eindeutig_schreibweise_und_ust_id(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    assert _firma_aus_text("Rechnung\nEmpfänger: Alpha Gesellschaft\nBerlin") == "Alpha GmbH"
    assert _firma_aus_text("Rechnung\nUSt-IdNr DE222222222") == "Beta GmbH"


def test_firma_unklar_und_bereichspfad(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    assert _firma_aus_text("Rechnung\nEmpfänger: Alpha und Beta") is None
    e = Einordnung(True, "eingang", "betrieb", date(2026, 10, 1), "Lieferant", "Rechnung", 1,
                   "EUR", "hoch", "Test", "rueckfall", "Beta GmbH")
    assert str(ziel(e, ".pdf")).endswith("ablage/Beta/2026/10/Eingang/2026-10-01_Lieferant_Rechnung.pdf")


def test_alte_einzelfirma_bleibt_betrieb(tmp_path, monkeypatch):
    (tmp_path / "konfig").mkdir()
    (tmp_path / "konfig" / "belege.toml").write_text(
        '[ablage]\nordner = "ablage"\nbereich_betrieb = "Betrieb"\n[betrieb]\nname = "Alt GmbH"\nnamen = ["Alt"]\n', encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)
    e = Einordnung(True, "eingang", "betrieb", date(2026, 10, 1), "Lieferant", "Rechnung", 1,
                   "EUR", "hoch", "Test", "rueckfall", "Alt GmbH")
    assert "/Betrieb/2026/10/" in str(ziel(e, ".pdf"))


def test_bericht_gruppiert_nach_firma():
    text, _ = bericht.text_und_betreff([
        {"art": "abgelegt", "text": "", "daten": {"firma": "Alpha GmbH", "lieferant": "A"}},
        {"art": "abgelegt", "text": "", "daten": {"firma": "Beta GmbH", "lieferant": "B"}},
        {"art": "unsortiert", "text": "beleg.pdf", "daten": {"grund": "Firma unklar"}},
    ])
    assert "Alpha GmbH (1)" in text and "Beta GmbH (1)" in text and "Firma unklar" in text


def test_monat_filtert_firma(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    tag = "2026-10-01"
    index = {"a": {"datum": tag, "betrag": 10, "lieferant": "Alpha", "art": "eingang", "bereich": "betrieb", "firma": "Alpha GmbH", "status": "abgelegt"},
             "b": {"datum": tag, "betrag": 10, "lieferant": "Beta", "art": "eingang", "bereich": "betrieb", "firma": "Beta GmbH", "status": "abgelegt"}}
    daten = monat.abgleichen([{"datum": tag, "betrag": -10, "name": "Alpha", "zweck": ""}], index, "Alpha GmbH")
    assert daten[0]["status"] == "zugeordnet"
