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


def test_scan_funde_kopiert_papierpost_und_laesst_original(repo):
    """I: Scan-Dienste behalten ihr Original; verarbeitet wird eine Arbeitskopie."""
    scan = repo / "scan"
    scan.mkdir()
    original = scan / "brief.pdf"
    original.write_bytes(b"Papierpost")
    toml = repo / "konfig/belege.toml"
    toml.write_text(toml.read_text().replace('scan_ordner = ""', f'scan_ordner = "{scan}"'), encoding="utf-8")
    fund = list(quellen.scan_funde())[0]
    assert original.exists() and fund.datei != original and fund.datei.read_bytes() == original.read_bytes()


def test_scan_funde_liefert_sha_nur_einmal(repo):
    scan = repo / "scan"
    scan.mkdir()
    (scan / "brief.pdf").write_bytes(b"Papierpost")
    toml = repo / "konfig/belege.toml"
    toml.write_text(toml.read_text().replace('scan_ordner = ""', f'scan_ordner = "{scan}"'), encoding="utf-8")
    assert len(list(quellen.scan_funde())) == 1
    assert list(quellen.scan_funde()) == []


def test_scan_funde_liest_unterordner_wie_dropscan(repo):
    """Dropscan legt je Scanbox und Tag einen Ordner an; versteckte Ordner bleiben draußen."""
    scan = repo / "scan"
    tag = scan / "Scanbox-12345" / "2026-10-28"
    tag.mkdir(parents=True)
    (tag / "Brief.pdf").write_bytes(b"Papierpost vom Amt")
    versteckt = scan / ".sync"
    versteckt.mkdir()
    (versteckt / "x.pdf").write_bytes(b"intern")
    toml = repo / "konfig/belege.toml"
    toml.write_text(toml.read_text().replace('scan_ordner = ""', f'scan_ordner = "{scan}"'), encoding="utf-8")
    funde = list(quellen.scan_funde())
    assert [f.name for f in funde] == ["Brief.pdf"]


def test_scan_funde_folgt_keinem_ordnerlink(repo):
    scan = repo / "scan"
    (scan / "a").mkdir(parents=True)
    (scan / "a" / "Brief.pdf").write_bytes(b"Papierpost")
    (scan / "a" / "schleife").symlink_to(scan, target_is_directory=True)
    toml = repo / "konfig/belege.toml"
    toml.write_text(toml.read_text().replace('scan_ordner = ""', f'scan_ordner = "{scan}"'), encoding="utf-8")
    assert [f.name for f in quellen.scan_funde()] == ["Brief.pdf"]
