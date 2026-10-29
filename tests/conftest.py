"""Gemeinsame Test-Umgebung: ein Repo im tmp-Ordner, ohne Modell, Netz und Konten."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

ECHT = Path(__file__).resolve().parents[1]

# Schon beim Import der Testmodule (etwa `kern.zone()` auf Modulebene) darf nichts die
# echte Einrichtung lesen oder anlegen: Wurzel vor dem ersten Import von belege umbiegen.
_IMPORT_WURZEL = Path(tempfile.mkdtemp(prefix="belege-tests-"))
shutil.copytree(ECHT / "vorlagen", _IMPORT_WURZEL / "vorlagen")
os.environ["BELEGE_ROOT"] = str(_IMPORT_WURZEL)

from belege import kern  # noqa: E402


@pytest.fixture(autouse=True)
def abgeschirmt(tmp_path_factory, monkeypatch):
    """Jeder Test läuft gegen einen leeren Wurzelordner, nie gegen das echte Repo:
    keine echte konfig/, keine .env mit Zugangsdaten, nichts landet in arbeit/."""
    wurzel = tmp_path_factory.mktemp("abgeschirmt")
    shutil.copytree(ECHT / "vorlagen", wurzel / "vorlagen")
    monkeypatch.setattr(kern, "ROOT", wurzel)
    monkeypatch.setenv("BELEGE_ROOT", str(wurzel))
    yield wurzel


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # Immer die Werksvorlage, nie die echte konfig/ einer fertigen Einrichtung: sonst
    # greifen eigene Regeln und echte Postfächer in die Tests ein.
    shutil.copytree(ECHT / "vorlagen" / "konfig", tmp_path / "konfig")
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
