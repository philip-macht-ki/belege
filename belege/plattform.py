"""Kleine, zentrale Plattformabfrage.

Linux folgt bei belege dem portablen/macOS-nahen Weg; nur Windows braucht
eigene Aufrufe für Aufgabenplanung und Dialoge.
"""
from __future__ import annotations

import sys


def ist_windows() -> bool:
    return sys.platform.startswith("win")


def ist_mac() -> bool:
    return sys.platform == "darwin"
