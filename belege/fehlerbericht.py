"""Geschwärzten Diagnosebericht erzeugen, ohne Zugänge oder Belege zu lesen."""
from __future__ import annotations

import platform
import re
import subprocess
import tomllib

from . import __version__, kern

SUPPORT_ADRESSE = "info@deern-jung.com"


def schwaerzen(text: str) -> str:
    """Entfernt typische personenbezogene und geheime Werte aus Diagnoseausgaben."""
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<mail>", text)
    text = re.sub(r"(?i)\b[A-Z]{2}\d{2}(?:[ ]?\d){10,30}(?![\d.])\b", "<iban>", text)
    text = re.sub(r"(?<![\w.])-?\d{1,3}(?:[. ]\d{3})*,\d{2}(?!\d)", "<betrag>", text)
    text = re.sub(r"(?<![\w.])-?\d+\.\d{2}(?!\d)", "<betrag>", text)
    geheim_name = r"(?:access_token|refresh_token|client_secret|api[_ -]?key|token|passwort|password|secret)"
    # Werte in Anführungszeichen ganz, auch mit Leerzeichen; sonst bis zum nächsten Trenner.
    text = re.sub(rf'(?i)(["\']?{geheim_name}["\']?\s*[:=]\s*)(?:"[^"\r\n]*"|\'[^\'\r\n]*\'|[^,\s}}]+)', r"\1<geheimnis>", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer <geheimnis>", text)
    # Der ganze Pfad wird ersetzt: Dateinamen dürfen Leerzeichen und Umlaute enthalten.
    text = re.sub(
        r"(?i)(?:(?:~|/|[A-Za-z]:[\\/])[^\r\n]*?\.(?:pdf|png|jpg|jpeg|heic|xml|zip)\b|\b[^\s/\\]+\.(?:pdf|png|jpg|jpeg|heic|xml|zip)\b)",
        "<datei>", text,
    )
    return text


def _system() -> str:
    modell = platform.mac_ver()[0] or platform.platform()
    try:
        macos = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True, timeout=3).stdout.strip()
        if macos:
            modell = f"macOS {macos}"
        modell += ", " + subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=3).stdout.strip()
        ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout.strip())
        modell += f", {ram // 1024**3} GB RAM"
    except Exception:
        pass
    return modell


def _konfig_struktur() -> str:
    """Liest nur die Form der Konfiguration, nie Adressen oder Zugangswerte."""
    datei = kern.pfad("konfig", "belege.toml")
    try:
        with datei.open("rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return "nicht lesbar"
    konten = cfg.get("konto", [])
    wege = {w: sum(1 for k in konten if isinstance(k, dict) and k.get("weg", "a") == w)
            for w in ("a", "b", "microsoft", "ordner")}
    return ", ".join(f"{weg}={anzahl}" for weg, anzahl in wege.items())


def _letzte_datei(teil: str, muster: str) -> str:
    """Gibt nur lokale, bereits gespeicherte Diagnosezeilen zurück."""
    try:
        dateien = sorted(kern.pfad("arbeit", teil).glob(muster))
        if not dateien:
            return "kein gespeicherter Stand"
        return "\n".join(dateien[-1].read_text(encoding="utf-8", errors="replace").splitlines()[-60:])
    except OSError:
        return "nicht lesbar"


def befehl(args) -> int:
    # Kein Aufruf von pruefen: Dieser Bericht darf weder Netz noch Token oder Geheimnisse berühren.
    logauszug = _letzte_datei("logs", "*.log")
    status = _letzte_datei("", "status*.txt")
    text = (f"# Fehlerbericht\n\nBelege-Version: {__version__}\n\nSystem: {_system()}\n\n"
            f"Konten: {_konfig_struktur()}\n\n## Letzter gespeicherter Status\n\n{status}\n\n"
            f"## Letzte Logzeilen\n\n{logauszug}\n\n"
            f"Schick diesen Text an {SUPPORT_ADRESSE}.")
    text = schwaerzen(text)
    ziel = kern.pfad("arbeit", f"fehlerbericht-{kern.jetzt():%Y-%m-%d-%H%M}.md")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    print(text)
    return 0
