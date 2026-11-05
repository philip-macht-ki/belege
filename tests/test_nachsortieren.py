"""Nachsortieren: Unsortiert ein zweites Mal ansehen, erst trocken, dann echt."""
from __future__ import annotations

import json
from datetime import date

from belege import bericht, nachsortieren, verarbeiten
from belege.typen import Einordnung, Text

# 1x1-PNG, wenige Bytes: steht für Logo oder Signaturbild.
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c63f8cfc0f01f0005840180842a6321"
                    "0000000049454e44ae426082")


def _einordnung(sicherheit="hoch", firma=""):
    def einordnen(fund, text, **_):
        return Einordnung(True, "eingang", "betrieb", date(2026, 10, 7), "Pixelwerk", "Software-Abo", 59.5,
                          "EUR", sicherheit, "Test.", "urteil", firma)
    return einordnen


def _unsortiert(repo, name="2026-10-08_scan.pdf", inhalt=b"%PDF scan"):
    ordner = repo / "ablage" / "Unsortiert"
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / name
    datei.write_bytes(inhalt)
    return datei


def _ereignisse(repo):
    zeilen = []
    for datei in (repo / "arbeit" / "ereignisse").glob("*.jsonl"):
        zeilen += [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines()]
    return zeilen


def test_mailbild_erst_trocken_dann_nach_zu_loeschen(repo):
    logo = _unsortiert(repo, "2026-10-08_image001.png", PNG)
    nachsortieren.lauf(False)
    assert logo.exists()
    nachsortieren.lauf(True)
    assert not logo.exists()
    assert (repo / "ablage" / "Unsortiert" / "Zu löschen" / logo.name).exists()
    assert any(e["art"] == "aussortiert" for e in _ereignisse(repo))


def test_werbung_geht_nach_zu_loeschen(repo, monkeypatch):
    prospekt = _unsortiert(repo, "2026-10-08_angebot.pdf")
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text(
        "Ihr Gutschein: 20 % Rabatt auf alles. Jetzt bestellen! Newsletter abmelden", "pdftotext", 1))
    nachsortieren.lauf(True)
    assert (repo / "ablage" / "Unsortiert" / "Zu löschen" / prospekt.name).exists()


def test_werbung_mit_rechnungsnummer_bleibt():
    assert nachsortieren.werbung("Rabatt-Gutschein. Rechnungsnummer 4711, zu zahlen 20,00 €") == ""


def test_jetzt_sicherer_beleg_wird_abgelegt(repo, monkeypatch):
    datei = _unsortiert(repo)
    sha = verarbeiten._sha(datei)
    (repo / "arbeit" / "index.json").write_text(json.dumps({sha: {"pfad": "Unsortiert/" + datei.name, "status": "unsortiert"}}))
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung Pixelwerk 59,50 €", "pdftotext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnung())
    nachsortieren.lauf(False)
    assert datei.exists()
    nachsortieren.lauf(True)
    assert not datei.exists()
    abgelegt = list((repo / "ablage").rglob("2026-10-07_Pixelwerk_Software-Abo.pdf"))
    assert len(abgelegt) == 1 and "Unsortiert" not in abgelegt[0].parts
    index = json.loads((repo / "arbeit" / "index.json").read_text())
    assert index[sha]["status"] == "abgelegt"


def test_weiter_unsicher_bleibt_liegen_und_wird_einmal_gemeldet(repo, monkeypatch):
    datei = _unsortiert(repo)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Irgendein Schreiben ohne Angaben", "pdftotext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnung("niedrig"))
    monkeypatch.setattr("belege.dokumente.automatisch", lambda *_a, **_k: None)
    nachsortieren.lauf(True)
    nachsortieren.lauf(True)
    assert datei.exists()
    assert list((repo / "ablage" / "Unsortiert").glob("*.pdf")) == [datei]
    gemeldet = [e for e in _ereignisse(repo) if e["art"] == "unsortiert" and e["daten"].get("grund") == "nachsortieren"]
    assert len(gemeldet) == 1


def test_unklare_firma_entscheidet_der_lieferant(repo, monkeypatch):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8")
                    + '\n[[firma]]\nname = "Alpha GmbH"\nust_id = "DE111111111"\nbereich = "Alpha"\n'
                    '[[firma]]\nname = "Beta GmbH"\nust_id = "DE222222222"\nbereich = "Beta"\n', encoding="utf-8")
    datei = _unsortiert(repo)
    (repo / "arbeit" / "index.json").write_text(json.dumps({"alt": {"lieferant": "Pixelwerk", "firma": "Beta GmbH", "status": "abgelegt"}}))
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung Pixelwerk 59,50 €", "pdftotext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnung(firma="unklar"))
    nachsortieren.lauf(True)
    assert not datei.exists()
    assert list((repo / "ablage" / "Beta").rglob("*Pixelwerk*.pdf"))


def test_lieferant_bei_zwei_firmen_bleibt_unklar(repo, monkeypatch):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8")
                    + '\n[[firma]]\nname = "Alpha GmbH"\nust_id = "DE111111111"\nbereich = "Alpha"\n'
                    '[[firma]]\nname = "Beta GmbH"\nust_id = "DE222222222"\nbereich = "Beta"\n', encoding="utf-8")
    datei = _unsortiert(repo)
    (repo / "arbeit" / "index.json").write_text(json.dumps({
        "a": {"lieferant": "Pixelwerk", "firma": "Alpha GmbH", "status": "abgelegt"},
        "b": {"lieferant": "Pixelwerk", "firma": "Beta GmbH", "status": "abgelegt"}}))
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung Pixelwerk 59,50 €", "pdftotext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnung(firma="unklar"))
    nachsortieren.lauf(True)
    assert datei.exists()


def test_aus_geschaltet(repo):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("false = aus.\nan = true", "false = aus.\nan = false"),
                    encoding="utf-8")
    logo = _unsortiert(repo, "2026-10-08_image001.png", PNG)
    assert nachsortieren.lauf(True) == []
    assert logo.exists()


def test_tag_lauf_sortiert_vor_dem_bericht_nach(monkeypatch):
    from belege import takt

    gesehen = {}
    monkeypatch.setattr(takt, "_lauf", lambda args, schritte, sperre: gesehen.setdefault("schritte", schritte))
    takt.befehl_tag(None)
    assert gesehen["schritte"] == ("downloads", "nachsortieren", "bericht")


def test_bericht_nennt_aussortiertes():
    text, _ = bericht.text_und_betreff([{"art": "aussortiert", "text": "image001.png: Bild unter 20 KB", "daten": {}}])
    assert "Zu löschen" in text and "image001.png" in text



def test_bild_wird_fuer_die_werbepruefung_nur_lokal_gelesen(repo, monkeypatch):
    bild = _unsortiert(repo, "2026-10-08_banner.png", PNG + b"\0" * 30_000)
    werbetext = " ".join(["Sommer"] * 30) + " Gutschein Rabatt jetzt bestellen"
    monkeypatch.setattr(nachsortieren, "_bildtext", lambda _d: werbetext)

    def keine_cloud(*_a, **_k):
        raise AssertionError("Bild darf hier nicht über auslesen (Claude-Stufe) laufen")

    monkeypatch.setattr("belege.text.auslesen", keine_cloud)
    nachsortieren.lauf(True)
    assert (repo / "ablage" / "Unsortiert" / "Zu löschen" / bild.name).exists()


def test_cloud_sperre_haelt_den_lauf_nicht_an(repo, monkeypatch):
    from belege import kern

    _unsortiert(repo, "2026-10-08_image001.png", PNG)
    _unsortiert(repo, "2026-10-09_image002.png", PNG)

    def gesperrt(*_a, **_k):
        raise kern.CloudGesperrt("image ablegen", OSError(35, "Resource deadlock avoided"))

    monkeypatch.setattr(kern, "cloud_verschieben", gesperrt)
    ergebnisse = nachsortieren.lauf(True)
    assert [e.status for e in ergebnisse] == ["cloud_gesperrt", "cloud_gesperrt"]
