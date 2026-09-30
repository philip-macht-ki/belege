"""Ein Kontoauszug über drei Monate für den Musterbetrieb, zum Ausprobieren von
`belege jahr`.

Manche Bank gibt den Auszug als eine einzige CSV über ein Quartal statt je Monat
aus, und genau das muss `belege jahr` lesen können. Der jüngste Monat ist
Zeile für Zeile derselbe wie in `kontoauszug.csv`, damit seine Belege
zugeordnet werden und `belege jahr` die Dubletten über beide Dateien nur einmal
zählt. Die zwei Monate davor haben keine Belege im Musterbetrieb: Sie zeigen,
wie die Liste „fehlt noch“ über ein Jahr aussieht. Erfundene Firmen, keine
echten Personen.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

KOPF = [
    "Buchungstag",
    "Valutadatum",
    "Beguenstigter/Zahlungspflichtiger",
    "Verwendungszweck",
    "Betrag",
    "Waehrung",
]

# Laufende Zahlungen in den zwei Monaten vor dem Musterauszug:
# (Tag, Name, Zweck, Betrag)
FRUEHER = [
    (3, "Pixelwerk Software GmbH", "Abo PW-1001", "-59,50"),
    (3, "Netzfunk", "Telefonrechnung NF-1002", "-29,99"),
    (5, "Hostingwerk", "Hosting HW-1006", "-9,90"),
    (10, "Finanzamt", "Steuervorauszahlung", "-120,00"),
]


def _vormonat(tag: date, schritte: int) -> date:
    """Der Monatserste `schritte` Monate vor `tag`."""
    monat = tag.month - schritte
    jahr = tag.year
    while monat < 1:
        monat += 12
        jahr -= 1
    return date(jahr, monat, 1)


def jahr_beispiel(ziel: Path, monatsauszug: Path | None = None) -> list[Path]:
    """Schreibt `kontoauszug_quartal.csv` nach `ziel` und gibt den Pfad zurück.

    `monatsauszug` ist der von `belege beispiel` erzeugte `kontoauszug.csv`;
    ohne ihn (oder wenn er fehlt) gilt der August 2026 als jüngster Monat.
    """
    ziel = Path(ziel).expanduser()
    ziel.mkdir(parents=True, exist_ok=True)
    zeilen: list[list[str]] = [KOPF]
    juengste: list[list[str]] = []
    if monatsauszug and Path(monatsauszug).exists():
        with open(monatsauszug, encoding="utf-8", newline="") as datei:
            juengste = [z for z in csv.reader(datei, delimiter=";")][1:]
    if juengste:
        tag, monat, jahr = (int(x) for x in juengste[0][0].split("."))
        stichtag = date(jahr, monat, tag)
    else:
        stichtag = date(2026, 8, 2)
        juengste = [[f"{stichtag:%d.%m.%Y}", f"{stichtag:%d.%m.%Y}", n, z, b, "EUR"]
                    for _, n, z, b in FRUEHER]

    for schritte in (2, 1):
        erster = _vormonat(stichtag, schritte)
        for tag_im_monat, name, zweck, betrag in FRUEHER:
            tag = erster.replace(day=tag_im_monat)
            datum = f"{tag:%d.%m.%Y}"
            zeilen.append([datum, datum, name, zweck, betrag, "EUR"])
        if schritte == 1:
            tag = erster.replace(day=8)
            zeilen.append([f"{tag:%d.%m.%Y}", f"{tag:%d.%m.%Y}", "Bürobedarf Ecke",
                           "Rechnung 4471", "-46,80", "EUR"])
    zeilen.extend(juengste)

    pfad = ziel / "kontoauszug_quartal.csv"
    with open(pfad, "w", encoding="utf-8", newline="") as datei:
        csv.writer(datei, delimiter=";").writerows(zeilen)
    return [pfad]
