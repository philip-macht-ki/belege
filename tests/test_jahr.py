"""Tests für den Jahresabgleich (`belege jahr`, Modul bh7)."""
from __future__ import annotations

import argparse

from belege import jahr, kern


def _args(**werte):
    """Baut die kleinen Argumente für einen Jahreslauf."""
    grund = {
        "jahr": None,
        "anfragen": False,
        "paket": False,
        "uebergabe": False,
        "echt": False,
        "ziel": [],
    }
    grund.update(werte)
    return argparse.Namespace(**grund)


def _csv(pfad, zeilen, header="Buchungstag;Name;Verwendungszweck;Betrag"):
    pfad.write_text(header + "\n" + "\n".join(zeilen) + "\n", encoding="utf-8")


def test_standardjahr_januar_februar_ist_das_vorjahr(monkeypatch):
    """Ohne --jahr zählt im Januar und Februar noch das Vorjahr, sonst das laufende."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    berlin = ZoneInfo("Europe/Berlin")
    monkeypatch.setattr(kern, "jetzt", lambda: datetime(2027, 1, 15, tzinfo=berlin))
    assert jahr._jahr(None) == "2026"
    monkeypatch.setattr(kern, "jetzt", lambda: datetime(2027, 2, 28, tzinfo=berlin))
    assert jahr._jahr(None) == "2026"
    monkeypatch.setattr(kern, "jetzt", lambda: datetime(2027, 3, 1, tzinfo=berlin))
    assert jahr._jahr(None) == "2027"
    assert jahr._jahr("2030") == "2030"


def test_dubletten_ueber_mehrere_csv_dateien_nur_einmal(repo):
    """Dieselbe Buchung in zwei Kontoauszug-Dateien darf nicht doppelt zählen."""
    auszuege = repo / "auszuege"
    _csv(
        auszuege / "a.csv",
        ["01.01.2030;Pixelwerk GmbH;Abo;-9,90", "02.01.2030;Nur In A;Sonstiges;-5,00"],
    )
    _csv(
        auszuege / "b.csv",
        ["01.01.2030;Pixelwerk GmbH;Abo;-9,90", "03.01.2030;Nur In B;Sonstiges;-7,00"],
    )
    dateien = jahr._auszugsdateien()
    ergebnis = jahr._buchungen_dedupliziert(dateien, "2030-01")
    assert len(ergebnis) == 3
    namen = sorted(x["name"] for x in ergebnis)
    assert namen == ["Nur In A", "Nur In B", "Pixelwerk GmbH"]


def test_monate_ohne_buchung_heissen_kontoauszug_fehlt(repo, capsys):
    """Ein Monat ohne jede Buchung zählt nie als erledigt."""
    auszuege = repo / "auszuege"
    _csv(auszuege / "jan.csv", ["01.01.2030;Pixelwerk GmbH;Abo;-9,90"])
    kern.schreiben(
        repo / "arbeit/index.json",
        {
            "a": {
                "datum": "2030-01-01",
                "betrag": 9.90,
                "lieferant": "Pixelwerk",
                "art": "eingang",
                "bereich": "betrieb",
                "status": "abgelegt",
            }
        },
    )
    assert jahr.befehl(_args(jahr="2030")) == 0
    daten = kern.lesen(repo / "arbeit" / "jahr" / "2030" / "jahr.json")
    assert daten["2030-01"]["status"] == "ausgewertet"
    for monat_str in (f"2030-{n:02d}" for n in range(2, 13)):
        assert daten[monat_str]["status"] == "kontoauszug_fehlt"
    uebersicht = (repo / "arbeit" / "jahr" / "2030" / "uebersicht.md").read_text()
    assert "2030-02: Kontoauszug fehlt" in uebersicht
    assert "2030-01: 1 Buchungen" in uebersicht
    ausgabe = capsys.readouterr().out
    assert "11 ohne Kontoauszug" in ausgabe
    assert "1 mit Kontoauszug" in ausgabe


def test_ausgabezeile_im_format_aus_architektur(repo, capsys):
    """Die Ausgabezeile folgt genau dem Beispiel aus ARCHITEKTUR.md."""
    auszuege = repo / "auszuege"
    _csv(
        auszuege / "jan.csv",
        [
            "01.01.2030;Pixelwerk GmbH;Abo;-9,90",
            "01.01.2030;Kopierzentrum Schnell;Kopien;-34,00",
            "01.01.2030;Finanzamt;Steuer;-12,00",
        ],
    )
    kern.schreiben(
        repo / "arbeit/index.json",
        {
            "a": {
                "datum": "2030-01-01",
                "betrag": 9.90,
                "lieferant": "Pixelwerk",
                "art": "eingang",
                "bereich": "betrieb",
                "status": "abgelegt",
            }
        },
    )
    assert jahr.befehl(_args(jahr="2030")) == 0
    ausgabe = capsys.readouterr().out.strip()
    assert ausgabe == (
        "ok: 2030: 12 Monate, 1 mit Kontoauszug, 3 Buchungen, 1 zugeordnet, "
        "0 prüfen, 1 fehlen noch (34,00 €), 11 ohne Kontoauszug"
    )


def test_trockenlauf_schreibt_nur_jahresausgaben(repo, monkeypatch):
    """Ohne --echt verschiebt, kopiert und sendet der Jahreslauf nichts."""
    auszuege = repo / "auszuege"
    _csv(auszuege / "jan.csv", ["01.01.2030;Kopierzentrum Schnell;Kopien;-34,00"])
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            'weg = "mail"\nadresse = ""\nordner = ""',
            f'weg = "ordner"\nadresse = ""\nordner = "{repo / "uebergabe_ziel"}"',
        ),
        encoding="utf-8",
    )
    gesendet, entwuerfe = [], []

    def falsch_senden(*a, **k):
        gesendet.append(a)
        return kern.Ergebnis("ok")

    def falsch_entwurf(*a, **k):
        entwuerfe.append(a)
        return kern.Ergebnis("ok")

    monkeypatch.setattr("belege.senden.senden", falsch_senden)
    monkeypatch.setattr("belege.senden.entwurf", falsch_entwurf)
    code = jahr.befehl(_args(jahr="2030", anfragen=True, paket=True, uebergabe=True))
    assert code == 0
    assert gesendet == []
    assert not (repo / "arbeit" / "jahr" / "2030" / "paket").exists()
    assert not (repo / "uebergabe_ziel").exists()
    assert (repo / "arbeit" / "jahr" / "2030" / "uebersicht.md").exists()
    assert (repo / "arbeit" / "jahr" / "2030" / "fehlt_noch.csv").exists()


def test_paket_nur_mit_echt(repo):
    """`--paket` legt ohne --echt nichts an, mit --echt schon."""
    auszuege = repo / "auszuege"
    _csv(auszuege / "jan.csv", ["01.01.2030;Kopierzentrum Schnell;Kopien;-34,00"])
    jahr.befehl(_args(jahr="2030", paket=True))
    assert not (repo / "arbeit" / "jahr" / "2030" / "paket").exists()
    jahr.befehl(_args(jahr="2030", paket=True, echt=True))
    assert (repo / "arbeit" / "jahr" / "2030" / "paket").exists()
    assert (repo / "arbeit" / "jahr" / "2030" / "paket" / "uebersicht.md").exists()


def test_uebergabe_mail_ist_immer_nur_ein_entwurf(repo, monkeypatch):
    """Bei weg=mail entsteht auch mit --echt nie eine Sendung, nur ein Entwurf."""
    auszuege = repo / "auszuege"
    _csv(auszuege / "jan.csv", ["01.01.2030;Kopierzentrum Schnell;Kopien;-34,00"])
    toml = repo / "konfig" / "belege.toml"
    neu = 'adresse = "steuerberater@example.de"\nordner = ""'
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('adresse = ""\nordner = ""', neu),
        encoding="utf-8",
    )
    entwuerfe, gesendet = [], []

    def falsch_entwurf(an, betreff, text, anhaenge, echt):
        entwuerfe.append((an, betreff, echt))
        return kern.Ergebnis("ok" if echt else "nichts", "x")

    def falsch_senden(*a, **k):
        gesendet.append(a)
        return kern.Ergebnis("ok")

    monkeypatch.setattr("belege.senden.entwurf", falsch_entwurf)
    monkeypatch.setattr("belege.senden.senden", falsch_senden)

    jahr.befehl(_args(jahr="2030", uebergabe=True))
    assert entwuerfe[-1][2] is False
    gesehen = kern.lesen(repo / "arbeit" / "gesehen.json", {}) or {}
    assert "uebergabe_jahr" not in gesehen

    jahr.befehl(_args(jahr="2030", uebergabe=True, echt=True))
    an, betreff, echt = entwuerfe[-1]
    assert an == "steuerberater@example.de" and echt
    assert gesendet == []

    anzahl = len(entwuerfe)
    jahr.befehl(_args(jahr="2030", uebergabe=True, echt=True))
    assert len(entwuerfe) == anzahl


def test_zweite_uebergabe_ohne_nochmal_wird_abgelehnt(repo, monkeypatch, capsys):
    """Eine zweite Übergabe im selben Jahr braucht ausdrücklich "nochmal"."""
    auszuege = repo / "auszuege"
    _csv(auszuege / "jan.csv", ["01.01.2030;Kopierzentrum Schnell;Kopien;-34,00"])
    toml = repo / "konfig" / "belege.toml"
    neu = 'adresse = "steuerberater@example.de"\nordner = ""'
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('adresse = ""\nordner = ""', neu),
        encoding="utf-8",
    )
    entwuerfe = []
    monkeypatch.setattr(
        "belege.senden.entwurf",
        lambda *a, **k: entwuerfe.append(a) or kern.Ergebnis("ok"),
    )
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: kern.Ergebnis("ok"))

    jahr.befehl(_args(jahr="2030", uebergabe=True, echt=True))
    anzahl = len(entwuerfe)

    jahr.befehl(_args(jahr="2030", uebergabe=True, echt=True))
    assert len(entwuerfe) == anzahl
    assert "schon am" in capsys.readouterr().out

    jahr.befehl(_args(jahr="2030", uebergabe=True, echt=True, ziel=["nochmal"]))
    assert len(entwuerfe) == anzahl + 1


def test_uebergabe_ordner_kopiert_nur_mit_echt(repo):
    """Bei weg=ordner entsteht die Kopie erst mit --echt."""
    auszuege = repo / "auszuege"
    _csv(auszuege / "jan.csv", ["01.01.2030;Kopierzentrum Schnell;Kopien;-34,00"])
    toml = repo / "konfig" / "belege.toml"
    ziel_ordner = repo / "steuerberater_ordner"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            'weg = "mail"\nadresse = ""\nordner = ""',
            f'weg = "ordner"\nadresse = ""\nordner = "{ziel_ordner}"',
        ),
        encoding="utf-8",
    )
    jahr.befehl(_args(jahr="2030", uebergabe=True))
    assert not (ziel_ordner / "2030").exists()

    jahr.befehl(_args(jahr="2030", uebergabe=True, echt=True))
    assert (ziel_ordner / "2030").exists()
    assert (ziel_ordner / "2030" / "uebersicht.md").exists()


def test_ungueltiges_jahr_bricht_mit_fehler_ab(capsys):
    from types import SimpleNamespace

    from belege import jahr

    code = jahr.befehl(SimpleNamespace(jahr="20xx", paket=False, anfragen=False,
                                       uebergabe=False, echt=False, ziel=[]))
    assert code == 2
    assert "fehler" in capsys.readouterr().out
