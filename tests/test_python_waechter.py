import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from belege import _python_waechter as w

REPO = Path(__file__).resolve().parents[1]
ALT = "/usr/bin/python3"


def test_waechter_und_paketkopf_parsen_mit_python_39():
    # Greift nur, wenn Python 3.9 die Dateien überhaupt lesen kann.
    for datei in ("belege/_python_waechter.py", "belege/__init__.py"):
        ast.parse((REPO / datei).read_text(encoding="utf-8"), feature_version=(3, 9))


def test_ziel_baut_den_gleichen_aufruf_nach(tmp_path):
    paket = tmp_path / "belege"
    paket.mkdir()
    (paket / "cli.py").write_text("", encoding="utf-8")
    fremd = tmp_path / "skript.py"
    fremd.write_text("", encoding="utf-8")
    assert w.ziel([str(paket / "cli.py"), "monat", "--echt"], str(paket)) == ["-m", "belege.cli", "monat", "--echt"]
    assert w.ziel([str(fremd), "a b"], str(paket)) == [str(fremd), "a b"]
    assert w.ziel(["-m", "--help"], str(paket), lambda: "belege.cli") == ["-m", "belege.cli", "--help"]
    assert w.ziel(["-m"], str(paket), lambda: None) is None
    assert w.ziel(["-c"], str(paket)) is None
    assert w.ziel([], str(paket)) is None


def test_hinweis_ist_deutsch_und_nennt_die_loesung():
    text = w.hinweis()
    assert "uv run belege" in text and "uv python install 3.12" in text


def _altes_python():
    if not os.path.exists(ALT):
        return None
    aus = subprocess.run([ALT, "-c", "import sys; print(int(sys.version_info < (3, 11)))"], capture_output=True, text=True)
    return ALT if aus.stdout.strip() == "1" else None


@pytest.mark.skipif(not _altes_python(), reason="kein Python unter 3.11 auf diesem Rechner")
def test_altes_python_startet_belege_neu():
    if not (REPO / ".venv").exists() and not shutil.which("uv"):
        pytest.skip("weder .venv noch uv da")
    env = {k: v for k, v in os.environ.items() if k not in (w.MERKER, "VIRTUAL_ENV", "PYTHONPATH")}
    aus = subprocess.run([ALT, "-m", "belege.cli", "--help"], cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert aus.returncode == 0, aus.stderr
    assert "usage: belege" in aus.stdout


@pytest.mark.skipif(not _altes_python(), reason="kein Python unter 3.11 auf diesem Rechner")
def test_altes_python_ohne_skript_erklaert_statt_traceback():
    aus = subprocess.run([ALT, "-c", "import belege"], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert aus.returncode == 2
    assert "Traceback" not in aus.stderr
    assert "uv run belege" in aus.stderr


def test_neues_python_bleibt_unberuehrt():
    assert sys.version_info >= w.MINDEST
