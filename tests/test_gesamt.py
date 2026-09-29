"""Gesamtlauf mit dem Musterbetrieb, ohne Modell (Regeln + Rückfall).

Prüft die Zusagen des Kurses: Belege landen am richtigen Ort, Downloads, die
keine Belege sind, bleiben liegen, nichts wird gelöscht, ein zweiter Lauf ändert
nichts, trocken ändert gar nichts.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from belege import kern, text
from belege.cli import main

REGELN = '''
ausschluss = ["newsletter@"]

[[absender]]
muster = "pixelwerk"
lieferant = "Pixelwerk Software GmbH"
beschreibung = "Software-Abo"

[[absender]]
muster = "netzfunk"
lieferant = "Netzfunk"
beschreibung = "Telefon"

[[absender]]
muster = "hostingwerk"
lieferant = "Hostingwerk"
beschreibung = "Hosting"

[[absender]]
muster = "zahnarzt"
lieferant = "Zahnarztpraxis Beispiel"
bereich = "privat"
art = "eingang"

[zahlungsabwickler]
domains = ["zahlfix.example"]

[monat]
ohne_beleg = ["Finanzamt"]
'''


def _alle_dateien(*ordner: Path) -> int:
    return sum(1 for o in ordner for p in o.rglob("*") if p.is_file())


@pytest.fixture
def muster(repo):
    assert main(["beispiel"]) == 0
    erzeugt = repo / "beispiel" / "erzeugt"
    for name in ("handy", "downloads"):
        for datei in (erzeugt / name).iterdir():
            shutil.copy2(datei, repo / name / datei.name)
    import os
    import time

    alt = time.time() - 3600  # Downloads müssen älter als zehn Minuten sein
    for datei in (repo / "downloads").iterdir():
        os.utime(datei, (alt, alt))
    (repo / "konfig" / "regeln.toml").write_text(REGELN, encoding="utf-8")
    return repo


def test_trocken_aendert_nichts(muster):
    vorher = sorted(p.name for p in (muster / "downloads").iterdir())
    assert main(["takt"]) == 0
    assert main(["tag"]) == 0
    assert not (muster / "arbeit" / "index.json").exists()
    assert not (muster / "arbeit" / "ereignisse").exists()
    assert not any((muster / "ablage").rglob("*.*"))
    assert sorted(p.name for p in (muster / "downloads").iterdir()) == vorher


def test_echt_legt_richtig_ab_und_loescht_nichts(muster):
    ablage, downloads, handy = muster / "ablage", muster / "downloads", muster / "handy"
    postfach = muster / "beispiel" / "erzeugt" / "postfach"
    mails_vorher = sorted(p.name for p in postfach.iterdir())
    dateien_vorher = _alle_dateien(downloads, handy)

    assert main(["takt", "--echt"]) == 0
    assert main(["tag", "--echt"]) == 0

    abgelegt = [p.relative_to(ablage).as_posix() for p in ablage.rglob("*.*")]
    def liegt(teil: str, ordner: str) -> bool:
        return any(ordner in pfad and teil in pfad for pfad in abgelegt)

    assert liegt("Pixelwerk", "Betrieb/"), abgelegt
    assert liegt("Netzfunk", "/Eingang/"), abgelegt
    assert liegt("Hostingwerk", "/Eingang/"), abgelegt
    assert liegt("Schriftwerk", "/Eingang/"), abgelegt  # Anzeigename, nicht Zahlfix
    assert not liegt("Zahlfix", ""), abgelegt
    assert liegt("Blatt", "Rechnung.xml") or any(p.endswith(".xml") for p in abgelegt), abgelegt
    assert any(p.endswith(".xml") for p in abgelegt) and sum(p.endswith(".pdf") and "Blatt" in p
                                                           for p in abgelegt) >= 1, abgelegt
    assert liegt("Zahnarzt", "Privat/"), abgelegt
    assert not liegt("Frühjahr", "") and not liegt("Angebot", ""), abgelegt

    # Downloads: Nicht-Belege und Unfertiges bleiben, das Duplikat bleibt und wird gemeldet
    uebrig = sorted(p.name for p in downloads.iterdir())
    assert "anleitung.pdf" in uebrig
    assert "urlaub.jpg" in uebrig
    assert "rechnung.pdf.crdownload" in uebrig
    assert "pixelwerk-duplicate.pdf" in uebrig
    assert "hostingwerk.pdf" not in uebrig
    ereignisse = "".join(p.read_text() for p in (muster / "arbeit" / "ereignisse").glob("*.jsonl"))
    assert '"doppelt"' in ereignisse

    # Nichts gelöscht: was aus Downloads/Handy fehlt, liegt jetzt in der Ablage
    assert _alle_dateien(downloads, handy) + len(abgelegt) >= dateien_vorher
    assert sorted(p.name for p in postfach.iterdir()) == mails_vorher

    # Kassenbons: mit Apple Vision abgelegt, ohne nach Unsortiert
    if text.stufen_verfuegbar().get("vision"):
        assert not list(handy.glob("*.jpg"))

    # Zweiter Lauf: nichts Neues
    index = kern.lesen(muster / "arbeit" / "index.json")
    assert main(["takt", "--echt"]) == 0
    assert main(["tag", "--echt"]) == 0
    assert kern.lesen(muster / "arbeit" / "index.json") == index


def test_monat_mit_musterbetrieb(muster, capsys):
    shutil.copy2(muster / "beispiel" / "erzeugt" / "kontoauszug.csv", muster / "auszuege" / "konto.csv")
    assert main(["takt", "--echt"]) == 0
    capsys.readouterr()
    assert main(["monat"]) == 0
    ausgabe = capsys.readouterr().out
    assert "fehlen noch" in ausgabe
    monat = next((muster / "arbeit" / "monat").iterdir())
    klaerung = (monat / "klaerung.md").read_text(encoding="utf-8")
    assert "Kopierzentrum Schnell" in klaerung
    assert "Finanzamt" not in klaerung
