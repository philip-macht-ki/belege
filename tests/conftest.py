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
    # Ab Werk aus (erst Teil 3); die Tests spielen eine fertige Einrichtung durch.
    t = t.replace("downloads_an = false", "downloads_an = true")
    toml.write_text(t, encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)
    monkeypatch.setenv("BELEGE_ROOT", str(tmp_path))
    monkeypatch.setenv("URTEIL_BACKEND", "ohne")
    yield tmp_path


@pytest.fixture(autouse=True)
def kein_lokales_modell(monkeypatch):
    """Tests fragen nie ein echtes Ollama; wer das Modell braucht, setzt es selbst."""
    from belege import vertraulich

    monkeypatch.setattr(vertraulich, "lokales_modell", lambda: None)


@pytest.fixture(autouse=True)
def kein_netz_fuer_rechnungslinks(monkeypatch):
    """Rechnungslinks laden in Tests nie wirklich; wer Netz braucht, ersetzt beides selbst."""
    from belege import rechnungslink

    def _verboten(*_a, **_k):
        raise AssertionError("Test hat versucht, einen Rechnungslink wirklich zu laden")

    monkeypatch.setattr(rechnungslink, "_host_erlaubt", lambda host, port: False)
    monkeypatch.setattr(rechnungslink, "_anfrage", _verboten)


@pytest.fixture(autouse=True)
def kein_starter_auffrischen(monkeypatch):
    """Ein Testlauf von `takt` fasst nie die echten Starter in ~/.local/bin an."""
    from belege import takt

    monkeypatch.setattr(takt, "_starter_auffrischen", lambda: False)
