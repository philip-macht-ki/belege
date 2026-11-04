"""Kleine, nachvollziehbare Stichwortregeln für die Einordnung."""
from __future__ import annotations
import json
from . import kern


def befehl(args) -> int:
    wort = " ".join(args.ziel).strip()
    if not wort or (not args.privat and not args.betrieb) or (args.privat and args.betrieb):
        print("fehler: Nutze: belege regel STICHWORT --privat|--betrieb [--echt]")
        return 2
    bereich = "privat" if args.privat else "betrieb"
    # JSON-Zeichenketten sind gültige TOML-Basiszeichenketten, auch mit Anführungszeichen im Wort.
    eintrag = f'[[stichwort]]\nwort = {json.dumps(wort, ensure_ascii=False)}\nbereich = "{bereich}"\n'
    if not kern.echt(args):
        print("trocken: würde folgende Regel eintragen:\n" + eintrag, end="")
        return 0
    ziel = kern.pfad("konfig", "regeln.toml")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if not ziel.exists():
        kern.konfig("regeln")
    with ziel.open("a", encoding="utf-8") as datei:
        datei.write("\n" + eintrag)
    print(f"ok: Stichwort „{wort}“ wird als {bereich} behandelt.")
    return 0
