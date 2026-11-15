"""Kalender-Zusätze des Postfach-Agenten, ohne Netz oder echten Kalender."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from belege import kern, postfach_agent as aufraeumen
from test_aufraeumen import _aktionen, _args, _einschalten, _mail, _regeln


@pytest.fixture(autouse=True)
def kalender_uhr(monkeypatch):
    monkeypatch.setattr(kern, "jetzt", lambda: datetime(2026, 11, 15, 10, 0, tzinfo=kern.zone()))


def test_kalender_regeln_lesen_und_titel_mit_komma_behalten(tmp_path):
    datei = tmp_path / "regeln.md"
    datei.write_text("- von: lohn@firma.example -> kalender: Löhne überweisen, 20.\n"
                     "- von: a@b.example -> entwurf: Danke, kommt am 20. und kalender: Löhne, bezahlen, 20.\n"
                     "- sonst -> archivieren und kalender: Ablage, morgen\n", encoding="utf-8")
    regeln, fehler = aufraeumen.regeln(datei)
    assert not fehler
    assert [(r["aktion"], r["wert"], r["kalender_titel"], r["kalender_tag"]) for r in regeln] == [
        ("kalender", "", "Löhne überweisen", "20."),
        ("entwurf", "Danke, kommt am 20.", "Löhne, bezahlen", "20."),
        ("archivieren", "", "Ablage", "morgen"),
    ]
    regel, fehler = aufraeumen.regeln(datei)
    assert not fehler and regel[1]["kalender_titel"] == "Löhne, bezahlen"


@pytest.mark.parametrize("regel", [
    "- von: a -> kalender: , 20.", "- von: a -> kalender: Löhne",
    "- von: a -> kalender: Löhne, übermorgen irgendwann", "- von: a -> kalender: Löhne, 31.02.",
    "- gelesen -> archivieren und kalender: X, 20.",
])
def test_kalender_regel_fehler_haben_zeilennummer(tmp_path, regel):
    datei = tmp_path / "regeln.md"
    datei.write_text("# Kopf\n\n" + regel + "\n", encoding="utf-8")
    _, fehler = aufraeumen.regeln(datei)
    assert len(fehler) == 1 and fehler[0].startswith("Zeile 3")


@pytest.mark.parametrize("eingabe, erwartet", [
    ("15.", "2026-11-15"), ("14.", "2026-12-14"), ("31.", "2026-11-30"),
    ("20.12.", "2026-12-20"), ("10.11.", "2027-11-10"),
    ("15.12.2026", "2026-12-15"), ("2026-12-15", "2026-12-15"),
    ("morgen", "2026-11-16"), ("in 3 tagen", "2026-11-18"),
])
def test_kalendertag_berechnen(eingabe, erwartet):
    assert aufraeumen._kalendertag(eingabe).isoformat() == erwartet


def test_kalender_versendet_ics_nach_entwurf(repo, monkeypatch):
    gesendet, entwuerfe = [], []
    monkeypatch.setattr("belege.senden.entwurf", lambda *a, **k: entwuerfe.append(a) or kern.Ergebnis("ok", "Entwurf angelegt"))
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a) or kern.Ergebnis("ok", "gesendet"))
    _einschalten(repo)
    _regeln(repo, "- von: lohn@firma.example -> entwurf: Danke und kalender: Löhne überweisen, 20.")
    _mail(repo, "lohn@firma.example", "Löhne", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    assert aufraeumen.laufen(_args(echt=True)) == 0
    assert len(entwuerfe) == len(gesendet) == 1
    an, betreff, _, anhaenge, echt = gesendet[0][:5]
    assert an == "mara@studio-beispiel.example" and betreff == "Termin: Löhne überweisen am 20.11.2026" and echt
    ics = anhaenge[0].read_bytes()
    assert b"BEGIN:VCALENDAR\r\n" in ics and b"METHOD:PUBLISH\r\n" in ics
    assert b"DTSTART;VALUE=DATE:20261120\r\n" in ics and b"DTEND;VALUE=DATE:20261121\r\n" in ics
    assert "SUMMARY:Löhne überweisen\r\n".encode() in ics and b"BEGIN:VALARM\r\n" in ics
    assert b"\n" not in ics.replace(b"\r\n", b"") and all(len(zeile) <= 75 for zeile in ics.split(b"\r\n") if zeile)


def test_ics_maskiert_titel_und_uid_ist_stabil(repo):
    mail = {"id": "m1", "von": "a@b.example", "betreff": "Frage"}
    uid1, _, datei1 = aufraeumen._termindatei("konto", mail, "Löhne; Mai, Juni", "20.")
    uid2, _, datei2 = aufraeumen._termindatei("konto", mail, "Löhne; Mai, Juni", "20.")
    assert uid1 == uid2 and datei1[1] == datei2[1]
    assert "SUMMARY:Löhne\\; Mai\\, Juni" in datei1[1]


def test_kalender_uid_merker_verhindert_zweiten_versand(repo, monkeypatch):
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a) or kern.Ergebnis("ok", "gesendet"))
    _einschalten(repo)
    _regeln(repo, "- sonst -> kalender: Löhne, 20.")
    _mail(repo, "lohn@firma.example", "Löhne", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    aufraeumen.laufen(_args(echt=True))
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {})
    gesehen.pop("aufraeumen:geschaeft", None)
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    aufraeumen.laufen(_args(echt=True))
    assert len(gesendet) == 1


@pytest.mark.parametrize("antwort", [kern.Ergebnis("fehler", "SMTP kaputt"), RuntimeError("SMTP kaputt")])
def test_kalenderfehler_laesst_hauptaktion_gelten(repo, monkeypatch, antwort):
    def senden(*_a, **_k):
        if isinstance(antwort, Exception):
            raise antwort
        return antwort
    monkeypatch.setattr("belege.senden.senden", senden)
    _einschalten(repo)
    _regeln(repo, "- sonst -> archivieren und kalender: Ablage, 20.")
    _mail(repo, "lohn@firma.example", "Löhne", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    assert aufraeumen.laufen(_args(echt=True)) == 0
    assert _aktionen(repo) and "Termin nicht verschickt" in (repo / "arbeit" / "aufraeumen.jsonl").read_text(encoding="utf-8")


def test_kalender_trocken_erstellt_und_senddet_nichts(repo, monkeypatch, capsys):
    monkeypatch.setattr("belege.senden.senden", lambda *_a, **_k: pytest.fail("darf nicht senden"))
    _einschalten(repo)
    _regeln(repo, "- sonst -> kalender: Löhne, 20.")
    _mail(repo, "lohn@firma.example", "Löhne", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    assert aufraeumen.laufen(_args()) == 0
    assert "würde Termin Löhne am 20.11.2026 verschicken" in capsys.readouterr().out
    assert not (repo / "arbeit" / "termine").exists()


def test_kalender_mit_privatem_bericht_verschweigt_maildaten(repo, monkeypatch):
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a) or kern.Ergebnis("ok", "gesendet"))
    _einschalten(repo)
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("betreffe_im_bericht = true", "betreffe_im_bericht = false"), encoding="utf-8")
    _regeln(repo, "- sonst -> kalender: Löhne, 20.")
    _mail(repo, "voll@geheim.example", "Streng geheim", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    aufraeumen.laufen(_args(echt=True))
    assert "voll@geheim.example" not in gesendet[0][2] and "Streng geheim" not in gesendet[0][2] and "Streng geheim" not in gesendet[0][1]


def test_regel_ohne_kalender_sendet_nichts(repo, monkeypatch):
    monkeypatch.setattr("belege.senden.senden", lambda *_a, **_k: pytest.fail("darf nicht senden"))
    _einschalten(repo)
    _regeln(repo, "- sonst -> archivieren")
    _mail(repo, "a@b.example", "A", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    assert aufraeumen.laufen(_args(echt=True)) == 0


def test_nicht_freigegebene_adresse_ergibt_entwurf_und_keinen_zweiten(repo, monkeypatch):
    """senden legt für eine nicht freigegebene Adresse nur einen Entwurf an; das steht dann auch so da."""
    aufrufe = []
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: aufrufe.append(a) or kern.Ergebnis(
        "befund", "ich@firma.example ist nicht freigegeben; deshalb entstand ein Entwurf."))
    _einschalten(repo)
    _regeln(repo, "- sonst -> kalender: Löhne, 20.")
    _mail(repo, "lohn@firma.example", "Löhne", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    aufraeumen.laufen(_args(echt=True))
    protokoll = (repo / "arbeit" / "aufraeumen.jsonl").read_text(encoding="utf-8")
    assert "liegt als Entwurf bereit" in protokoll and "Termin nicht verschickt" not in protokoll
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {})
    gesehen.pop("aufraeumen:geschaeft", None)
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    aufraeumen.laufen(_args(echt=True))
    assert len(aufrufe) == 1


def test_gesperrter_anhang_gilt_nicht_als_verschickt(repo, monkeypatch):
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: kern.Ergebnis("befund", "Nicht gesendet: Anhang gesperrt"))
    _einschalten(repo)
    _regeln(repo, "- sonst -> kalender: Löhne, 20.")
    _mail(repo, "lohn@firma.example", "Löhne", datum="Sun, 15 Nov 2026 08:00:00 +0100")
    aufraeumen.laufen(_args(echt=True))
    assert "Termin nicht verschickt" in (repo / "arbeit" / "aufraeumen.jsonl").read_text(encoding="utf-8")
    assert not (kern.lesen(kern.pfad("arbeit", "termine.json"), {}) or {}).get("uids")


def test_kalender_ohne_titel_und_tag_ist_keine_gueltige_aktion(tmp_path):
    datei = tmp_path / "regeln.md"
    datei.write_text("- von: a -> kalender\n- von: b -> archivieren und kalender\n", encoding="utf-8")
    regeln, fehler = aufraeumen.regeln(datei)
    assert not regeln and len(fehler) == 2


def test_echte_ics_datei_geht_durch_die_anhangspruefung(repo):
    """Kein gepatchtes senden: Die erzeugte Datei muss die Anhangsprüfung wirklich bestehen."""
    from belege.senden import _sichere_anhaenge

    _, _, (name, inhalt) = aufraeumen._termindatei("geschaeft", {"id": "m1", "von": "a@b.example", "betreff": "Löhne"}, "Löhne überweisen", "20.")
    datei = repo / "arbeit" / "termine" / name
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(inhalt, encoding="utf-8", newline="")
    assert _sichere_anhaenge([datei])[0] is True
    roh = datei.read_bytes()
    assert roh.count(b"\r\n") == roh.count(b"\n") and all(len(z) <= 75 for z in roh.split(b"\r\n"))
