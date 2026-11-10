"""Verhalten beim Nachholen von Monatsübergaben und offenen Posten."""
from __future__ import annotations

import argparse
from datetime import datetime

from belege import kern, monat, posten, takt


def _args(**werte):
    grund = {"monat": None, "auszug": None, "uebergabe": True, "anfragen": False,
             "echt": True, "ziel": []}
    grund.update(werte)
    return argparse.Namespace(**grund)


def _uhr(monkeypatch, zeit):
    monkeypatch.setattr(kern, "jetzt", lambda: zeit[0])
    monkeypatch.setattr(takt, "jetzt", lambda: zeit[0])


def _auszuege_bis_oktober(repo):
    datei = repo / "auszuege" / "2026.csv"
    datei.write_text(
        "Datum;Name;Betrag\n"
        "02.08.2026;Bank;-1,00\n"
        "02.09.2026;Bank;-1,00\n"
        "02.10.2026;Bank;-1,00\n",
        encoding="utf-8",
    )


def _uebergabe_einrichten(repo):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8")
        .replace('adresse = ""\nordner = ""', 'adresse = "steuer@example.com"\nordner = ""'),
        encoding="utf-8",
    )


def _monat_lauf_vorbereiten(repo, monkeypatch):
    _auszuege_bis_oktober(repo)
    _uebergabe_einrichten(repo)
    monkeypatch.setattr(monat, "_nachsuche", lambda *args: None)
    monkeypatch.setattr(monat.monatsmail, "senden", lambda *args: None)
    gesendet = []
    monkeypatch.setattr(
        "belege.senden.senden",
        lambda an, betreff, text, anhaenge, echt, **kw: gesendet.append((betreff, echt)) or kern.Ergebnis("ok"),
    )
    return gesendet


def test_nachholen_monat_uebergibt_die_letzten_drei_monate_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    gesendet = _monat_lauf_vorbereiten(repo, monkeypatch)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {"2026-07": "2026-08-03T10:00:00+02:00"}})

    assert monat.befehl(_args()) == 0

    assert [betreff for betreff, _ in gesendet] == [
        "Belege 08/2026, Studio Beispiel", "Belege 09/2026, Studio Beispiel", "Belege 10/2026, Studio Beispiel",
    ]
    assert all((repo / "arbeit" / "monat" / wert / "abgleich.json").exists()
               for wert in ("2026-08", "2026-09", "2026-10"))


def test_nachholen_monat_uebergibt_den_vormonat_nicht_erneut(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    gesendet = _monat_lauf_vorbereiten(repo, monkeypatch)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {"2026-10": "2026-11-03T10:00:00+01:00"}})

    assert monat.befehl(_args()) == 0

    assert gesendet == []


def test_nachholen_monat_frische_einrichtung_bearbeitet_nur_vormonat(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    gesendet = _monat_lauf_vorbereiten(repo, monkeypatch)

    assert monat.befehl(_args()) == 0

    assert [betreff for betreff, _ in gesendet] == ["Belege 10/2026, Studio Beispiel"]


def test_nachholen_monat_meldet_ausgelassene_monate(repo, monkeypatch, capsys):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    gesendet = _monat_lauf_vorbereiten(repo, monkeypatch)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {"2026-03": "2026-04-03T10:00:00+02:00"}})

    assert monat.befehl(_args()) == 0

    assert [betreff for betreff, _ in gesendet] == [
        "Belege 08/2026, Studio Beispiel", "Belege 09/2026, Studio Beispiel", "Belege 10/2026, Studio Beispiel",
    ]
    assert "2026-04 bis 2026-07" in capsys.readouterr().out


def test_nachholen_posten_sendet_verpassten_zwischenstand_nur_einmal(repo, monkeypatch):
    zeit = [datetime(2026, 11, 4, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    posten.fortschreiben([{"datum": "2026-11-01", "betrag": -12.5, "name": "Pixelwerk", "zweck": "Abo", "status": "fehlt"}])
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-10", "lauf": {"tag": zeit[0].isoformat(), "monat": zeit[0].isoformat(), "posten": "2026-10-15T07:00:00+02:00"}})
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *args, **kw: gesendet.append(args) or kern.Ergebnis("ok"))

    takt._nachholen(_args())
    takt._nachholen(_args())
    zeit[0] = datetime(2026, 11, 15, 10, tzinfo=kern.zone())
    takt._nachholen(_args())

    assert len(gesendet) == 2


def test_nachholen_posten_holt_lauf_vom_ersten_nicht_erneut_nach(repo, monkeypatch):
    zeit = [datetime(2026, 11, 2, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    posten.fortschreiben([{"datum": "2026-11-01", "betrag": -12.5, "name": "Pixelwerk", "zweck": "Abo", "status": "fehlt"}])
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"lauf": {"posten": "2026-11-01T08:00:00+01:00", "tag": zeit[0].isoformat(), "monat": zeit[0].isoformat()}})
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *args, **kw: gesendet.append(args) or kern.Ergebnis("ok"))

    takt._nachholen(_args())

    assert gesendet == []


def test_nachholen_monat_bestimmt_den_stand_je_firma(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    gesendet = _monat_lauf_vorbereiten(repo, monkeypatch)
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('name = "Studio Beispiel"', 'name = "Firma A"', 1)
        + '\n[[firma]]\nname = "Firma B"\nnamen = ["Firma B"]\nbereich = "Firma B"\nkonten = []\n',
        encoding="utf-8",
    )
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {
        "Firma A:2026-09": "2026-10-03T10:00:00+02:00",
        "Firma B:2026-07": "2026-08-03T10:00:00+02:00",
    }})

    assert monat.befehl(_args()) == 0

    assert [betreff for betreff, _ in gesendet] == [
        "Belege 10/2026, Firma A",
        "Belege 08/2026, Firma B", "Belege 09/2026, Firma B", "Belege 10/2026, Firma B",
    ]


def test_nachholen_monat_einzelfirma_liest_alten_einfachen_merker(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    gesendet = _monat_lauf_vorbereiten(repo, monkeypatch)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {"2026-07": "2026-08-03T10:00:00+02:00"}})

    assert monat.befehl(_args()) == 0

    assert [betreff for betreff, _ in gesendet] == [
        "Belege 08/2026, Studio Beispiel", "Belege 09/2026, Studio Beispiel", "Belege 10/2026, Studio Beispiel",
    ]


def test_nach_update_holt_monat_keine_alte_handluecke_nach(repo, monkeypatch):
    zeit = [datetime(2026, 11, 12, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-11", "uebergabe": {"2026-08": "2026-09-03T09:00:00+02:00"}})
    assert monat.faellige_monate() == (["2026-10"], [])


def test_nach_update_holt_monate_seit_start_ueber_jahreswechsel_nach(repo, monkeypatch):
    zeit = [datetime(2027, 2, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"nachholen_ab_monat": "2026-11", "uebergabe": {"2026-08": "2026-09-03T09:00:00+02:00"}})
    assert monat.faellige_monate() == (["2026-11", "2026-12", "2027-01"], [])


def test_monatsnachholen_stoppt_an_fehlermonat_und_setzt_dort_fort(repo, monkeypatch):
    zeit = [datetime(2026, 11, 5, 10, tzinfo=kern.zone())]
    _uhr(monkeypatch, zeit)
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {"2026-07": "2026-08-03T10:00:00+02:00"}})
    original = monat.befehl
    aufrufe, fehler = [], [True]

    def lauf(args):
        if args.monat is None:
            return original(args)
        aufrufe.append(args.monat)
        if args.monat == "2026-09" and fehler and fehler.pop():
            return 1
        kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {args.monat: zeit[0].isoformat()}})
        return 0

    monkeypatch.setattr(monat, "befehl", lauf)
    assert monat.befehl(_args()) == 1
    assert aufrufe == ["2026-08", "2026-09"]
    assert monat.befehl(_args()) == 0
    assert aufrufe == ["2026-08", "2026-09", "2026-09", "2026-10"]
