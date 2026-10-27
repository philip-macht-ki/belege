"""Sichere Aktualisierungen für einen Belege-Ordner beim Kunden."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from argparse import Namespace
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__
from .kern import ereignis, pfad

_VERSION = re.compile(r'^## \[?(v?\d+\.\d+\.\d+)\]?')


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=pfad(), text=True, capture_output=True, check=check)


def _version(text: str) -> str:
    found = re.search(r'__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']', text)
    return found.group(1) if found else "unbekannt"


def _abschnitte(text: str) -> list[tuple[str, str, str]]:
    """(Version, Aktion, Kunden-Text), in Changelog-Reihenfolge."""
    teile = re.split(r'(?=^## \[?v?\d+\.\d+\.\d+\]?)', text, flags=re.M)
    antwort = []
    for teil in teile:
        kopf = _VERSION.search(teil)
        if not kopf:
            continue
        aktion = re.search(r'^aktion:\s*(keine|konfig|zeitplan|claude|sicherheit)\s*$', teil, re.M)
        antwort.append((kopf.group(1).lstrip("v"), aktion.group(1) if aktion else "claude", teil.strip()))
    return antwort


def _neu(changelog: str, alt: str, neu: str) -> list[tuple[str, str, str]]:
    alle = _abschnitte(changelog)
    def zahl(v: str) -> tuple[int, int, int]: return tuple(map(int, v.split(".")))
    return [e for e in alle if zahl(alt) < zahl(e[0]) <= zahl(neu)]


def _changelog_remote() -> str:
    r = _git("show", "origin/main:CHANGELOG.md", check=False)
    return r.stdout if r.returncode == 0 else pfad("CHANGELOG.md").read_text(encoding="utf-8")


def _sperre_aktiv() -> str | None:
    for name in ("takt", "monat"):
        datei = pfad("arbeit", f".{name}.pid")
        if not datei.exists():
            continue
        try:
            os.kill(int(datei.read_text().strip()), 0)
        except (ValueError, ProcessLookupError):
            continue
        return name
    return None


def _persoenliche_konfig_sichern() -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in pfad("konfig").glob("*") if p.is_file()}


def _konfig_erganzen() -> list[str]:
    angelegt = []
    quelle = pfad("vorlagen", "konfig")
    ziel = pfad("konfig")
    ziel.mkdir(exist_ok=True)
    for vorlage in quelle.glob("*"):
        kunde = ziel / vorlage.name
        if not kunde.exists():
            shutil.copyfile(vorlage, kunde)
            angelegt.append(vorlage.name)
    # Neue Pflichtabschnitte bekommen einen sicheren Standardwert. Bestehende
    # Werte werden nie verändert; bei komplexeren Änderungen hilft Claude.
    belege = ziel / "belege.toml"
    if belege.exists():
        text = belege.read_text(encoding="utf-8")
        if not re.search(r"^\[update\]\s*$", text, re.M):
            belege.write_text(text.rstrip() + "\n\n[update]\nautomatisch = true\n", encoding="utf-8")
            angelegt.append("belege.toml: automatische Updates ergänzt")
    return angelegt


def _pruefen() -> int:
    from .pruefen import befehl
    return befehl(Namespace())


def _zeitplaene() -> None:
    from .zeitplan import neu_laden
    neu_laden()


def _gesehen() -> set[str]:
    try:
        return set(json.loads(pfad("arbeit", "update-gesehen.json").read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def _merken(version: str) -> None:
    gesehen = _gesehen() | {version}
    ziel = pfad("arbeit", "update-gesehen.json")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(sorted(gesehen)) + "\n", encoding="utf-8")


def _zeige(alt: str, neu: str, neue: list[tuple[str, str, str]]) -> None:
    print(f"Belege ist auf Version {alt}; verfügbar ist {neu}.")
    for _, _, text in neue:
        print("\n" + text)


_FAELLIG_TAGE = 6


def _letzte_pruefung_alt_genug() -> bool:
    """Automatische Läufe höchstens einmal pro Woche: sonntags planmäßig, sonst beim
    nächsten Start, wenn der Sonntag verpasst wurde (Mac aus oder zugeklappt)."""
    datei = pfad("arbeit", "update-letzte-pruefung.txt")
    try:
        letzte = datetime.fromisoformat(datei.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return datetime.now() - letzte >= timedelta(days=_FAELLIG_TAGE)


def _pruefung_merken() -> None:
    datei = pfad("arbeit", "update-letzte-pruefung.txt")
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(datetime.now().isoformat(timespec="seconds") + "\n", encoding="utf-8")


def _plus_ordner() -> Path:
    return Path(os.environ.get("BELEGE_PLUS", "~/belege-plus")).expanduser()


def _plus_vorhanden() -> bool:
    return (_plus_ordner() / "pyproject.toml").is_file()


def _plus_aktualisieren(automatisch: bool) -> None:
    """Aktualisiert Belege Plus, wenn es installiert ist. Ein Fehler dort ändert nie das Basis-Update."""
    plus = _plus_ordner()
    if not _plus_vorhanden():
        return
    befehl = ["uv", "--directory", str(plus), "run", "plus", "update", "--echt"]
    if automatisch:
        befehl.append("--automatisch")
    try:
        ergebnis = subprocess.run(befehl, timeout=600, capture_output=True, text=True)
        if ergebnis.returncode:
            ereignis("update", f"Belege Plus konnte nicht aktualisiert werden: Exit-Code {ergebnis.returncode}")
    except subprocess.TimeoutExpired:
        ereignis("update", "Belege Plus konnte nicht aktualisiert werden: Zeitüberschreitung")
    except OSError as fehler:
        ereignis("update", f"Belege Plus konnte nicht aktualisiert werden: {fehler}")


# Automatische Updates gibt es ohne Plus nur in den ersten vier Wochen ab der
# Einrichtung (Philip, 27.10.2026). Von Hand geht es immer, Sicherheitsupdates
# (aktion: sicherheit) kommen immer automatisch.
FREI_TAGE = 28
OHNE_SCHRITT = {"keine", "zeitplan", "sicherheit"}


def einrichtung_merken() -> date:
    """Datum der ersten Einrichtung in arbeit/einrichtung.json; Bestand ohne Datum: ab heute."""
    datei = pfad("arbeit", "einrichtung.json")
    try:
        return date.fromisoformat(json.loads(datei.read_text(encoding="utf-8"))["seit"][:10])
    except (OSError, ValueError, KeyError, TypeError):
        heute = datetime.now().date()
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(json.dumps({"seit": heute.isoformat()}) + "\n", encoding="utf-8")
        return heute


def _plus_gueltig() -> bool:
    """Gültige, vom Server signierte Plus-Lizenz? Fragt `plus lizenz` (prüft die Signatur selbst)."""
    if not _plus_vorhanden():
        return False
    try:
        r = subprocess.run(["uv", "--directory", str(_plus_ordner()), "run", "plus", "lizenz"],
                           timeout=120, capture_output=True, text=True)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _automatik_frei() -> bool:
    if datetime.now().date() - einrichtung_merken() < timedelta(days=FREI_TAGE):
        return True
    return _plus_gueltig()


def _plus_name() -> str:
    try:
        from .kern import konfig

        return str(konfig("belege").get("update", {}).get("plus_name", "")).strip() or "Agent Plus"
    except Exception:  # noqa: BLE001 - nur ein Name im Hinweis
        return "Agent Plus"


def befehl(args) -> int:
    """`belege aktualisieren`: trocken erklären, mit --echt sicher einspielen."""
    einrichtung_merken()  # Bestand ohne Datum: die vier Wochen beginnen beim ersten Lauf
    if getattr(args, "automatisch", False):
        if not _letzte_pruefung_alt_genug():
            print("nichts: Update wurde in den letzten Tagen schon geprüft.")
            return 0
        _pruefung_merken()
    try:
        _git("fetch", "origin")
        remote = _git("show", "origin/main:belege/__init__.py").stdout
        neu = _version(remote)
        changelog = _changelog_remote()
    except (OSError, subprocess.CalledProcessError) as fehler:
        print(f"fehler: Update nicht prüfbar: {fehler}")
        return 1
    alt = __version__
    neue = _neu(changelog, alt, neu) if neu != "unbekannt" else []
    if neu == alt:
        print(f"Belege ist schon aktuell (Version {alt}).")
        # Plus hat eigene Versionen: auch ohne Basis-Update nachsehen, aber nur bei grünem Selbsttest.
        if getattr(args, "echt", False) and _plus_vorhanden() and _pruefen() == 0:
            _plus_aktualisieren(getattr(args, "automatisch", False))
        return 0
    if not getattr(args, "echt", False):
        _zeige(alt, neu, neue)
        return 0
    nur_sicherheit = bool(neue) and all(a == "sicherheit" for _, a, _ in neue)
    if getattr(args, "automatisch", False) and not nur_sicherheit \
            and not _automatik_frei():
        hinweis = (f"Automatische Updates sind nach 4 Wochen pausiert. Von Hand: `uv run belege aktualisieren --echt`. "
                   f"Dauerhaft automatisch mit {_plus_name()}.")
        if f"pausiert:{neu}" not in _gesehen():
            ereignis("update", hinweis)
            _merken(f"pausiert:{neu}")
        print(f"nichts: {hinweis}")
        return 0
    if getattr(args, "automatisch", False) and any(a not in OHNE_SCHRITT for _, a, _ in neue):
        if neu not in _gesehen():
            print("Neue Version mit einem Schritt für dich – sag deinem Claude: ‚Update‘")
            _merken(neu)
        return 0
    lauf = _sperre_aktiv()
    if lauf:
        print(f"nichts: Der {lauf}-Lauf arbeitet gerade noch. Das Update wartet auf den nächsten Sonntag.")
        return 0
    # Alte Installationen hatten Konfigurationsdateien noch im Git-Index.
    # Sie sind persönliche Daten und zählen deshalb nie als Programmänderung.
    status = _git("status", "--porcelain", "--untracked-files=no", "--", ".", ":(exclude)konfig").stdout.strip()
    if status:
        print("nichts: Deine Programmdateien wurden verändert. Sag deinem Claude: ‚Prüfe meine lokalen Änderungen in Belege und aktualisiere sicher.‘")
        return 1
    alt_commit = _git("rev-parse", "HEAD").stdout.strip()
    konfig = _persoenliche_konfig_sichern()
    vorher_rot = _pruefen() != 0
    try:
        # Für Kunden alter Fassungen waren die Dateien noch versioniert. Die
        # Sicherung oben wird sofort zurückgeschrieben; so darf Git sie entfernen.
        _git("checkout", "--", "konfig", check=False)
        _git("pull", "--ff-only")
        for datei, inhalt in konfig.items():
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_bytes(inhalt)
        _git("rev-parse", "HEAD")  # klare Fehlerstelle, bevor Abhängigkeiten geändert werden
        subprocess.run(["uv", "sync"], cwd=pfad(), check=True)
        angelegt = _konfig_erganzen()
        _zeitplaene()
        nachher_rot = _pruefen() != 0
        if nachher_rot and not vorher_rot:
            raise RuntimeError("Der Selbsttest ist nach dem Update rot")
    except Exception as fehler:
        _git("reset", "--hard", alt_commit)
        for datei, inhalt in konfig.items():
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_bytes(inhalt)
        subprocess.run(["uv", "sync"], cwd=pfad(), check=False)
        try:
            _zeitplaene()
        except Exception:
            pass
        print(f"Belege blieb auf Version {alt}. Das Update wurde zurückgenommen: {fehler}. Sag deinem Claude: ‚Prüfe das Belege-Update.‘")
        return 1
    jetzt = _version((pfad("belege", "__init__.py")).read_text(encoding="utf-8"))
    neu_text = "; ".join(re.sub(r"\s+", " ", t).replace("#", "").strip() for _, _, t in neue)
    extra = f" Neue Vorlage angelegt: {', '.join(angelegt)}." if angelegt else ""
    text = f"Belege ist jetzt auf Version {jetzt}. Neu: {neu_text or 'Verbesserungen im Hintergrund.'} Du musst nichts tun.{extra}"
    ereignis("update", text)
    _plus_aktualisieren(getattr(args, "automatisch", False))
    print(text)
    return 0
