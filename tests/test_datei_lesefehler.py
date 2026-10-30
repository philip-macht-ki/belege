"""Lesefehler aus Cloud-Ordnern werden in Klartext gemeldet und später nachgeholt."""

from __future__ import annotations

import errno
from datetime import date

from belege import kern, verarbeiten
from belege.typen import Fund


def _fund(repo):
    datei = repo / "scan.pdf"
    datei.write_bytes(b"%PDF-1.4")
    return Fund(datei, "handy", datei.name, date(2026, 10, 29))


def test_drive_gibt_datei_nicht_heraus_wartet(repo, monkeypatch):
    """Errno 11 aus Google Drive ist kein Fehler, sondern ein Fall für den nächsten Lauf."""
    def blockiert(_):
        raise OSError(errno.EDEADLK, "Resource deadlock avoided")

    monkeypatch.setattr(verarbeiten, "_sha", blockiert)
    ergebnis = verarbeiten.verarbeite(_fund(repo), False)
    assert ergebnis.status == "spaeter"
    assert "Cloud-Ordner" in ergebnis.meldung
    assert "Errno" not in ergebnis.meldung


def test_anderer_lesefehler_nennt_ursache(repo, monkeypatch):
    """Ein echter Lesefehler bleibt ein Fehler, aber in einem verständlichen Satz."""
    def verweigert(_):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(verarbeiten, "_sha", verweigert)
    ergebnis = verarbeiten.verarbeite(_fund(repo), False)
    assert ergebnis.status == "fehler"
    assert "Festplattenvollzugriff" in ergebnis.meldung


def test_datei_fehler_klartext():
    meldung, wartet = kern.datei_fehler("a.pdf", OSError(errno.EDEADLK, "Resource deadlock avoided"))
    assert wartet and "nächste Lauf" in meldung
    meldung, wartet = kern.datei_fehler("a.pdf", FileNotFoundError(errno.ENOENT, "No such file"))
    assert not wartet and "nicht mehr da" in meldung
