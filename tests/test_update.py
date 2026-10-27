import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

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


def _release(quelle, version="1.5.0", aktion="keine"):
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
    assert "Version 1.5.0" in capsys.readouterr().out


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
