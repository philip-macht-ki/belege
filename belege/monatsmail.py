"""Lesbare Monatsmail nach dem Monatsabgleich.

Die Dateien unter arbeit/monat/<JJJJ-MM>/ bleiben technisch. Die Mail an dich
fasst sie so zusammen, dass man sie in einer Minute liest: je Firma, was fehlt,
gruppiert nach Lieferant, und wer den Beleg holt.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import kern

MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember")

# Status im Abgleich -> Zusatz in der Zeile (leer = eine normale Rechnung fehlt)
OFFEN = (
    ("fehlt", ""),
    ("gefunden", ""),
    ("abschlag", "Abschlagsplan oder Jahresrechnung fehlt"),
    ("lohn", "Lohnabrechnung fehlt"),
    ("abgabe", "Bescheid fehlt"),
    ("pruefen", "Bitte prüfen"),
)
WEG = {
    "fehlt": "nicht im Postfach gefunden, beim Anbieter anfordern",
    "gefunden": "liegt schon in Postfach oder Downloads, Claude legt ihn ab",
    "abschlag": "kommt vom Versorger",
    "lohn": "kommt vom Lohnbüro",
    "abgabe": "kommt vom Amt",
}


def euro(wert: float) -> str:
    return f"{abs(wert):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def lieferant(name: str) -> str:
    """Kontotext auf den Lieferantennamen kürzen."""
    n = re.split(r"\s{2,}|\bDE\d{2}[0-9 ]{10,}|, Originalbetrag|\bEREF:|\bIBAN:", str(name or ""))[0]
    n = re.sub(r"\s+", " ", n).strip(" ,") or "Unbekannt"
    return (n[:42].rsplit(" ", 1)[0] + " …") if len(n) > 45 else n


def anzahl_offen(daten: list[dict]) -> int:
    status = {s for s, _ in OFFEN}
    return sum(x.get("status") in status for x in daten)


def _wann(tage: list[date]) -> str:
    tage = sorted(tage)
    if len(tage) == 1:
        return f"{tage[0]:%d.%m.}"
    if tage[0] == tage[-1]:
        return f"{len(tage)} Abbuchungen am {tage[0]:%d.%m.}"
    return f"{len(tage)} Abbuchungen {tage[0]:%d.%m.} bis {tage[-1]:%d.%m.}"


def _zeilen(daten: list[dict]) -> list[str]:
    zeilen = []
    for status, label in OFFEN:
        gruppen: dict[str, list[dict]] = defaultdict(list)
        for x in daten:
            if x.get("status") == status:
                gruppen[lieferant(x.get("name", ""))].append(x)
        for name, posten in sorted(gruppen.items(), key=lambda kv: -sum(abs(p["betrag"]) for p in kv[1])):
            summe = sum(abs(p["betrag"]) for p in posten)
            wann = _wann([date.fromisoformat(p["datum"]) for p in posten])
            if status == "pruefen":
                hinweise = {p.get("hinweis") for p in posten} - {None, ""}
                weg = hinweise.pop() if len(hinweise) == 1 else "mehrere Treffer oder Name unklar"
            else:
                weg = WEG[status]
            zeilen.append(f"• {name}: {euro(summe)} €, {wann} · {weg}" + (f" ({label})" if label else ""))
    return zeilen


def falscher_monatsordner(monat: str, index: dict, firma: str | None = None) -> list[str]:
    """Belege dieses Monats, deren Datei in einem anderen Monatsordner liegt."""
    treffer = []
    for eintrag in index.values():
        datum = str(eintrag.get("datum", ""))
        if not datum.startswith(monat) or eintrag.get("status", "abgelegt") != "abgelegt":
            continue
        if firma and kern.firma_von(eintrag) != firma:
            continue
        teile = Path(str(eintrag.get("pfad", ""))).parts
        if len(teile) < 4:
            continue
        jahr, mon = teile[-4], teile[-3]
        if re.fullmatch(r"\d{4}", jahr) and re.fullmatch(r"\d{2}", mon) and f"{jahr}-{mon}" != monat:
            treffer.append(f"{teile[-1]} (Belegdatum {date.fromisoformat(datum[:10]):%d.%m.%Y}, liegt in {jahr}/{mon})")
    return sorted(treffer)


def fehlende_auszuege(monat: str) -> list[str]:
    """Konten aus konfig/konten.toml, für die der Kontoauszug dieses Monats fehlt."""
    zustand = kern.lesen(kern.pfad("arbeit", "konten.json"), {}) or {}
    return sorted(k for k, v in zustand.items() if isinstance(v, dict) and v.get("fehlt") and v.get("monat") == monat)


def text(monat: str, firmen: list[tuple[str, list[dict]]], index: dict, mehrere: bool = False) -> str:
    """firmen: (Name, Abgleich) je Firma, wie `belege monat` sie erzeugt."""
    jahr, mon = int(monat[:4]), int(monat[5:])
    gesamt = sum(anzahl_offen(daten) for _, daten in firmen)
    out = [f"Belegcheck {MONATE[mon - 1]} {jahr}", "",
           f"Stand {kern.jetzt():%d.%m.%Y}. "
           + (f"Es fehlen {gesamt} Belege." if gesamt else "Zu allen Abbuchungen liegt ein Beleg vor."), ""]
    ordner = []
    for name, daten in firmen:
        ordner += [f"• {name}: {z}" if mehrere else f"• {z}"
                   for z in falscher_monatsordner(monat, index, name if mehrere else None)]
        zeilen = _zeilen(daten)
        if zeilen:
            out += [f"{name.upper()} ({anzahl_offen(daten)} fehlen)"] + zeilen + [""]
    if ordner:
        out += ["Liegt im falschen Monatsordner", "Diese Belege sind da, aber im falschen Monat abgelegt:"] + ordner + [""]
    auszuege = fehlende_auszuege(monat)
    out += ["Fehlende Kontoauszüge: " + ("; ".join(auszuege) if auszuege else "keine"), ""]
    out += ["Was zu tun ist",
            "Sag in einer Claude-Sitzung „Hol die fehlenden Belege“. Was schon in Postfach oder Downloads liegt, "
            "legt Claude selbst ab, für den Rest schreibt er dir Anfragen an die Anbieter als Entwurf. Was dann noch offen ist, kommt mit "
            "der Offene-Posten-Mail, dort antwortest du je Beleg mit einer Zeile.", "",
            "Für Claude/Technik",
            f"- Einzelberichte: arbeit/monat/{monat}/ (fehlt_noch.md, pruefen.md, klaerung.md, abgleich.json)"]
    return "\n".join(out)


def senden(monat: str, inhalt: str, args) -> None:
    """Schickt die Monatsmail einmal je Monat an die Berichtsadresse.

    Nur im geplanten Monatslauf (`monat --uebergabe --echt`), nie beim
    Zwischenstand oder bei einem Lauf von Hand ohne Übergabe.
    """
    ziel = kern.pfad("arbeit", "monat", monat, "belegcheck.txt")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(inhalt + "\n", encoding="utf-8")
    if not kern.echt(args) or not getattr(args, "uebergabe", False) or getattr(args, "zwischenstand", False):
        return
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    if gesehen.get("monatsmail", {}).get(monat):
        return
    from .posten import _zieladresse
    from .senden import senden as mail_senden
    adresse = _zieladresse()
    if not adresse:
        return
    r = mail_senden(adresse, inhalt.splitlines()[0], inhalt, [], True, fortschritt=f"monatsmail:{monat}")
    print(f"{r.status}: Monatsmail {r.meldung}")
    if r.gut:
        gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
        gesehen.setdefault("monatsmail", {})[monat] = kern.jetzt().isoformat()
        kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
