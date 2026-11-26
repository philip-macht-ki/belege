"""Belegverzeichnis: Einträge, deren Datei fehlt (Fehlerbericht ZAMCOM 25.11.2026)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from belege import kern, verarbeiten, verzeichnis
from belege.typen import Einordnung, Fund, Text

MILES = dict(lieferant="MILES Mobility GmbH", beschreibung="Rechnung Carsharing Fahrt", betrag=17.89)


def _index(repo: Path) -> dict:
    return json.loads((repo / "arbeit" / "index.json").read_text(encoding="utf-8"))


def _einordnung(tag: date, firma: str = "", **werte) -> Einordnung:
    w = {**MILES, **werte}
    return Einordnung(True, "eingang", "betrieb", tag, w["lieferant"], w["beschreibung"], w["betrag"],
                      "EUR", "hoch", "Testregel.", "regel", firma)


def _ablegen(repo: Path, monkeypatch, name: str, inhalt: bytes, einordnung: Einordnung) -> str:
    datei = repo / name
    datei.write_bytes(inhalt)
    monkeypatch.setattr("belege.einordnen.einordnen", lambda *_a, **_k: einordnung)
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("MILES Mobility GmbH Rechnung", "klartext", 1))
    ergebnis = verarbeiten.verarbeite(Fund(datei, "postfach", name, einordnung.datum), True)
    assert ergebnis.status == "ok", ergebnis.meldung
    return str(Path(ergebnis.daten["pfad"]).relative_to(repo / "ablage"))


def _firma_zamcom(repo: Path) -> None:
    """Die Einrichtung bekommt später einen [[firma]]-Block mit eigenem Ordner."""
    toml = repo / "konfig" / "belege.toml"
    text = toml.read_text(encoding="utf-8").replace('name = "Studio Beispiel"', 'name = "ZAMCOM GmbH"')
    toml.write_text(text + '\n[[firma]]\nname = "ZAMCOM GmbH"\nnamen = ["ZAMCOM GmbH", "ZAMCOM"]\nbereich = "ZAMCOM"\n',
                    encoding="utf-8")


def test_ursache_geloeschte_dublette_bleibt_im_index_und_wird_geheilt(repo, monkeypatch):
    """Nachbau des Fehlerberichts.

    Vor dem [[firma]]-Block legt belege unter Betrieb/ ab, danach unter ZAMCOM/.
    Eine zweite, bytegleich andere Fassung derselben Rechnung landet so im
    Firmenordner, der Tagesbericht sagt „lösch eine der beiden Dateien“, und die
    Person löscht die alte Betrieb-Datei. Bis 1.20.0 blieb der Eintrag mit
    ``Betrieb/…`` für immer im Index und zählte in jeder Auswertung doppelt.
    """
    tag = date(2026, 9, 2)
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('name = "Studio Beispiel"', 'name = "ZAMCOM GmbH"'),
                    encoding="utf-8")
    alt = _ablegen(repo, monkeypatch, "miles.pdf", b"%PDF MILES Fassung 1", _einordnung(tag, "ZAMCOM GmbH"))
    assert alt.startswith("Betrieb/2026/09/Eingang/2026-09-02_MILES-Mobility-GmbH")
    _firma_zamcom(repo)
    neu = _ablegen(repo, monkeypatch, "miles2.pdf", b"%PDF MILES Fassung 2", _einordnung(tag, "ZAMCOM GmbH"))
    assert neu.startswith("ZAMCOM/2026/09/Eingang/")
    hinweis = [e for e in kern.ereignisse() if "Möglicherweise doppelt" in e["text"]]
    assert hinweis and "lösch eine der beiden Dateien" in hinweis[0]["text"]

    (repo / "ablage" / alt).unlink()  # so, wie der Hinweis es vorschlägt
    assert sorted(e["pfad"] for e in _index(repo).values()) == sorted([alt, neu])  # verwaist

    ergebnisse = verzeichnis.lauf(True)
    pfade = [e["pfad"] for e in _index(repo).values()]
    assert pfade == [neu]
    assert all("moegliche_dublette" not in e for e in _index(repo).values())
    gesichert = [json.loads(z) for z in (repo / "arbeit" / verzeichnis.ENTFERNT).read_text().splitlines()]
    assert gesichert[0]["eintrag"]["pfad"] == alt
    assert any(e.status == "ok" for e in ergebnisse)
    assert (repo / "ablage" / neu).exists()  # keine Datei angefasst


def test_falscher_zusatz_wird_auf_vorhandene_datei_umgebogen(repo, monkeypatch):
    """Index nennt …_2.pdf, auf der Platte liegt nur die Datei ohne _2 mit genau diesem Inhalt."""
    tag = date(2026, 11, 9)
    erster = _ablegen(repo, monkeypatch, "a.pdf", b"%PDF erste", _einordnung(tag))
    zweiter = _ablegen(repo, monkeypatch, "b.pdf", b"%PDF zweite", _einordnung(tag))
    assert zweiter.endswith("_2.pdf")
    # Von Hand aufgeräumt: die erste gelöscht, die zweite auf den Namen ohne _2 gebracht.
    (repo / "ablage" / erster).unlink()
    (repo / "ablage" / zweiter).rename(repo / "ablage" / erster)

    verzeichnis.lauf(True)
    index = _index(repo)
    assert len(index) == 1
    (schluessel, eintrag), = index.items()
    assert eintrag["pfad"] == erster
    assert schluessel == verarbeiten._sha(repo / "ablage" / erster)


def test_umbenannter_firmenordner_wird_nachgezogen(repo, monkeypatch):
    """Betrieb/ von Hand in ZAMCOM/ umbenannt: gleicher Inhalt, also nur der Pfad neu."""
    tag = date(2026, 9, 2)
    alt = _ablegen(repo, monkeypatch, "miles.pdf", b"%PDF MILES", _einordnung(tag))
    _firma_zamcom(repo)
    (repo / "ablage" / "Betrieb").rename(repo / "ablage" / "ZAMCOM")
    verzeichnis.lauf(True)
    (eintrag,) = _index(repo).values()
    assert eintrag["pfad"] == "ZAMCOM" + alt.removeprefix("Betrieb")


def test_ohne_duplikat_nur_melden_nie_entfernen(repo, monkeypatch):
    """Fehlt die Datei und gibt es kein Duplikat, bleibt der Eintrag und steht einmal im Bericht."""
    pfad = _ablegen(repo, monkeypatch, "a.pdf", b"%PDF einzig", _einordnung(date(2026, 10, 1)))
    (repo / "ablage" / pfad).unlink()
    vorher = _index(repo)
    verzeichnis.lauf(True)
    verzeichnis.lauf(True)
    assert _index(repo) == vorher
    gemeldet = [e for e in kern.ereignisse() if e.get("daten", {}).get("grund") == "verzeichnis"]
    assert len(gemeldet) == 1 and pfad in gemeldet[0]["text"]
    assert not (repo / "arbeit" / verzeichnis.ENTFERNT).exists()


def test_anderer_betrag_ist_kein_duplikat(repo, monkeypatch):
    tag = date(2026, 10, 1)
    erster = _ablegen(repo, monkeypatch, "a.pdf", b"%PDF a", _einordnung(tag))
    _ablegen(repo, monkeypatch, "b.pdf", b"%PDF b", _einordnung(tag, betrag=18.0))
    (repo / "ablage" / erster).unlink()
    verzeichnis.lauf(True)
    assert erster in [e["pfad"] for e in _index(repo).values()]


def test_trocken_aendert_nichts(repo, monkeypatch, capsys):
    tag = date(2026, 10, 1)
    erster = _ablegen(repo, monkeypatch, "a.pdf", b"%PDF a", _einordnung(tag))
    _ablegen(repo, monkeypatch, "b.pdf", b"%PDF b", _einordnung(tag))
    (repo / "ablage" / erster).unlink()
    vorher = _index(repo)
    verzeichnis.lauf(False)
    assert _index(repo) == vorher
    assert "würde entfernen" in capsys.readouterr().out


def test_ablage_nicht_erreichbar_aendert_nichts(repo, monkeypatch):
    """Fehlt fast alles (Cloud-Ordner nicht eingebunden), wird nichts entfernt."""
    tag = date(2026, 10, 1)
    for nummer in range(24):
        _ablegen(repo, monkeypatch, f"{nummer}.pdf", f"%PDF {nummer}".encode(), _einordnung(tag, betrag=10 + nummer))
    _ablegen(repo, monkeypatch, "x.pdf", b"%PDF x", _einordnung(tag, betrag=10))
    for eintrag in list(_index(repo).values())[:23]:
        (repo / "ablage" / eintrag["pfad"]).unlink()
    vorher = _index(repo)
    ergebnisse = verzeichnis.lauf(True)
    assert _index(repo) == vorher
    assert ergebnisse and "nicht erreichbar" in ergebnisse[0].meldung


def test_tageslauf_pflegt_verzeichnis_vor_dem_bericht():
    import inspect

    from belege import takt

    quelle = inspect.getsource(takt.befehl_tag)
    assert '("downloads", "nachsortieren", "verzeichnis", "bericht")' in quelle


def test_pfade_ausserhalb_der_ablage_bleiben_unangetastet(repo, monkeypatch, tmp_path):
    """Absolute oder mit .. aus der Ablage führende Pfade zählen weder als fehlend noch als Duplikat."""
    tag = date(2026, 10, 1)
    innen = _ablegen(repo, monkeypatch, "a.pdf", b"%PDF a", _einordnung(tag))
    index = _index(repo)
    fremd = tmp_path / "anderswo.pdf"
    fremd.write_bytes(b"x")
    vorlage = next(iter(index.values()))
    index["absolut"] = {**vorlage, "pfad": str(fremd)}
    index["hinaus"] = {**vorlage, "pfad": "../weg/b.pdf"}
    (repo / "arbeit" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (repo / "ablage" / innen).unlink()
    verzeichnis.lauf(True)
    nachher = _index(repo)
    assert {"absolut", "hinaus"} <= set(nachher)
    assert innen in [e["pfad"] for e in nachher.values()]  # Duplikat nur außerhalb: bleibt


def test_vertraulich_nennt_keinen_pfad(repo, monkeypatch):
    tag = date(2026, 10, 1)
    erster = _ablegen(repo, monkeypatch, "a.pdf", b"%PDF a", _einordnung(tag))
    _ablegen(repo, monkeypatch, "b.pdf", b"%PDF b", _einordnung(tag))
    index = _index(repo)
    for e in index.values():
        e["vertraulich"] = True
    (repo / "arbeit" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (repo / "ablage" / erster).unlink()
    ergebnisse = verzeichnis.lauf(True)
    eigene = [e for e in kern.ereignisse() if e["art"] == "verzeichnis" or e.get("daten", {}).get("grund") == "verzeichnis"]
    assert eigene
    texte = " ".join(e.meldung for e in ergebnisse) + json.dumps(eigene, ensure_ascii=False)
    assert "MILES" not in texte and "vertraulicher Beleg" in texte


def test_laeuft_unter_der_gesamtsperre():
    from belege import cli

    assert "verzeichnis" in cli.SCHREIBEND and "tag" in cli.SCHREIBEND and "takt" in cli.SCHREIBEND
