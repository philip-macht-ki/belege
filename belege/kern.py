"""Gemeinsamer Kern: Pfade, Konfiguration, JSON, Zeit, Sperre, Protokoll, Ereignisse.

Jeder Schritt gibt ein `Ergebnis` zurück, statt still zu scheitern.
Formate der Dateien stehen in ARCHITEKTUR.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("BELEGE_ROOT", Path(__file__).resolve().parents[1]))


def _env_laden() -> None:
    """Liest .env im Repo-Ordner (NAME=wert je Zeile). Die Umgebung hat Vorrang."""
    datei = ROOT / ".env"
    if not datei.exists():
        return
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        os.environ.setdefault(name.strip(), wert.strip().strip('"').strip("'"))


_env_laden()


@dataclass
class Ergebnis:
    """status: ok | befund | fehler | nichts. Ein Befund stoppt nichts, er wird gezeigt."""

    status: str
    meldung: str = ""
    daten: dict = field(default_factory=dict)

    @property
    def gut(self) -> bool:
        return self.status in ("ok", "befund", "nichts")


def konfig(name: str) -> dict:
    """Liest konfig/<name> (mit oder ohne .toml)."""
    datei = ROOT / "konfig" / (name if name.endswith(".toml") else f"{name}.toml")
    with open(datei, "rb") as f:
        return tomllib.load(f)


def pfad(*teile: str | Path) -> Path:
    return ROOT.joinpath(*[str(t) for t in teile])


def lesen(p: Path, standard=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return standard


def schreiben(p: Path, daten) -> None:
    """Schreibt JSON atomar, damit ein Abbruch keine halbe Datei hinterlässt."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def zone() -> ZoneInfo:
    return ZoneInfo(konfig("belege").get("zeitzone", "Europe/Berlin"))


def jetzt() -> datetime:
    return datetime.now(zone())


def lauf(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Führt einen Befehl aus. Wirft mit lesbarer Meldung, wenn er scheitert."""
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode != 0:
        schwanz = (r.stderr or r.stdout or "").strip().splitlines()[-8:]
        raise RuntimeError(f"{Path(str(cmd[0])).name} scheiterte ({r.returncode}): " + " | ".join(schwanz))
    return r


def log(zeile: str) -> None:
    """Eine Zeile ins Tagesprotokoll arbeit/logs/<datum>.log und auf den Bildschirm."""
    t = jetzt()
    ziel = pfad("arbeit", "logs", f"{t:%Y-%m-%d}.log")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "a", encoding="utf-8") as f:
        f.write(f"{t:%H:%M:%S} {zeile}\n")
    print(zeile, flush=True)


class Sperre:
    """Verhindert zwei gleichzeitige Läufe. Prüft die PID, nicht den Befehlstext
    (pgrep findet sonst die eigene Diagnose-Shell)."""

    def __init__(self, name: str = "lauf"):
        self.p = pfad("arbeit", f".{name}.pid")

    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        if self.p.exists():
            try:
                pid = int(self.p.read_text().strip())
                os.kill(pid, 0)
                raise RuntimeError(f"Ein Lauf ist schon aktiv (PID {pid}).")
            except (ValueError, ProcessLookupError):
                pass  # verwaiste Sperre von einem abgebrochenen Lauf
            except PermissionError:
                raise RuntimeError("Ein Lauf ist schon aktiv.")
        self.p.write_text(str(os.getpid()))
        return self

    def __exit__(self, *_):
        self.p.unlink(missing_ok=True)


def ereignis(art: str, text: str, **daten) -> None:
    """Eine Zeile nach arbeit/ereignisse/<datum>.jsonl. Nur hier wird die Datei geschrieben;
    der Bericht liest ausschließlich dort."""
    t = jetzt()
    ziel = pfad("arbeit", "ereignisse", f"{t:%Y-%m-%d}.jsonl")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zeile = {"zeit": t.isoformat(timespec="seconds"), "art": art, "text": text, "daten": daten}
    with open(ziel, "a", encoding="utf-8") as f:
        f.write(json.dumps(zeile, ensure_ascii=False, default=str) + "\n")


def ereignisse(seit: datetime | None = None) -> list[dict]:
    """Alle Ereignisse von gestern und heute, optional erst ab `seit`."""
    from datetime import timedelta

    heute = jetzt().date()
    zeilen: list[dict] = []
    for tag in (heute - timedelta(days=1), heute):
        datei = pfad("arbeit", "ereignisse", f"{tag:%Y-%m-%d}.jsonl")
        if not datei.exists():
            continue
        for z in datei.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(z)
            except json.JSONDecodeError:
                continue
            if seit is None or datetime.fromisoformat(e["zeit"]) > seit:
                zeilen.append(e)
    return zeilen


def erweitert(p: str | Path) -> Path:
    """~ und relative Pfade (relativ zum Repo) auflösen."""
    p = Path(str(p)).expanduser()
    return p if p.is_absolute() else ROOT / p


def freier_name(ziel: Path) -> Path:
    """ziel, oder ziel_2, ziel_3 … wenn der Name schon vergeben ist. Nie überschreiben."""
    kandidat, nummer = ziel, 2
    while kandidat.exists():
        kandidat = ziel.with_name(f"{ziel.stem}_{nummer}{ziel.suffix}")
        nummer += 1
    return kandidat


def ablage_ordner() -> Path:
    return erweitert(konfig("belege")["ablage"]["ordner"])


def echt(args) -> bool:
    """Trocken ist Standard. Nur --echt verschiebt, sendet oder ändert Zustand."""
    return bool(getattr(args, "echt", False))


def konten() -> list[dict]:
    """Die Postfächer aus konfig/belege.toml ([[konto]])."""
    return list(konfig("belege").get("konto", []))


def konto(name: str | None = None) -> dict:
    alle = konten()
    if not alle:
        raise RuntimeError("In konfig/belege.toml ist noch kein Postfach eingetragen ([[konto]]).")
    if name is None:
        return alle[0]
    for k in alle:
        if k.get("name") == name:
            return k
    raise RuntimeError(f"Kein Postfach mit dem Namen {name!r} in konfig/belege.toml.")
