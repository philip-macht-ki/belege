"""Die regelmäßigen Läufe bei launchd bzw. der Windows-Aufgabenplanung an- und abmelden.

Ohne --echt wird nur gezeigt, was eingerichtet würde. Mit --echt wird vorher
nachgefragt. Weil der Claude der Person nicht in ein Terminal tippen kann, gilt
`BELEGE_JA=1` als Antwort „ja“, aber nur zusammen mit --echt.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .kern import echt, fremder_rechner, konfig, pfad, rechner
from .plattform import ist_windows

LAEUFE = ("takt", "tag", "monat", "posten", "update")
# Optional, nur wenn konfig/moneymoney.toml `an = true` sagt.
ZUSATZ = ("moneymoney",)


def laeufe() -> tuple[str, ...]:
    """Die Läufe, die `zeitplan an` einrichtet."""
    from .moneymoney import einstellungen

    k = konfig("belege")
    basis = tuple(n for n in LAEUFE if n != "update" or k.get("update", {}).get("automatisch", True))
    return basis + (("moneymoney",) if einstellungen().get("an") else ())


def neu_laden() -> None:
    """Schreibt die vorhandenen Zeitpläne nach einem Update neu, ohne Uhrzeiten zu ändern."""
    if ist_windows():
        for name in laeufe():
            _windows_anmelden(name)
        return
    uid = os.getuid()
    for name in laeufe():
        ziel = _ziel(name)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(plist_text(name), encoding="utf-8")
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{_label(name)}"], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(ziel)], check=True)


def _label(name: str) -> str:
    return f"de.belege.{name}"


def _ziel(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_label(name)}.plist"


def _task_name(name: str) -> str:
    return f"belege {name}"


def _powershell_befehl(name: str) -> str:
    uv = (shutil.which("uv") or "uv").replace("'", "''")
    ordner = str(pfad()).replace("'", "''")
    befehle = {
        "takt": "takt --echt", "tag": "tag --echt",
        "monat": "monat --uebergabe --echt", "posten": "monat --zwischenstand --echt; & '{uv}' run belege posten --mail --echt",
        "update": "aktualisieren --automatisch --echt", "moneymoney": "moneymoney --echt",
    }
    lauf = f"& '{uv}' run belege " + befehle[name].format(uv=uv)
    if name == "monat":
        lauf = "if ((Get-Date).Day -ge 3) { " + lauf + " }"
    return f"Set-Location -LiteralPath '{ordner}'; {lauf}"


def windows_xml(name: str) -> str:
    """Task-Scheduler-XML; StartWhenAvailable holt verpasste Läufe nach."""
    start = "2020-01-01T00:00:00"
    if name == "takt":
        trigger = f"<TimeTrigger><StartBoundary>{start}</StartBoundary><Repetition><Interval>PT{int(konfig('belege').get('takt', {}).get('minuten', 15))}M</Interval></Repetition></TimeTrigger>"
    elif name == "tag":
        hour, minute = str(konfig("belege").get("takt", {}).get("tag_uhrzeit", "21:00")).split(":")
        trigger = f"<CalendarTrigger><StartBoundary>2020-01-01T{int(hour):02}:{int(minute):02}:00</StartBoundary><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
    elif name == "posten":
        trigger = "<CalendarTrigger><StartBoundary>2020-01-01T07:00:00</StartBoundary><ScheduleByMonth><DaysOfMonth><Day>1</Day><Day>15</Day></DaysOfMonth><Months><January/><February/><March/><April/><May/><June/><July/><August/><September/><October/><November/><December/></Months></ScheduleByMonth></CalendarTrigger>"
    elif name == "update":
        trigger = "<CalendarTrigger><StartBoundary>2020-01-04T06:00:00</StartBoundary><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Sunday/></DaysOfWeek></ScheduleByWeek></CalendarTrigger>"
    elif name == "moneymoney":
        trigger = "<CalendarTrigger><StartBoundary>2020-01-01T07:00:00</StartBoundary><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger><CalendarTrigger><StartBoundary>2020-01-01T19:00:00</StartBoundary><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
    else:  # monat
        trigger = "<CalendarTrigger><StartBoundary>2020-01-01T09:00:00</StartBoundary><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
    root = ET.Element("Task", {"version": "1.4", "xmlns": "http://schemas.microsoft.com/windows/2004/02/mit/task"})
    triggers = ET.SubElement(root, "Triggers")
    # XML aus der festen Vorlage kontrolliert einfügen; keine fremden Werte.
    wrapper = ET.fromstring(f"<W xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task'>{trigger}</W>")
    triggers.extend(list(wrapper))
    principals = ET.SubElement(root, "Principals")
    ET.SubElement(ET.SubElement(principals, "Principal", {"id": "Author"}), "LogonType").text = "InteractiveToken"
    settings = ET.SubElement(root, "Settings")
    ET.SubElement(settings, "StartWhenAvailable").text = "true"
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "AllowStartOnDemand").text = "true"
    actions = ET.SubElement(root, "Actions", {"Context": "Author"})
    action = ET.SubElement(actions, "Exec")
    ET.SubElement(action, "Command").text = "powershell.exe"
    ET.SubElement(action, "Arguments").text = "-NoProfile -ExecutionPolicy Bypass -Command " + _powershell_befehl(name)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _windows_anmelden(name: str) -> None:
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-16", delete=False) as datei:
        datei.write(windows_xml(name))
        xml = datei.name
    try:
        subprocess.run(["schtasks.exe", "/Create", "/TN", _task_name(name), "/XML", xml, "/F"], check=True, capture_output=True)
    finally:
        Path(xml).unlink(missing_ok=True)


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
    if ist_windows():
        r = subprocess.run(["schtasks.exe", "/Query", "/TN", _task_name(name)], capture_output=True)
        return r.returncode == 0
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
    erlaubt = fremder_rechner()
    if erlaubt:
        print(f"fehler: Der Zeitplan gehört auf {erlaubt}, dieser Rechner heißt {rechner()}. Nichts eingerichtet.")
        return 1
    if not _zugestimmt():
        print("nichts: abgebrochen.")
        return 0
    if ist_windows():
        for name in laeufe():
            _windows_anmelden(name)
    else:
        uid = os.getuid()
        for name in laeufe():
            ziel = _ziel(name)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_text(plist_text(name), encoding="utf-8")
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{_label(name)}"], capture_output=True)
            subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(ziel)], check=True)
    from .update import einrichtung_merken

    einrichtung_merken()  # Start der vier Wochen mit automatischen Updates, nur nach echter Einrichtung
    print("ok: Zeitplan eingerichtet. Prüfen mit: uv run belege zeitplan zeigen")
    return 0


def _aus() -> int:
    """Abmelden und die Dateien nach arbeit/zeitplan-alt/ verschieben, nicht löschen."""
    if ist_windows():
        for name in LAEUFE + ZUSATZ:
            subprocess.run(["schtasks.exe", "/Delete", "/TN", _task_name(name), "/F"], capture_output=True)
        print("ok: Zeitplan ausgeschaltet.")
        return 0
    alt = pfad("arbeit", "zeitplan-alt")
    alt.mkdir(parents=True, exist_ok=True)
    for name in LAEUFE + ZUSATZ:
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
        for name in laeufe():
            print(f"{'an ' if angemeldet(name) else 'aus'}: {_label(name)}")
        return 0
    if aktion not in ("an", "aus"):
        print("fehler: Nutze: belege zeitplan an | aus | zeigen")
        return 2
    if not echt(args):
        tun = "einrichten" if aktion == "an" else "ausschalten"
        print(f"trocken: würde {tun}: " + ", ".join(_label(n) for n in (laeufe() if aktion == "an" else LAEUFE + ZUSATZ)))
        if aktion == "an":
            print(windows_xml("takt") if ist_windows() else plist_text("takt"))
        return 0
    try:
        return _an() if aktion == "an" else _aus()
    except Exception as fehler:  # noqa: BLE001
        print(f"fehler: Zeitplan nicht geändert: {fehler}")
        return 1
