"""Gemeinsame Test-Umgebung: ein Repo im tmp-Ordner, ohne Modell, Netz und Konten."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from belege import kern

ECHT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    shutil.copytree(ECHT / "konfig", tmp_path / "konfig")
    if (ECHT / "vorlagen").exists():
        shutil.copytree(ECHT / "vorlagen", tmp_path / "vorlagen")
    for ordner in ("arbeit", "ablage", "handy", "downloads", "auszuege", "beispiel/erzeugt/postfach"):
        (tmp_path / ordner).mkdir(parents=True, exist_ok=True)
    toml = tmp_path / "konfig" / "belege.toml"
    t = toml.read_text(encoding="utf-8")
    t = t.replace('ordner = "~/Belege"', f'ordner = "{tmp_path / "ablage"}"')
    t = t.replace('handy_ordner = "~/Belege/Eingang"', f'handy_ordner = "{tmp_path / "handy"}"')
    t = t.replace('downloads = "~/Downloads"', f'downloads = "{tmp_path / "downloads"}"')
    t = t.replace('auszuege = "~/Belege/Kontoauszuege"', f'auszuege = "{tmp_path / "auszuege"}"')
    toml.write_text(t, encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)
    monkeypatch.setenv("BELEGE_ROOT", str(tmp_path))
    monkeypatch.setenv("URTEIL_BACKEND", "ohne")
    yield tmp_path
