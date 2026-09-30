"""Notfallordner aus konfig/notfall.toml und dem Dokumentverzeichnis bauen.

Modul bh8, siehe ARCHITEKTUR.md. Der Befehl liest nie Passwörter: enthält
``konfig/notfall.toml`` einen Feldnamen oder einen Wert, der danach aussieht,
bricht er mit ``fehler`` ab, statt irgendetwas zu schreiben.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from .kern import ablage_ordner, echt as _echt, ereignis, jetzt, konfig

VERBOTENE_WOERTER = (
    "passwort",
    "kennwort",
    "pin",
    "tan",
    "schlüssel",
    "schluessel",
    "secret",
    "geheim",
    "zugangscode",
    "apikey",
    "api_key",
)

# "passwortmanager" ist ein erlaubter Abschnittsname: Er nennt nur, WELCHER
# Passwortmanager benutzt wird, nie ein Passwort selbst. Seine Felder werden
# trotzdem geprüft.
ERLAUBTE_SCHLUESSEL = {"passwortmanager"}


class NotfallFehler(RuntimeError):
    """konfig/notfall.toml enthält etwas, das nach einem Zugangsgeheimnis aussieht."""


def _verdaechtiger_schluessel(name: str) -> bool:
    if str(name).lower() in ERLAUBTE_SCHLUESSEL:
        return False
    klein = str(name).lower()
    return any(wort in klein for wort in VERBOTENE_WOERTER)


def _verdaechtiger_wert(wert: str) -> bool:
    klein = str(wert).lower()
    return any(wort in klein for wort in VERBOTENE_WOERTER)


def pruefe_keine_passwoerter(daten: object, pfad: str = "") -> str | None:
    """Durchsucht die ganze Struktur rekursiv nach passwortähnlichen Feldern
    oder Werten."""
    if isinstance(daten, dict):
        for schluessel, wert in daten.items():
            stelle = f"{pfad}.{schluessel}" if pfad else str(schluessel)
            if _verdaechtiger_schluessel(schluessel):
                return (
                    f"Das Feld '{stelle}' klingt nach einem Passwort, einer "
                    "PIN, TAN oder einem Schlüssel. Bitte entfernen."
                )
            fehler = pruefe_keine_passwoerter(wert, stelle)
            if fehler:
                return fehler
    elif isinstance(daten, list):
        for index, element in enumerate(daten):
            fehler = pruefe_keine_passwoerter(element, f"{pfad}[{index}]")
            if fehler:
                return fehler
    elif isinstance(daten, str) and _verdaechtiger_wert(daten):
        stelle = pfad or "ein Wert"
        return (
            f"Der Wert bei '{stelle}' klingt nach einem Passwort oder "
            "Schlüssel. Bitte entfernen."
        )
    return None


def _vertraege_und_versicherungen() -> list[dict]:
    """Verträge und Versicherungen aus dem Dokumentverzeichnis mit ihrer
    nächsten Frist."""
    from .dokumente import _index as dokumente_index

    ergebnis = []
    for eintrag in dokumente_index().values():
        if eintrag.get("art") not in {"vertrag", "versicherung"}:
            continue
        mit_datum = [f for f in eintrag.get("fristen", []) if f.get("datum")]
        naechste = min(mit_datum, key=lambda f: f["datum"]) if mit_datum else None
        ergebnis.append(
            {
                "gegenueber": eintrag.get("gegenueber", "Unbekannt"),
                "titel": eintrag.get("titel", ""),
                "datum": naechste["datum"] if naechste else None,
                "text": naechste["text"] if naechste else "prüfen",
            }
        )
    return sorted(
        ergebnis, key=lambda e: (e["datum"] is None, e["datum"] or "", e["gegenueber"])
    )


def _abschnitte(daten: dict, vertraege: list[dict]) -> list[tuple[str, list[str]]]:
    """Baut die Abschnitte des Notfallordners als (Überschrift, Zeilen)-Liste."""
    betrieb = konfig("belege").get("betrieb", {}).get("name", "")
    abschnitte: list[tuple[str, list[str]]] = []

    personen = [
        f"{p.get('name', '')} ({p.get('rolle', '')}): {p.get('kontakt', '')}"
        for p in daten.get("ansprechpartner", [])
    ]
    abschnitte.append(
        ("Ansprechpartner", personen or ["Keine Ansprechpartner eingetragen."])
    )

    pm = daten.get("passwortmanager", {})
    if pm:
        teile = (pm.get("name", ""), pm.get("hinweis", ""))
        pm_zeile = ": ".join(x for x in teile if x)
        abschnitte.append(("Passwortmanager", [pm_zeile]))

    if vertraege:
        zeilen = [
            f"{v['gegenueber']} ({v['titel']}): nächste Frist "
            f"{v['datum'] if v['datum'] else 'prüfen'}: {v['text']}"
            for v in vertraege
        ]
    else:
        zeilen = [
            "Noch keine Dokumente eingeordnet (`belege dokumente --echt` ausführen)."
        ]
    abschnitte.append(("Laufende Verträge und Versicherungen", zeilen))

    ablage = daten.get("ablage", {})
    abschnitte.append(
        (
            "Wo die Unterlagen liegen",
            [
                f"Belege: {ablage.get('belege', '(nicht eingetragen)')}",
                f"Dokumente: {ablage.get('dokumente', '(nicht eingetragen)')}",
            ],
        )
    )

    uebergabe = konfig("belege").get("uebergabe", {})
    steuer_zeile = (
        uebergabe.get("adresse") or uebergabe.get("ordner") or "(nicht eingetragen)"
    )
    weg = uebergabe.get("weg", "mail")
    abschnitte.append(
        ("Steuerberater / Übergabe", [f"Weg: {weg}, {steuer_zeile}"])
    )

    hinweise = daten.get("hinweise", {}).get("text", [])
    if hinweise:
        abschnitte.append(("Hinweise", list(hinweise)))

    if betrieb:
        abschnitte.insert(0, ("Betrieb", [betrieb]))
    return abschnitte


def _markdown(abschnitte: list[tuple[str, list[str]]]) -> str:
    zeilen = ["# Notfallordner", "", f"Stand: {jetzt():%d.%m.%Y}", ""]
    for ueberschrift, inhalt in abschnitte:
        zeilen.append(f"## {ueberschrift}")
        zeilen.extend(f"- {zeile}" for zeile in inhalt)
        zeilen.append("")
    return "\n".join(zeilen) + "\n"


def _pdf(ziel: Path, abschnitte: list[tuple[str, list[str]]]) -> None:
    """Baut das Notfallordner-PDF mit derselben Unicode-Schrift wie die
    Musterbelege."""
    from .beispiel import _schrift

    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    _schrift(pdf, fett=True, groesse=16)
    pdf.multi_cell(0, 9, "Notfallordner", new_x="LMARGIN", new_y="NEXT")
    _schrift(pdf, groesse=9.5)
    pdf.multi_cell(0, 6, f"Stand: {jetzt():%d.%m.%Y}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for ueberschrift, inhalt in abschnitte:
        _schrift(pdf, fett=True, groesse=12)
        pdf.multi_cell(0, 7, ueberschrift, new_x="LMARGIN", new_y="NEXT")
        _schrift(pdf, groesse=10)
        for zeile in inhalt:
            pdf.multi_cell(0, 6, f"- {zeile}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))


def befehl(args) -> int:
    """`belege notfall [--echt]`: Notfallordner.md und .pdf aus notfall.toml
    schreiben."""
    try:
        daten = konfig("notfall")
    except FileNotFoundError:
        print(
            "Keine konfig/notfall.toml gefunden. "
            "Lege sie nach dem Muster in ARCHITEKTUR.md an."
        )
        return 2
    mangel = pruefe_keine_passwoerter(daten)
    if mangel:
        print(f"fehler: {mangel}")
        return 1
    vertraege = _vertraege_und_versicherungen()
    abschnitte = _abschnitte(daten, vertraege)
    ziel_md = ablage_ordner() / "Notfallordner" / "Notfallordner.md"
    ziel_pdf = ziel_md.with_suffix(".pdf")
    if not _echt(args):
        print(f"würde schreiben: {ziel_md}")
        print(f"würde schreiben: {ziel_pdf}")
        return 0
    ziel_md.parent.mkdir(parents=True, exist_ok=True)
    ziel_md.write_text(_markdown(abschnitte), encoding="utf-8")
    _pdf(ziel_pdf, abschnitte)
    ereignis(
        "abgelegt", "Notfallordner wurde aktualisiert.",
        quelle="notfall", pfad=str(ziel_md),
    )
    print(f"ok: {ziel_md}")
    print(f"ok: {ziel_pdf}")
    return 0
