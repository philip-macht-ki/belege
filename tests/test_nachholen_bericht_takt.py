"""Verhalten beim Nachholen von Tagesbericht und Kalenderläufen."""
from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta

from belege import bericht, kern, monat, posten, takt


def _args():
    return Namespace(echt=True, tage=None, konto=None)


def _uhr(monkeypatch, zeit):
    monkeypatch.setattr(kern, "jetzt", lambda: zeit[0])
    monkeypatch.setattr(bericht, "jetzt", lambda: zeit[0])
    monkeypatch.setattr(takt, "jetzt", lambda: zeit[0])


def _ereignis(zeit, name):
    kern.ereignis("abgelegt", name, datum=zeit.date().isoformat(), lieferant=name, betrag=1)


def _uebergabe_einrichten(repo):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'adresse = ""\nordner = ""', 'adresse = "steuer@example.com"\nordner = ""'), encoding="utf-8")


def _posten_einrichten(repo):
    kern.schreiben(repo / "arbeit" / "posten.json", {})


def test_1_tagesbericht_holt_alle_verpassten_tage_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 12, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    for monat, tag in ((10, 29), (10, 30), (10, 31), (11, 1), (11, 2), (11, 3), (11, 4)):
        zeit[0] = datetime(2026, monat, tag, 12, tzinfo=kern.zone())
        _ereignis(zeit[0], f"tag-{monat}-{tag}")
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"bericht": "2026-10-29T23:00:00+01:00"})
    zeit[0] = datetime(2026, 11, 4, 12, tzinfo=kern.zone())
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a: gesendet.append(a) or kern.Ergebnis("ok"))

    assert bericht.befehl(_args()) == 0

    assert len(gesendet) == 1
    text = gesendet[0][2]
    assert "Zusammenfassung vom 29.10.2026 bis 04.11.2026" in text
    assert all(f"tag-{monat}-{tag}" in text for monat, tag in ((10, 30), (10, 31), (11, 1), (11, 2), (11, 3), (11, 4)))
    assert "tag-10-29" not in text


def test_2_tagesbericht_von_gestern_bleibt_bei_gestern_und_heute(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 12, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    for tag in (2, 3, 4):
        zeit[0] = datetime(2026, 11, tag, 12, tzinfo=kern.zone())
        _ereignis(zeit[0], f"tag-{tag}")
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"bericht": "2026-11-03T00:00:00+01:00"})
    zeit[0] = datetime(2026, 11, 4, 12, tzinfo=kern.zone())
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a: gesendet.append(a) or kern.Ergebnis("ok"))

    assert bericht.befehl(_args()) == 0

    text = gesendet[0][2]
    assert "tag-3" in text and "tag-4" in text and "tag-2" not in text
    assert "Zusammenfassung vom" not in text


def test_3_tagesbericht_begrenzt_den_zeitraum_auf_dreissig_tage(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 12, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    for tag, name in ((4, "zu-alt"), (5, "grenze")):
        zeit[0] = datetime(2026, 10, tag, 14, tzinfo=kern.zone())
        _ereignis(zeit[0], name)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"bericht": "2026-08-06T12:00:00+02:00"})
    zeit[0] = datetime(2026, 11, 4, 12, tzinfo=kern.zone())
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a: gesendet.append(a) or kern.Ergebnis("ok"))

    assert bericht.befehl(_args()) == 0

    assert "grenze" in gesendet[0][2] and "zu-alt" not in gesendet[0][2]
    assert "Zusammenfassung vom 05.10.2026 bis 04.11.2026" in gesendet[0][2]


def test_4_takt_holt_den_verpassten_tageslauf_nur_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-10", "lauf": {"tag": "2026-11-02T21:00:00+01:00", "monat": zeit[0].isoformat(), "posten": zeit[0].isoformat()}})
    aufrufe = []
    monkeypatch.setattr(takt, "_lauf", lambda *a: aufrufe.append(a[1]) or True)

    takt._nachholen(_args())
    zeit[0] = datetime(2026, 11, 4, 10, 45, tzinfo=kern.zone())
    takt._nachholen(_args())

    assert aufrufe == [("downloads", "nachsortieren", "bericht")]


def test_4b_tageslauf_nach_nachholen_vor_kalendertermin_sendet_nur_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 20, 58, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-10", "lauf": {"tag": "2026-11-03T21:00:00+01:00", "monat": zeit[0].isoformat(), "posten": zeit[0].isoformat()}})
    aufrufe = []
    monkeypatch.setattr(takt, "_lauf", lambda *a: aufrufe.append(a[2]) or True)
    takt._nachholen(_args())
    zeit[0] = datetime(2026, 11, 4, 21, tzinfo=kern.zone())
    assert takt.befehl_tag(_args()) == 0
    assert aufrufe == ["tag"]


def test_5_takt_holt_normal_gelaufenen_tageslauf_nicht_nach(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"lauf": {"tag": "2026-11-03T21:00:00+01:00"}})
    aufrufe = []
    monkeypatch.setattr(takt, "_lauf", lambda *a: aufrufe.append(a) or True)

    takt._nachholen(_args())
    assert aufrufe == []


def test_6_takt_holt_verpassten_monatslauf_nur_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    _uebergabe_einrichten(repo)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-10", "lauf": {"tag": "2026-11-04T21:00:00+01:00", "monat": "2026-10-03T09:00:00+02:00", "posten": zeit[0].isoformat()}})
    aufrufe = []
    monkeypatch.setattr(monat, "befehl", lambda args: aufrufe.append(args) or 0)

    takt._nachholen(_args())
    zeit[0] = datetime(2026, 11, 5, 10, 45, tzinfo=kern.zone())
    takt._nachholen(_args())

    assert len(aufrufe) == 1


def test_7_takt_holt_verpassten_posten_zwischenstand_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    _posten_einrichten(repo)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-10", "lauf": {"tag": "2026-11-03T21:00:00+01:00", "monat": zeit[0].isoformat(), "posten": "2026-10-15T07:00:00+02:00"}})
    aufrufe = []
    monkeypatch.setattr(posten, "befehl", lambda args: aufrufe.append(args) or 0)

    takt._nachholen(_args())
    takt._nachholen(_args())

    assert len(aufrufe) == 1 and aufrufe[0].mail


def test_8_fehler_beim_nachholen_bremst_takt_und_wird_erst_nach_stunde_wiederholt(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-10", "lauf": {"tag": "2026-11-02T21:00:00+01:00", "monat": zeit[0].isoformat(), "posten": zeit[0].isoformat()}})
    normal, nachholen = [], []

    def lauf(args, schritte, sperre):
        (nachholen if sperre == "tag" else normal).append(schritte)
        if sperre == "tag":
            raise RuntimeError("kaputt")
        return True

    monkeypatch.setattr(takt, "_lauf", lauf)

    assert takt.befehl(_args()) == 0
    zeit[0] += timedelta(minutes=15)
    assert takt.befehl(_args()) == 0
    zeit[0] += timedelta(minutes=46)
    assert takt.befehl(_args()) == 0

    assert len(normal) == 3
    assert len(nachholen) == 2
    assert (kern.lesen(repo / "arbeit" / "gesehen.json", {}) or {})["lauf"]["tag"].startswith("2026-11-02")


def test_9_altmerker_verhindern_nach_update_doppelte_kalenderlaeufe(repo, monkeypatch):
    zeit = [datetime(2026, 11, 12, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    _uebergabe_einrichten(repo)
    _posten_einrichten(repo)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {
        "bericht": "2026-11-11T21:00:00+01:00",
        "uebergabe": {"2026-10": "2026-11-03T09:00:00+01:00"},
        "gesendet_teile": {"posten:2026-11-01": [1]},
    })
    aufrufe = []
    monkeypatch.setattr(takt, "_lauf", lambda *a: aufrufe.append("tag") or True)
    monkeypatch.setattr(monat, "befehl", lambda *a: aufrufe.append("monat") or 0)
    monkeypatch.setattr(posten, "befehl", lambda *a: aufrufe.append("posten") or 0)

    takt._nachholen(_args())

    lauf = kern.lesen(repo / "arbeit" / "gesehen.json")["lauf"]
    assert set(lauf) == {"tag", "monat", "posten"}
    assert aufrufe == []


def test_10_nachholen_achtet_auf_eingerichtete_ziele_und_postenstand(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8")
                    .replace('adresse = "mara@studio-beispiel.example"', 'adresse = ""')
                    .replace('adresse = ""\nordner = ""', 'adresse = ""\nordner = ""'), encoding="utf-8")
    aufrufe = []
    monkeypatch.setattr(takt, "_lauf", lambda *a: aufrufe.append("tag") or True)
    monkeypatch.setattr(monat, "befehl", lambda *a: aufrufe.append("monat") or 0)
    monkeypatch.setattr(posten, "befehl", lambda *a: aufrufe.append("posten") or 0)

    takt._nachholen(_args())
    assert aufrufe == []


def test_11_erstes_update_ohne_berichtsmerker_sendet_nichts(repo, monkeypatch):
    zeit = [datetime(2026, 11, 12, 10, 30, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    aufrufe = []
    monkeypatch.setattr(takt, "_lauf", lambda *a: aufrufe.append(a) or True)
    takt._nachholen(_args())
    assert aufrufe == []
