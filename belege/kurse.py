"""EZB-Referenzkurse für den vorsichtigen Fremdwährungsabgleich.

Einzige Netzadresse: die Kurslisten der Europäischen Zentralbank. Gemerkt wird in
`arbeit/kurse.json`; je Liste höchstens ein Abruf am Tag. Ohne Netz gibt es keinen
Kurs und keinen Fehler, der Abgleich bleibt dann vorsichtig.
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from . import kern

KURZ = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
LANG = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
ABRUF = "__abruf__"


def _cache() -> dict:
    return kern.lesen(kern.pfad("arbeit", "kurse.json"), {}) or {}


def _lesen(xml: bytes) -> dict[str, dict[str, float]]:
    """Liest eine EZB-Kursliste als {Tag: {Währung: Kurs}}."""
    daten: dict[str, dict[str, float]] = {}
    for tag in ET.fromstring(xml).iter():
        zeit = tag.attrib.get("time")
        if not zeit:
            continue
        werte = {kind.attrib["currency"]: float(kind.attrib["rate"])
                 for kind in tag if "currency" in kind.attrib and "rate" in kind.attrib}
        if werte:
            daten[zeit] = werte
    return daten


def _laden(url: str) -> dict[str, dict[str, float]]:
    with urllib.request.urlopen(url, timeout=15) as antwort:  # noqa: S310 - feste EZB-Adresse
        return _lesen(antwort.read())


def _aus_cache(cache: dict, code: str, tag: date) -> float | None:
    """Kurs des Tages, sonst der letzte davor (Wochenende, Feiertag), höchstens 7 Tage zurück."""
    for zurueck in range(8):
        werte = cache.get((tag - timedelta(days=zurueck)).isoformat()) or {}
        if code in werte:
            return float(werte[code])
    return None


def kurs(waehrung: str, tag: date) -> float | None:
    """Einheiten der Fremdwährung je 1 EUR am Tag, sonst None."""
    code = str(waehrung).strip().upper()
    if code == "EUR":
        return 1.0
    cache = _cache()
    wert = _aus_cache(cache, code, tag)
    if wert is not None:
        return wert
    heute = kern.jetzt().date()
    url = KURZ if tag >= heute - timedelta(days=80) else LANG
    abrufe = cache.setdefault(ABRUF, {})
    if abrufe.get(url) == heute.isoformat():
        return None  # heute schon versucht: nicht bei jeder Buchung neu fragen
    abrufe[url] = heute.isoformat()
    try:
        cache.update(_laden(url))
    except Exception as fehler:  # noqa: BLE001 - das Netz darf den Monatslauf nie stoppen
        kern.log(f"EZB-Kurse nicht abrufbar, Fremdwährung bleibt heute ohne Umrechnung: {fehler}")
    kern.schreiben(kern.pfad("arbeit", "kurse.json"), cache)
    return _aus_cache(cache, code, tag)


def in_euro(betrag: float, waehrung: str, tag: date) -> float | None:
    """Rechnet einen Betrag zum EZB-Referenzkurs auf zwei Eurostellen um."""
    wert = kurs(waehrung, tag)
    return round(float(betrag) / wert, 2) if wert else None
