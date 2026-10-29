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
from . import text as texterkennung
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


def _inhalt(text: str) -> str:
    """Macht pdftotext-Spalten für die Muster lesbar, ohne Zeilen zu verlieren."""
    return re.sub(r"[ \t]+", " ", text)


def _unlesbar(text: str) -> bool:
    zeilen = [zeile.strip() for zeile in text.splitlines() if zeile.strip()]
    glyphen = sum(bool(re.fullmatch(r"(?:/g[0-9a-f]+)+", zeile, re.I)) for zeile in zeilen)
    # Nummern steigern die allgemeine OCR-Quote; sie zählen nur zusammen mit
    # einem echten Glyphenfehler als unlesbar.
    return (bool(zeilen) and glyphen / len(zeilen) > .20) or (
        texterkennung.fehlerquote(text) > .10 and bool(re.search(r"/g[0-9a-f]+|�", text, re.I)))


def _kein_rechnungsdokument(text: str) -> bool:
    zeilen = [zeile.strip() for zeile in text.splitlines() if zeile.strip()]
    kopf = "\n".join(zeilen[:15])
    if re.search(r"\b(?:das\s+ist\s+keine\s+rechnung|this\s+is\s+not\s+an\s+invoice)\b", text, re.I):
        return True
    if re.search(r"\b(?:gutschrift|credit note|erstattung|refund|zahlungserinnerung|mahnung|"
                 r"auftragsbestätigung|order confirmation|pro[ -]?forma|angebot|kontoauszug|"
                 r"jahreskonto|auszahlungs(?:übersicht|bericht)|zahlungsbericht|zahlungsbeleg|"
                 r"lohnabrechnung|berechnung der umsatzsteuer)\b|\w*(?:vertrag|bescheid)\w*|"
                 r"(?:landesjustizkasse|gerichtskasse|justizkasse)", kopf, re.I):
        return True
    if (re.search(r"\bpayment\s+receipt\b", kopf, re.I)
            and not re.search(r"\b(?:invoice|rechnung)\b", kopf, re.I)):
        return True
    rechnungswort = (r"\b(?:rechnung(?:s(?:nummer|datum))?|invoice|receipt|quittung|"
                     r"gutschrift|beleg|bill)\b")
    return not bool(re.search(rechnungswort, "\n".join(zeilen[:40]), re.I))


def _behoerde_im_kopf(text: str) -> bool:
    kopf = "\n".join(zeile.strip() for zeile in text.splitlines() if zeile.strip())
    return bool(re.search(r"\b(?:finanzamt|landesjustizkasse|amtsgericht)\b", "\n".join(kopf.splitlines()[:5]), re.I))


def _rechnungsnummer_vorhanden(text: str, xml: dict | None) -> bool:
    if str((xml or {}).get("nummer", "")).strip():
        return True
    # Manche Layouts nennen nur den Titel und setzen die Nummer direkt dahinter oder darunter.
    titel_nummer = re.compile(r"\b(?:rechnung|invoice|receipt|quittung|beleg)\b[ \t:#.]*"
                              r"(?:\n[ \t]*)?([A-Z0-9][A-Z0-9./-]*)", re.I)
    datum = re.compile(r"(?:\d{1,2}[./-]\d{1,2}[./-](?:\d{2}|\d{4})|"
                       r"\d{4}[./-]\d{1,2}[./-]\d{1,2})$")
    for treffer in titel_nummer.finditer(text):
        kandidat = treffer.group(1).strip(".,:;#")
        if len(re.sub(r"\D", "", kandidat)) >= 4 and not datum.fullmatch(kandidat):
            return True
    # Das Muster aus 1.12.0 gilt weiter, damit kurze Nummern wie "RE-22" nicht neu auffallen.
    if re.search(r"(?:rechnungs?(?:nummer|\s*-?nr\.?)|rg\.?\s*-?nr\.?|re\.?\s*-?nr\.?|belegnummer|"
                 r"invoice\s*(?:no\.?|number|nr\.?)|(?:rechnung|invoice)\s*\n\s*(?:nr\.?|no\.?|number))"
                 r"\s*[:#.]?\s*[A-Z0-9][A-Z0-9./-]{2,}", text, re.I):
        return True
    zeilen = text.splitlines()
    etikett = re.compile(r"(?:rechnungs?(?:nummer|\s*-?nr\.?)|rg\.?\s*-?nr\.?|re\.?\s*-?nr\.?|"
                         r"beleg(?:nummer|\s*-?nr\.?)|invoice|receipt|credit note number|"
                         r"(?:\bnummer\b|\bnr\.?\b|\bno\.?\b|#))", re.I)
    datum = re.compile(r"^(?:\d{1,2}[./-]\d{1,2}[./-](?:\d{2}|\d{4})|\d{4}[./-]\d{1,2}[./-]\d{1,2})$")
    for nr, zeile in enumerate(zeilen):
        if not etikett.search(zeile):
            continue
        for kandidatzeile in zeilen[nr:nr + 4]:
            for token in re.findall(r"[A-Z0-9][A-Z0-9./-]*\d[A-Z0-9./-]*", kandidatzeile, re.I):
                sauber = token.strip(".,:;#")
                if len(re.sub(r"\D", "", sauber)) >= 3 and not datum.fullmatch(sauber):
                    return True
    return False


def _drittland(text: str, xml: dict | None, firma: dict | None) -> bool:
    """Drittländer ohne Lieferanten-USt-IdNr. nicht nach EU-Pflichtangaben bewerten."""
    land = (r"\b(?:united states|usa|u\.s\.a\.|australia|australien|singapore|singapur|"
            r"canada|united kingdom|\buk\b|großbritannien|switzerland|schweiz|norway|norwegen|"
            r"israel|india|indien|japan|china|hong kong)\b|\bABN\s*\d")
    waehrung = r"(?:\$\s*\d|\b(?:USD|AUD|SGD|CAD|GBP|CHF)\b)"
    return not _lieferanten_ust(text, xml, firma) and bool(re.search(land, text, re.I) or re.search(waehrung, text, re.I))


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
    ziele = [(firma or {}).get("anschrift"), *((firma or {}).get("weitere_anschriften", []) or [])]
    ziele = [ziel for ziel in ziele if isinstance(ziel, dict) and all(
        str(ziel.get(feld, "")).strip() for feld in ("strasse", "plz", "ort"))]
    if not ziele:
        return None
    kopf = "\n".join(text.splitlines()[:40])
    def passt(gefunden: str) -> bool:
        normal = _anschrift_normal(gefunden)
        return any(_anschrift_normal(str(ziel["strasse"])) in normal
                   and str(ziel["plz"]) in gefunden
                   and _anschrift_normal(str(ziel["ort"])) in normal for ziel in ziele)
    if passt(kopf):
        return None
    gefunden = str((xml or {}).get("kaeufer_anschrift", "")).strip()
    if not gefunden:
        zeilen, name_gefunden = _anschrift_zeilen(firma, text) if firma else ([], False)
        gefunden = "\n".join(zeilen)
    else:
        name_gefunden = True
    if not gefunden:
        return "Anschrift fehlt" if name_gefunden else None
    if passt(gefunden):
        return None
    if any(str(ziel["plz"]) in gefunden for ziel in ziele):
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
    if re.search(
        r"reverse[\s-]*charge|§\s*13b|steuerschuldnerschaft\s+des\s+leistungsempfängers|"
        r"(?:gemäß|gemass|under)\s+(?:artikel|article)\s*196", text, re.I):
        return True
    return any(re.search(r"(?:artikel|article|art\.)\s*196", absatz, re.I)
               and re.search(r"(?:2006\s*/\s*112|leistungsempf)", absatz, re.I)
               for absatz in re.split(r"\n\s*\n", text))


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
    if _reverse_charge_hinweis(text) or re.search(r"steuerbefrei|steuerfrei|kleinunternehmer|§\s*19\s*ustg|innergemeinschaftliche\s+lieferung", text, re.I):
        return True
    if (xml or {}).get("steuer"):
        return True
    steuerwort = r"(?:steuersatz|mwst|ust|umsatzsteuer|vat|steuer)"
    prozent = r"(?:\d{1,2}(?:[,.]\d{1,2})?)\s*%"
    return bool(re.search(rf"{steuerwort}.{{0,45}}\b{prozent}|\b{prozent}.{{0,45}}{steuerwort}", text, re.I)
                or re.search(rf"{steuerwort}[^\n]{{0,45}}\n[^\n]*\b{prozent}", text, re.I))


def pruefe(e: Einordnung, text: Text, *, xml: dict | None = None) -> list[str]:
    """Gibt nur klare fehlende oder unklare Pflichtangaben zurück, ohne zu raten."""
    cfg = kern.konfig("belege").get("pruefung", {})
    regeln = list(cfg.get("regeln", STANDARD))
    firma = _firma(e)
    if firma and firma.get("pruefung") is False:
        return []
    inhalt = _inhalt(text.text)
    if _unlesbar(inhalt) or _kein_rechnungsdokument(inhalt) or _behoerde_im_kopf(inhalt):
        return []
    kleinbetrag = e.betrag is not None and e.betrag <= float(cfg.get("kleinbetrag", 250.0))
    drittland = _drittland(inhalt, xml, firma)
    befund: list[str] = []
    if "empfaenger" in regeln and not kleinbetrag:
        punkt = _empfaenger(inhalt, _firma(e), xml)
        if punkt:
            befund.append(punkt)
    if "anschrift" in regeln and not kleinbetrag:
        punkt = _anschrift(e, inhalt, xml)
        if punkt:
            befund.append(punkt)
    # Der Ausleser hält nur den Anfang langer Abrechnungen vor. Alles weitere
    # könnte auf einer abgeschnittenen letzten Seite stehen.
    if text.seiten > 2 or len(text.text) >= 5990:
        return befund
    if "ust_id_lieferant" in regeln and not kleinbetrag and not drittland and not _hat_lieferantensteuer(inhalt, xml):
        befund.append(NAMEN["ust_id_lieferant"] + " fehlt")
    if "rechnungsnummer" in regeln and not kleinbetrag and not _rechnungsnummer_vorhanden(inhalt, xml):
        befund.append(NAMEN["rechnungsnummer"] + " fehlt")
    monat = (r"(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|"
             r"oktober|november|dezember|january|february|march|april|may|june|july|"
             r"august|september|october|november|december|jan|feb|mar|apr|jun|jul|"
             r"aug|sep|sept|oct|nov|dec)")
    # Jedes vollständige Datum zählt: Ein Fehlbefund samt Entwurf an den Lieferanten wiegt schwerer
    # als ein übersehenes fehlendes Rechnungsdatum.
    datum_muster = (rf"(?:\d{{1,2}}\.\d{{1,2}}\.\d{{2,4}}|\d{{1,2}}[/-]\d{{1,2}}[/-]20\d{{2}}|20\d{{2}}[./-]\d{{1,2}}[./-]\d{{1,2}}|"
                    rf"\d{{1,2}}\.?\s+{monat}\.?\s+20\d{{2}}|{monat}\.?\s+\d{{1,2}},?\s+20\d{{2}})")
    if "datum" in regeln and not ((xml or {}).get("datum") or re.search(datum_muster, inhalt, re.I)):
        befund.append("Rechnungsdatum fehlt")
    leistung_muster = (r"(?:leistung(?:sdatum|szeitraum)?|leistungsdatum\s+entspricht\s+rechnungsdatum|"
                       r"bezeichnung|beschreibung|artikel|position|pos\.?|description|item|menge|"
                       r"leistungszeitraum|service)\D{0,80}\S")
    if "leistung" in regeln and not ((xml or {}).get("positionen") or re.search(leistung_muster, inhalt, re.I)):
        befund.append(NAMEN["leistung"] + " fehlt")
    steuer_ok = _hat_steuer(inhalt, xml) or (kleinbetrag and bool(re.search(r"\b\d{1,2}\s*%", inhalt)))
    if "steuer" in regeln and not drittland and not steuer_ok:
        befund.append(NAMEN["steuer"] + " fehlt")
    if kleinbetrag:
        anschrift = (r"(?:\b\d{4,5}\b|\b[A-Z]\d{2}\s?[A-Z0-9]{3}\b|"
                     r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b|"
                     r"\b(?:deutschland|germany|ireland|irland|france|frankreich|netherlands|niederlande|"
                     r"luxembourg|luxemburg|belgium|belgien|österreich|austria|schweiz|switzerland|"
                     r"united kingdom|united states|usa|lithuania|lietuva|poland|polen|italy|italien|"
                     r"spain|spanien|portugal|denmark|dänemark|sweden|schweden|finland|finnland|"
                     r"estonia|estland|latvia|lettland|czech|tschechien|slovakia|slowakei|slovenia|slowenien|"
                     r"hungary|ungarn|romania|rumänien|bulgaria|croatia|kroatien|greece|griechenland)\b)")
        if not re.search(anschrift, inhalt, re.I):
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
    firma = _firma(e)
    if firma and firma.get("pruefung") is False:
        return []
    inhalt = _inhalt(text.text)
    if _unlesbar(inhalt):
        return []
    ust = _lieferanten_ust(inhalt, xml, firma) or ""
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
