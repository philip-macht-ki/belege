"""Fängt einen Start mit zu altem Python ab, bevor ein Import scheitert.

belege braucht Python 3.11 oder neuer (tomllib). `uv run belege …` sorgt dafür
von allein. Wer stattdessen `python3 -m belege.cli …` oder `/usr/bin/python3 …`
tippt, landet auf dem Mac oft bei Apples Python 3.9. Dann startet dieser Wächter
denselben Aufruf mit dem Python aus `.venv` (oder über uv) neu; geht das nicht,
erklärt er auf Deutsch, was zu tun ist, statt einen Traceback zu zeigen.

Absichtlich ohne Syntax neuer als 3.9, sonst greift er auf altem Python nicht.
"""
import os
import shutil
import subprocess
import sys

MINDEST = (3, 11)
MERKER = "BELEGE_PYTHON_NEUSTART"
PAKET = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.dirname(PAKET)


def _modul_bei_m():
    """Bei `python3 -m belege.x` steht in sys.argv[0] beim Paketimport nur „-m“; runpy kennt den Namen."""
    rahmen = sys._getframe()
    while rahmen is not None:
        if os.path.basename(rahmen.f_code.co_filename) == "runpy.py":
            name = rahmen.f_locals.get("mod_name")
            if isinstance(name, str) and name.split(".")[0] == "belege":
                return name
        rahmen = rahmen.f_back
    return None


def ziel(argv, paket=PAKET, modul_bei_m=_modul_bei_m):
    """Argumente für den Neustart, ohne Interpreter; None, wenn keine Skriptdatei da ist."""
    if argv and argv[0] == "-m":
        modul = modul_bei_m()
        return ["-m", modul] + list(argv[1:]) if modul else None
    if not argv or not argv[0] or not os.path.isfile(argv[0]):
        return None  # etwa `python3 -c …` oder eine interaktive Sitzung
    skript = os.path.abspath(argv[0])
    if os.path.dirname(skript) == paket and skript.endswith(".py"):
        modul = os.path.splitext(os.path.basename(skript))[0]
        return ["-m", "belege" if modul == "__main__" else "belege." + modul] + list(argv[1:])
    return [skript] + list(argv[1:])


def _neu_genug(befehl):
    try:
        aus = subprocess.run(
            befehl + ["-c", "import sys; print(int(sys.version_info >= %r))" % (MINDEST,)],
            capture_output=True, text=True, timeout=60,
        )
        return aus.returncode == 0 and aus.stdout.strip().endswith("1")
    except (OSError, subprocess.SubprocessError):
        return False


def interpreter(projekt=PROJEKT):
    """Ein Python ab 3.11 mit den Paketen von belege: zuerst `.venv`, sonst über uv."""
    for teil in (("bin", "python"), ("Scripts", "python.exe")):
        pfad = os.path.join(projekt, ".venv", *teil)
        if os.access(pfad, os.X_OK) and _neu_genug([pfad]):
            return [pfad]
    uv = shutil.which("uv") or next(
        (p for p in (os.path.expanduser("~/.local/bin/uv"), os.path.expanduser("~/.cargo/bin/uv")) if os.access(p, os.X_OK)),
        None,
    )
    if uv:
        befehl = [uv, "run", "--quiet", "--project", projekt, "python"]
        if _neu_genug(befehl):
            return befehl
    return None


def hinweis():
    ist = ".".join(str(x) for x in sys.version_info[:3])
    return (
        "\nbelege braucht Python %d.%d oder neuer. Gestartet wurde es mit Python %s (%s).\n\n"
        "So geht es: im Ordner von belege immer `uv run belege …` nutzen, nicht `python3 …`.\n"
        "Klappt das auch nicht, sag deinem Claude: „Richte Python für belege ein“.\n"
        "Claude führt dann `uv python install 3.12` und `uv sync` aus.\n\n"
        % (MINDEST[0], MINDEST[1], ist, sys.executable)
    )


def sicherstellen():
    if sys.version_info >= MINDEST:
        return
    argumente = ziel(sys.argv)
    befehl = None if (argumente is None or os.environ.get(MERKER)) else interpreter()
    if not befehl:
        sys.stderr.write(hinweis())
        raise SystemExit(2)
    umgebung = dict(os.environ)
    umgebung[MERKER] = "1"
    umgebung["PYTHONPATH"] = os.pathsep.join(p for p in (PROJEKT, umgebung.get("PYTHONPATH")) if p)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        raise SystemExit(subprocess.call(befehl + argumente, env=umgebung))
    os.execve(befehl[0], befehl + argumente, umgebung)


sicherstellen()
