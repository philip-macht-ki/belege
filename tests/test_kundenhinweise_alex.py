"""Regressionen für Hinweise eines Kunden mit Intel-Mac."""
from __future__ import annotations

import json
import socket
from email.message import EmailMessage
from pathlib import Path

import pytest


def test_intel_mac_haelt_cryptography_und_nennt_pixi(monkeypatch):
    from belege import pruefen

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    lock = Path(__file__).parents[1] / "uv.lock"
    assert 'cryptography<49; sys_platform == \'darwin\' and platform_machine == \'x86_64\'' in pyproject.read_text()
    locktext = lock.read_text()
    assert 'name = "cryptography"' in locktext
    assert 'version = "48.' in locktext
    assert "platform_machine == 'x86_64'" in locktext
    monkeypatch.setattr(pruefen.sys, "platform", "darwin")
    monkeypatch.setattr(pruefen.platform, "machine", lambda: "x86_64")
    assert "pixi (conda-forge)" in pruefen._poppler_hinweis()


def test_scan_bleibt_nach_trockenlauf_fuer_echten_lauf(repo):
    from belege import quellen

    scan = repo / "scan"
    scan.mkdir()
    (scan / "brief.pdf").write_bytes(b"Papierpost")
    toml = repo / "konfig/belege.toml"
    toml.write_text(toml.read_text().replace('scan_ordner = ""', f'scan_ordner = "{scan}"'), encoding="utf-8")

    assert [fund.name for fund in quellen.scan_funde()] == ["brief.pdf"]
    gesehen = repo / "arbeit" / "gesehen.json"
    assert not gesehen.exists() or "scan_sha" not in json.loads(gesehen.read_text())
    assert [fund.name for fund in quellen.scan_funde(echt=True)] == ["brief.pdf"]


def test_eigener_tagesbericht_wird_nicht_als_beleg_gelesen(repo):
    from belege.postfach import OrdnerPostfach

    ordner = repo / "postfach"
    ordner.mkdir()
    mail = EmailMessage()
    mail["From"] = "Mara Beispiel <mara@studio-beispiel.example>"
    mail["To"] = "mara@studio-beispiel.example"
    mail["Subject"] = "Belege: heute nichts Neues"
    mail.set_content("Tagesbericht")
    (ordner / "bericht.eml").write_bytes(mail.as_bytes())
    box = OrdnerPostfach({"name": "geschaeft", "weg": "ordner", "adresse": "mara@studio-beispiel.example", "ordner": str(ordner)})
    assert box.suchen() == []


def test_ohne_dns_kommt_keine_serverkonfigurationsmeldung(monkeypatch):
    from belege import postfach

    def ohne_dns(*_a, **_k):
        raise socket.gaierror("kein DNS")

    monkeypatch.setattr(postfach.socket, "getaddrinfo", ohne_dns)
    with pytest.raises(RuntimeError, match="Gerade keine Internetverbindung"):
        postfach._server("firma.example", {})


def test_laengerer_firmenname_gewinnt_bei_enthaltener_gmbh(repo):
    from belege.einordnen import _firma_aus_text

    toml = repo / "konfig/belege.toml"
    with toml.open("a", encoding="utf-8") as datei:
        datei.write(
            '\n[[firma]]\nname = "Eventschmiede Koblenz GmbH"\nbereich = "GmbH"\n'
            '\n[[firma]]\nname = "Eventschmiede Koblenz GmbH & Co. KG"\nbereich = "KG"\n'
        )
    assert _firma_aus_text("Rechnung an Eventschmiede Koblenz GmbH & Co. KG") == (
        "Eventschmiede Koblenz GmbH & Co. KG"
    )
    assert _firma_aus_text("Rechnung an Eventschmiede Koblenz GmbH") == "Eventschmiede Koblenz GmbH"
