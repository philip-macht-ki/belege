import shutil
import subprocess
from argparse import Namespace
from types import SimpleNamespace
from pathlib import Path

import pytest

from belege import kern, update


ECHT = Path(__file__).resolve().parents[1]


def _run(*cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)


def _git_repo(tmp_path, monkeypatch):
    quelle, bare, kunde = tmp_path / "quelle", tmp_path / "origin.git", tmp_path / "kunde"
    shutil.copytree(ECHT, quelle, ignore=shutil.ignore_patterns(".git", ".venv", "arbeit", ".pytest_cache", ".vorlage"))
    _run("git", "init", "-b", "main", cwd=quelle)
    _run("git", "config", "user.email", "test@example.invalid", cwd=quelle)
    _run("git", "config", "user.name", "Test", cwd=quelle)
    _run("git", "add", ".", cwd=quelle)
    _run("git", "add", "-f", "konfig", cwd=quelle)  # Kunde einer älteren Version
    _run("git", "commit", "-m", "Basis", cwd=quelle)
    _run("git", "clone", "--bare", str(quelle), str(bare), cwd=tmp_path)
    _run("git", "clone", str(bare), str(kunde), cwd=tmp_path)
    monkeypatch.setattr(kern, "ROOT", kunde)
    monkeypatch.setattr(update, "pfad", lambda *teile: kunde.joinpath(*map(str, teile)))
    return quelle, kunde


def _release(quelle, version="9.9.0", aktion="keine"):
    p = quelle / "belege/__init__.py"
    p.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    c = quelle / "CHANGELOG.md"
    c.write_text(f"# Änderungen für dich\n\n## [{version}]\naktion: {aktion}\n\n### Was ist neu für dich\n\n- Testverbesserung.\n\n### Musst du etwas tun?\n\nNein.\n\n" + c.read_text(), encoding="utf-8")
    _run("git", "rm", "--cached", "-r", "konfig", cwd=quelle)
    _run("git", "add", ".", cwd=quelle)
    _run("git", "commit", "-m", "Release", cwd=quelle)
    _run("git", "push", str(quelle.parent / "origin.git"), "main", cwd=quelle)


def test_fast_forward_mit_lokalem_bare_repo_und_konfig_bleibt(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    (kunde / "konfig/belege.toml").write_text("persoenlich = true\n")
    _release(quelle)
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    echt_run = subprocess.run
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0) if cmd[:2] == ["uv", "sync"] else echt_run(cmd, **kw))
    assert update.befehl(Namespace(echt=True, automatisch=False)) == 0
    assert "persoenlich = true" in (kunde / "konfig/belege.toml").read_text()
    assert "Version 9.9.0" in capsys.readouterr().out


def test_lokale_programmdatei_bricht_ohne_aenderung_ab(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    (kunde / "README.md").write_text("eigene Änderung\n")
    vorher = _run("git", "rev-parse", "HEAD", cwd=kunde).stdout
    assert update.befehl(Namespace(echt=True, automatisch=False)) == 1
    assert _run("git", "rev-parse", "HEAD", cwd=kunde).stdout == vorher
    assert "Sag deinem Claude" in capsys.readouterr().out


def test_roter_selbsttest_rollt_auf_alten_commit_zurueck(tmp_path, monkeypatch):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    vorher = _run("git", "rev-parse", "HEAD", cwd=kunde).stdout
    werte = iter([0, 1])
    monkeypatch.setattr(update, "_pruefen", lambda: next(werte))
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    echt_run = subprocess.run
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0) if cmd[:2] == ["uv", "sync"] else echt_run(cmd, **kw))
    assert update.befehl(Namespace(echt=True, automatisch=False)) == 1
    assert _run("git", "rev-parse", "HEAD", cwd=kunde).stdout == vorher


def test_automatisch_mit_konfig_zeigt_nur_meldung(tmp_path, monkeypatch, capsys):
    quelle, _ = _git_repo(tmp_path, monkeypatch)
    _release(quelle, aktion="konfig")
    assert update.befehl(Namespace(echt=True, automatisch=True)) == 0
    assert "Schritt für dich" in capsys.readouterr().out


def test_fehlende_konfig_vorlage_wird_angelegt_und_bestehende_bleibt(repo):
    (repo / "vorlagen/konfig").mkdir(parents=True, exist_ok=True)
    (repo / "vorlagen/konfig/neu.toml").write_text("wert = 1\n")
    (repo / "konfig/belege.toml").write_text("eigen = true\n")
    assert "neu.toml" in update._konfig_erganzen()
    assert (repo / "konfig/neu.toml").exists()
    assert (repo / "konfig/belege.toml").read_text().startswith("eigen = true\n")
    assert "[update]" in (repo / "konfig/belege.toml").read_text()


def test_automatisch_hoechstens_einmal_pro_woche(monkeypatch, tmp_path):
    """Verpasster Sonntag wird beim nächsten Start nachgeholt, sonst keine doppelte Prüfung."""
    from datetime import datetime, timedelta
    from belege import update
    datei = tmp_path / "update-letzte-pruefung.txt"
    monkeypatch.setattr(update, "pfad", lambda *teile: tmp_path / teile[-1])
    assert update._letzte_pruefung_alt_genug()  # noch nie geprüft
    datei.write_text((datetime.now() - timedelta(days=2)).isoformat())
    assert not update._letzte_pruefung_alt_genug()
    datei.write_text((datetime.now() - timedelta(days=8)).isoformat())
    assert update._letzte_pruefung_alt_genug()


def test_plus_ohne_installation_startet_keinen_subprocess(monkeypatch, tmp_path):
    monkeypatch.setenv("BELEGE_PLUS", str(tmp_path / "nicht-installiert"))
    monkeypatch.setattr(update.subprocess, "run", lambda *args, **kwargs: pytest.fail("Subprocess gestartet"))
    update._plus_aktualisieren(False)


def test_plus_wird_mit_automatisch_aktualisiert(monkeypatch, tmp_path):
    plus = tmp_path / "belege-plus"
    plus.mkdir()
    (plus / "pyproject.toml").write_text("[project]\nname = 'belege-plus'\n")
    aufrufe = []
    monkeypatch.setenv("BELEGE_PLUS", str(plus))
    monkeypatch.setattr(update.subprocess, "run", lambda *args, **kwargs: aufrufe.append((args, kwargs)) or subprocess.CompletedProcess(args[0], 0))
    update._plus_aktualisieren(True)
    assert aufrufe == [
        ((["uv", "--directory", str(plus), "run", "plus", "update", "--echt", "--automatisch"],),
         {"timeout": 600, "capture_output": True, "text": True})
    ]


def test_plus_fehler_rollt_basisupdate_nicht_zurueck(tmp_path, monkeypatch):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    plus = tmp_path / "belege-plus"
    plus.mkdir()
    (plus / "pyproject.toml").write_text("[project]\nname = 'belege-plus'\n")
    monkeypatch.setenv("BELEGE_PLUS", str(plus))
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    ereignisse = []
    monkeypatch.setattr(update, "ereignis", lambda *args: ereignisse.append(args))
    echt_run = subprocess.run
    def lauf(cmd, **kwargs):
        if cmd[:2] == ["uv", "sync"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[:5] == ["uv", "--directory", str(plus), "run", "plus"]:
            return subprocess.CompletedProcess(cmd, 1)
        return echt_run(cmd, **kwargs)
    monkeypatch.setattr(update.subprocess, "run", lauf)
    assert update.befehl(Namespace(echt=True, automatisch=False)) == 0
    assert _run("git", "rev-parse", "HEAD", cwd=kunde).stdout == _run("git", "rev-parse", "origin/main", cwd=kunde).stdout
    assert ("update", "Belege Plus konnte nicht aktualisiert werden: Exit-Code 1") in ereignisse


def test_plus_auch_ohne_basis_update_bei_gruenem_selbsttest(tmp_path, monkeypatch):
    plus = tmp_path / "plus"
    plus.mkdir()
    (plus / "pyproject.toml").write_text("[project]\nname='belege-plus'\n")
    monkeypatch.setenv("BELEGE_PLUS", str(plus))
    aufrufe = []
    monkeypatch.setattr(update, "_git", lambda *a, **k: SimpleNamespace(stdout=f'__version__ = "{update.__version__}"', returncode=0))
    monkeypatch.setattr(update, "_changelog_remote", lambda: "")
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_plus_aktualisieren", lambda automatisch: aufrufe.append(automatisch))
    assert update.befehl(Namespace(echt=True, automatisch=False)) == 0
    assert aufrufe == [False]
    monkeypatch.setattr(update, "_pruefen", lambda: 1)
    update.befehl(Namespace(echt=True, automatisch=False))
    assert aufrufe == [False], "roter Selbsttest: Plus bleibt, wie es ist"


def _alt_eingerichtet(kunde, tage=40):
    import json
    from datetime import date, timedelta

    (kunde / "arbeit").mkdir(exist_ok=True)
    (kunde / "arbeit/einrichtung.json").write_text(json.dumps({"seit": (date.today() - timedelta(days=tage)).isoformat()}))


def _ohne_pull(monkeypatch):
    echt_git = update._git
    monkeypatch.setattr(update, "_git", lambda *a, **k: pytest.fail("Update eingespielt") if a[:1] == ("pull",) else echt_git(*a, **k))


def test_nach_vier_wochen_ohne_plus_pausiert_automatik_mit_einem_hinweis(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    _alt_eingerichtet(kunde)
    monkeypatch.setattr(update, "_plus_gueltig", lambda: False)
    monkeypatch.setattr(update, "_letzte_pruefung_alt_genug", lambda: True)
    ereignisse = []
    monkeypatch.setattr(update, "ereignis", lambda *a: ereignisse.append(a))
    _ohne_pull(monkeypatch)
    assert update.befehl(Namespace(echt=True, automatisch=True)) == 0
    assert update.befehl(Namespace(echt=True, automatisch=True)) == 0
    assert len(ereignisse) == 1, "Hinweis nur einmal je Version"
    assert "nach 4 Wochen pausiert" in ereignisse[0][1] and "uv run belege aktualisieren --echt" in ereignisse[0][1]
    assert "Agent Plus" in ereignisse[0][1]


def test_von_hand_geht_nach_vier_wochen_weiter(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    _alt_eingerichtet(kunde)
    monkeypatch.setattr(update, "_plus_gueltig", lambda: pytest.fail("von Hand fragt keine Lizenz"))
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    echt_run = subprocess.run
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0) if cmd[:2] == ["uv", "sync"] else echt_run(cmd, **kw))
    assert update.befehl(Namespace(echt=True, automatisch=False)) == 0
    assert "Version 9.9.0" in capsys.readouterr().out


def test_sicherheitsupdate_kommt_auch_ohne_plus_automatisch(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle, aktion="sicherheit")
    _alt_eingerichtet(kunde)
    monkeypatch.setattr(update, "_plus_gueltig", lambda: False)
    monkeypatch.setattr(update, "_letzte_pruefung_alt_genug", lambda: True)
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    echt_run = subprocess.run
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0) if cmd[:2] == ["uv", "sync"] else echt_run(cmd, **kw))
    assert update.befehl(Namespace(echt=True, automatisch=True)) == 0
    assert "Version 9.9.0" in capsys.readouterr().out


def test_mit_gueltiger_plus_lizenz_laeuft_automatik_weiter(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    _alt_eingerichtet(kunde)
    monkeypatch.setattr(update, "_plus_gueltig", lambda: True)
    monkeypatch.setattr(update, "_letzte_pruefung_alt_genug", lambda: True)
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    monkeypatch.setattr(update, "_plus_aktualisieren", lambda automatisch: None)
    echt_run = subprocess.run
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0) if cmd[:2] == ["uv", "sync"] else echt_run(cmd, **kw))
    assert update.befehl(Namespace(echt=True, automatisch=True)) == 0
    assert "Version 9.9.0" in capsys.readouterr().out


def test_in_den_ersten_vier_wochen_ohne_plus_automatisch(tmp_path, monkeypatch, capsys):
    quelle, kunde = _git_repo(tmp_path, monkeypatch)
    _release(quelle)
    _alt_eingerichtet(kunde, tage=27)
    monkeypatch.setattr(update, "_plus_gueltig", lambda: pytest.fail("in der Frist keine Lizenzfrage"))
    monkeypatch.setattr(update, "_letzte_pruefung_alt_genug", lambda: True)
    monkeypatch.setattr(update, "_pruefen", lambda: 0)
    monkeypatch.setattr(update, "_zeitplaene", lambda: None)
    echt_run = subprocess.run
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0) if cmd[:2] == ["uv", "sync"] else echt_run(cmd, **kw))
    assert update.befehl(Namespace(echt=True, automatisch=True)) == 0
    assert "Version 9.9.0" in capsys.readouterr().out


def test_bestand_ohne_datum_startet_heute(tmp_path, monkeypatch):
    from datetime import date

    monkeypatch.setattr(update, "pfad", lambda *teile: tmp_path.joinpath(*map(str, teile)))
    assert update.einrichtung_merken() == date.today()
    assert (tmp_path / "arbeit/einrichtung.json").exists()


def test_plus_lizenz_wird_ueber_plus_gefragt(tmp_path, monkeypatch):
    plus = tmp_path / "plus"
    plus.mkdir()
    (plus / "pyproject.toml").write_text("")
    monkeypatch.setenv("BELEGE_PLUS", str(plus))
    aufrufe = []
    monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: aufrufe.append(cmd) or subprocess.CompletedProcess(cmd, 1))
    assert update._plus_gueltig() is False
    assert aufrufe[0][-2:] == ["plus", "lizenz"]
    monkeypatch.setenv("BELEGE_PLUS", str(tmp_path / "fehlt"))
    assert update._plus_gueltig() is False
