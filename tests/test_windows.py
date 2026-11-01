"""Windows-Zweige ohne einen Windows-Rechner prüfen."""
from argparse import Namespace

from belege import anmelden, bericht, einrichten, kern, moneymoney, rechner, zeitplan


class Antwort:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_windows_zeitplan_erzeugt_start_when_available_und_schtasks(repo, monkeypatch):
    monkeypatch.setattr(zeitplan, "ist_windows", lambda: True)
    monkeypatch.setenv("BELEGE_JA", "1")
    aufrufe = []
    monkeypatch.setattr(zeitplan.subprocess, "run", lambda args, **kwargs: aufrufe.append(args) or Antwort())
    xml = zeitplan.windows_xml("takt")
    assert "StartWhenAvailable" in xml
    assert "PT15M" in xml
    assert zeitplan.befehl(Namespace(ziel=["an"], echt=True)) == 0
    assert any(a[:3] == ["schtasks.exe", "/Create", "/TN"] for a in aufrufe)


def test_windows_zeitplan_status_und_bericht_nutzen_schtasks(monkeypatch):
    monkeypatch.setattr(zeitplan, "ist_windows", lambda: True)
    monkeypatch.setattr(bericht, "ist_windows", lambda: True)
    aufrufe = []
    monkeypatch.setattr(zeitplan.subprocess, "run", lambda args, **kwargs: aufrufe.append(args) or Antwort())
    monkeypatch.setattr(bericht.subprocess, "run", lambda args, **kwargs: aufrufe.append(args) or Antwort())
    assert zeitplan.angemeldet("takt")
    assert bericht.zeitplan_an()
    assert all(a[0] == "schtasks.exe" for a in aufrufe)


def test_windows_passwortdialog_schreibt_nie_das_geheimnis_aus(repo, monkeypatch, capsys):
    monkeypatch.setattr(anmelden, "ist_windows", lambda: True)
    monkeypatch.setattr(anmelden.subprocess, "run", lambda *a, **k: Antwort())
    assert anmelden.befehl(Namespace(konto=None, schluesselbund="geschaeft", rechte=None, microsoft=None)) == 0
    assert "Passwort" in capsys.readouterr().out


def test_windows_moneymoney_erklaert_csv_weg(monkeypatch, capsys):
    monkeypatch.setattr(moneymoney, "ist_windows", lambda: True)
    assert moneymoney.befehl(Namespace(ziel=[], testordner=None)) == 0
    assert "CSV" in capsys.readouterr().out


def test_rechner_windows_gibt_eine_zeile(monkeypatch, capsys):
    monkeypatch.setattr(rechner, "ist_windows", lambda: True)
    assert rechner.befehl(Namespace(echt=False)) == 0
    assert capsys.readouterr().out.startswith("Rechner: windows,")


def test_windows_starter_nutzt_cmd_und_npm_pfad(monkeypatch, tmp_path):
    monkeypatch.setattr(einrichten, "ist_windows", lambda: True)
    monkeypatch.setattr(einrichten.Path, "home", classmethod(lambda cls: tmp_path))
    ok, ziel = einrichten.anlegen("codex")
    assert ok and ziel.endswith("codex.cmd")
    assert "%APPDATA%\\npm\\codex.cmd" in open(ziel, encoding="utf-8").read()
