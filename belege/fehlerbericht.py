"""Geschwärzten Diagnosebericht erzeugen, ohne Zugänge oder Belege zu lesen."""
from __future__ import annotations

import io
import platform
import re
import subprocess
from contextlib import redirect_stdout

from . import __version__, kern

SUPPORT_ADRESSE = "info@deern-jung.com"


def schwaerzen(text: str) -> str:
    """Entfernt typische personenbezogene und geheime Werte aus Diagnoseausgaben."""
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<mail>", text)
    text = re.sub(r"\b[A-Z]{2}\d{2}(?:[ ]?\d){10,30}\b", "<iban>", text)
    text = re.sub(r"(?i)\b\d{1,3}(?:[. ]\d{3})*,\d{2}\s*(?:€|eur)\b", "<betrag>", text)
    text = re.sub(r"(?i)\b(?:token|passwort|password|secret|api[_ -]?key)\s*[:=]\s*\S+", "<geheimnis>", text)
    text = re.sub(r"(?i)\b[^\s/]+\.(?:pdf|xml|jpg|jpeg|png|heic|tif|tiff|docx)\b", "<datei>", text)
    return text


def _system() -> str:
    modell = platform.mac_ver()[0] or platform.platform()
    try:
        modell += ", " + subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=3).stdout.strip()
        ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout.strip())
        modell += f", {ram // 1024**3} GB RAM"
    except Exception:
        pass
    return modell


def befehl(args) -> int:
    from . import pruefen
    ausgabe = io.StringIO()
    with redirect_stdout(ausgabe):
        pruefen.befehl(args)
    cfg = kern.konfig("belege")
    konten = cfg.get("konto", [])
    wege = {w: sum(1 for k in konten if k.get("weg", "a") == w) for w in ("a", "b", "microsoft", "ordner")}
    ablage = str(kern.ablage_ordner()).replace(str(__import__("pathlib").Path.home()), "~")
    logs = sorted(kern.pfad("arbeit", "logs").glob("*.log"))
    letzte = "\n".join(line for p in logs for line in p.read_text(encoding="utf-8", errors="replace").splitlines())
    logauszug = "\n".join(letzte.splitlines()[-60:])
    text = (f"# Fehlerbericht\n\nBelege-Version: {__version__}\n\nSystem: {_system()}\n\n"
            f"Konten: " + ", ".join(f"{w}={n}" for w, n in wege.items()) + f"\n\nAblage: {ablage}\n\n"
            f"## Prüfung\n\n{ausgabe.getvalue()}\n## Letzte Logzeilen\n\n{logauszug}\n\n"
            f"Schick diesen Text an {SUPPORT_ADRESSE}.")
    text = schwaerzen(text)
    ziel = kern.pfad("arbeit", f"fehlerbericht-{kern.jetzt():%Y-%m-%d-%H%M}.md")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    print(text)
    return 0
