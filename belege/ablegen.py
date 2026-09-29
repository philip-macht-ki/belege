"""Dateien sicher, kollisionsfrei und standardmäßig nur im Trockenlauf ablegen."""
from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import replace
from pathlib import Path

from .kern import Ergebnis, ablage_ordner, konfig
from .typen import Einordnung, Fund, Text


def sauber(wert: str) -> str:
    """Bereinigt einen Namen für einen verständlichen Dateinamen.

    Umlaute bleiben lesbar, Leerzeichen werden Bindestriche und andere Zeichen
    verschwinden. Das verhindert ungültige oder schwer lesbare Ablagepfade.
    """
    wert = re.sub(r"\s+", "-", str(wert).strip())
    wert = "".join(zeichen for zeichen in wert if zeichen.isalnum() or zeichen == "-")
    wert = re.sub(r"-+", "-", wert).strip("-")
    return wert or "Unbekannt"


def dateiname(e: Einordnung, ext: str) -> str:
    """Baut den Vertragsnamen mit begrenztem Lieferanten und Beschreibungsteil."""
    datum = e.datum.isoformat() if e.datum else "ohne-Datum"
    lieferant = sauber(e.lieferant)[:40]
    beschreibung = sauber(e.beschreibung)[:40]
    endung = ext if ext.startswith(".") else f".{ext}"
    name = f"{datum}_{lieferant}_{beschreibung}"
    maximal = 120 - len(endung)
    return f"{name[:maximal].rstrip('-')}{endung.lower()}"


def ziel(e: Einordnung, ext: str) -> Path:
    """Ermittelt den normalen Zielpfad für eine ausreichend sichere Einordnung."""
    if e.datum is None:
        return ablage_ordner() / "Unsortiert" / dateiname(e, ext)
    cfg = konfig("belege").get("ablage", {})
    if e.bereich == "privat" and not cfg.get("privat", False):
        return ablage_ordner() / "Unsortiert" / dateiname(e, ext)
    bereich = cfg.get(f"bereich_{e.bereich}", e.bereich.title())
    art = {"eingang": "Eingang", "ausgang": "Ausgang", "sonstige": "Sonstige"}[e.art]
    return ablage_ordner() / bereich / f"{e.datum:%Y}" / f"{e.datum:%m}" / art / dateiname(e, ext)


def _sha(datei: Path) -> str:
    """Berechnet den Fingerabdruck über die unveränderten Dateibytes."""
    return hashlib.sha256(datei.read_bytes()).hexdigest()


def _unsortiert(fund: Fund, e: Einordnung) -> bool:
    """Entscheidet, ob ein Fund gemäß Vertrag nicht in den Fachordner darf."""
    privat_aus = e.bereich == "privat" and not konfig("belege").get("ablage", {}).get("privat", False)
    return not e.ist_beleg or e.sicherheit == "niedrig" or e.datum is None or privat_aus


def _freier_pfad(kandidat: Path, weitere_endungen: tuple[str, ...] = ()) -> Path:
    """Findet einen freien Namen und schützt bei E-Rechnungen auch die Sichtfassung."""
    nummer = 1
    while True:
        zusatz = "" if nummer == 1 else f"_{nummer}"
        pfad = kandidat.with_name(f"{kandidat.stem}{zusatz}{kandidat.suffix}")
        belegt = [pfad, *(pfad.with_suffix(endung) for endung in weitere_endungen)]
        if not any(datei.exists() for datei in belegt):
            return pfad
        nummer += 1


def ablegen(fund: Fund, e: Einordnung, text: Text, echt: bool) -> Ergebnis:
    """Legt einen Fund nur mit ``echt`` ab und überschreibt niemals eine Datei.

    Mailanhänge werden kopiert, Dateien aus Handy und Downloads dürfen gemäß Fund
    verschoben werden. E-Rechnungen erhalten zusätzlich eine Sicht-PDF.
    """
    from .xrechnung import ist_erechnung, lesen, sicht_pdf

    sha = _sha(fund.datei)
    erechnung = fund.datei.suffix.lower() == ".xml" and ist_erechnung(fund.datei)
    if _unsortiert(fund, e):
        name = sauber(Path(fund.name).stem)
        kandidat = ablage_ordner() / "Unsortiert" / (
            f"{fund.eingang:%Y-%m-%d}_{name}{fund.datei.suffix.lower()}"
        )
        status = "unsortiert"
    else:
        einordnung = replace(e, beschreibung="Rechnung") if erechnung else e
        kandidat = ziel(einordnung, fund.datei.suffix)
        status = "abgelegt"
    pfad = _freier_pfad(kandidat, (".pdf",) if erechnung else ())
    daten = {"pfad": str(pfad), "sha": sha, "status": status}
    if not echt:
        return Ergebnis("nichts", f"Würde unter {pfad} ablegen.", daten)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    if fund.verschieben:
        shutil.move(str(fund.datei), str(pfad))
    else:
        shutil.copy2(fund.datei, pfad)
    if erechnung:
        sicht_pdf(lesen(pfad), pfad, pfad.with_suffix(".pdf"))
        daten["xml"] = str(pfad)
    if status == "unsortiert":
        return Ergebnis("befund", f"Zur Prüfung unter {pfad} abgelegt.", daten)
    return Ergebnis("ok", f"Unter {pfad} abgelegt.", daten)
