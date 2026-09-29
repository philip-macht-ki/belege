"""Tests für Funde aus den drei Quellen."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

from belege import quellen


def test_download_dublette_liefert_fund_ohne_zustand(repo):
    """Die Quelle liefert auch Duplikate; gemeldet wird erst in verarbeite (nur mit --echt)."""
    datei = repo / "downloads" / "doppelt.pdf"
    datei.write_bytes(b"gleich")
    alt = (date.today() - timedelta(minutes=11)).strftime("%s")
    os.utime(datei, (float(alt), float(alt)))
    assert [f.name for f in quellen.downloads_funde()] == ["doppelt.pdf"]
    assert not (repo / "arbeit" / "gesehen.json").exists()


def test_mail_erledigt_erst_mit_echt(repo):
    """Der Fortschritt eines Postfachs ändert sich erst beim echten Lauf."""
    quellen.mail_erledigt("geschaeft", "mail-1", False)
    assert not (repo / "arbeit" / "gesehen.json").exists()
    quellen.mail_erledigt("geschaeft", "mail-1", True)
    daten = json.loads((repo / "arbeit" / "gesehen.json").read_text())
    assert daten["geschaeft"]["mails"] == ["mail-1"]
