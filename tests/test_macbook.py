"""MacBook-fest: zugeklappt, ohne Netz, Aufwach-Burst."""
from datetime import date, timedelta

import pytest

from belege import kern, quellen, urteil, verarbeiten
from belege.typen import Fund, Text


def test_rueckblick_ab_letztem_lauf_mit_grenzen(repo):
    cfg = {"laufend_tage": 3, "erste_tage": 30, "max_tage": 60}
    heute = kern.jetzt()
    assert quellen.rueckblick_tage({}, cfg) == 30
    assert quellen.rueckblick_tage({"lauf": heute.isoformat()}, cfg) == 3
    # Eine Woche zugeklappt: die ganze Woche plus Puffer, nicht nur drei Tage.
    assert quellen.rueckblick_tage({"lauf": (heute - timedelta(days=7)).isoformat()}, cfg) == 9
    assert quellen.rueckblick_tage({"stand": (heute - timedelta(days=200)).isoformat()}, cfg) == 60


def test_unerreichbar_gibt_keine_rueckfallregel(repo, monkeypatch):
    monkeypatch.setenv("URTEIL_BACKEND", "claude")

    def offline(*_):
        raise urteil.Unerreichbar("claude -p scheiterte: getaddrinfo ENOTFOUND")

    monkeypatch.setattr(urteil, "BACKENDS", {"claude": offline})
    with pytest.raises(urteil.Unerreichbar):
        urteil.frage("x", zweck="t", rueckfall=lambda: pytest.fail("Rückfallregel offline benutzt"))


def test_offline_bleibt_der_fund_liegen(repo, monkeypatch):
    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    monkeypatch.setattr(urteil, "BACKENDS", {"claude": lambda *a: (_ for _ in ()).throw(urteil.Unerreichbar("weg"))})
    monkeypatch.setattr(kern, "netz_da", lambda *a: False)
    monkeypatch.setattr("belege.text.auslesen", lambda _, **__: Text("Rechnung Hetzner 4,51 EUR", "pdftotext", 1))
    datei = repo / "handy" / "rechnung.pdf"
    datei.write_bytes(b"pdf")
    for _ in range(3):
        ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 1)), True)
    assert ergebnis.status == "spaeter" and not ergebnis.gut
    assert datei.exists(), "Datei bleibt im Eingang"
    assert not list((repo / "ablage").rglob("*.pdf"))
    zeilen = "".join(p.read_text(encoding="utf-8") for p in (repo / "arbeit" / "ereignisse").glob("*.jsonl"))
    assert zeilen.count('"art": "offline"') == 1, "höchstens eine Zeile am Tag"
    assert '"art": "fehler"' not in zeilen


def test_gesamtsperre_laesst_nur_einen_laufen(repo):
    with kern.Gesamtsperre(0) as erster:
        assert erster
        with kern.Gesamtsperre(0) as zweiter:
            assert not zweiter
    with kern.Gesamtsperre(0) as danach:
        assert danach


def test_netzfehler_erkannt():
    import socket

    assert kern.netzfehler(socket.gaierror(8, "nodename nor servname provided"))
    assert kern.netzfehler(TimeoutError())
    assert not kern.netzfehler(ValueError("Spalte fehlt"))


def test_rechner_erkennt_macbook_am_akku(monkeypatch):
    from belege import rechner

    monkeypatch.setattr(rechner, "_aus", lambda cmd: {
        "pmset": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1) 80%; discharging",
        "system_profiler": "      Model Name: MacBook Air\n      Chip: Apple M2\n",
        "sysctl": str(16 * 1024**3),
    }[cmd[0]])
    daten = rechner.erkennen()
    assert daten["art"] == "macbook" and daten["modell"] == "MacBook Air" and daten["ram_gb"] == 16
    assert daten["am_netzteil"] is False
    monkeypatch.setattr(rechner, "_aus", lambda cmd: "Now drawing from 'AC Power'\n" if cmd[0] == "pmset" else "")
    assert rechner.art() == "dauerrechner"
