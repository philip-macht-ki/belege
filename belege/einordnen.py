"""Belege anhand von Regeln, E-Rechnungen und einem geprüften Urteil einordnen."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .kern import konfig, firmen, firma, hat_stammdatenblatt
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


def pruefe(antwort: object, firmennamen: set[str] | None = None) -> str | None:
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
    if firmennamen is not None:
        if antwort.get("firma") not in firmennamen | {"unklar"}:
            return "firma muss genau ein Firmenname aus der Liste oder unklar sein."
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


def _nummer_normal(wert: object) -> str:
    """USt-IdNr. und Steuernummer ohne deren übliche Trennzeichen."""
    return re.sub(r"[^a-z0-9]", "", str(wert).casefold())


def _empfaengerraum(zeilen: list[str]) -> str:
    """Kopf plus Empfängerfenster, aber nie den Lieferantenfuß einer Rechnung."""
    marker = re.compile(r"rechnung\s+an|rechnungsempf[äa]nger|\bempf[äa]nger\b|\bkunde\b|\ban\s*:", re.I)
    for nr, zeile in enumerate(zeilen):
        if marker.search(zeile):
            return "\n".join(zeilen[nr:min(nr + 8, len(zeilen))])
    # Ohne Marker ist nur der knappe Kopf belastbar. So zählt die USt-IdNr.
    # eines Lieferanten im späteren Impressum nicht als eigene Nummer.
    kurz = []
    for zeile in zeilen[:12]:
        # Ab hier steht bei klassischen PDFs das Lieferanten-Impressum. Seine
        # Nummer darf ohne Empfängerbezug nie eine eigene Firma auswählen.
        if re.search(r"\bimpressum\b|\b(?:lieferant|verkäufer|seller)\b", zeile, re.I):
            break
        kurz.append(zeile)
    return "\n".join(kurz)


def _anschrift_treffer(zeilen: list[str]) -> set[str]:
    """Anschrift entscheidet nur bei genau einer Stammdatenfirma."""
    if not hat_stammdatenblatt():
        return set()
    raum = "\n".join(zeilen)
    funde: dict[tuple[str, str], list[str]] = {}
    for eintrag in firmen():
        anschrift = eintrag.get("anschrift")
        if not isinstance(anschrift, dict):
            continue
        strasse, plz = _nummer_normal(anschrift.get("strasse", "")), _nummer_normal(anschrift.get("plz", ""))
        if strasse and plz:
            funde.setdefault((strasse, plz), []).append(eintrag["name"])
    treffer: set[str] = set()
    normal = _nummer_normal(raum)
    for (strasse, plz), namen in funde.items():
        if len(namen) == 1 and strasse in normal and plz in normal:
            treffer.add(namen[0])
    return treffer


def _merkmale(text: str, art: str | None = None) -> tuple[set[str], set[str], set[str]]:
    """Eigene Nummern, eindeutige Anschriften und Namen in ihrer Rangfolge."""
    zeilen = text.splitlines()[:45]
    oben = "\n".join(zeilen)
    nummernraum = text if art == "ausgang" else _empfaengerraum(zeilen)
    nummern = _nummer_normal(nummernraum)
    nummer_treffer, namen_treffer = set(), set()
    for eintrag in firmen():
        ids = [eintrag.get("ust_id", ""), eintrag.get("steuernummer", "")]
        if any((normal := _nummer_normal(wert)) and normal in nummern for wert in ids):
            nummer_treffer.add(eintrag["name"])
        namen = [eintrag["name"], *eintrag.get("namen", [])]
        if any(str(name).strip() and str(name).casefold() in oben.casefold() for name in namen):
            namen_treffer.add(eintrag["name"])
    return nummer_treffer, _anschrift_treffer(zeilen), namen_treffer


def _firmen_im_text(text: str) -> set[str]:
    """Alle erkannten eigenen Firmen (für die Unklarheitsbehandlung)."""
    nummern, anschriften, namen = _merkmale(text)
    return nummern | anschriften | namen


def _firma_aus_abschnitt(text: str, kandidaten: set[str]) -> str | None:
    """Gibt genau eine eigene Firma aus einem begrenzten Textabschnitt zurück."""
    treffer = _firmen_im_text(text) & kandidaten
    return next(iter(treffer)) if len(treffer) == 1 else None


def _firma_aus_text(text: str, art: str | None = None) -> str | None:
    """Erkennt die Firma nach allen Treffern und ihrer Belegposition.

    Bei mehreren eigenen Firmen entscheidet bei Eingangsrechnungen ausschließlich
    der Empfängerblock, bei Ausgangsrechnungen der kurze Ausstellerkopf.
    """
    nummern, anschriften, namen = _merkmale(text, art)
    # Nummern sind die stärkste Zuordnung. Verschiedene eigene Nummern oder
    # eine dazu eindeutig widersprüchliche Namensnennung bleiben unklar.
    if nummern:
        if len(nummern) != 1:
            return None
        erkannt = next(iter(nummern))
        # Bei Eingangsrechnungen ist ein anderer eigener Name im Ausstellerkopf
        # kein Widerspruch: maßgeblich bleibt der explizite Empfängerblock.
        relevante_namen = namen
        zeilen = text.splitlines()[:45]
        marker = re.compile(r"rechnung\s+an|rechnungsempf[äa]nger|kunde|an\s*:", re.I)
        marker_nr = next((i for i, zeile in enumerate(zeilen) if marker.search(zeile)), None)
        if art != "ausgang" and marker_nr is not None:
            im_block = _merkmale("\n".join(zeilen[marker_nr:marker_nr + 7]))[2]
            if im_block:
                relevante_namen = im_block
        if relevante_namen and relevante_namen != {erkannt}:
            return None
        return erkannt
    if anschriften:
        if len(anschriften) != 1:
            return None
        erkannt = next(iter(anschriften))
        if namen and namen != {erkannt}:
            return None
        return erkannt
    treffer = namen
    if len(treffer) != 1:
        if not treffer:
            return None
        zeilen = text.splitlines()[:45]
        marker = re.compile(r"rechnung\s+an|rechnungsempf[äa]nger|kunde|an\s*:", re.I)
        marker_nr = next((i for i, zeile in enumerate(zeilen) if marker.search(zeile)), None)
        if art == "ausgang":
            return _firma_aus_abschnitt("\n".join(zeilen[:5]), treffer)
        if marker_nr is not None:
            empfaenger = _firma_aus_abschnitt("\n".join(zeilen[marker_nr:marker_nr + 7]), treffer)
            if empfaenger:
                return empfaenger
            return _firma_aus_abschnitt("\n".join(zeilen[:marker_nr]), treffer)
        return _firma_aus_abschnitt("\n".join(zeilen[:5]), treffer)
    return next(iter(treffer))


def _eigener_betrieb(text: str) -> bool:
    """Erkennt den Betrieb nur im kurzen Briefkopf, nicht im Empfängerblock."""
    # Nur die ersten zwei Zeilen mit Inhalt: dort steht der Aussteller. Schon ab
    # Zeile drei beginnt bei vielen Rechnungen das Empfängerfenster, und dann
    # hält man jede Rechnung AN dich für eine Rechnung VON dir.
    zeilen = [z for z in text.splitlines() if z.strip()][:2]
    kopf = "\n".join(zeilen).lower()
    for eintrag in firmen():
        namen = [eintrag["name"], *eintrag.get("namen", [])]
        ust_id = str(eintrag.get("ust_id", "")).strip()
        if any(name and str(name).lower() in kopf for name in namen) or bool(ust_id and ust_id.lower() in kopf):
            return True
    return False


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
    treffer = _firmen_im_text(inhalt)
    erkannt = _firma_aus_text(inhalt, art)
    # Ein Kontohinweis ist nur ein schwacher Rückfall, nie eine Überschreibung
    # eines Adressfelds und nie eine Wahl zwischen mehreren Firmen.
    if not treffer and fund.mail:
        vorschlag = next((k.get("firma") for k in konfig("belege").get("konto", [])
                          if k.get("name") == fund.mail.get("konto") and firma(k.get("firma"))), None)
        if vorschlag:
            erkannt = str(vorschlag)
    firma_unklar = bool(treffer) and not erkannt
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
        "sicherheit": "mittel" if ((regel or zahlungsname or (eigener and ist_beleg) or erkannt) and ist_beleg)
        else "niedrig",
        "grund": "Feste Regel erkannt."
        if regel
        else "Ohne Modell nur vorsichtig erkannt.",
        "firma": "unklar" if firma_unklar else erkannt or (firmen()[0]["name"] if len(firmen()) == 1 else "unklar"),
    }


def _aus_xml(fund: Fund) -> Einordnung | None:
    """Liest eine E-Rechnung ohne Modell und bestimmt ihre Richtung über Käufer und Verkäufer."""
    from .xrechnung import ist_erechnung, lesen

    if fund.datei.suffix.lower() != ".xml" or not ist_erechnung(fund.datei):
        return None
    daten = lesen(fund.datei)
    def eigene_firma(name: str, ust: str) -> str | None:
        treffer = []
        for f in firmen():
            namen = [f["name"], *f.get("namen", [])]
            eigene_ust = str(f.get("ust_id", "")).strip().lower()
            if any(wert and str(wert).lower() in name.lower() for wert in namen) or (eigene_ust and ust.lower() == eigene_ust):
                treffer.append(f["name"])
        return treffer[0] if len(treffer) == 1 else None
    kaeufer = eigene_firma(daten.get("kaeufer", ""), daten.get("kaeufer_ust", ""))
    verkaeufer = eigene_firma(daten.get("verkaeufer", ""), daten.get("verkaeufer_ust", ""))
    ist_kaeufer, ist_verkaeufer = bool(kaeufer), bool(verkaeufer)
    zwischen_eigenen = ist_kaeufer and ist_verkaeufer and kaeufer != verkaeufer
    art = "ausgang" if ist_verkaeufer and not ist_kaeufer else "eingang"
    partner = (
        daten.get("kaeufer", "") if art == "ausgang" else daten.get("verkaeufer", "")
    )
    position = next(iter(daten.get("positionen", [])), {}).get("text", "Rechnung")
    unklar = zwischen_eigenen or not (kaeufer or verkaeufer)
    return Einordnung(
        True,
        art,
        "betrieb",
        daten.get("datum"),
        partner or "Unbekannt",
        re.sub(r"\s+", "-", position)[:80],
        float(daten.get("betrag") or 0) or None,
        daten.get("waehrung", "EUR"),
        "niedrig" if unklar else "hoch",
        "Rechnung zwischen eigenen Firmen" if zwischen_eigenen else "Firma unklar" if unklar else "E-Rechnung mit eindeutigem Geschäftspartner.",
        "xml", "unklar" if unklar else kaeufer or verkaeufer,
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


def einordnen(fund: Fund, text: Text, nur_lokal: bool = False) -> Einordnung:
    """Ordnet einen Fund nach festen Regeln, E-Rechnung und geprüftem Modellurteil ein.

    Ohne Modell liefert die Rückfallregel immer ein nachvollziehbares, vorsichtiges
    Ergebnis. So bleiben Tests und der lokale Betrieb unabhängig von einem Konto.
    """
    regel = _regel(fund)
    zahlungsname = _zahlungsabwickler(fund)
    firmen_treffer = _firmen_im_text(text.text)
    xml = _aus_xml(fund)
    if xml:
        return _sicheres_datum(xml, fund.eingang)
    alle_firmen = firmen()
    firmennamen = {f["name"] for f in alle_firmen}
    auftrag = vorlage(
        "einordnen",
        betrieb="; ".join(f"{f['name']} (Schreibweisen: {', '.join(f.get('namen', []))}; USt-IdNr.: {f.get('ust_id', '')})" for f in alle_firmen),
        namen=", ".join(firmennamen), ust_id="", taetigkeit="",
        firmen=", ".join(firmennamen),
        privat_erlaubt=konfig("belege").get("ablage", {}).get("privat", False),
        mail=_mailtext(fund),
        dateiname=fund.name,
        text=text.text[:6000],
    )
    antwort = frage(
        auftrag,
        zweck="einordnen",
        pruefe=lambda antwort: pruefe(antwort, firmennamen),
        rueckfall=lambda: _rueckfall(fund, text, regel, zahlungsname),
        nur_lokal=nur_lokal,
    )
    if regel:
        for feld in ("lieferant", "bereich", "art", "beschreibung"):
            if regel.get(feld):
                antwort[feld] = regel[feld]
    if zahlungsname:
        antwort["lieferant"] = zahlungsname
    deterministische_firma = _firma_aus_text(text.text, antwort["art"])
    # Das sichtbar adressierte Unternehmen gewinnt immer gegen ein Modellurteil
    # und gegen den Eingangsweg des Postfachs.
    if deterministische_firma:
        antwort["firma"] = deterministische_firma
    elif firmen_treffer:
        # Mehrdeutigkeit aus dem Beleg ist stärker als Modell und Postfach.
        antwort["firma"] = "unklar"
    datum = date.fromisoformat(antwort["datum"]) if antwort["datum"] else None
    erkannte_firma = antwort.get("firma", "")
    if len(alle_firmen) == 1 and not erkannte_firma:
        erkannte_firma = alle_firmen[0]["name"]
    unklar = erkannte_firma not in firmennamen
    ergebnis = Einordnung(
        ist_beleg=antwort["ist_beleg"],
        art=antwort["art"],
        bereich=antwort["bereich"],
        datum=datum,
        lieferant=antwort["lieferant"],
        beschreibung=antwort["beschreibung"],
        betrag=float(antwort["betrag"]) if antwort["betrag"] is not None else None,
        waehrung=antwort["waehrung"],
        sicherheit="niedrig" if unklar else antwort["sicherheit"],
        grund="Firma unklar" if unklar else antwort["grund"],
        quelle=(
            "regel"
            if regel
            else "rueckfall"
            if antwort.get("grund") == "Ohne Modell nur vorsichtig erkannt."
            else "urteil"
        ), firma=erkannte_firma if not unklar else "unklar",
    )
    return _sicheres_datum(ergebnis, fund.eingang)
