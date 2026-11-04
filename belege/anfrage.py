"""Nachfragen des Steuerbüros sicher gegen das lokale Belegverzeichnis abgleichen."""
from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import kern


@dataclass
class Anfrage:
    zeile: str
    datum: date | None
    betrag: float | None
    lieferant: str


def _betrag(text: str) -> float | None:
    # Ein Datum wie 10.10.2026 darf nicht als Betrag 10,10 zählen.
    text = re.sub(r"\b20\d{2}-\d{1,2}-\d{1,2}\b|\b\d{1,2}\.\d{1,2}\.(?:20\d{2})?", "", text)
    treffer = re.search(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[,.]\d{2})(?!\d)", text)
    if not treffer:
        return None
    wert = treffer.group(0)
    return float(wert.replace(".", "").replace(",", ".")) if "," in wert else float(wert)


def _datum(text: str, heute: date | None = None) -> date | None:
    heute = heute or kern.jetzt().date()
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    de = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", text)
    kurz = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(?!\d)", text)
    try:
        if iso:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        if de:
            return date(int(de[3]), int(de[2]), int(de[1]))
        if kurz:
            return date(heute.year, int(kurz[2]), int(kurz[1]))
    except ValueError:
        return None
    return None


def lesen(text: str) -> list[Anfrage]:
    """Liest die brauchbaren Zeilen einer kopierten Mail oder Liste."""
    ergebnis = []
    for zeile in text.splitlines():
        datum, betrag = _datum(zeile), _betrag(zeile)
        if datum is None and betrag is None:
            continue
        rest = re.sub(r"\b20\d{2}-\d{1,2}-\d{1,2}\b|\b\d{1,2}\.\d{1,2}\.(?:20\d{2})?", "", zeile)
        rest = re.sub(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[,.]\d{2})(?!\d)", "", rest)
        lieferant = re.sub(r"[|;,€]", " ", rest).strip()
        ergebnis.append(Anfrage(zeile.strip(), datum, betrag, lieferant))
    return ergebnis


def zuordnen(anfrage: Anfrage, index: dict) -> tuple[dict | None, list[dict]]:
    """Nimmt bei mehreren gültigen Kandidaten den mit Datum, Betrag und Name besten."""
    kandidaten = []
    woerter = [w.lower() for w in re.findall(r"[\wäöüß]{3,}", anfrage.lieferant)]
    for eintrag in index.values():
        betrag, datum = eintrag.get("betrag"), eintrag.get("datum")
        if anfrage.betrag is not None and (betrag is None or abs(float(betrag) - anfrage.betrag) > .01):
            continue
        try:
            tag = date.fromisoformat(str(datum))
        except ValueError:
            tag = None
        if anfrage.datum and (tag is None or abs((tag - anfrage.datum).days) > 7):
            continue
        namen = " ".join(str(eintrag.get(k, "")) for k in ("lieferant", "beschreibung")).lower()
        score = sum(w in namen for w in woerter) * 100
        score -= abs((tag - anfrage.datum).days) if tag and anfrage.datum else 0
        kandidaten.append((score, eintrag))
    kandidaten.sort(key=lambda paar: paar[0], reverse=True)
    return (kandidaten[0][1] if kandidaten else None, [e for _, e in kandidaten[1:]])


def bericht(text: str) -> tuple[list[tuple[Anfrage, dict | None, list[dict]]], str]:
    index = kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}
    zeilen = [(a, *zuordnen(a, index)) for a in lesen(text)]
    ausgabe = ["# Nachfrage Steuerbüro", "", "| Anfrage | Ergebnis |", "| --- | --- |"]
    for a, fund, weitere in zeilen:
        status = f"gefunden: {fund.get('pfad', '')}" if fund else "nicht gefunden"
        if weitere:
            status += f" (weitere Kandidaten: {len(weitere)})"
        ausgabe.append(f"| {a.zeile} | {status} |")
    return zeilen, "\n".join(ausgabe) + "\n"


def befehl(args) -> int:
    quelle = Path(args.ziel[0]) if args.ziel else None
    text = quelle.read_text(encoding="utf-8") if quelle else sys.stdin.read()
    zuordnungen, ausgabe = bericht(text)
    if not kern.echt(args):
        print(ausgabe, end="")
        if getattr(args, "postfach", False) and any(f is None for _, f, _ in zuordnungen):
            print("\nIm Postfach nachsehen: belege postfach --tage 30 --echt")
        return 0
    ziel = kern.ablage_ordner() / "Anfragen" / f"{kern.jetzt():%Y-%m-%d}"
    ziel.mkdir(parents=True, exist_ok=True)
    anhaenge, fehlend = [], []
    for anfrage, fund, _ in zuordnungen:
        if not fund or not fund.get("pfad"):
            fehlend.append(anfrage.zeile)
            continue
        quelle = kern.ablage_ordner() / fund["pfad"]
        if quelle.exists():
            kopie = ziel / quelle.name
            shutil.copy2(quelle, kopie)
            anhaenge.append(kopie.name)
    antwort = "Guten Tag,\n\nanbei die gefundenen Belege: " + (", ".join(anhaenge) or "keine") + ".\n"
    if fehlend:
        antwort += "Folgende Posten fehlen noch: " + "; ".join(fehlend) + ".\n"
    antwort += "\nFreundliche Grüße\n"
    (ziel / "antwort.md").write_text(ausgabe + "\n" + antwort, encoding="utf-8")
    print(f"ok: Anfrage abgelegt unter {ziel}")
    return 0
