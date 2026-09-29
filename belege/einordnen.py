"""Belege anhand von Regeln, E-Rechnungen und einem geprüften Urteil einordnen."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .kern import konfig
from .typen import Einordnung, Fund, Text
from .urteil import frage, vorlage

BELEGWOERTER = (
    "rechnung",
    "quittung",
    "beleg",
    "kassenbon",
    "invoice",
    "receipt",
    "bon",
    "mwst",
    "ust",
)
NEWSLETTERWOERTER = ("angebot", "newsletter", "abmelden", "werbung", "rabatt")
FRISTWOERTER = (
    "zahlbar bis",
    "fällig am",
    "faellig am",
    "gültig bis",
    "gueltig bis",
    "due",
    "valid until",
)
KOPFZEILEN = {"invoice", "receipt", "rechnung", "quittung", "beleg", "kassenbon"}


def pruefe(antwort: object) -> str | None:
    """Prüft ein Modellurteil gegen den festen Einordnungs-Vertrag.

    Ungültige Antworten werden von ``urteil.frage`` verworfen und nie als Beleg
    abgelegt. Das schützt vor unvollständigem oder falsch formatiertem JSON.
    """
    if not isinstance(antwort, dict):
        return "Die Antwort muss ein JSON-Objekt sein."
    felder = {
        "ist_beleg",
        "art",
        "bereich",
        "datum",
        "lieferant",
        "beschreibung",
        "betrag",
        "waehrung",
        "sicherheit",
        "grund",
    }
    fehlend = felder - antwort.keys()
    if fehlend:
        return f"Diese Felder fehlen: {', '.join(sorted(fehlend))}."
    if not isinstance(antwort["ist_beleg"], bool):
        return "ist_beleg muss true oder false sein."
    if antwort["art"] not in {"eingang", "ausgang", "sonstige"}:
        return "art muss eingang, ausgang oder sonstige sein."
    if antwort["bereich"] not in {"betrieb", "privat"}:
        return "bereich muss betrieb oder privat sein."
    if antwort["sicherheit"] not in {"hoch", "mittel", "niedrig"}:
        return "sicherheit muss hoch, mittel oder niedrig sein."
    if antwort["waehrung"] != "EUR":
        return "waehrung muss EUR sein."
    if antwort["datum"] is not None:
        if not isinstance(antwort["datum"], str):
            return "datum muss JJJJ-MM-TT oder null sein."
        try:
            if date.fromisoformat(antwort["datum"]).year < 2000:
                return "datum darf nicht vor 2000 liegen."
        except ValueError:
            return "datum muss JJJJ-MM-TT oder null sein."
    if antwort["betrag"] is not None:
        if isinstance(antwort["betrag"], bool) or not isinstance(
            antwort["betrag"], (int, float)
        ):
            return "betrag muss eine positive Zahl oder null sein."
        if antwort["betrag"] <= 0:
            return "betrag muss positiv sein."
    textfelder = ("lieferant", "beschreibung", "grund")
    if not all(
        isinstance(antwort[name], str) and antwort[name].strip() for name in textfelder
    ):
        return "lieferant, beschreibung und grund müssen kurze Texte sein."
    woerter = [wort for wort in antwort["beschreibung"].split("-") if wort]
    if not 1 <= len(woerter) <= 4:
        return "beschreibung braucht ein bis vier Wörter mit Bindestrichen."
    return None


def _mailtext(fund: Fund) -> str:
    """Baut den kleinen, für Regeln relevanten Mailkopf zusammen."""
    if not fund.mail:
        return ""
    return " ".join(
        str(fund.mail.get(name, "")) for name in ("von", "von_name", "betreff")
    )


def _regel(fund: Fund) -> dict | None:
    """Findet die erste passende feste Absenderregel."""
    suchraum = f"{_mailtext(fund)} {fund.name}".lower()
    for regel in konfig("regeln").get("absender", []):
        if str(regel.get("muster", "")).lower() in suchraum:
            return regel
    return None


def _datum(wert: str) -> date | None:
    """Liest ISO- und deutsche Daten sicher als Datum."""
    wert = wert.strip()
    for muster, gruppe in (
        (r"(20\d{2})-(\d{2})-(\d{2})", "iso"),
        (r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", "de"),
    ):
        treffer = re.search(muster, wert)
        if not treffer:
            continue
        try:
            if gruppe == "iso":
                return date(int(treffer[1]), int(treffer[2]), int(treffer[3]))
            return date(int(treffer[3]), int(treffer[2]), int(treffer[1]))
        except ValueError:
            return None
    # Englische Belege (Stripe & Co.): "August 13, 2026" oder "13 August 2026"
    monate = {name: nr for nr, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"), start=1)}
    muster = r"(?:([a-z]+)\.? (\d{1,2}),? (20\d{2}))|(?:(\d{1,2}) ([a-z]+)\.? (20\d{2}))"
    for treffer in re.finditer(muster, wert.lower()):
        name, tag, jahr = (treffer[1], treffer[2], treffer[3]) if treffer[1] else (
            treffer[5], treffer[4], treffer[6])
        nummer = next((nr for voll, nr in monate.items() if voll.startswith(name[:3])), None)
        if nummer and len(name) >= 3:
            try:
                return date(int(jahr), nummer, int(tag))
            except ValueError:
                return None
    return None


def _belegdatum(text: str) -> date | None:
    """Nimmt ein Rechnungsdatum vor dem ersten Datum außerhalb von Fristzeilen."""
    zeilen = text.splitlines()
    for zeile in zeilen:
        if re.search(
            r"\b(rechnungsdatum|document date|\bdate\b|\bdatum\b)\b", zeile, re.I
        ):
            if not any(wort in zeile.lower() for wort in FRISTWOERTER):
                treffer = _datum(zeile)
                if treffer:
                    return treffer
    for zeile in zeilen:
        if not any(wort in zeile.lower() for wort in FRISTWOERTER):
            treffer = _datum(zeile)
            if treffer:
                return treffer
    return None


def _betrag(text: str) -> float | None:
    """Liest den größten Gesamtbetrag aus eindeutig beschrifteten Zeilen."""
    werte = []
    for zeile in text.splitlines():
        if not re.search(r"gesamt|summe|brutto|total|zu zahlen", zeile, re.I):
            continue
        for wert in re.findall(r"(?:€\s*)?\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d{2})?", zeile):
            zahl = wert.replace("€", "").replace(" ", "").strip()
            if "," in zahl:
                zahl = zahl.replace(".", "").replace(",", ".")
            try:
                werte.append(float(zahl))
            except ValueError:
                continue
    return max(werte) if werte else None


def _eigener_betrieb(text: str) -> bool:
    """Erkennt den Betrieb nur im kurzen Briefkopf, nicht im Empfängerblock."""
    betrieb = konfig("belege").get("betrieb", {})
    # Nur die ersten zwei Zeilen mit Inhalt: dort steht der Aussteller. Schon ab
    # Zeile drei beginnt bei vielen Rechnungen das Empfängerfenster, und dann
    # hält man jede Rechnung AN dich für eine Rechnung VON dir.
    zeilen = [z for z in text.splitlines() if z.strip()][:2]
    kopf = "\n".join(zeilen).lower()
    namen = [betrieb.get("name", ""), *betrieb.get("namen", [])]
    ust_id = str(betrieb.get("ust_id", "")).strip()
    return any(name and name.lower() in kopf for name in namen) or bool(
        ust_id and ust_id.lower() in kopf
    )


def _lieferant(text: str, fund: Fund) -> str:
    """Nimmt eine sinnvolle Briefkopfzeile und überspringt Labels und Überschriften."""
    for zeile in text.splitlines()[:7]:
        kandidat = re.sub(r"\s+", " ", zeile).strip(" :-")
        klein = kandidat.lower()
        if not kandidat or klein in KOPFZEILEN or ":" in kandidat:
            continue
        if _datum(kandidat) or re.search(
            r"\b(rechnung|invoice|receipt|quittung|beleg)\b", klein
        ):
            continue
        if re.fullmatch(r"[\d., €EUR]+", kandidat):
            continue
        return kandidat[:80]
    if fund.mail and fund.mail.get("von_name"):
        return str(fund.mail["von_name"])[:80]
    return "Unbekannt"


def _zahlungsabwickler(fund: Fund) -> str | None:
    """Kürzt den Anzeigenamen eines Zahlungsabwicklers auf den eigentlichen Anbieter."""
    if not fund.mail:
        return None
    domains = konfig("regeln").get("zahlungsabwickler", {}).get("domains", [])
    absender = str(fund.mail.get("von", "")).lower()
    if not any(domain.lower() in absender for domain in domains):
        return None
    name = str(fund.mail.get("von_name", "")).strip()
    name = re.split(r"\s+(?:via|über)\s+|\s*\(via[^)]*\)", name, flags=re.I)[0]
    return name.strip() or None


def _rueckfall(
    fund: Fund, text: Text, regel: dict | None, zahlungsname: str | None
) -> dict:
    """Ordnet ohne Modell nachvollziehbar und absichtlich vorsichtig ein."""
    inhalt = text.text
    klein = inhalt.lower()
    newsletter = any(wort in klein for wort in NEWSLETTERWOERTER)
    ist_beleg = not newsletter and any(wort in klein for wort in BELEGWOERTER)
    eigener = _eigener_betrieb(inhalt)
    eigene = {str(k.get("adresse", "")).lower() for k in konfig("belege").get("konto", [])}
    absender = str((fund.mail or {}).get("von", "")).lower()
    extern = bool(absender) and not any(adresse and adresse in absender for adresse in eigene)
    art = "ausgang" if eigener and not extern else "eingang"
    if regel and regel.get("art"):
        art = regel["art"]
    beschreibung = str((regel or {}).get("beschreibung") or "Rechnung")
    beschreibung = re.sub(r"\s+", "-", beschreibung.strip()) or "Rechnung"
    return {
        "ist_beleg": ist_beleg,
        "art": art,
        "bereich": str((regel or {}).get("bereich") or "betrieb"),
        "datum": _belegdatum(inhalt).isoformat() if _belegdatum(inhalt) else None,
        "lieferant": str(
            (regel or {}).get("lieferant") or zahlungsname or _lieferant(inhalt, fund)
        ),
        "beschreibung": beschreibung,
        "betrag": _betrag(inhalt),
        "waehrung": "EUR",
        "sicherheit": "mittel" if (regel or zahlungsname or (eigener and ist_beleg)) and ist_beleg
        else "niedrig",
        "grund": "Feste Regel erkannt."
        if regel
        else "Ohne Modell nur vorsichtig erkannt.",
    }


def _aus_xml(fund: Fund) -> Einordnung | None:
    """Liest eine E-Rechnung ohne Modell und bestimmt ihre Richtung über Käufer und Verkäufer."""
    from .xrechnung import ist_erechnung, lesen

    if fund.datei.suffix.lower() != ".xml" or not ist_erechnung(fund.datei):
        return None
    daten = lesen(fund.datei)
    betrieb = konfig("belege").get("betrieb", {})
    namen = [betrieb.get("name", ""), *betrieb.get("namen", [])]
    ust_id = str(betrieb.get("ust_id", "")).strip().lower()

    def ist_eigen(name: str, ust: str) -> bool:
        hat_namen = any(name and wert.lower() in name.lower() for wert in namen)
        return hat_namen or bool(ust_id and ust.lower() == ust_id)

    ist_kaeufer = ist_eigen(daten.get("kaeufer", ""), daten.get("kaeufer_ust", ""))
    ist_verkaeufer = ist_eigen(
        daten.get("verkaeufer", ""), daten.get("verkaeufer_ust", "")
    )
    art = "ausgang" if ist_verkaeufer and not ist_kaeufer else "eingang"
    partner = (
        daten.get("kaeufer", "") if art == "ausgang" else daten.get("verkaeufer", "")
    )
    position = next(iter(daten.get("positionen", [])), {}).get("text", "Rechnung")
    return Einordnung(
        True,
        art,
        "betrieb",
        daten.get("datum"),
        partner or "Unbekannt",
        re.sub(r"\s+", "-", position)[:80],
        float(daten.get("betrag") or 0) or None,
        daten.get("waehrung", "EUR"),
        "hoch",
        "E-Rechnung mit eindeutigem Geschäftspartner.",
        "xml",
    )


def _sicheres_datum(einordnung: Einordnung, eingang: date) -> Einordnung:
    """Ersetzt unplausible Daten durch das Eingangsdatum und senkt die Sicherheit."""
    if einordnung.datum is None:
        return einordnung
    if einordnung.datum.year < 2000 or einordnung.datum > eingang + timedelta(days=90):
        einordnung.datum = eingang
        if einordnung.sicherheit == "hoch":
            einordnung.sicherheit = "mittel"
    return einordnung


def einordnen(fund: Fund, text: Text) -> Einordnung:
    """Ordnet einen Fund nach festen Regeln, E-Rechnung und geprüftem Modellurteil ein.

    Ohne Modell liefert die Rückfallregel immer ein nachvollziehbares, vorsichtiges
    Ergebnis. So bleiben Tests und der lokale Betrieb unabhängig von einem Konto.
    """
    regel = _regel(fund)
    zahlungsname = _zahlungsabwickler(fund)
    xml = _aus_xml(fund)
    if xml:
        return _sicheres_datum(xml, fund.eingang)
    betriebsdaten = konfig("belege").get("betrieb", {})
    auftrag = vorlage(
        "einordnen",
        betrieb=betriebsdaten.get("name", ""),
        namen=", ".join(betriebsdaten.get("namen", [])),
        ust_id=betriebsdaten.get("ust_id", ""),
        taetigkeit=betriebsdaten.get("taetigkeit", ""),
        privat_erlaubt=konfig("belege").get("ablage", {}).get("privat", False),
        mail=_mailtext(fund),
        dateiname=fund.name,
        text=text.text[:6000],
    )
    antwort = frage(
        auftrag,
        zweck="einordnen",
        pruefe=pruefe,
        rueckfall=lambda: _rueckfall(fund, text, regel, zahlungsname),
    )
    if regel:
        for feld in ("lieferant", "bereich", "art", "beschreibung"):
            if regel.get(feld):
                antwort[feld] = regel[feld]
    if zahlungsname:
        antwort["lieferant"] = zahlungsname
    datum = date.fromisoformat(antwort["datum"]) if antwort["datum"] else None
    ergebnis = Einordnung(
        ist_beleg=antwort["ist_beleg"],
        art=antwort["art"],
        bereich=antwort["bereich"],
        datum=datum,
        lieferant=antwort["lieferant"],
        beschreibung=antwort["beschreibung"],
        betrag=float(antwort["betrag"]) if antwort["betrag"] is not None else None,
        waehrung=antwort["waehrung"],
        sicherheit=antwort["sicherheit"],
        grund=antwort["grund"],
        quelle=(
            "regel"
            if regel
            else "rueckfall"
            if antwort.get("grund") == "Ohne Modell nur vorsichtig erkannt."
            else "urteil"
        ),
    )
    return _sicheres_datum(ergebnis, fund.eingang)
