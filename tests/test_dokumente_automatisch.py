"""Tests für die Dokumentweiche im Belegweg (ab 1.9.0)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from belege import bericht, kern, verarbeiten
from belege.typen import Einordnung, Fund, Text

VERTRAG = (
    "Telefonica Germany\nMobilfunkvertrag Nr. 4711\nVertragsbeginn 01.10.2026\n"
    "Mindestlaufzeit 24 Monate. Der Vertrag läuft bis 30.09.2028."
)


def _kein_beleg(fund, text, **_):
    return Einordnung(False, "sonstige", "betrieb", None, "Unbekannt", "Dokument", None,
                      "EUR", "niedrig", "Kein Beleg.", "rueckfall")


def _dokument(art="vertrag", sicherheit=0.9, fristen=None):
    def einordnen(text, dateiname, nur_lokal=False):
        einordnen.nur_lokal = nur_lokal
        return {"art": art, "bereich": "privat", "gegenueber": "Telefonica", "titel": "Handyvertrag",
                "datum": "2026-10-01", "fristen": fristen or [], "sicherheit": sicherheit,
                "grund": "Test."}
    einordnen.nur_lokal = None
    return einordnen


@pytest.fixture
def weg(repo, monkeypatch):
    """Belegurteil: kein Beleg; Text aus dem Test."""
    monkeypatch.setattr("belege.einordnen.einordnen", _kein_beleg)

    def text_setzen(inhalt, stufe="klartext"):
        monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text(inhalt, stufe, 1))

    text_setzen(VERTRAG)
    return text_setzen


def _ereignisse(art):
    return [e for e in kern.ereignisse() if e["art"] == art]


def _dokindex(repo):
    pfad = repo / "arbeit" / "dokumente.json"
    return json.loads(pfad.read_text()) if pfad.exists() else {}


def test_handy_vertrag_landet_in_dokumente(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(
        fristen=[{"art": "ablauf", "datum": "2028-09-30", "text": "läuft bis 30.09.2028"}]))
    datei = repo / "handy" / "scan.pdf"
    datei.write_bytes(b"vertrag")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 28), verschieben=True), True)
    assert ergebnis.status == "ok", ergebnis.meldung
    assert ergebnis.daten["status"] == "dokument"
    ziel = repo / "ablage" / "Dokumente" / "Vertrag" / "Telefonica" / "2026-10-01_Handyvertrag.pdf"
    assert ziel.exists() and not datei.exists()
    eintrag = next(iter(_dokindex(repo).values()))
    assert eintrag["quelle"] == "handy" and eintrag["fristen"][0]["datum"] == "2028-09-30"
    assert not (repo / "ablage" / "Unsortiert").exists()
    assert not (repo / "arbeit" / "index.json").exists()
    assert _ereignisse("dokument")[0]["daten"]["frist"]["datum"] == "2028-09-30"


def test_postfach_vertrag_wird_kopiert(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())
    datei = repo / "anhang.pdf"
    datei.write_bytes(b"mail-vertrag")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 28), mail={"id": "1", "konto": "k"})
    assert verarbeiten.verarbeite(fund, True).status == "ok"
    assert datei.exists()
    assert list((repo / "ablage" / "Dokumente" / "Vertrag").rglob("*.pdf"))


def test_postfach_newsletter_fragt_kein_zweites_urteil(repo, weg, monkeypatch):
    def nie(*_a, **_k):
        raise AssertionError("kein Dokumenturteil für Newsletter")

    monkeypatch.setattr("belege.dokumente.dokument_einordnen", nie)
    weg("Ihr Vertrag-Vorteil im Oktober! Hier abmelden.")
    datei = repo / "news.pdf"
    datei.write_bytes(b"news")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 28), mail={"id": "1", "konto": "k"})
    assert verarbeiten.verarbeite(fund, True).status == "nichts"
    assert not (repo / "ablage" / "Dokumente").exists()


def test_postfach_nimmt_nur_klare_arten(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(art="sonstiges"))
    datei = repo / "anhang.pdf"
    datei.write_bytes(b"sonstiges")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 28), mail={"id": "1", "konto": "k"})
    assert verarbeiten.verarbeite(fund, True).status == "nichts"
    assert _dokindex(repo) == {}


def test_postfach_bild_bleibt_unberuehrt(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())
    datei = repo / "foto.jpg"
    datei.write_bytes(b"bild")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 28), mail={"id": "1", "konto": "k"})
    assert verarbeiten.verarbeite(fund, True).status == "nichts"


def test_downloads_unsicher_bleibt_liegen(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(sicherheit=0.5))
    datei = repo / "downloads" / "vertrag.pdf"
    datei.write_bytes(b"dl")
    fund = Fund(datei, "downloads", datei.name, date(2026, 10, 28), verschieben=True)
    assert verarbeiten.verarbeite(fund, True).status == "nichts"
    assert datei.exists()


def test_downloads_klarer_vertrag_wird_verschoben(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(art="versicherung"))
    datei = repo / "downloads" / "police.pdf"
    datei.write_bytes(b"police")
    fund = Fund(datei, "downloads", datei.name, date(2026, 10, 28), verschieben=True)
    assert verarbeiten.verarbeite(fund, True).status == "ok"
    assert not datei.exists()
    assert list((repo / "ablage" / "Dokumente" / "Versicherung").rglob("*.pdf"))


def test_scan_unsicher_geht_nach_unsortiert(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(sicherheit=0.4))
    datei = repo / "brief.pdf"
    datei.write_bytes(b"scan")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "scan", datei.name, date(2026, 10, 28)), True)
    assert ergebnis.daten["status"] == "unsortiert"
    assert _dokindex(repo) == {}


def test_vertrauliches_nur_lokal_und_ohne_namen_im_bericht(repo, weg, monkeypatch):
    from belege.vertraulich import Urteil

    einordnen = _dokument(art="gesundheit")
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", einordnen)
    monkeypatch.setattr("belege.vertraulich.pruefen", lambda *_a, **_k: Urteil(True, "Gesundheit"))
    datei = repo / "brief.pdf"
    datei.write_bytes(b"arzt")
    assert verarbeiten.verarbeite(Fund(datei, "scan", datei.name, date(2026, 10, 28)), True).status == "ok"
    assert einordnen.nur_lokal is True
    assert next(iter(_dokindex(repo).values()))["vertraulich"] is True
    text, _ = bericht.text_und_betreff(_ereignisse("dokument"))
    assert "Telefonica" not in text and "Handyvertrag" not in text
    assert "Dokumente/Gesundheit" in text


def test_ohne_text_keine_weiche(repo, weg, monkeypatch):
    def nie(*_a, **_k):
        raise AssertionError("ohne Text kein Dokumenturteil")

    monkeypatch.setattr("belege.dokumente.dokument_einordnen", nie)
    weg("", stufe="ohne_text")
    datei = repo / "handy" / "foto.pdf"
    datei.write_bytes(b"leer")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 28), verschieben=True), True)
    assert ergebnis.daten["status"] == "unsortiert"


def test_schalter_aus(repo, weg, monkeypatch):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text().replace("automatisch = true", "automatisch = false"))
    assert "automatisch = false" in toml.read_text()
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())
    datei = repo / "handy" / "vertrag.pdf"
    datei.write_bytes(b"aus")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 28), verschieben=True), True)
    assert ergebnis.daten["status"] == "unsortiert"


def test_trocken_aendert_nichts(repo, weg, monkeypatch, capsys):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())
    datei = repo / "handy" / "vertrag.pdf"
    datei.write_bytes(b"trocken")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 28), verschieben=True), False)
    assert ergebnis.status == "nichts" and datei.exists()
    assert "würde als Dokument ablegen" in capsys.readouterr().out
    assert _dokindex(repo) == {} and not _ereignisse("dokument")


def test_dublette_eines_dokuments(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())
    erste = repo / "handy" / "a.pdf"
    erste.write_bytes(b"gleich")
    verarbeiten.verarbeite(Fund(erste, "handy", erste.name, date(2026, 10, 28), verschieben=True), True)
    zweite = repo / "anhang.pdf"
    zweite.write_bytes(b"gleich")
    fund = Fund(zweite, "postfach", zweite.name, date(2026, 10, 28), mail={"id": "2", "konto": "k"})
    ergebnis = verarbeiten.verarbeite(fund, True)
    assert ergebnis.status == "nichts" and "Dokumente/Vertrag" in ergebnis.meldung
    assert len(list((repo / "ablage" / "Dokumente").rglob("*.pdf"))) == 1


def test_bericht_nennt_dokument_mit_frist():
    liste = [{"art": "dokument", "text": "x", "daten": {
        "dokumentart": "behoerde", "gegenueber": "Finanzamt Koblenz", "titel": "Vorauszahlung",
        "frist": {"art": "zahlung", "datum": "2026-12-10"}, "vertraulich": False}}]
    text, betreff = bericht.text_und_betreff(liste)
    assert "Dokumente abgelegt (1)" in text
    assert "Behörde: Finanzamt Koblenz, Vorauszahlung (Zahlung bis 10.12.2026)" in text
    assert "1 Dokumente" in betreff


def test_vertrauliche_dublette_nennt_nur_den_ordner(repo, weg, monkeypatch):
    from belege.vertraulich import Urteil

    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(art="gesundheit"))
    monkeypatch.setattr("belege.vertraulich.pruefen", lambda *_a, **_k: Urteil(True, "Gesundheit"))
    erste = repo / "Befund_Dr_Mueller.pdf"
    erste.write_bytes(b"arztbrief")
    verarbeiten.verarbeite(Fund(erste, "scan", erste.name, date(2026, 10, 28)), True)
    zweite = repo / "downloads" / "Befund_Dr_Mueller_Kopie.pdf"
    zweite.write_bytes(b"arztbrief")
    ergebnis = verarbeiten.verarbeite(Fund(zweite, "downloads", zweite.name, date(2026, 10, 28), verschieben=True), True)
    assert ergebnis.status == "nichts"
    text, _ = bericht.text_und_betreff(kern.ereignisse())
    assert "Telefonica" not in text and "Handyvertrag" not in text and "Mueller" not in text
    assert "Dokumente/Gesundheit" in text


def test_vertraulich_gescheitert_ohne_dateinamen(repo, weg, monkeypatch):
    from belege.vertraulich import Urteil

    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument(art="gesundheit"))
    monkeypatch.setattr("belege.vertraulich.pruefen", lambda *_a, **_k: Urteil(True, "Gesundheit"))

    def kaputt(*_a, **_k):
        raise OSError("Platte voll")

    monkeypatch.setattr("belege.dokumente.shutil.move", kaputt)
    datei = repo / "handy" / "Befund_Dr_Mueller.pdf"
    datei.write_bytes(b"geheim")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 28), verschieben=True), True)
    assert ergebnis.status == "fehler" and "Mueller" not in ergebnis.meldung
    assert datei.exists() and _dokindex(repo) == {}
    text, _ = bericht.text_und_betreff(kern.ereignisse())
    assert "Mueller" not in text


def test_scheitert_das_verschieben_bleibt_nichts_im_verzeichnis(repo, weg, monkeypatch):
    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())

    def kaputt(*_a, **_k):
        raise OSError("Platte voll")

    monkeypatch.setattr("belege.dokumente.shutil.move", kaputt)
    datei = repo / "handy" / "vertrag.pdf"
    datei.write_bytes(b"voll")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 28), verschieben=True), True)
    assert ergebnis.status == "fehler"
    assert datei.exists() and _dokindex(repo) == {}


def test_postfach_dokument_markiert_mail_als_erledigt(repo, weg, monkeypatch):
    from argparse import Namespace

    from belege import quellen, takt

    monkeypatch.setattr("belege.dokumente.dokument_einordnen", _dokument())
    datei = repo / "anhang.pdf"
    datei.write_bytes(b"takt")
    fund = Fund(datei, "postfach", datei.name, date(2026, 10, 28), mail={"id": "m1", "konto": "geschaeft"})
    monkeypatch.setattr(takt, "_funde", lambda *_a: [fund])
    monkeypatch.setattr(takt, "_postfach_konten", lambda *_a: ["geschaeft"])
    erledigt = []
    monkeypatch.setattr(quellen, "mail_erledigt", lambda konto, mail_id, echt: erledigt.append(mail_id))
    monkeypatch.setattr(quellen, "lauf_abschliessen", lambda *_a: None)
    ergebnisse = takt.quelle_abarbeiten("postfach", Namespace(echt=True))
    assert ergebnisse[0].status == "ok"
    assert erledigt == ["m1"]
