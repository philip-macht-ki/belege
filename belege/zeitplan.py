"""Die drei regelmäßigen Läufe bei launchd an- und abmelden.

Ohne --echt wird nur gezeigt, was eingerichtet würde. Mit --echt wird vorher
nachgefragt. Weil der Claude der Person nicht in ein Terminal tippen kann, gilt
`BELEGE_JA=1` als Antwort „ja“, aber nur zusammen mit --echt.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .kern import echt, konfig, pfad

LAEUFE = ("takt", "tag", "monat")


def _label(name: str) -> str:
    return f"de.belege.{name}"


def _ziel(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_label(name)}.plist"


def plist_text(name: str) -> str:
    """Füllt die Vorlage aus zeitplan/ mit Repo-Pfad, uv und den Zeiten aus der Konfiguration."""
    k = konfig("belege")
    stunde, minute = str(k.get("takt", {}).get("tag_uhrzeit", "21:00")).split(":")
    werte = {
        "__REPO__": str(pfad()),
        "__UV__": shutil.which("uv") or "uv",
        "__SEKUNDEN__": str(int(k.get("takt", {}).get("minuten", 15)) * 60),
        "__STUNDE__": str(int(stunde)),
        "__MINUTE__": str(int(minute)),
        "__TAG__": str(int(k.get("uebergabe", {}).get("tag", 3))),
    }
    text = pfad("zeitplan", f"{_label(name)}.plist.vorlage").read_text(encoding="utf-8")
    for platzhalter, wert in werte.items():
        text = text.replace(platzhalter, wert)
    return text


def angemeldet(name: str) -> bool:
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{_label(name)}"], capture_output=True)
    return r.returncode == 0


def _zugestimmt() -> bool:
    if os.environ.get("BELEGE_JA") == "1":
        return True
    if not sys.stdin.isatty():
        print("nichts: Keine Rückfrage möglich. Frag die Person und setz dann BELEGE_JA=1.")
        return False
    return input("Zeitplan wirklich einrichten? [ja] ").strip().lower() == "ja"


def _an() -> int:
    if not _zugestimmt():
        print("nichts: abgebrochen.")
        return 0
    uid = os.getuid()
    for name in LAEUFE:
        ziel = _ziel(name)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(plist_text(name), encoding="utf-8")
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{_label(name)}"], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(ziel)], check=True)
    print("ok: Zeitplan eingerichtet. Prüfen mit: uv run belege zeitplan zeigen")
    return 0


def _aus() -> int:
    """Abmelden und die Dateien nach arbeit/zeitplan-alt/ verschieben, nicht löschen."""
    alt = pfad("arbeit", "zeitplan-alt")
    alt.mkdir(parents=True, exist_ok=True)
    for name in LAEUFE:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{_label(name)}"], capture_output=True)
        ziel = _ziel(name)
        if ziel.exists():
            ziel.replace(alt / ziel.name)
    print("ok: Zeitplan ausgeschaltet.")
    return 0


def befehl(args) -> int:
    """`belege zeitplan an|aus|zeigen`."""
    aktion = (getattr(args, "ziel", None) or ["zeigen"])[0]
    if aktion == "zeigen":
        for name in LAEUFE:
            print(f"{'an ' if angemeldet(name) else 'aus'}: {_label(name)}")
        return 0
    if aktion not in ("an", "aus"):
        print("fehler: Nutze: belege zeitplan an | aus | zeigen")
        return 2
    if not echt(args):
        tun = "einrichten" if aktion == "an" else "ausschalten"
        print(f"trocken: würde {tun}: " + ", ".join(_label(n) for n in LAEUFE))
        if aktion == "an":
            print(plist_text("takt"))
        return 0
    try:
        return _an() if aktion == "an" else _aus()
    except Exception as fehler:  # noqa: BLE001
        print(f"fehler: Zeitplan nicht geändert: {fehler}")
        return 1
