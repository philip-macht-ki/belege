"""Deterministische Pflichtangaben-Prüfung für Eingangsrechnungen."""
from __future__ import annotations

import re
import json
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from . import kern
from .typen import Einordnung, Text


STANDARD = ["empfaenger", "anschrift", "ust_id_lieferant", "rechnungsnummer", "datum", "steuer", "leistung"]
NAMEN = {
    "empfaenger": "Empfänger",
    "anschrift": "Anschrift",
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


_POSITION_ODER_SUMME = re.compile(r"(?:\bpos\.?\b|\bmenge\b|\bbeschreibung\b|\bnetto\b|\bsumme\b|\bgesamt\b|\btotal\b)", re.I)
_FUSSZEILE = re.compile(
    r"(?:\bhrb\b|\bamtsgericht\b|\bgeschäftsführer\b|\biban\b|\bbic\b|\bbankverbindung\b|"
    r"\btel\.?(?:efon)?\b|\bfax\b|\be[ -]?mail\b|\bwww\.|\bsitz der gesellschaft\b|\bust\s*-?id\s*(?:nr\.?)?\b)",
    re.I,
)


def _kopfzeilen(text: str) -> list[str]:
    """Gibt den Rechnungskopf vor den Positionen zurück.

    Stammdatenzeilen des Lieferanten (Tel., HRB, USt-IdNr. …) stehen oft auch im Kopf.
    Ein Block mit solchen Zeilen gehört dem Lieferanten und wird ganz geleert, statt
    den Kopf zu beenden; ein Empfängerblock dahinter bleibt so erhalten.
    """
    kopf: list[str] = []
    for zeile in text.splitlines()[:30]:
        if _POSITION_ODER_SUMME.search(zeile):
            break
        kopf.append(zeile)
    anfang = 0
    for nr in range(len(kopf) + 1):
        if nr == len(kopf) or not kopf[nr].strip():
            if any(_FUSSZEILE.search(zeile) for zeile in kopf[anfang:nr]):
                kopf[anfang:nr] = [""] * (nr - anfang)
            anfang = nr + 1
    return kopf


def _empfaenger(text: str, firma: dict | None, xml: dict | None) -> str | None:
    if not firma:
        return "Empfängerfirma unklar"
    namen = [str(firma.get("name", "")), *map(str, firma.get("namen", []))]
    gefunden = str((xml or {}).get("kaeufer", ""))
    if gefunden and any(_normal(name) == _normal(gefunden) for name in namen):
        return None
    # Wie in 1.12.0: Der Empfänger darf irgendwo oben stehen, sonst gäbe es neue Fehlbefunde.
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


def _anschrift_normal(wert: str) -> str:
    """Vergleicht Anschriften tolerant, ohne die Hausnummer zu verlieren."""
    wert = wert.casefold().replace("ß", "ss")
    wert = wert.replace("str.", "strasse")
    wert = re.sub(r"\bnr\.?\s*", "", wert)
    return re.sub(r"[^a-z0-9]", "", wert)


def _anschrift_zeilen(firma: dict, text: str) -> tuple[list[str], bool]:
    """Liest den zusammenhängenden Fensterkuvert-Block um den Empfängernamen."""
    namen = [str(firma.get("name", "")), *map(str, firma.get("namen", []))]
    zeilen = _kopfzeilen(text)
    for nr, zeile in enumerate(zeilen):
        if any(_normal(name) and _normal(name) in _normal(zeile) for name in namen):
            anfang = nr
            while anfang and zeilen[anfang - 1].strip():
                anfang -= 1
            ende = nr + 1
            while ende < len(zeilen) and zeilen[ende].strip():
                ende += 1
            return [zeile.strip() for zeile in zeilen[max(anfang, nr - 5):min(ende, nr + 6)]], True
    return [], False


def _empfaengerblock_ust_zeilen(firma: dict | None, text: str) -> set[int]:
    """Markiert USt-Zeilen im Kopfblock des Empfängers, auch ohne eigene USt-Konfig."""
    if not firma:
        return set()
    namen = [str(firma.get("name", "")), *map(str, firma.get("namen", []))]
    zeilen = text.splitlines()[:30]
    for nr, zeile in enumerate(zeilen):
        if _POSITION_ODER_SUMME.search(zeile):
            return set()
        if _FUSSZEILE.search(zeile):
            continue
        if any(_normal(name) and _normal(name) in _normal(zeile) for name in namen):
            block = {nr}
            for ende in range(nr + 1, len(zeilen)):
                if not zeilen[ende].strip() or _POSITION_ODER_SUMME.search(zeilen[ende]):
                    break
                block.add(ende)
                if _FUSSZEILE.search(zeilen[ende]):
                    break
            return block
    return set()


def _anschrift(e: Einordnung, text: str, xml: dict | None) -> str | None:
    firma = _firma(e)
    ziel = (firma or {}).get("anschrift")
    if not isinstance(ziel, dict) or not all(str(ziel.get(feld, "")).strip() for feld in ("strasse", "plz", "ort")):
        return None
    erwartet_strasse = str(ziel["strasse"])
    erwartet_plz = str(ziel["plz"])
    erwartet_ort = str(ziel["ort"])
    gefunden = str((xml or {}).get("kaeufer_anschrift", "")).strip()
    if not gefunden:
        zeilen, name_gefunden = _anschrift_zeilen(firma, text) if firma else ([], False)
        gefunden = "\n".join(zeilen)
    else:
        name_gefunden = True
    if not gefunden:
        return "Anschrift fehlt" if name_gefunden else None
    normal = _anschrift_normal(gefunden)
    if (_anschrift_normal(erwartet_strasse) in normal and erwartet_plz in normal
            and _anschrift_normal(erwartet_ort) in normal):
        return None
    if erwartet_plz in gefunden:
        return None
    hat_adresse = bool(re.search(r"\b\d{5}\b", gefunden) and re.search(r"\d", gefunden)
                       and re.search(r"(?:str(?:\.|asse)|stra(?:ß|ss)e|weg\b|allee\b|platz\b|gasse\b|ufer\b|ring\b)", gefunden, re.I))
    if hat_adresse:
        zeile = re.sub(r"\s+", " ", gefunden)[:100]
        return f"Anschrift abweichend: {zeile}"
    return "Anschrift fehlt"


def _hat_lieferantensteuer(text: str, xml: dict | None) -> bool:
    if (xml or {}).get("verkaeufer_ust"):
        return True
    kennzeichen = r"(?:steuer\s*(?:-| )?nr\.?|st\.?\s*-?nr\.?|stnr|ust\s*-?id\s*nr\.?|ustidnr|ust\s*-?id|umsatzsteuer\s*-?identifikationsnummer|vat\s*(?:id|no\.?)?)"
    eu_format = r"(?:DE\s?\d{9}|ATU\s?\d{8}|[A-Z]{2}\s?[A-Z0-9]{7,14})"
    return bool(re.search(rf"\b{eu_format}\b", text, re.I) or
                re.search(rf"\b{kennzeichen}\s*[:#.]?\s*[A-Z0-9][A-Z0-9 ./-]{{4,}}", text, re.I))


_UST_ID_FORMATS = {
    "AT": r"U\d{8}", "BE": r"\d{10}", "BG": r"\d{9,10}", "CY": r"\d{8}[A-Z]",
    "CZ": r"\d{8,10}", "DE": r"\d{9}", "DK": r"\d{8}", "EE": r"\d{9}",
    "EL": r"\d{9}", "ES": r"[A-Z0-9]\d{7}[A-Z0-9]", "FI": r"\d{8}",
    "FR": r"[A-Z0-9]{2}\d{9}", "HR": r"\d{11}", "HU": r"\d{8}",
    "IE": r"[A-Z0-9]\d{6,7}[A-Z]{1,2}", "IT": r"\d{11}", "LT": r"\d{9}(?:\d{3})?",
    "LU": r"\d{8}", "LV": r"\d{11}", "MT": r"\d{8}", "NL": r"\d{9}B\d{2}",
    "PL": r"\d{10}", "PT": r"\d{9}", "RO": r"\d{2,10}", "SE": r"\d{12}",
    "SI": r"\d{8}", "SK": r"\d{10}", "XI": r"(?:\d{9}|\d{12})",
}
_UST_ID_KENNZEICHEN = re.compile(
    r"(?:ust\s*-?id\s*(?:nr\.?)?|ustidnr|umsatzsteuer\s*-?identifikationsnummer|"
    r"vat(?:\s*(?:id|number|no\.?)?)?|tva|iva|btw|nif)", re.I)
_EMPFÄNGERZEILE = re.compile(r"(?:rechnungsempf|rechnung\s+an|\bempf[aä]nger\b|\bkund[ei]\b|\ban\s*:)", re.I)
_EMPFÄNGER_UST_KENNZEICHEN = re.compile(
    r"(?:ihre\s+ust\s*-?id\s*(?:nr\.?)?|kunden\s*-?ust\s*-?id|"
    r"ust\s*-?id\s+des\s+leistungsempfängers|your\s+vat|customer\s+vat)", re.I)


def _ust_id(nummer: str) -> str | None:
    """Normalisiert nur USt-IdNrn. aus EU-Mitgliedstaaten und Nordirland."""
    nummer = re.sub(r"[\s.-]", "", nummer.upper())
    land, wert = nummer[:2], nummer[2:]
    if land in _UST_ID_FORMATS and re.fullmatch(_UST_ID_FORMATS[land], wert):
        return nummer
    return None


def _ust_id_aus_text(text: str, eigene: str, firma: dict | None) -> str | None:
    """Liest eine gekennzeichnete Lieferanten-USt-IdNr., nicht Rechnungsnummern."""
    zeilen = text.splitlines()
    empfaengerblock = _empfaengerblock_ust_zeilen(firma, text)
    for nr, zeile in enumerate(zeilen):
        if _EMPFÄNGERZEILE.search(zeile):
            continue
        vorherige = zeilen[nr - 1] if nr else ""
        if (nr in empfaengerblock or _EMPFÄNGER_UST_KENNZEICHEN.search(zeile)
                or _EMPFÄNGER_UST_KENNZEICHEN.search(vorherige)):
            continue
        hat_kennzeichen = bool(_UST_ID_KENNZEICHEN.search(zeile))
        if not hat_kennzeichen and nr:
            hat_kennzeichen = bool(_UST_ID_KENNZEICHEN.search(vorherige))
        if not hat_kennzeichen:
            continue
        for kandidat in re.findall(r"\b[A-Z]{2}[A-Z0-9 .-]{6,14}\b", zeile, re.I):
            nummer = _ust_id(kandidat)
            if nummer and nummer != eigene:
                return nummer
    return None


def _lieferanten_ust(text: str, xml: dict | None, firma: dict | None) -> str | None:
    """Nimmt nur eine EU-USt-IdNr. des Lieferanten, nie die eigene."""
    eigene = _ust_id(str((firma or {}).get("ust_id", ""))) or ""
    xml_nummer = _ust_id(str((xml or {}).get("verkaeufer_ust", "")))
    if xml_nummer and xml_nummer != eigene:
        return xml_nummer
    return _ust_id_aus_text(text, eigene, firma)


def _vies_pruefen(nummer: str) -> bool | None:
    """Prüft eine EU-USt-IdNr.; None bedeutet absichtlich keinen Befund."""
    cache_datei = kern.pfad("arbeit", "ust_id_cache.json")
    cache = kern.lesen(cache_datei, {}) or {}
    jetzt = kern.jetzt()
    eintrag = cache.get(nummer, {})
    try:
        frisch = jetzt - datetime.fromisoformat(eintrag["am"]) < timedelta(days=30)
    except (KeyError, TypeError, ValueError):
        frisch = False
    if frisch and eintrag.get("gueltig") in (True, False):
        return bool(eintrag["gueltig"])
    land, wert = nummer[:2], nummer[2:]
    url = f"https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{land}/vat/{wert}"
    try:
        with urlopen(url, timeout=10) as antwort:  # nosec B310 - feste URL der EU-Kommission
            daten = json.loads(antwort.read().decode("utf-8"))
    except (OSError, URLError, HTTPError, ValueError, json.JSONDecodeError) as fehler:
        code = getattr(fehler, "code", None)
        zusatz = f" ({code})" if code is not None else ""
        kern.log(f"EU-USt-IdNr.-Abfrage für {_ust_id_maskieren(nummer)} nicht verfügbar{zusatz}")
        return None
    fehlercode = str(daten.get("userError", "")).upper()
    if fehlercode and fehlercode not in {"VALID", "INVALID"}:
        kern.log(f"EU-USt-IdNr.-Abfrage für {_ust_id_maskieren(nummer)} nicht verfügbar: {fehlercode}")
        return None
    gueltig = bool(daten.get("isValid"))
    cache[nummer] = {"am": jetzt.isoformat(), "gueltig": gueltig}
    kern.schreiben(cache_datei, cache)
    return gueltig


def _ust_id_maskieren(nummer: str) -> str:
    return f"{nummer[:2]}***{nummer[-3:]}"


def _reverse_charge_hinweis(text: str) -> bool:
    return bool(re.search(r"reverse\s*charge|§\s*13b|steuerschuldnerschaft\s+des\s+leistungsempfängers", text, re.I))


def _keine_umsatzsteuer_berechnet(text: str) -> bool:
    """Erkennt einen ausgewiesenen Null-Steuersatz, nicht bloß eine USt-IdNr."""
    nullsatz = re.compile(r"(?:mwst|umsatzsteuer|(?<![\w-])ust(?!\s*-?id)|vat|tax|steuerbetrag).{0,45}\b0(?:[,.]0+)?(?:\s*%|\b)", re.I)
    nullbetrag = re.compile(r"(?:mwst|umsatzsteuer|(?<![\w-])ust(?!\s*-?id)|vat|tax|steuerbetrag).{0,45}\b0[,.]00\b", re.I)
    positiv = re.compile(r"(?:mwst|umsatzsteuer|(?<![\w-])ust(?!\s*-?id)|vat|tax|steuerbetrag).{0,45}\b(?:[1-9]\d{0,2}(?:[.]\d{3})*|[1-9]\d*)(?:[,.]\d{2})\b", re.I)
    return bool(nullsatz.search(text) or nullbetrag.search(text)) and not bool(positiv.search(text))


def _deutsche_steuernummer_ausserhalb_empfaengerblock(text: str) -> bool:
    zeilen = text.splitlines()
    im_empfaengerblock = False
    for zeile in zeilen:
        if not zeile.strip():
            im_empfaengerblock = False
            continue
        if _EMPFÄNGERZEILE.search(zeile):
            im_empfaengerblock = True
        if not im_empfaengerblock and re.search(r"\b(?:steuer\s*(?:-| )?nr\.?|st\.?\s*-?nr\.?)\s*[:#.]?\s*\d", zeile, re.I):
            return True
    return False


def _hat_steuer(text: str, xml: dict | None) -> bool:
    if re.search(r"reverse\s*charge|steuerschuldnerschaft\s+des\s+leistungsempfängers|§\s*13b\s*ustg|steuerbefrei|steuerfrei|kleinunternehmer|§\s*19\s*ustg|innergemeinschaftliche\s+lieferung", text, re.I):
        return True
    if (xml or {}).get("steuer"):
        return True
    return bool(re.search(r"(?:steuersatz|mwst|ust|umsatzsteuer|steuer).{0,45}\b(?:\d{1,2}[,.]\d{1,2}|\d{1,2})\s*%", text, re.I))


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
    if "anschrift" in regeln and not kleinbetrag:
        punkt = _anschrift(e, inhalt, xml)
        if punkt:
            befund.append(punkt)
    if "ust_id_lieferant" in regeln and not kleinbetrag and not _hat_lieferantensteuer(inhalt, xml):
        befund.append(NAMEN["ust_id_lieferant"] + " fehlt")
    nummer = str((xml or {}).get("nummer", ""))
    nummer_muster = (r"(?:rechnungs?(?:nummer|\s*-?nr\.?)|rg\.?\s*-?nr\.?|re\.?\s*-?nr\.?|belegnummer|"
                     r"invoice\s*(?:no\.?|number|nr\.?)|(?:rechnung|invoice)\s*\n\s*(?:nr\.?|no\.?|number))"
                     r"\s*[:#.]?\s*[A-Z0-9][A-Z0-9./-]{2,}")
    if "rechnungsnummer" in regeln and not kleinbetrag and not (nummer or re.search(nummer_muster, inhalt, re.I)):
        befund.append(NAMEN["rechnungsnummer"] + " fehlt")
    monat = (r"(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|"
             r"oktober|november|dezember|january|february|march|april|may|june|july|"
             r"august|september|october|november|december|jan|feb|mar|apr|jun|jul|"
             r"aug|sep|sept|oct|nov|dec)")
    # Jedes vollständige Datum zählt: Ein Fehlbefund samt Entwurf an den Lieferanten wiegt schwerer
    # als ein übersehenes fehlendes Rechnungsdatum.
    datum_muster = (rf"(?:\d{{1,2}}[./-]\d{{1,2}}[./-]20\d{{2}}|20\d{{2}}[./-]\d{{1,2}}[./-]\d{{1,2}}|"
                    rf"\d{{1,2}}\.?\s+{monat}\s+20\d{{2}}|{monat}\s+\d{{1,2}},?\s+20\d{{2}})")
    if "datum" in regeln and not ((xml or {}).get("datum") or re.search(datum_muster, inhalt, re.I)):
        befund.append("Rechnungsdatum fehlt")
    leistung_muster = (r"(?:leistung(?:sdatum|szeitraum)?|leistungsdatum\s+entspricht\s+rechnungsdatum|"
                       r"bezeichnung|beschreibung|artikel|position|pos\.?|description|item|menge|"
                       r"leistungszeitraum|service)\D{0,80}\S")
    if "leistung" in regeln and not ((xml or {}).get("positionen") or re.search(leistung_muster, inhalt, re.I)):
        befund.append(NAMEN["leistung"] + " fehlt")
    steuer_ok = _hat_steuer(inhalt, xml) or (kleinbetrag and bool(re.search(r"\b\d{1,2}\s*%", inhalt)))
    if "steuer" in regeln and not steuer_ok:
        befund.append(NAMEN["steuer"] + " fehlt")
    if kleinbetrag:
        if not re.search(r"\b\d{5}\s+[A-Za-zÄÖÜäöüß-]+", inhalt):
            befund.append("Name und Anschrift des Lieferanten fehlt")
        if not (e.betrag or re.search(r"(?:brutto|gesamt|summe).{0,25}\d+[,.]\d{2}", inhalt, re.I)):
            befund.append("Bruttobetrag fehlt")
    if (not befund and cfg.get("an", False) and cfg.get("ust_id_amtlich", False) and not kleinbetrag):
        nummer = _lieferanten_ust(inhalt, xml, _firma(e))
        if nummer and _vies_pruefen(nummer) is False:
            befund.append(f"USt-IdNr. des Lieferanten laut EU-Abfrage ungültig ({nummer})")
    return befund


def hinweise(e: Einordnung, text: Text, *, xml: dict | None = None) -> list[str]:
    """Gibt Buchhaltungshinweise zurück; sie sind ausdrücklich keine Befunde."""
    cfg = kern.konfig("belege").get("pruefung", {})
    if not (cfg.get("an", False) and e.ist_beleg and e.art == "eingang" and e.bereich == "betrieb" and e.firma != "unklar"):
        return []
    inhalt = text.text
    ust = _lieferanten_ust(inhalt, xml, _firma(e)) or ""
    reverse = _reverse_charge_hinweis(inhalt) or bool(ust and not ust.startswith("DE") and _keine_umsatzsteuer_berechnet(inhalt))
    ergebnis = ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"] if reverse else []
    kleinbetrag = e.betrag is not None and e.betrag <= float(cfg.get("kleinbetrag", 250.0))
    deutsch = ust.startswith("DE") or _deutsche_steuernummer_ausserhalb_empfaengerblock(inhalt)
    if deutsch and not kleinbetrag and xml is None:
        ergebnis.append("Lieferant schickt keine E-Rechnung; ab 2027/2028 Pflicht, rechtzeitig nachfragen")
    return ergebnis


def befehl(args) -> int:
    """Prüft eine Datei trocken, ohne etwas abzulegen oder zu senden."""
    from datetime import date
    from .einordnen import _aus_xml, einordnen
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
    xml = None
    xml_datei = datei
    temporaer = None
    if datei.suffix.lower() == ".pdf":
        try:
            from facturx import get_xml_from_pdf
            from .xrechnung import zugferd_in
            if zugferd_in(datei):
                import tempfile
                roh = get_xml_from_pdf(datei.read_bytes(), check_xsd=False)
                if isinstance(roh, tuple):
                    roh = roh[1]
                if roh:
                    temporaer = tempfile.TemporaryDirectory()
                    xml_datei = Path(temporaer.name) / "zugferd.xml"
                    xml_datei.write_bytes(roh)
        except (OSError, ValueError):
            pass
    if xml_datei.suffix.lower() == ".xml":
        try:
            from .xrechnung import ist_erechnung, lesen, sichttext
            if ist_erechnung(xml_datei):
                xml = lesen(xml_datei)
                text = Text(sichttext(xml), "xml", 1)
                xml_fund = Fund(xml_datei, fund.quelle, xml_datei.name, fund.eingang)
                e = _aus_xml(xml_fund) or einordnen(fund, text)
            else:
                text = auslesen(datei)
                e = einordnen(fund, text)
        except (OSError, ValueError):
            text = auslesen(datei)
            e = einordnen(fund, text)
    else:
        text = auslesen(datei)
        e = einordnen(fund, text)
    try:
        if e.firma == "unklar":
            print("Firma unklar – wird nicht geprüft, landet in Unsortiert")
            return 0
        if not (e.ist_beleg and e.art == "eingang" and e.bereich == "betrieb"):
            print("Nicht geprüft: keine Eingangsrechnung des Betriebs.")
            return 0
        befund = pruefe(e, text, xml=xml)
        notizen = hinweise(e, text, xml=xml)
        print("OK: Pflichtangaben erfüllt." if not befund else "Befund:\n- " + "\n- ".join(befund))
        if notizen:
            print("Hinweise für die Buchhaltung:\n- " + "\n- ".join(notizen))
        return 0
    finally:
        if temporaer:
            temporaer.cleanup()
