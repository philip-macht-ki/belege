"""Welcher Mac ist das? Selbst nachsehen statt fragen.

Viele wissen nicht, welchen Mac sie haben. Ein Akku heißt MacBook, alles andere
gilt als Dauerrechner (Mac mini, iMac, Mac Studio). Daraus folgen nur weiche
Voreinstellungen: Lebenszeichen, ob ein lokales Modell passt, Hinweise.

    belege rechner          zeigt, was erkannt wurde
    belege rechner --echt   merkt es sich in arbeit/rechner.json
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

from . import kern


def _aus(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def art() -> str:
    """„macbook“, wenn ein eingebauter Akku da ist, sonst „dauerrechner“."""
    return "macbook" if "InternalBattery" in _aus(["pmset", "-g", "batt"]) else "dauerrechner"


def erkennen() -> dict:
    """Modell, Chip, Arbeitsspeicher, freier Platz und Stromquelle dieses Macs."""
    hardware = _aus(["system_profiler", "SPHardwareDataType"])

    def feld(name: str) -> str:
        treffer = re.search(rf"^\s*{name}:\s*(.+)$", hardware, re.M)
        return treffer.group(1).strip() if treffer else ""

    try:
        ram = int(_aus(["sysctl", "-n", "hw.memsize"]).strip()) // 1024**3
    except ValueError:
        ram = 0
    frei = shutil.disk_usage(str(kern.pfad())).free // 1024**3
    batt = _aus(["pmset", "-g", "batt"])
    return {
        "art": "macbook" if "InternalBattery" in batt else "dauerrechner",
        "modell": feld("Model Name") or _aus(["sysctl", "-n", "hw.model"]).strip(),
        "chip": feld("Chip") or feld("Processor Name"),
        "ram_gb": ram,
        "frei_gb": frei,
        "am_netzteil": "AC Power" in batt,
        "lokales_modell": "qwen3:8b" if ram >= 16 else "keins",
    }


def befehl(args) -> int:
    daten = erkennen()
    print(json.dumps(daten, ensure_ascii=False, indent=2))
    if kern.echt(args):
        kern.schreiben(kern.pfad("arbeit", "rechner.json"), {**daten, "erkannt": kern.jetzt().isoformat()})
    return 0
