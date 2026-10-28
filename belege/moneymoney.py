"""Optional: Kontoumsätze aus MoneyMoney als CSV in den Auszugsordner schreiben.

Wer MoneyMoney nicht nutzt, lädt die Kontoauszüge weiter selbst herunter; nichts
anderes hängt an diesem Modul. Gelesen wird nur über die AppleScript-Befehle
`export accounts` und `export transactions`. Überweisungen, Lastschriften oder
Änderungen in MoneyMoney löst belege nie aus.

Ein Monat je Konto und Datei, z.B. `2026-10_Girokonto_MoneyMoney.csv`. Die
Formate liest `belege monat` wie einen Export von der Bank:
- "bank": Semikolon, Spalten wie beim Sparkassen-Export, Ausgaben negativ.
- "amex" (oder "kreditkarte", dasselbe): wie der CSV-Export von amex.de,
  Datum/Beschreibung/Betrag, Belastungen positiv (MoneyMoney zählt umgekehrt).
"""

from __future__ import annotations

import csv
import io
import os
import plistlib
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from . import kern

FORMATE = ("bank", "amex", "kreditkarte")

BANK_SPALTEN = [
    "Buchungstag", "Valutadatum", "Buchungstext", "Verwendungszweck",
    "Beguenstigter/Zahlungspflichtiger", "Kontonummer/IBAN", "BIC (SWIFT-Code)",
    "Betrag", "Waehrung", "Konto",
]
AMEX_SPALTEN = ["Datum", "Beschreibung", "Betrag", "Konto"]

# Die Kennung kommt als Argument, nie in den Skripttext: kein Zitat-Problem, keine Einschleusung.
_KONTEN = 'tell application "MoneyMoney" to export accounts'
_UMSAETZE = (
    "on run argv\n"
    'tell application "MoneyMoney" to export transactions from account (item 1 of argv) '
    'from date (item 2 of argv) to date (item 3 of argv) as "plist"\n'
    "end run"
)


def einstellungen() -> dict:
    """konfig/moneymoney.toml; fehlt sie, ist MoneyMoney aus."""
    try:
        return kern.konfig("moneymoney")
    except FileNotFoundError:
        return {"an": False}


def _osa(skript: str, *argumente: str):
    r = subprocess.run(["osascript", "-e", skript, *argumente], capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or "osascript ohne Meldung")
    try:
        return plistlib.loads(r.stdout)
    except Exception as fehler:  # noqa: BLE001
        raise RuntimeError(f"MoneyMoney hat keine lesbare Liste geliefert: {fehler}") from fehler


def konten_mm() -> list[dict]:
    return _osa(_KONTEN)


def umsaetze_mm(konto: str, von: date, bis: date) -> list[dict]:
    return _osa(_UMSAETZE, konto, von.isoformat(), bis.isoformat()).get("transactions", [])


def _ohne_leer(wert: str) -> str:
    return "".join(str(wert).split()).upper()


def finde(konten: list[dict], kennung: str) -> dict | None:
    """IBAN, Kontonummer oder deren Ende, Leerzeichen egal. Nie mehrdeutig raten."""
    gesucht = _ohne_leer(kennung)
    if not gesucht:
        return None
    treffer = [
        k for k in konten
        if k.get("accountNumber") and (
            _ohne_leer(k["accountNumber"]) == gesucht or _ohne_leer(k["accountNumber"]).endswith(gesucht)
        )
    ]
    return treffer[0] if len(treffer) == 1 else None


def _tag(wert) -> date:
    if isinstance(wert, datetime):
        return wert.date()
    if isinstance(wert, date):
        return wert
    return date.fromisoformat(str(wert)[:10])


def _betrag(wert) -> Decimal:
    return Decimal(str(wert)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _komma(wert: Decimal) -> str:
    return format(wert, ".2f").replace(".", ",")


def monate(anzahl: int, heute: date) -> list[date]:
    """Erste Tage der letzten `anzahl` Monate, der laufende zuerst."""
    erster = heute.replace(day=1)
    ergebnis = []
    for _ in range(max(anzahl, 1)):
        ergebnis.append(erster)
        erster = (erster - timedelta(days=1)).replace(day=1)
    return ergebnis


def letzter_tag(erster: date) -> date:
    return (erster.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def im_monat(umsaetze: list[dict], erster: date) -> list[dict]:
    """Nur gebuchte Umsätze; vorgemerkte ändern sich noch."""
    ende = letzter_tag(erster)
    return sorted(
        (u for u in umsaetze if u.get("booked") is True and erster <= _tag(u["bookingDate"]) <= ende),
        key=lambda u: _tag(u["bookingDate"]),
    )


def csv_inhalt(format: str, umsaetze: list[dict], konto: str = "") -> bytes:
    """Ein Monat eines Kontos als CSV im gewählten Format."""
    aus = io.StringIO(newline="")
    if format in ("amex", "kreditkarte"):
        schreiber = csv.DictWriter(aus, fieldnames=AMEX_SPALTEN)
        schreiber.writeheader()
        for u in umsaetze:
            text = " ".join(t for t in (u.get("name", ""), u.get("purpose", "")) if t).strip()
            schreiber.writerow({
                "Datum": f"{_tag(u['bookingDate']):%d.%m.%Y}",
                "Beschreibung": text,
                "Betrag": _komma(-_betrag(u["amount"])),
                "Konto": konto,
            })
    elif format == "bank":
        schreiber = csv.DictWriter(aus, fieldnames=BANK_SPALTEN, delimiter=";", quoting=csv.QUOTE_ALL)
        schreiber.writeheader()
        for u in umsaetze:
            schreiber.writerow({
                "Buchungstag": f"{_tag(u['bookingDate']):%d.%m.%Y}",
                "Valutadatum": f"{_tag(u.get('valueDate') or u['bookingDate']):%d.%m.%Y}",
                "Buchungstext": u.get("bookingText", ""),
                "Verwendungszweck": u.get("purpose", ""),
                "Beguenstigter/Zahlungspflichtiger": u.get("name", ""),
                "Kontonummer/IBAN": u.get("accountNumber", ""),
                "BIC (SWIFT-Code)": u.get("bankCode", ""),
                "Betrag": _komma(_betrag(u["amount"])),
                "Waehrung": u.get("currency", "EUR"),
                "Konto": konto,
            })
    else:
        raise ValueError(f"unbekanntes Format {format!r}, erlaubt: {', '.join(FORMATE)}")
    return b"\xef\xbb\xbf" + aus.getvalue().encode("utf-8")


def dateiname(eintrag: dict, erster: date) -> str:
    name = "".join(z if z.isalnum() or z in "-_" else "_" for z in str(eintrag.get("name") or "Konto"))
    return f"{erster:%Y-%m}_{name}_MoneyMoney.csv"


def ordner(eintrag: dict, testordner: str | None) -> Path:
    """Testordner schlägt alles; sonst der Ordner am Konto, sonst der Auszugsordner."""
    if testordner:
        return kern.erweitert(testordner)
    standard = kern.konfig("belege").get("monat", {}).get("auszuege", "~/Belege/Kontoauszuege")
    return kern.erweitert(eintrag.get("ordner") or standard)


def schreiben(ziel: Path, inhalt: bytes) -> bool:
    """Ersetzt nur bei geändertem Inhalt, atomar. Löscht nie."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists() and ziel.read_bytes() == inhalt:
        return False
    with tempfile.NamedTemporaryFile(dir=ziel.parent, delete=False) as f:
        f.write(inhalt)
        name = f.name
    os.replace(name, ziel)
    return True


def _veraltet(konto: dict, tage: int, jetzt: datetime) -> str | None:
    """Datum des letzten Abrufs, wenn er länger als `tage` her ist."""
    stand = konto.get("refreshTimestamp")
    if not isinstance(stand, datetime):
        return "unbekannt"
    if stand.tzinfo is None:
        stand = stand.replace(tzinfo=jetzt.tzinfo)
    if (jetzt - stand).total_seconds() > tage * 86400:
        return f"{stand:%d.%m.%Y}"
    return None


def befehl_konten() -> int:
    """Name, Kennung und Art je Konto, für die Konfig. Ohne Kontostand und Umsätze."""
    try:
        bekannt = konten_mm()
    except RuntimeError as fehler:
        print(f"fehler: MoneyMoney nicht erreichbar. Öffne und entsperre MoneyMoney. ({fehler})")
        return 1
    for konto in bekannt:
        if konto.get("group") or not konto.get("accountNumber"):
            continue
        print(f"{konto.get('name', '')} | {konto['accountNumber']} | {konto.get('type', '')}")
    return 0


def befehl(args) -> int:
    """`belege moneymoney [konten] [--echt] [--testordner PFAD]`."""
    if (getattr(args, "ziel", None) or [""])[0] == "konten":
        return befehl_konten()
    cfg = einstellungen()
    eintraege = cfg.get("konto", [])
    if not cfg.get("an") and not getattr(args, "testordner", None):
        print("nichts: MoneyMoney ist aus. Einschalten in konfig/moneymoney.toml (an = true), siehe einrichten_moneymoney.md.")
        return 0
    if not eintraege:
        print("fehler: In konfig/moneymoney.toml steht noch kein [[konto]].")
        return 2
    falsch = [e.get("name", "?") for e in eintraege if e.get("format") not in FORMATE]
    if falsch:
        print(f"fehler: Format fehlt oder unbekannt bei {', '.join(falsch)}. Erlaubt: {', '.join(FORMATE)}.")
        return 2
    try:
        bekannt = konten_mm()
    except RuntimeError as fehler:
        text = "MoneyMoney nicht erreichbar. Öffne MoneyMoney, entsperre es und ruf die Konten ab."
        kern.log(f"fehler: {text} ({fehler})")
        kern.ereignis("monat", text)
        print(f"fehler: {text}")
        return 1
    echt = kern.echt(args)
    jetzt = kern.jetzt()
    liste = monate(int(cfg.get("monate", 2)), jetzt.date())
    warnen = int(cfg.get("warnen_nach_tagen", 3))
    fehler_gesamt = 0
    for eintrag in eintraege:
        name = eintrag.get("name", "Konto")
        konto = finde(bekannt, str(eintrag.get("kennung", "")))
        if not konto:
            text = f"MoneyMoney: Konto {name} nicht gefunden oder nicht eindeutig. Prüfe die Kennung in konfig/moneymoney.toml."
            kern.ereignis("monat", text)
            print(f"fehler: {text}")
            fehler_gesamt += 1
            continue
        alt = _veraltet(konto, warnen, jetzt)
        if alt:
            text = f"MoneyMoney: {name} zuletzt abgerufen am {alt}. Öffne MoneyMoney und ruf das Konto ab, ggf. mit TAN."
            kern.ereignis("monat", text)
            print(f"warnung: {text}")
        try:
            alle = umsaetze_mm(str(konto.get("uuid") or konto["accountNumber"]), liste[-1], letzter_tag(liste[0]))
        except RuntimeError as fehler:
            kern.log(f"fehler: MoneyMoney-Umsätze {name}: {fehler}")
            print(f"fehler: Umsätze von {name} nicht lesbar: {fehler}")
            fehler_gesamt += 1
            continue
        for erster in liste:
            zeilen = im_monat(alle, erster)
            ziel = ordner(eintrag, getattr(args, "testordner", None)) / dateiname(eintrag, erster)
            if not echt:
                print(f"trocken: würde schreiben {ziel} ({len(zeilen)} Buchungen)")
                continue
            neu = schreiben(ziel, csv_inhalt(eintrag["format"], zeilen, str(eintrag.get("kennung", ""))))
            print(f"{'ok' if neu else 'gleich'}: {ziel} ({len(zeilen)} Buchungen)")
    if echt:
        kern.log(f"moneymoney: {len(eintraege)} Konten, {len(liste)} Monate, {fehler_gesamt} Fehler")
    return 1 if fehler_gesamt else 0
