"""Tests für kurzzeitige Sperren von Cloud-Ordnern."""
from __future__ import annotations

import argparse
import errno
from datetime import date

import pytest

from belege import kern, takt
from belege.ablegen import ablegen
from belege.typen import Einordnung, Fund, Text


def _einordnung():
    return Einordnung(
        ist_beleg=True, art="eingang", bereich="betrieb", datum=date(2026, 11, 2),
        lieferant="Beispiel", beschreibung="Rechnung", betrag=1.0, waehrung="EUR",
        sicherheit="hoch", grund="Test", quelle="test",
    )


def test_cloud_sicher_wiederholt_deadlock(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(kern.time, "sleep", lambda _: None)

    def gesperrt_dann_ok():
        aufrufe.append(1)
        if len(aufrufe) < 3:
            raise OSError(errno.EDEADLK, "gesperrt")
        return "ok"

    assert kern.cloud_sicher(gesperrt_dann_ok, beschreibung="Test") == "ok"
    assert len(aufrufe) == 3


def test_cloud_sicher_gibt_nach_wiederholten_sperren_auf(monkeypatch):
    monkeypatch.setattr(kern.time, "sleep", lambda _: None)

    with pytest.raises(kern.CloudGesperrt, match="Cloud-Ordner.*nächste Lauf"):
        kern.cloud_sicher(
            lambda: (_ for _ in ()).throw(OSError(errno.EDEADLK, "gesperrt")),
            beschreibung="Testdatei",
        )


def test_cloud_sicher_reicht_andere_osfehler_durch():
    with pytest.raises(OSError, match="Platte voll"):
        kern.cloud_sicher(
            lambda: (_ for _ in ()).throw(OSError(errno.ENOSPC, "Platte voll")),
            beschreibung="Testdatei",
        )


def test_takt_macht_nach_cloud_sperre_mit_naechstem_fund_weiter(repo, monkeypatch):
    gesperrt = repo / "handy" / "gesperrt.pdf"
    erfolgreich = repo / "handy" / "erfolgreich.pdf"
    gesperrt.write_bytes(b"eins")
    erfolgreich.write_bytes(b"zwei")
    funde = [
        Fund(gesperrt, "handy", gesperrt.name, date(2026, 11, 2), verschieben=False),
        Fund(erfolgreich, "handy", erfolgreich.name, date(2026, 11, 2), verschieben=False),
    ]
    echtes_copy2 = __import__("belege.ablegen", fromlist=["shutil"]).shutil.copy2
    monkeypatch.setattr(kern.time, "sleep", lambda _: None)

    def copy2_mit_sperre(quelle, ziel):
        if str(quelle).endswith("gesperrt.pdf"):
            raise OSError(errno.EDEADLK, "gesperrt")
        return echtes_copy2(quelle, ziel)

    monkeypatch.setattr("belege.ablegen.shutil.copy2", copy2_mit_sperre)
    monkeypatch.setattr(takt, "_funde", lambda *_: funde)
    monkeypatch.setattr(
        "belege.verarbeiten.verarbeite",
        lambda fund, echt: ablegen(fund, _einordnung(), Text("", "leer"), echt),
    )

    ergebnisse = takt.quelle_abarbeiten("handy", argparse.Namespace(echt=True))

    assert [e.status for e in ergebnisse] == ["cloud_gesperrt", "ok"]
    assert gesperrt.exists()
    assert list((repo / "ablage").rglob("*.pdf"))
    assert not (repo / "arbeit" / "index.json").exists()
    ereignisse = kern.ereignisse()
    assert any(e["art"] == "cloud_gesperrt" for e in ereignisse)
