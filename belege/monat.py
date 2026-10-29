"""Monatlicher, bewusst konservativer Abgleich von Kontoauszug und Belegen."""

from __future__ import annotations

import csv
import re
import shutil
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from . import kern


def _monatsname(monat: str) -> str:
    return ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
            "September", "Oktober", "November", "Dezember")[int(monat[5:]) - 1]

BEKANNTE = {
    "datum": ("buchungstag", "datum", "valuta"),
    "betrag": ("betrag", "umsatz"),
    # "beschreibung" zuletzt: so heißt der Name nur im Kreditkartenexport von amex.de.
    "name": ("beguenstigter", "zahlungspflichtiger", "name", "empfänger", "empfaenger", "beschreibung"),
    "zweck": ("verwendungszweck", "buchungstext"),
    "soll_haben": ("soll/haben", "soll haben", "soll", "haben"),
    "originalbetrag": ("originalbetrag", "betrag in fremdwaehrung", "fremdbetrag"),
}


def _monat(wert: str | None) -> str:
    """Gibt den gewünschten Monat zurück, standardmäßig den Vormonat."""
    if wert and re.fullmatch(r"\d{4}-\d{2}", wert):
        return wert
    erster = kern.jetzt().date().replace(day=1)
    return (erster - timedelta(days=1)).strftime("%Y-%m")


def _normal(wert: str) -> str:
    """Vereinfacht Namen für einen vorsichtigen Lieferantenvergleich."""
    wert = (
        wert.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    wert = unicodedata.normalize("NFKD", wert).encode("ascii", "ignore").decode()
    wert = re.sub(r"\b(gmbh|ug|ag|e\.?k\.?|inc|ltd)\b", " ", wert)
    return re.sub(r"[^a-z0-9]+", " ", wert).strip()


def _betrag(wert: str, soll_haben: str = "") -> float:
    """Liest deutsche und englische Betragsformate einschließlich Soll/Haben."""
    text = str(wert).replace("€", "").replace(" ", "").strip()
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    zahl = float(re.sub(r"[^0-9.+-]", "", text) or "0")
    if "soll" in soll_haben.lower() and zahl > 0:
        return -zahl
    return zahl


def _spalten(kopf: list[str]) -> dict[str, str | None]:
    """Erkennt eindeutige Spalten oder fragt bei Mehrdeutigkeit konservativ nach."""
    klein = {wert: _normal(wert) for wert in kopf}
    gefunden: dict[str, list[str]] = {}
    for art, namen in BEKANNTE.items():
        # Die Namen stehen nach Vorrang: "Buchungstag" schlägt "Valuta". Die erste
        # Stufe, die genau eine Spalte trifft, gewinnt.
        gefunden[art] = []
        for name in namen:
            treffer = [original for original, normal in klein.items() if name in normal]
            if treffer:
                gefunden[art] = treffer
                break
    if all(len(gefunden[art]) == 1 for art in ("datum", "betrag", "name")):
        return {
            art: (werte[0] if len(werte) == 1 else None)
            for art, werte in gefunden.items()
        }
    from .urteil import frage, vorlage

    def rueckfall():
        return {
            art: (werte[0] if len(werte) == 1 else None)
            for art, werte in gefunden.items()
        }

    antwort = frage(
        vorlage("spalten", kopfzeile=" | ".join(kopf)),
        zweck="spalten",
        rueckfall=rueckfall,
    )
    if not isinstance(antwort, dict):
        return rueckfall()
    return {
        art: antwort.get(art) if antwort.get(art) in kopf else None for art in BEKANNTE
    }


def buchungen(datei: Path, monat: str | None) -> list[dict]:
    """Liest einen Auszug robust und gibt nur Buchungen des gewünschten Monats zurück."""
    return _buchungen_und_format(datei, monat)[0]


def _buchungen_und_format(datei: Path, monat: str | None) -> tuple[list[dict], bool]:
    """Wie buchungen, dazu ob die Datei ein Kartenexport im Format von amex.de ist."""
    roh = next(
        (
            datei.read_text(encoding=kodierung)
            for kodierung in ("utf-8-sig", "cp1252", "latin-1")
            if _lesbar(datei, kodierung)
        ),
        "",
    )
    zeilen = roh.splitlines()
    kopf_nr = next(
        (
            i
            for i, zeile in enumerate(zeilen)
            if len(_teile(zeile)) >= 3
            and sum(
                bool(re.search("datum|betrag|umsatz|name|zweck|buchung", z, re.I))
                for z in _teile(zeile)
            )
            >= 2
        ),
        -1,
    )
    if kopf_nr < 0:
        raise RuntimeError(
            "Die CSV hat keine erkennbare Kopfzeile. Prüfe den Kontoauszug."
        )
    muster = csv.Sniffer().sniff(
        "\n".join(zeilen[kopf_nr : kopf_nr + 3]), delimiters=";,\t|"
    )
    leser = csv.DictReader(zeilen[kopf_nr:], dialect=muster)
    spalten = _spalten(leser.fieldnames or [])
    konto_spalte = next((spalte for spalte in leser.fieldnames or []
                         if _normal(spalte) in {"konto", "kontokennung", "eigenes konto", "eigene iban"}), None)
    if not all(spalten.get(art) for art in ("datum", "betrag", "name")):
        raise RuntimeError(
            "Datum, Betrag oder Name sind nicht eindeutig. Prüfe die CSV-Spalten."
        )
    # Kreditkarte im Format von amex.de (auch aus `belege moneymoney`): Belastungen
    # stehen dort positiv. Umgedreht gilt wie beim Girokonto: Ausgabe negativ.
    karte = _kreditkarte(leser.fieldnames or [], spalten)
    vorzeichen = -1 if karte else 1
    ergebnis = []
    for zeile in leser:
        try:
            tag = _datum(zeile[spalten["datum"]])
            menge = vorzeichen * _betrag(
                zeile[spalten["betrag"]], zeile.get(spalten.get("soll_haben") or "", "")
            )
        except (KeyError, ValueError):
            continue
        if monat is None or tag.strftime("%Y-%m") == monat:
            buchung = {
                    "datum": tag.isoformat(),
                    "betrag": menge,
                    "name": zeile[spalten["name"]].strip(),
                    "zweck": zeile.get(spalten.get("zweck") or "", "").strip(),
                    "originalbetrag": _betrag(zeile[spalten["originalbetrag"]])
                    if spalten.get("originalbetrag") and zeile.get(spalten["originalbetrag"], "").strip() else None,
                }
            if konto_spalte and zeile.get(konto_spalte, "").strip():
                buchung["konto"] = zeile[konto_spalte].strip()
            ergebnis.append(buchung)
    return ergebnis, karte


def _kreditkarte(kopf: list[str], spalten: dict) -> bool:
    """Kopf wie beim CSV-Export von amex.de: Datum, Beschreibung, Betrag."""
    normal = {_normal(wert) for wert in kopf}
    return (
        {"datum", "beschreibung", "betrag"} <= normal
        and _normal(spalten.get("name") or "") == "beschreibung"
        and not spalten.get("soll_haben")
    )


def buchungen_aus(dateien: list[Path], monat: str | None) -> list[dict]:
    """Liest einen Monat aus mehreren Auszügen und zählt Dubletten nur einmal.

    Mehrere CSVs sind normal: ein Girokonto und eine Kreditkarte, oder eine
    Jahres-CSV neben einer Monats-CSV, oder derselbe Kartenumsatz von amex.de und
    aus MoneyMoney. Dieselbe Buchung (Datum, Betrag, Name, Zweck) fließt nur einmal
    in den Abgleich. Zwei gleiche Buchungen in derselben Datei (zweimal Kaffee am
    selben Tag) bleiben zwei.

    Kartenexporte (Format amex.de) vergleichen statt des ganzen Namens nur die
    ersten zwei Wörter (Händler und Referenz), weil zwei Exporte denselben Umsatz
    verschieden schreiben: „FACEBK *XD8YZ42FB4 DUBLIN“ bei amex.de, „Facebk
    *XD8YZ42FB4 Dublin Facebook Advertisi“ in MoneyMoney (Philip, 28.10.2026: 52
    Buchungen doppelt). Girokonto und Karte teilen sich nie einen Schlüssel.
    """
    gesehen: dict[tuple, int] = {}
    ergebnis: list[dict] = []
    mehrere_firmen = len(kern.firmen()) > 1
    for datei in dateien:
        try:
            gefunden, karte = _buchungen_und_format(datei, monat)
        except Exception as fehler:  # noqa: BLE001 - eine kaputte CSV stoppt den Rest nicht
            kern.log(f"Kontoauszug {datei.name} für {monat} nicht lesbar: {fehler}")
            continue
        in_datei: dict[tuple, int] = {}
        for buchung in gefunden:
            schluessel = _dublettenschluessel(buchung, karte)
            if mehrere_firmen and buchung.get("konto"):
                # Bei mehreren Firmen sind gleiche Umsätze auf verschiedenen Firmenkonten keine Dublette.
                schluessel = (_konto_kennung(buchung["konto"]),) + schluessel
            in_datei[schluessel] = in_datei.get(schluessel, 0) + 1
            # Neu ist nur, was diese Datei öfter enthält als jede Datei davor.
            if in_datei[schluessel] <= gesehen.get(schluessel, 0):
                continue
            gesehen[schluessel] = in_datei[schluessel]
            ergebnis.append(buchung)
    return ergebnis


def _dublettenschluessel(buchung: dict, karte: bool) -> tuple:
    """Schlüssel für dieselbe Buchung in mehreren Dateien (siehe buchungen_aus)."""
    if karte:
        woerter = re.findall(r"[\wäöüß]+", buchung["name"].casefold())
        if len(woerter) >= 2:
            return ("karte", buchung["datum"], buchung["betrag"], tuple(woerter[:2]))
    return (buchung["datum"], buchung["betrag"], buchung["name"], buchung["zweck"])


def _lesbar(datei: Path, kodierung: str) -> bool:
    """Prüft eine Kodierung ohne unlesbare CSV-Ausnahme nach außen zu geben."""
    try:
        datei.read_text(encoding=kodierung)
        return True
    except UnicodeDecodeError:
        return False


def _teile(zeile: str) -> list[str]:
    """Teilt eine mögliche Kopfzeile grob für ihre Erkennung."""
    return re.split(r"[;,\t|]", zeile)


def _datum(wert: str) -> date:
    """Liest die gebräuchlichen Datumsformate eines Kontoauszugs."""
    for format in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return (
                date.fromisoformat(wert)
                if format == "%Y-%m-%d"
                else datetime.strptime(wert.strip(), format).date()
            )
        except ValueError:
            continue
    raise ValueError(wert)


def _auszuege(args, monat: str) -> list[Path]:
    """Der angegebene Kontoauszug, sonst alle im Auszugsordner mit Buchungen im Monat."""
    if getattr(args, "auszug", None):
        return [Path(args.auszug).expanduser()]
    ordner = kern.erweitert(kern.konfig("belege").get("monat", {}).get("auszuege", ""))
    treffer = []
    for datei in sorted(ordner.glob("*.csv")):
        try:
            if buchungen(datei, monat):
                treffer.append(datei)
        except Exception as fehler:  # noqa: BLE001 - eine kaputte CSV soll die Suche nicht stoppen
            kern.log(f"Kontoauszug {datei.name} nicht lesbar: {fehler}")
    return treffer


def _konten_pruefen(monat: str, args) -> list[Path]:
    """Prüft das optionale Register und meldet eine Auszugslücke höchstens wöchentlich."""
    try:
        register = kern.konfig("konten").get("konto", [])
    except FileNotFoundError:
        return []
    if not register:
        return []
    zustand = kern.lesen(kern.pfad("arbeit", "konten.json"), {}) or {}
    heute = kern.jetzt().date()
    dateien = []
    standard = kern.erweitert(kern.konfig("belege").get("monat", {}).get("auszuege", ""))
    for konto in register:
        if konto.get("aktiv_ab", "") and monat < str(konto["aktiv_ab"]):
            continue
        ordner = kern.erweitert(konto.get("ordner") or standard)
        kandidaten = sorted(ordner.glob(konto.get("muster") or "*")) if ordner.exists() else []
        vorhanden = []
        for datei in kandidaten:
            if konto.get("quelle", "csv") in {"csv", "moneymoney"}:
                try:
                    if buchungen(datei, monat):
                        vorhanden.append(datei)
                except Exception:
                    continue
            elif datei.is_file() and (monat in datei.name or not konto.get("muster")):
                vorhanden.append(datei)
        kurz = str(konto.get("kuerzel") or konto.get("name"))
        alt = zustand.get(kurz, {})
        if vorhanden:
            dateien.extend(vorhanden)
            if alt.get("fehlt"):
                kern.ereignis("monat", f"Kontoauszug {konto.get('name', kurz)} für {_monatsname(monat)} ist da – danke.")
            zustand[kurz] = {"fehlt": False, "monat": monat}
            continue
        letzter = alt.get("gemeldet")
        erneut = not letzter
        if letzter:
            try:
                erneut = (heute - date.fromisoformat(letzter)).days >= 7
            except ValueError:
                erneut = True
        if not alt.get("fehlt") or erneut:
            kern.ereignis("monat", f"Für {_monatsname(monat)} fehlt der Kontoauszug von {konto.get('name', kurz)}. Lade ihn im Online-Banking als CSV herunter und leg ihn in {ordner.name} – oder verbinde das Konto mit MoneyMoney.")
            alt["gemeldet"] = heute.isoformat()
        alt.update(fehlt=True, monat=monat)
        zustand[kurz] = alt
    kern.schreiben(kern.pfad("arbeit", "konten.json"), zustand)
    return dateien


def _lieferanten(beleg: dict) -> list[str]:
    """Gibt Lieferant und seine bewusst gepflegten Aliasnamen zurück."""
    name = str(beleg.get("lieferant", ""))
    aliase = kern.konfig("regeln").get("monat", {}).get("aliase", {})
    ergebnis = [name]
    for hauptname, werte in aliase.items():
        if _normal(hauptname) == _normal(name):
            ergebnis.extend(str(wert) for wert in werte)
    iban = beleg.get("gegen_iban") or beleg.get("iban")
    if iban:
        ergebnis.append(str(iban))
    return ergebnis


def _gleicher_name(beleg: dict, buchung: dict) -> bool:
    """Ein Betrag genügt nie: Lieferant, Alias oder Gegen-IBAN müssen vorkommen."""
    suchraum = _normal(f"{buchung['name']} {buchung['zweck']}").split()
    for name in _lieferanten(beleg):
        woerter = [wort for wort in _normal(name).split() if len(wort) >= 3]
        if woerter and any(wort in suchraum for wort in woerter):
            return True
    return False


def _referenz(beleg: dict) -> str:
    """Nimmt eine Rechnungsnummer aus dem Index oder dem Dateinamen, nie Daten."""
    wert = str(beleg.get("rechnungsnummer") or beleg.get("nummer") or Path(str(beleg.get("pfad", ""))).stem)
    treffer = re.findall(r"[A-Za-z]*[0-9][A-Za-z0-9-]*", wert)
    for nummer in sorted(treffer, key=len, reverse=True):
        ziffern = re.sub(r"\D", "", nummer)
        if re.fullmatch(r"20\d{2}[-.]?\d{2}[-.]?\d{2}", nummer) or re.fullmatch(r"0+\d", ziffern):
            continue
        if len(nummer) >= 4:
            return nummer
    return ""


def _beleg_betrag(beleg: dict) -> float | None:
    """Originalbetrag ist bei Fremdwährung maßgeblich, sonst der Euro-Betrag."""
    wert = beleg.get("originalbetrag") if beleg.get("originalbetrag") is not None else beleg.get("betrag")
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _sonderart(buchung: dict) -> str | None:
    """Kennzeichnet Zahlungen, deren Nachweis kein normaler Beleg ist."""
    cfg = kern.konfig("regeln").get("monat", {})
    raum = _normal(f"{buchung['name']} {buchung['zweck']}")
    for art, status in (("lohn", "lohn"), ("abgaben", "abgabe"), ("bank", "bank"), ("abschlag", "abschlag")):
        if any(_normal(str(muster)) in raum for muster in cfg.get(art, [])):
            return status
    return None


def abgleichen(buchungen_liste: list[dict], index: dict, firma: str | None = None) -> list[dict]:
    """Ordnet Belege nur bei einem eindeutigen Kandidaten mit Namensbezug zu."""
    benutzt: set[str] = set()
    ohne = kern.konfig("regeln").get("monat", {}).get("ohne_beleg", [])
    ergebnis = []
    for buchung in buchungen_liste:
        eintrag = dict(buchung)
        if any(
            _normal(muster) in _normal(f"{buchung['name']} {buchung['zweck']}")
            for muster in ohne
        ):
            eintrag["status"] = "ohne_beleg"
            ergebnis.append(eintrag)
            continue
        sonder = _sonderart(buchung)
        if sonder:
            eintrag["status"] = sonder
            ergebnis.append(eintrag)
            continue
        art = "eingang" if buchung["betrag"] < 0 else "ausgang"
        tag = date.fromisoformat(buchung["datum"])
        kandidaten = [
            (sha, beleg)
            for sha, beleg in index.items()
            if sha not in benutzt
            and beleg.get("status") == "abgelegt"
            and beleg.get("bereich") == "betrieb"
            and (firma is None or kern.firma_von(beleg) == firma)
            and beleg.get("art") == art
            and _beleg_betrag(beleg) is not None
            and abs(abs(buchung.get("originalbetrag") if buchung.get("originalbetrag") is not None else buchung["betrag"]) - _beleg_betrag(beleg)) <= 0.01
            and _im_fenster(beleg.get("datum"), tag)
        ]
        passende = [
            (sha, beleg) for sha, beleg in kandidaten if _gleicher_name(beleg, buchung)
        ]
        # Rechnung und Quittung derselben Zahlung sind ein Beleg-Paar. Die
        # Rechnung bleibt der sichtbare Hauptbeleg.
        rechnungen = [(sha, beleg) for sha, beleg in passende if not _ist_quittung(beleg)]
        quittungen = [(sha, beleg) for sha, beleg in passende if _ist_quittung(beleg)]
        if len(rechnungen) == 1 and quittungen:
            passende = rechnungen
            kandidaten = rechnungen
        referenz = [(sha, beleg) for sha, beleg in passende if (nummer := _referenz(beleg)) and nummer.lower() in buchung.get("zweck", "").lower()]
        privat = [
            beleg for beleg in index.values()
            if beleg.get("bereich") == "privat" and beleg.get("status") == "abgelegt"
            and beleg.get("betrag") is not None
            and abs(abs(buchung["betrag"]) - float(beleg["betrag"])) <= 0.01
            and _im_fenster(beleg.get("datum"), tag) and _gleicher_name(beleg, buchung)
        ]
        if referenz and len(referenz) == 1:
            eintrag["status"] = "zugeordnet"
            eintrag["beleg"] = referenz[0][0]
            benutzt.add(referenz[0][0])
        elif not kandidaten and privat:
            # Vom Geschäftskonto bezahlt, Beleg liegt unter Privat: für den Steuerberater eine
            # Privatentnahme, kein fehlender Beleg.
            eintrag["status"] = "privat"
            eintrag["beleg_pfad"] = privat[0].get("pfad")
        elif len(passende) == 1 and (len(kandidaten) == 1 or buchung.get("originalbetrag") is not None):
            eintrag["status"] = "zugeordnet"
            eintrag["beleg"] = passende[0][0]
            benutzt.add(passende[0][0])
        elif kandidaten:
            eintrag["status"] = "pruefen"
        else:
            # Ohne Originalbetrag bleibt Fremdwährung nur ein Hinweis, niemals Zuordnung.
            fremd = any(
                str(beleg.get("waehrung", "EUR")) != "EUR"
                and beleg.get("betrag") is not None
                and abs(abs(buchung["betrag"]) - float(beleg["betrag"])) <= abs(float(beleg["betrag"])) * .03
                and _gleicher_name(beleg, buchung)
                for beleg in index.values()
            )
            eintrag["status"] = "pruefen" if fremd else "fehlt"
        ergebnis.append(eintrag)
    _sammelrechnungen(ergebnis, index, benutzt, firma)
    _dauerbelege(ergebnis)
    return ergebnis


def _ist_quittung(beleg: dict) -> bool:
    """Erkennt Zahlungsbestätigungen, die zu einer Rechnung gehören können."""
    raum = " ".join(str(beleg.get(name, "")) for name in ("titel", "beschreibung", "text", "pfad"))
    return bool(re.search(r"quittung|receipt|zahlungsbestätigung|zahlungsbestaetigung", raum, re.I))


def _sammelrechnungen(ergebnis: list[dict], index: dict, benutzt: set[str], firma: str | None = None) -> None:
    """Ordnet bis zu sechs Teilzahlungen einer passenden Sammelrechnung zu."""
    offen = [x for x in ergebnis if x["status"] in {"fehlt", "pruefen"}]
    for sha, beleg in index.items():
        if (sha in benutzt or beleg.get("status") != "abgelegt" or _beleg_betrag(beleg) is None
                or (firma is not None and kern.firma_von(beleg) != firma)):
            continue
        passende = [x for x in offen if _gleicher_name(beleg, x) and _im_fenster(beleg.get("datum"), date.fromisoformat(x["datum"]))]
        for anzahl in range(2, min(6, len(passende)) + 1):
            from itertools import combinations
            for gruppe in combinations(passende, anzahl):
                if abs(sum(abs(x["betrag"]) for x in gruppe) - _beleg_betrag(beleg)) <= 0.01:
                    for x in gruppe:
                        x["status"], x["beleg"] = "zugeordnet (Sammelrechnung)", sha
                    benutzt.add(sha)
                    break


def _beitragsnummer(buchung: dict) -> str:
    """Neunstellige Beitragsnummer aus einer Rundfunk-Abbuchung, sonst leer."""
    text = f"{buchung.get('name', '')} {buchung.get('zweck', '')}"
    if "rundfunk" not in _normal(text) and "beitragsservice" not in _normal(text):
        return ""
    # „Beitragsnr.“, „Beitragsnummer“, „Beitrags-Nr.“, mit oder ohne Leerzeichen in der Nummer.
    treffer = re.search(r"beitrags?\s*-?\s*(?:nr\.?|nummer)\s*:?\s*(?<!\d)(\d{3}\s?\d{3}\s?\d{3})(?!\d)", text, re.I)
    return re.sub(r"\s", "", treffer.group(1)) if treffer else ""


def _enthaelt_nummer(text: str, nummer: str) -> bool:
    """Die Beitragsnummer steht als eigene Zahl im Text, nicht als Teil einer längeren."""
    ziffern = re.sub(r"(?<=\d)\s(?=\d)", "", text)
    return re.search(rf"(?<!\d){nummer}(?!\d)", ziffern) is not None


def _dauerbelege(ergebnis: list[dict]) -> None:
    """Findet Verträge in der Dokumentenablage, Kündigungen sind kein Nachweis.

    Rundfunkbeitrag (Philip, 28.10.2026): keine Monatsrechnung; Dauerbeleg ist der
    Bescheid bzw. die Anmeldebestätigung des Beitragsservice mit derselben Beitragsnummer.
    """
    dokumente = kern.lesen(kern.pfad("arbeit", "dokumente.json"), {}) or {}
    for buchung in ergebnis:
        if buchung["status"] != "fehlt":
            continue
        nummer = _beitragsnummer(buchung)
        if nummer:
            for eintrag in dokumente.values():
                raum = f"{eintrag.get('gegenueber', '')} {eintrag.get('titel', '')} {eintrag.get('text', '')}"
                if _enthaelt_nummer(raum, nummer):
                    buchung["status"] = "zugeordnet (Dauerbeleg)"
                    buchung["beleg_pfad"] = eintrag.get("pfad")
                    break
            if buchung["status"] != "fehlt":
                continue
        for eintrag in dokumente.values():
            raum = f"{eintrag.get('gegenueber', '')} {eintrag.get('titel', '')} {eintrag.get('text', '')} {eintrag.get('pfad', '')}"
            if "kündigung" in _normal(raum) or "kuendigung" in _normal(raum):
                continue
            probe = {"lieferant": eintrag.get("gegenueber", "")}
            if eintrag.get("art") == "vertrag" and _gleicher_name(probe, buchung):
                buchung["status"] = "zugeordnet (Dauerbeleg)"
                buchung["beleg_pfad"] = eintrag.get("pfad")
                break


def _im_fenster(wert: str | None, tag: date) -> bool:
    """Prüft das vertragliche Zeitfenster rund um eine Buchung."""
    try:
        belegtag = date.fromisoformat(str(wert))
    except ValueError:
        return False
    return tag - timedelta(days=45) <= belegtag <= tag + timedelta(days=5)


def euro(betrag: float) -> str:
    """12.5 → "12,50 €" (nur der Betrag wird umformatiert, nie der übrige Text)."""
    return f"{abs(betrag):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _tag(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d.%m.%Y")


def _zeile(buchung: dict) -> str:
    zweck = f" · {buchung['zweck']}" if buchung.get("zweck") else ""
    return f"- {_tag(buchung['datum'])} · {euro(buchung['betrag'])} · {buchung['name']}{zweck}"


def offene_posten_text(monat: str, ergebnis: list[dict]) -> str:
    """Der Text für den Steuerberater: was fehlt, was zu prüfen ist, mit Summen."""
    offen = [x for x in ergebnis if x["status"] == "fehlt"]
    pruefen = [x for x in ergebnis if x["status"] == "pruefen"]
    teile = []
    if offen:
        summe = euro(sum(abs(x["betrag"]) for x in offen))
        teile.append(f"Zu diesen Zahlungen fehlt noch ein Beleg ({len(offen)}, zusammen {summe}):\n"
                     + "\n".join(_zeile(x) for x in offen))
    if pruefen:
        teile.append("Hier passen mehrere Belege oder der Name ist unklar, bitte prüfen:\n"
                     + "\n".join(_zeile(x) for x in pruefen))
    privat = [x for x in ergebnis if x["status"] == "privat"]
    if privat:
        teile.append("Vom Geschäftskonto bezahlt, der Beleg ist privat (vermutlich Privatentnahme):\n"
                     + "\n".join(_zeile(x) for x in privat))
    erklaerungen = {
        "lohn": "Lohnabrechnung nötig, sie kommt vom Lohnbüro:",
        "abgabe": "Bescheid nötig:",
        "bank": "Kontoauszug genügt:",
        "abschlag": "Abschlagsplan oder Jahresrechnung nötig:",
    }
    for status, text in erklaerungen.items():
        posten = [x for x in ergebnis if x["status"] == status]
        if posten:
            teile.append(text + "\n" + "\n".join(_zeile(x) for x in posten))
    gefunden = [x for x in ergebnis if x["status"] == "gefunden"]
    if gefunden:
        teile.append("Liegt schon woanders, bitte ablegen:\n" + "\n".join(
            _zeile(x) + f" → {x.get('fund', '')}" for x in gefunden
        ))
    if not teile:
        teile.append(f"Zu allen Zahlungen im {monat[5:]}/{monat[:4]} liegt ein Beleg vor.")
    return "\n\n".join(teile)


def _schreibe_ausgaben(ordner: Path, monat: str, ergebnis: list[dict], mahnungen: list[dict] | None = None,
                       hinweis: str | None = None, name: str | None = None) -> None:
    """Schreibt die lesbaren Abgleichdateien nach arbeit/monat/<JJJJ-MM>/."""
    ordner.mkdir(parents=True, exist_ok=True)
    offen = [x for x in ergebnis if x["status"] == "fehlt"]
    pruefen = [x for x in ergebnis if x["status"] == "pruefen"]

    spalten = ["Datum", "Betrag", "Name", "Verwendungszweck"]
    with open(ordner / "fehlt_noch.csv", "w", encoding="utf-8", newline="") as ziel:
        schreiber = csv.DictWriter(ziel, fieldnames=spalten, delimiter=";")
        schreiber.writeheader()
        for x in offen:
            schreiber.writerow({
                "Datum": _tag(x["datum"]),
                "Betrag": f"{abs(x['betrag']):.2f}".replace(".", ","),
                "Name": x["name"],
                "Verwendungszweck": x["zweck"],
            })

    summe = euro(sum(abs(x["betrag"]) for x in offen))
    (ordner / "fehlt_noch.md").write_text(
        "# Fehlende Belege\n\n" + (f"> {hinweis}\n\n" if hinweis else "")
        + "\n".join(_zeile(x) for x in offen) + f"\n\nSumme: {summe}\n",
        encoding="utf-8",
    )
    (ordner / "pruefen.md").write_text(
        "# Bitte prüfen\n\n" + "\n".join(_zeile(x) for x in pruefen) + "\n", encoding="utf-8"
    )

    betrieb = name or kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")
    zeilen = [f"# Offene Posten {monat[5:]}/{monat[:4]}, {betrieb}", ""]
    if hinweis:
        zeilen += [hinweis, ""]
    for x in offen + pruefen:
        zeilen.append(_zeile(x) + " → Was ist das? ______")
    privat = [x for x in ergebnis if x["status"] == "privat"]
    if privat:
        zeilen += ["", "Vom Geschäftskonto bezahlt, Beleg privat:"] + [_zeile(x) for x in privat]
    (ordner / "klaerung.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    if mahnungen:
        (ordner / "mahnungen.md").write_text("# Mahnungen\n\n" + "\n".join(
            f"- {x['glaeubiger']}: {x['status']} ({x['pfad']})" for x in mahnungen
        ) + "\n", encoding="utf-8")
    kern.schreiben(ordner / "abgleich.json", ergebnis)


def _konto_kennung(wert: object) -> str:
    """Vergleicht IBANs und Kontokennungen robust, Leerzeichen sind egal."""
    return re.sub(r"\s+", "", str(wert or "")).casefold()


def _buchungen_fuer_firma(buchungen: list[dict], firma: dict, alle_firmen: list[dict]) -> list[dict]:
    """Gibt nur die Buchungen der Firmenkonten; nicht zugeordnete gehören zur Hauptfirma."""
    zugeordnet = {
        _konto_kennung(konto)
        for eintrag in alle_firmen for konto in eintrag.get("konten", [])
        if _konto_kennung(konto)
    }
    eigene = {_konto_kennung(konto) for konto in firma.get("konten", []) if _konto_kennung(konto)}
    hauptfirma = alle_firmen[0]["name"]
    if firma["name"] == hauptfirma:
        # Die Hauptfirma bekommt ihre eigenen Konten und alles, was keiner Firma zugeordnet ist,
        # auch Buchungen ohne erkannte Kontokennung.
        return [buchung for buchung in buchungen
                if _konto_kennung(buchung.get("konto")) in eigene or _konto_kennung(buchung.get("konto")) not in zugeordnet]
    if eigene:
        return [buchung for buchung in buchungen if _konto_kennung(buchung.get("konto")) in eigene]
    return []


def _fund_passt(datei: Path, buchung: dict, mail: dict | None = None) -> bool:
    """Prüft Nachsuche konservativ über Betrag und Lieferantenbezug im Fund."""
    try:
        from .text import auslesen
        erkannt = auslesen(datei, mail=mail).text
        text = erkannt + " " + datei.name
        # Alte, beschädigte Pseudo-PDFs bleiben für die Nachsuche lesbar; echte
        # PDFs gehen stets durch die Text-Kaskade (auch bei Flate-Kompression).
        if not erkannt.strip() and datei.suffix.lower() == ".pdf":
            text = datei.read_text(encoding="utf-8", errors="ignore") + " " + datei.name
    except (OSError, ValueError):
        return False
    # Der Buchungsname muss im Fund auftauchen. Ohne sichere Lieferantenangabe
    # wird ein gleich hoher Betrag nie als Fund gemeldet.
    name = _normal(buchung["name"])
    if not any(wort in _normal(text).split() for wort in name.split() if len(wort) >= 4):
        return False
    zahlen = re.findall(r"\d+(?:[.,]\d{2})", text)
    return any(abs(_betrag(wert) - abs(buchung["betrag"])) <= .01 for wert in zahlen)


def _nachsuche(daten: list[dict], args) -> None:
    """Sucht fehlende Belege lesend in allen bekannten Eingängen.

    Ein einzelner Fund darf mit --echt durch den normalen Ablageweg laufen.
    """
    from . import quellen
    cfg = kern.konfig("belege")
    funde = list(quellen.downloads_funde() or []) + list(quellen.handy_funde() or []) + list(quellen.scan_funde() or [])
    eingang_wert = str(cfg.get("dokumente", {}).get("eingang", "")).strip()
    eingang = kern.erweitert(eingang_wert) if eingang_wert else None
    if eingang and eingang.is_dir():
        from .typen import Fund
        for datei in eingang.iterdir():
            if datei.is_file():
                funde.append(Fund(datei, "dokumente-eingang", datei.name, date.fromtimestamp(datei.stat().st_mtime)))
    for konto in cfg.get("konto", []):
        if not konto.get("belege", True):
            continue
        try:
            funde.extend(quellen.postfach_funde(konto["name"], 55) or [])
        except Exception:  # ein nicht eingerichtetes Postfach soll Monatsende nicht bremsen
            continue
    for buchung in (x for x in daten if x["status"] == "fehlt"):
        passende = [fund for fund in funde if _fund_passt(fund.datei, buchung, fund.mail)]
        if not passende:
            continue
        if len(passende) > 1:
            buchung["status"] = "pruefen"
            buchung["hinweis"] = "Nachsuche mehrdeutig: mehrere passende Funde"
            continue
        fund = passende[0]
        buchung["status"] = "gefunden"
        buchung["fund"] = str(fund.mail.get("betreff") if fund.mail else fund.datei)
        buchung["quelle"] = fund.quelle
        if kern.echt(args):
            from .verarbeiten import verarbeite
            verarbeite(fund, True)


def _mahnungen() -> list[dict]:
    """Gleicht abgelegte Mahnungen mit allen verfügbaren Kontoauszügen ab."""
    dokumente = kern.lesen(kern.pfad("arbeit", "dokumente.json"), {}) or {}
    auszug_ordner = kern.erweitert(kern.konfig("belege").get("monat", {}).get("auszuege", ""))
    alle = []
    for csv_datei in auszug_ordner.glob("*.csv"):
        # Mahnungen dürfen alte Zahlungen suchen, nicht nur den gerade
        # abgeglichenen Monat.
        try:
            alle.extend(buchungen(csv_datei, None))
        except Exception:
            continue
    ergebnis = []
    for eintrag in dokumente.values():
        text = f"{eintrag.get('titel', '')} {eintrag.get('text', '')}"
        if not re.search(r"mahnung|zahlungserinnerung|letzte aufforderung", text, re.I):
            continue
        try:
            tag = date.fromisoformat(str(eintrag.get("datum")))
        except ValueError:
            continue
        glaeubiger = str(eintrag.get("gegenueber", ""))
        betraege = [float(w) for w in re.findall(r"\d+(?:[.,]\d{2})", text) for w in [_betrag(w)]]
        letzter_auszug = max((date.fromisoformat(b["datum"]) for b in alle), default=None)
        if letzter_auszug is None or letzter_auszug < tag:
            ergebnis.append({"glaeubiger": glaeubiger, "status": "nicht prüfbar, Auszug fehlt", "pfad": eintrag.get("pfad", "")})
            continue
        passende = [b for b in alle if tag - timedelta(days=60) <= date.fromisoformat(b["datum"]) <= tag
                    and _gleicher_name({"lieferant": glaeubiger}, b)
                    and (not betraege or any(abs(abs(b["betrag"]) - wert) <= .01 for wert in betraege))]
        status = f"bezahlt am {_tag(passende[0]['datum'])}" if passende else "offen"
        ergebnis.append({"glaeubiger": glaeubiger, "status": status, "pfad": eintrag.get("pfad", "")})
    return ergebnis


def _als_pdf(bild: Path, ziel: Path) -> Path:
    """Fotos (Kassenbons) werden für die Übergabe zu PDF: DATEV nimmt nur PDF/TIF."""
    from PIL import Image

    pdf = kern.freier_name(ziel / (bild.stem + ".pdf"))
    with Image.open(bild) as offen:
        offen.convert("RGB").save(pdf, "PDF", resolution=200)
    return pdf


def paket_packen(monat: str, ziel: Path, index: dict, firma: str | None = None, belegart: str | None = None) -> list[Path]:
    """Kopiert alle abgelegten Betriebsbelege des Monats nach <ziel>/paket/.

    PDFs werden byte-gleich kopiert (ZUGFeRD bleibt erhalten), Fotos zu PDF
    umgewandelt, das XML einer E-Rechnung kommt dazu, außer nur_pdf_tif ist an.
    """
    paket = ziel / "paket"
    if paket.exists():
        shutil.rmtree(paket)  # unser eigenes Zwischenpaket, nie Belege des Mitglieds
    paket.mkdir(parents=True)
    nur_pdf = kern.konfig("belege").get("uebergabe", {}).get("nur_pdf_tif", False)
    ablage = kern.ablage_ordner()
    dateien: list[Path] = []
    for beleg in index.values():
        if str(beleg.get("datum", ""))[:7] != monat:
            continue
        if beleg.get("bereich") != "betrieb" or beleg.get("status") != "abgelegt":
            continue
        if belegart and beleg.get("art") != belegart:
            continue
        if firma is not None and kern.firma_von(beleg) != firma:
            continue
        quelle = ablage / str(beleg.get("pfad", ""))
        if not quelle.exists():
            continue
        if quelle.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic"):
            dateien.append(_als_pdf(quelle, paket))
        else:
            kopie = kern.freier_name(paket / quelle.name)
            shutil.copy2(quelle, kopie)
            dateien.append(kopie)
        if beleg.get("xml") and not nur_pdf:
            xml = ablage / beleg["xml"]
            if xml.exists():
                xml_kopie = kern.freier_name(paket / xml.name)
                shutil.copy2(xml, xml_kopie)
                dateien.append(xml_kopie)
    return sorted(dateien)


def _hinweise_text(monat: str, index: dict, firma: dict | None = None) -> str:
    """Formatiert reine Buchhaltungshinweise für die monatliche Übergabe."""
    zeilen = []
    for eintrag in index.values():
        if not str(eintrag.get("datum", "")).startswith(monat):
            continue
        if firma and kern.firma_von(eintrag) != firma["name"]:
            continue
        for hinweis in eintrag.get("hinweise", []):
            zeilen.append(f"- {Path(str(eintrag.get('pfad', 'Unbekannt'))).name}: {hinweis}")
    return "Hinweise für die Buchhaltung\n" + "\n".join(zeilen) if zeilen else ""


def _uebergabe(monat: str, ziel: Path, index: dict, ergebnis: list[dict], args, firma: dict | None = None) -> None:
    """Übergibt das Paket an den Steuerberater, einmal je Monat.

    Die offenen Posten stehen im Mailtext, nicht als Anhang, weil Beleg-Adressen
    wie DATEV Upload Mail nur PDF und TIF annehmen.
    """
    echt = kern.echt(args)
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    schluessel = f"{firma['name']}:{monat}" if firma else monat
    uebergaben = gesehen.get("uebergabe", {})
    schon = uebergaben.get(schluessel)
    # Der alte Schlüssel ohne Firma steht für die damalige einzige Firma und
    # schützt bei der Migration ausschließlich die heutige Hauptfirma.
    if firma and firma["name"] == kern.firmen()[0]["name"]:
        schon = schon or uebergaben.get(monat)
    if schon and "nochmal" not in (getattr(args, "ziel", None) or []):
        print(f"nichts: {monat} wurde schon am {schon[:10]} übergeben. Nochmal: belege monat nochmal "
              f"--monat {monat} --uebergabe --echt")
        return

    cfg = kern.konfig("belege").get("uebergabe", {})
    cfg = {**cfg, **({"adresse": firma["uebergabe"]} if firma and firma.get("uebergabe") else {})}
    adressen = cfg.get("adressen") if isinstance(cfg.get("adressen"), dict) else None
    hinweise = _hinweise_text(monat, index, firma)
    if adressen and cfg.get("weg", "mail") == "mail":
        from .senden import senden
        name = firma["name"] if firma else kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")
        for art in ("eingang", "ausgang", "sonstige"):
            eigene = f"{schluessel}:{art}"
            if gesehen.get("uebergabe", {}).get(eigene):
                continue
            adresse = adressen.get(art) or cfg.get("adresse", "")
            dateien = paket_packen(monat, ziel / art, index, firma["name"] if firma else None, art)
            if not dateien:
                continue
            if not adresse:
                print(f"befund: {art}: keine Übergabe-Adresse eingetragen, nicht gesendet.")
                continue
            # Die offenen Posten stehen wie bei der gemeinsamen Übergabe im Text, hier in der Mail mit den Eingangsbelegen.
            posten = ("\n\n" + offene_posten_text(monat, ergebnis)) if art == "eingang" else ""
            notizen = ("\n\n" + hinweise) if art == "eingang" and hinweise else ""
            text_art = f"Hallo,\n\nanbei {len(dateien)} Belege ({art}) für {monat[5:]}/{monat[:4]}.{posten}{notizen}\n\nViele Grüße\n{name}"
            r = senden(adresse, f"Belege {monat[5:]}/{monat[:4]} ({art}), {name}", text_art, dateien, echt, fortschritt=f"uebergabe:{eigene}")
            print(f"{r.status}: {r.meldung}")
            if echt and r.status == "ok":
                gesehen.setdefault("uebergabe", {})[eigene] = kern.jetzt().isoformat(timespec="seconds")
                kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
        return
    dateien = paket_packen(monat, ziel, index, firma["name"] if firma else None)
    betrieb = firma["name"] if firma else kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")
    betreff = f"Belege {monat[5:]}/{monat[:4]}, {betrieb}"
    text = (
        f"Hallo,\n\nanbei {len(dateien)} Belege für {monat[5:]}/{monat[:4]}.\n\n"
        + offene_posten_text(monat, ergebnis)
        + (("\n\n" + hinweise) if hinweise else "")
        + f"\n\nViele Grüße\n{betrieb}"
    )

    if cfg.get("weg") == "ordner":
        if not cfg.get("ordner"):
            print("fehler: [uebergabe] ordner ist leer.")
            return
        zielordner = kern.erweitert(cfg["ordner"]) / monat
        if not echt:
            print(f"trocken: würde {len(dateien)} Dateien nach {zielordner} kopieren.")
            return
        zielordner.mkdir(parents=True, exist_ok=True)
        for datei in dateien + [ziel / "fehlt_noch.md", ziel / "klaerung.md"]:
            shutil.copy2(datei, kern.freier_name(zielordner / datei.name))
        ergebnis_text = f"{len(dateien)} Belege nach {zielordner} kopiert"
    else:
        if not cfg.get("adresse"):
            print("fehler: [uebergabe] adresse ist leer. "
                  "Sag deinem Claude: Richte Teil 5 aus einrichten.md ein.")
            return
        from .senden import senden

        r = senden(cfg["adresse"], betreff, text, dateien, echt, fortschritt=f"uebergabe:{schluessel}")
        print(f"{r.status}: {r.meldung}")
        if not echt or r.status != "ok":
            return
        ergebnis_text = f"{len(dateien)} Belege an {cfg['adresse']} gesendet"

    gesehen.setdefault("uebergabe", {})[schluessel] = kern.jetzt().isoformat(timespec="seconds")
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    kern.ereignis("monat", f"Übergabe {monat}: {ergebnis_text}")


def _anfragen(daten: list[dict], echt: bool) -> None:
    """Legt für jede fehlende Ausgabe einen Rechnungsentwurf an, nie eine Sendung."""
    from .postfach import oeffnen
    from .senden import entwurf

    postfach = oeffnen()
    for buchung in (x for x in daten if x["status"] == "fehlt"):
        wort = next(iter(_normal(buchung["name"]).split()), "")
        treffer = postfach.suchen(f"von:{wort}", max=1) if wort else []
        an = treffer[0].get("von", "") if treffer else ""
        tag = date.fromisoformat(buchung["datum"])
        text = (
            f"Guten Tag,\n\nbitte schicken Sie mir die Rechnung zur Zahlung vom {tag:%d.%m.%Y} "
            f"über {euro(buchung['betrag'])} als PDF. Verwendungszweck: {buchung['zweck']}\n\nDanke."
        )
        entwurf(
            an,
            f"Rechnung zur Zahlung vom {tag:%d.%m.%Y} über {euro(buchung['betrag'])}",
            text,
            [],
            echt,
        )


def befehl(args) -> int:
    """Führt Monatsabgleich, optionale Übergabe und Rechnungsanfragen aus."""
    monat = _monat(getattr(args, "monat", None))
    auszuege = [datei for datei in _auszuege(args, monat) if datei.exists()]
    register_dateien = _konten_pruefen(monat, args)
    if register_dateien:
        auszuege = list(dict.fromkeys(auszuege + register_dateien))
    if not auszuege:
        ordner = kern.erweitert(
            kern.konfig("belege").get("monat", {}).get("auszuege", "")
        )
        text = f"Für {_monatsname(monat)} fehlt der Kontoauszug. Lade ihn im Online-Banking als CSV herunter und leg ihn in {ordner.name} – oder verbinde das Konto mit MoneyMoney."
        kern.ereignis("monat", text)
        print(f"nichts: {text}")
        return 0
    index = kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}
    alle_firmen = kern.firmen()
    if len(alle_firmen) > 1:
        buchungen = buchungen_aus(auszuege, monat)
        alle_daten: list[dict] = []
        for einzelfirma in alle_firmen:
            hinweis = None
            if not einzelfirma.get("konten") and einzelfirma["name"] != alle_firmen[0]["name"]:
                hinweis = "Kontoauszug keiner Firma zugeordnet: trag in [[firma]] konten ein"
            daten_firma = abgleichen(_buchungen_fuer_firma(buchungen, einzelfirma, alle_firmen), index, einzelfirma["name"])
            _nachsuche(daten_firma, args)
            alle_daten += daten_firma
            ziel_firma = kern.pfad("arbeit", "monat", monat, einzelfirma["bereich"])
            _schreibe_ausgaben(ziel_firma, monat, daten_firma, _mahnungen(), hinweis, einzelfirma["name"])
            zugeordnet = sum(x["status"].startswith("zugeordnet") for x in daten_firma)
            fehlt = [x for x in daten_firma if x["status"] == "fehlt"]
            zusatz = f" – {hinweis}" if hinweis else ""
            print(f"ok: {einzelfirma['name']}: {zugeordnet} zugeordnet, {len(fehlt)} fehlen noch{zusatz}")
            if getattr(args, "uebergabe", False):
                _uebergabe(monat, ziel_firma, index, daten_firma, args, einzelfirma)
            if getattr(args, "anfragen", False):
                _anfragen(daten_firma, kern.echt(args))
        from .posten import fortschreiben
        fortschreiben(alle_daten)
        return 0
    daten = abgleichen(buchungen_aus(auszuege, monat), index)
    _nachsuche(daten, args)
    from .posten import fortschreiben
    fortschreiben(daten)
    mahnungen = _mahnungen()
    ziel = kern.pfad("arbeit", "monat", monat)
    _schreibe_ausgaben(ziel, monat, daten, mahnungen)
    zugeordnet = sum(x["status"].startswith("zugeordnet") for x in daten)
    pruefen = sum(x["status"] == "pruefen" for x in daten)
    fehlt = [x for x in daten if x["status"] == "fehlt"]
    fehlbetrag = f"{sum(abs(x['betrag']) for x in fehlt):.2f}".replace(".", ",")
    ohne_beleg = sum(x["status"] == "ohne_beleg" for x in daten)
    privat = sum(x["status"] == "privat" for x in daten)
    print(
        f"ok: {len(daten)} Buchungen, {zugeordnet} zugeordnet, {pruefen} prüfen, "
        f"{len(fehlt)} fehlen noch ({fehlbetrag} €), {privat} privat bezahlt, {ohne_beleg} ohne Beleg nötig"
    )
    kern.ereignis("monat", f"{_monatsname(monat)}: {zugeordnet} Abbuchungen zugeordnet, {len(fehlt)} fehlen noch ({fehlbetrag} €). Die Liste kommt am 1. und 15. per Mail.")
    if getattr(args, "uebergabe", False):
        _uebergabe(monat, ziel, index, daten, args)
    if getattr(args, "anfragen", False):
        _anfragen(daten, kern.echt(args))
    return 0
