"""Deterministische Pflichtangaben-Prüfung für Eingangsrechnungen."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from . import kern
from .typen import Einordnung, Text


STANDARD = ["empfaenger", "ust_id_lieferant", "rechnungsnummer", "datum", "steuer", "leistung"]
NAMEN = {
    "empfaenger": "Empfänger",
    "ust_id_lieferant": "USt-IdNr. oder Steuernummer des Lieferanten",
    "rechnungsnummer": "Rechnungsnummer",
    "datum": "Ausstellungsdatum",
    "steuer": "Steuersatz und Steuerbetrag oder Steuerhinweis",
    "leistung": "Leistungsbeschreibung oder Leistungszeitraum",
}


def _normal(wert: str) -> str:
    return re.sub(r"[^a-z0-9]", "", wert.casefold().replace("ß", "ss"))


def _firma(e: Einordnung) -> dict | None:
    return kern.firma(e.firma) or (kern.firmen()[0] if len(kern.firmen()) == 1 else None)


def _empfaenger(text: str, firma: dict | None, xml: dict | None) -> str | None:
    if not firma:
        return "Empfängerfirma unklar"
    namen = [str(firma.get("name", "")), *map(str, firma.get("namen", []))]
    gefunden = str((xml or {}).get("kaeufer", ""))
    if gefunden and any(_normal(name) == _normal(gefunden) for name in namen):
        return None
    oben = "\n".join(text.splitlines()[:55])
    if any(_normal(name) and _normal(name) in _normal(oben) for name in namen):
        return None
    if not gefunden:
        zeilen = oben.splitlines()
        for nr, zeile in enumerate(zeilen):
            if re.search(r"rechnungsempf|rechnung an|\bkund[ei]\b|\ban\s*:", zeile, re.I):
                gefunden = re.sub(r"^.*?(?:rechnungsempf[äa]nger|rechnung an|\bkund[ei]\b|\ban)\s*:?\s*", "", zeile, flags=re.I).strip()
                if not gefunden and nr + 1 < len(zeilen):
                    gefunden = zeilen[nr + 1].strip()
                break
    kandidat = _normal(gefunden)
    if kandidat:
        for name in namen:
            vergleich = _normal(name)
            if vergleich and SequenceMatcher(None, kandidat, vergleich).ratio() >= .72:
                return f"Firmenname abweichend: {gefunden[:100]}"
    return "Empfänger fehlt"


def _hat_lieferantensteuer(text: str, xml: dict | None) -> bool:
    if (xml or {}).get("verkaeufer_ust"):
        return True
    return bool(re.search(r"\b(?:DE\s?\d{9}|ATU\d{8}|[A-Z]{2}\s?[A-Z0-9]{7,14}|steuer(?:-| )?nr\.?\s*[:#]?\s*[0-9/.-]{6,})\b", text, re.I))


def _hat_steuer(text: str, xml: dict | None) -> bool:
    if re.search(r"reverse\s*charge|steuerbefrei|kleinunternehmer|§\s*19", text, re.I):
        return True
    if (xml or {}).get("steuer"):
        return True
    return bool(re.search(r"\b(?:\d{1,2}[,.]\d{1,2}|\d{1,2})\s*%", text) and
                re.search(r"(?:mwst|ust|umsatzsteuer|steuer).{0,45}\d+[,.]\d{2}", text, re.I))


def pruefe(e: Einordnung, text: Text, *, xml: dict | None = None) -> list[str]:
    """Gibt nur klare fehlende oder unklare Pflichtangaben zurück, ohne zu raten."""
    cfg = kern.konfig("belege").get("pruefung", {})
    regeln = list(cfg.get("regeln", STANDARD))
    inhalt = text.text
    kleinbetrag = e.betrag is not None and e.betrag <= float(cfg.get("kleinbetrag", 250.0))
    befund: list[str] = []
    if "empfaenger" in regeln and not kleinbetrag:
        punkt = _empfaenger(inhalt, _firma(e), xml)
        if punkt:
            befund.append(punkt)
    if "ust_id_lieferant" in regeln and not kleinbetrag and not _hat_lieferantensteuer(inhalt, xml):
        befund.append(NAMEN["ust_id_lieferant"] + " fehlt")
    nummer = str((xml or {}).get("nummer", ""))
    if "rechnungsnummer" in regeln and not kleinbetrag and not (nummer or re.search(r"(?:rechnung(?:snummer|\s*(?:nr\.?|nummer))|invoice\s*(?:nr\.?|number|no\.?))\s*[:#]?\s*[A-Z0-9][A-Z0-9./-]{2,}", inhalt, re.I)):
        befund.append(NAMEN["rechnungsnummer"] + " fehlt")
    if "datum" in regeln and not ((xml or {}).get("datum") or re.search(r"(?:rechnungsdatum|ausstellungsdatum|invoice date|\bdatum\b)\D{0,20}\d{1,2}[.]\d{1,2}[.]20\d{2}", inhalt, re.I)):
        befund.append(NAMEN["datum"] + " fehlt")
    if "leistung" in regeln and not ((xml or {}).get("positionen") or re.search(r"(?:leistung|artikel|position|menge|leistungszeitraum|service|beschreibung)\D{0,80}\S", inhalt, re.I)):
        befund.append(NAMEN["leistung"] + " fehlt")
    steuer_ok = _hat_steuer(inhalt, xml) or (kleinbetrag and bool(re.search(r"\b\d{1,2}\s*%", inhalt)))
    if "steuer" in regeln and not steuer_ok:
        befund.append(NAMEN["steuer"] + " fehlt")
    if kleinbetrag:
        if not re.search(r"\b\d{5}\s+[A-Za-zÄÖÜäöüß-]+", inhalt):
            befund.append("Name und Anschrift des Lieferanten fehlt")
        if not (e.betrag or re.search(r"(?:brutto|gesamt|summe).{0,25}\d+[,.]\d{2}", inhalt, re.I)):
            befund.append("Bruttobetrag fehlt")
    return befund


def befehl(args) -> int:
    """Prüft eine Datei trocken, ohne etwas abzulegen oder zu senden."""
    from datetime import date
    from .einordnen import einordnen
    from .text import auslesen
    from .typen import Fund
    if len(args.ziel) != 1:
        print("Bitte nenne genau eine Datei, zum Beispiel: belege pruefung Rechnung.pdf")
        return 2
    datei = Path(args.ziel[0]).expanduser()
    if not datei.is_file():
        print(f"Nicht gefunden: {datei}")
        return 2
    fund = Fund(datei, "handy", datei.name, date.fromtimestamp(datei.stat().st_mtime))
    text = auslesen(datei)
    e = einordnen(fund, text)
    if not (e.ist_beleg and e.art == "eingang" and e.bereich == "betrieb"):
        print("Nicht geprüft: keine Eingangsrechnung des Betriebs.")
        return 0
    befund = pruefe(e, text)
    print("OK: Pflichtangaben erfüllt." if not befund else "Befund:\n- " + "\n- ".join(befund))
    return 0
