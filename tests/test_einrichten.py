from pathlib import Path

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
