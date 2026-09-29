import plistlib
import shutil
from argparse import Namespace
from pathlib import Path

from belege import zeitplan

ECHT = Path(__file__).resolve().parents[1]


def _vorlagen(repo):
    shutil.copytree(ECHT / "zeitplan", repo / "zeitplan")


def test_plists_sind_gueltig_und_gefuellt(repo):
    _vorlagen(repo)
    takt = plistlib.loads(zeitplan.plist_text("takt").encode())
    assert takt["StartInterval"] == 900
    assert "belege takt --echt" in takt["ProgramArguments"][2]
    tag = plistlib.loads(zeitplan.plist_text("tag").encode())
    assert tag["StartCalendarInterval"] == {"Hour": 21, "Minute": 0}
    monat = plistlib.loads(zeitplan.plist_text("monat").encode())
    assert monat["StartCalendarInterval"]["Day"] == 3
    assert "monat --uebergabe --echt" in monat["ProgramArguments"][2]


def test_trocken_schreibt_nichts(repo, monkeypatch):
    _vorlagen(repo)
    aufrufe = []
    monkeypatch.setattr(zeitplan.Path, "home", lambda: repo / "home")
    monkeypatch.setattr(zeitplan.subprocess, "run", lambda *a, **k: aufrufe.append(a))
    assert zeitplan.befehl(Namespace(ziel=["an"], echt=False)) == 0
    assert not (repo / "home").exists()
    assert aufrufe == []


def test_echt_ohne_zustimmung_bricht_ab(repo, monkeypatch):
    _vorlagen(repo)
    monkeypatch.setattr(zeitplan.Path, "home", lambda: repo / "home")
    monkeypatch.delenv("BELEGE_JA", raising=False)
    monkeypatch.setattr(zeitplan.sys.stdin, "isatty", lambda: False)
    assert zeitplan.befehl(Namespace(ziel=["an"], echt=True)) == 0
    assert not (repo / "home").exists()


def test_aus_verschiebt_statt_zu_loeschen(repo, monkeypatch):
    home = repo / "home" / "Library" / "LaunchAgents"
    home.mkdir(parents=True)
    (home / "de.belege.takt.plist").write_text("x")
    monkeypatch.setattr(zeitplan.Path, "home", lambda: repo / "home")
    monkeypatch.setattr(zeitplan.subprocess, "run", lambda *a, **k: None)
    assert zeitplan.befehl(Namespace(ziel=["aus"], echt=True)) == 0
    assert (repo / "arbeit" / "zeitplan-alt" / "de.belege.takt.plist").exists()
