"""Tests für die Ablage von Dokumenten, die kein Beleg sind (Modul bh8)."""
from __future__ import annotations

import argparse
import json
from datetime import date

from belege import dokumente, notfall
from belege.typen import Text


def _args(**werte):
    """Baut die kleinen Argumente für einen Dokumente- oder Fristenlauf."""
    grund = {"ziel": [], "echt": False, "tage": None}
    grund.update(werte)
    return argparse.Namespace(**grund)


def _text(inhalt: str) -> Text:
    return Text(inhalt, "klartext", 1)


def _index(repo) -> dict:
    return json.loads((repo / "arbeit" / "dokumente.json").read_text(encoding="utf-8"))


def test_ablagepfad_und_name_aus_stichwort(repo, monkeypatch):
    """Ein erkanntes Stichwort legt sauber unter Art/Gegenüber ab."""
    datei = repo / "mietvertrag.pdf"
    datei.write_bytes(b"pdf")
    monkeypatch.setattr(
        "belege.text.auslesen",
        lambda _: _text("Mietvertrag über Geschäftsräume. Laufzeit bis 31.12.2027."),
    )
    dokumente.befehl(_args(ziel=[str(datei)], echt=True))
    eintrag = next(iter(_index(repo).values()))
    assert eintrag["art"] == "vertrag"
    assert eintrag["abgelegt"] is True
    ziel = repo / "ablage" / eintrag["pfad"]
    assert ziel.exists()
    assert "/Vertrag/" in eintrag["pfad"].replace("\\", "/")
    assert eintrag["pfad"].startswith("Dokumente/")


def test_unsortiert_bei_unsicherheit(repo, monkeypatch):
    """Ohne bekanntes Stichwort bleibt die Sicherheit niedrig, es geht
    nach Unsortiert."""
    datei = repo / "raetsel.pdf"
    datei.write_bytes(b"pdf")
    monkeypatch.setattr(
        "belege.text.auslesen",
        lambda _: _text("Ein Text ganz ohne erkennbares Stichwort."),
    )
    dokumente.befehl(_args(ziel=[str(datei)], echt=True))
    eintrag = next(iter(_index(repo).values()))
    assert eintrag["abgelegt"] is False
    assert "/Unsortiert/" in eintrag["pfad"].replace("\\", "/")


def test_beleg_wandert_in_handy_ordner(repo, monkeypatch):
    """Eine erkennbare Rechnung geht nicht in die Dokumentablage, sondern
    zum Belegweg."""
    datei = repo / "rechnung.pdf"
    datei.write_bytes(b"pdf")
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _: _text("Rechnung Nr. 123 über 50,00 EUR.")
    )
    dokumente.befehl(_args(ziel=[str(datei)], echt=True))
    handy_dateien = list((repo / "handy").iterdir())
    assert len(handy_dateien) == 1
    dokumente_json = repo / "arbeit" / "dokumente.json"
    assert not dokumente_json.exists() or _index(repo) == {}


def test_dublette_wird_uebersprungen(repo, monkeypatch):
    """Dieselbe Datei ein zweites Mal führt zu keinem zweiten Eintrag."""
    datei = repo / "vertrag.pdf"
    datei.write_bytes(b"immer derselbe Inhalt")
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _: _text("Mietvertrag. Laufzeit bis 31.12.2027.")
    )
    dokumente.befehl(_args(ziel=[str(datei)], echt=True))
    # verhalten wie eine erneut vorgelegte Kopie
    datei.write_bytes(b"immer derselbe Inhalt")
    dokumente.befehl(_args(ziel=[str(datei)], echt=True))
    assert len(_index(repo)) == 1


def test_trockenlauf_aendert_nichts(repo, monkeypatch):
    """Ohne --echt verschiebt, legt und schreibt kein Befehl irgendetwas."""
    datei = repo / "vertrag.pdf"
    datei.write_bytes(b"pdf")
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _: _text("Mietvertrag. Laufzeit bis 31.12.2027.")
    )
    dokumente.befehl(_args(ziel=[str(datei)], echt=False))
    assert not (repo / "arbeit" / "dokumente.json").exists()
    assert list((repo / "ablage").rglob("*")) == []
    assert datei.exists()

    dokumente.befehl_fristen(_args(tage=3650, echt=False))
    assert not (repo / "ablage" / "Dokumente" / "fristen.ics").exists()

    notfall.befehl(_args(echt=False))
    assert not (repo / "ablage" / "Notfallordner").exists()


def test_monate_abzueglich_monatsende_und_schaltjahr():
    """Die Monatsrechnung klemmt auf den letzten gültigen Tag des Zielmonats."""
    assert dokumente.monate_abzueglich(date(2027, 3, 31), 1) == date(2027, 2, 28)
    assert dokumente.monate_abzueglich(date(2028, 2, 29), 12) == date(2027, 2, 28)
    assert dokumente.monate_abzueglich(date(2027, 12, 31), 3) == date(2027, 9, 30)
    assert dokumente.monate_abzueglich(date(2027, 3, 14), 1) == date(2027, 2, 14)


def test_berechne_fristen_ergaenzt_kuendigung_aus_ablauf():
    """Mit Laufzeitende und Monatsangabe rechnet ausschließlich der Code
    das Kündigungsdatum."""
    fristen = [
        {"art": "ablauf", "datum": "2027-12-31", "text": "Läuft bis 31.12.2027."},
        {
            "art": "kuendigung", "datum": None,
            "text": "Kündigungsfrist: 3 Monate zum Ende der Laufzeit.",
        },
    ]
    ergebnis = dokumente.berechne_fristen(fristen)
    kuendigung = next(f for f in ergebnis if f["art"] == "kuendigung")
    assert kuendigung["datum"] == "2027-09-30"


def test_berechne_fristen_bleibt_pruefen_ohne_sichere_angabe():
    """Ohne bekanntes Laufzeitende bleibt die Frist null und damit ein Prüffall."""
    fristen = [
        {
            "art": "kuendigung",
            "datum": None,
            "text": (
                "Kündigung mit einer Frist von 3 Monaten vor Ablauf möglich, "
                "jährliche Verlängerung."
            ),
        }
    ]
    ergebnis = dokumente.berechne_fristen(fristen)
    assert ergebnis[0]["datum"] is None


def test_ics_fold_schneidet_nie_mitten_in_ein_umlaut():
    """Eine lange Beschreibung mit Umlauten genau an der Faltgrenze darf nicht
    kaputtgehen (Regression: ein Fund im echten Lauf mit claude als Backend)."""
    text = (
        "Die Vorauszahlung in Höhe von 640,00 EUR ist am 10.12.2026 fällig, "
        "bitte fristgerecht überweisen."
    )
    zeile = dokumente._ics_fold(f"DESCRIPTION:{dokumente._ics_escape(text)}")
    entfaltet = zeile.replace("\r\n ", "")
    assert entfaltet == f"DESCRIPTION:{dokumente._ics_escape(text)}"
    for teilzeile in zeile.split("\r\n"):
        assert len(teilzeile.encode("utf-8")) <= 75


def test_ics_parsebar_und_uid_stabil_bei_zweitem_lauf(repo, monkeypatch):
    """Ein erneuter Lauf erzeugt dieselbe UID, damit der Kalender
    aktualisiert statt verdoppelt."""
    datei = repo / "vertrag.pdf"
    datei.write_bytes(b"pdf")
    monkeypatch.setattr(
        "belege.text.auslesen", lambda _: _text("Mietvertrag. Laufzeit bis 31.12.2027.")
    )
    dokumente.befehl(_args(ziel=[str(datei)], echt=True))
    index_pfad = repo / "arbeit" / "dokumente.json"
    index = _index(repo)
    sha = next(iter(index))
    index[sha]["fristen"] = [
        {
            "art": "kuendigung", "datum": "2027-09-30",
            "text": "Kündigungsfrist 3 Monate.",
        }
    ]
    index_pfad.write_text(json.dumps(index), encoding="utf-8")

    dokumente.befehl_fristen(_args(tage=3650, echt=True))
    ics_pfad = repo / "ablage" / "Dokumente" / "fristen.ics"
    inhalt_1 = ics_pfad.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in inhalt_1 and "END:VCALENDAR" in inhalt_1
    assert inhalt_1.count("BEGIN:VEVENT") == inhalt_1.count("END:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20270930" in inhalt_1
    uid_1 = next(z for z in inhalt_1.splitlines() if z.startswith("UID:"))

    dokumente.befehl_fristen(_args(tage=3650, echt=True))
    inhalt_2 = ics_pfad.read_text(encoding="utf-8")
    uid_2 = next(z for z in inhalt_2.splitlines() if z.startswith("UID:"))
    assert uid_1 == uid_2


def test_ics_zwei_fristen_gleicher_art_haben_eigene_uid_und_utc_stempel():
    from belege import dokumente

    fristen = [
        {"sha": "a" * 64, "art": "zahlung", "datum": "2026-12-10", "gegenueber": "Amt", "titel": "Bescheid", "text": "erste"},
        {"sha": "a" * 64, "art": "zahlung", "datum": "2027-03-10", "gegenueber": "Amt", "titel": "Bescheid", "text": "zweite"},
    ]
    text = dokumente.baue_ics(fristen, 28)
    uids = [z for z in text.splitlines() if z.startswith("UID:")]
    assert len(uids) == 2 and len(set(uids)) == 2
    stempel = [z for z in text.splitlines() if z.startswith("DTSTAMP:")][0]
    assert stempel.endswith("Z")
