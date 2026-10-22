from pathlib import Path
import os
import subprocess

from belege import einrichten


def test_claude_starter_markiert_und_legt_an(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ok, ziel = einrichten.anlegen()
    assert ok
    assert einrichten.MARKER in Path(ziel).read_text()
    assert 'claude.app/Contents/MacOS/claude' in Path(ziel).read_text()


def test_claude_starter_ueberschreibt_fremde_datei_nicht(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ziel = tmp_path / ".local/bin/claude"
    ziel.parent.mkdir(parents=True)
    ziel.write_text("fremd")
    ok, _ = einrichten.anlegen()
    assert not ok
    assert ziel.read_text() == "fremd"


def test_claude_starter_nimmt_hoehere_versionsnummer(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    original = einrichten.starter_text
    monkeypatch.setattr(
        einrichten, "starter_text",
        lambda: original().replace(
            '"$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude',
            '"$HOME/kein-cli"',
        ),
    )
    basis = tmp_path / "Library/Application Support/Claude/claude-code"
    for version in ("2.1.99", "2.1.304"):
        cli = basis / version / "claude.app/Contents/MacOS/claude"
        cli.parent.mkdir(parents=True)
        cli.write_text(f"#!/bin/zsh\necho {version}\n")
        cli.chmod(0o755)
    ok, ziel = einrichten.anlegen()
    assert ok
    ergebnis = subprocess.run(
        [ziel], capture_output=True, text=True, check=True,
        env={"HOME": str(tmp_path), "PATH": os.environ["PATH"]},
    )
    assert ergebnis.stdout.strip() == "2.1.304"
