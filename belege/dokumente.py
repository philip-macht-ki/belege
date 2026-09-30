"""Ablage für Dokumente, die kein Beleg sind: Verträge, Versicherungen, Briefe.

Modul bh8, siehe ARCHITEKTUR.md, Abschnitt "Ablage für Dokumente". Der Ablauf
folgt demselben Grundsatz wie die Belege: Regeln und Modell entscheiden,
Fristen rechnet ausschließlich der Code, und ohne ``--echt`` ändert sich nichts.
"""
from __future__ import annotations

import calendar
import hashlib
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from . import kern
from .ablegen import sauber
from .einordnen import BELEGWOERTER, _belegdatum, _datum as _zeilendatum
from .kern import ablage_ordner, ereignis, erweitert, konfig
from .kern import echt as _echt
from .kern import jetzt, lesen, pfad, schreiben
from .urteil import frage, vorlage

ARTEN = {
    "vertrag", "versicherung", "kunde", "behoerde", "bank", "gesundheit",
    "beleg", "sonstiges",
}
FRISTARTEN = {"kuendigung", "ablauf", "zahlung", "termin"}
ART_ORDNER = {
    "vertrag": "Vertrag",
    "versicherung": "Versicherung",
    "kunde": "Kunde",
    "behoerde": "Behörde",
    "bank": "Bank",
    "gesundheit": "Gesundheit",
    "sonstiges": "Sonstiges",
}
ENDUNGEN = {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}
SICHERHEITSSCHWELLE = 0.7

STICHWORT_ARTEN = (
    (("mietvertrag", "vertrag", "laufzeit"), "vertrag"),
    (("versicherungsschein", "police", "versicherung"), "versicherung"),
    (("finanzamt", "bescheid", "steuer"), "behoerde"),
    (("kontoauszug", "bank", "iban"), "bank"),
    (("arzt", "praxis", "klinik"), "gesundheit"),
)

BEZUGSWOERTER = (
    "laufzeitende", "ende der laufzeit", "vor ablauf", "zum vertragsende",
    "vertragsende",
)
ZAHLWOERTER = {
    "einen": 1, "eine": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
    "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12,
}


def _index() -> dict:
    """Liest das Dokumentverzeichnis und schützt vor kaputtem JSON mit einem
    leeren Verzeichnis."""
    return lesen(pfad("arbeit", "dokumente.json"), {}) or {}


def _speichere(index: dict) -> None:
    schreiben(pfad("arbeit", "dokumente.json"), index)


def _sha(datei: Path) -> str:
    """Berechnet den Fingerabdruck über die unveränderten Dateibytes, in Blöcken."""
    pruefsumme = hashlib.sha256()
    with open(datei, "rb") as offen:
        for block in iter(lambda: offen.read(1 << 20), b""):
            pruefsumme.update(block)
    return pruefsumme.hexdigest()


def pruefe(antwort: object) -> str | None:
    """Prüft ein Modellurteil gegen den Dokument-Vertrag aus ARCHITEKTUR.md."""
    if not isinstance(antwort, dict):
        return "Die Antwort muss ein JSON-Objekt sein."
    felder = {
        "art", "bereich", "gegenueber", "titel", "datum", "fristen",
        "sicherheit", "grund",
    }
    fehlend = felder - antwort.keys()
    if fehlend:
        return f"Diese Felder fehlen: {', '.join(sorted(fehlend))}."
    if antwort["art"] not in ARTEN:
        return f"art muss eine von {', '.join(sorted(ARTEN))} sein."
    if antwort["bereich"] not in {"betrieb", "privat"}:
        return "bereich muss betrieb oder privat sein."
    if not isinstance(antwort["gegenueber"], str) or not antwort["gegenueber"].strip():
        return "gegenueber darf nicht leer sein."
    if len(antwort["gegenueber"]) > 40:
        return "gegenueber darf höchstens 40 Zeichen haben."
    if not isinstance(antwort["titel"], str) or not antwort["titel"].strip():
        return "titel darf nicht leer sein."
    if len(antwort["titel"]) > 40:
        return "titel darf höchstens 40 Zeichen haben."
    if antwort["datum"] is not None:
        if not isinstance(antwort["datum"], str):
            return "datum muss JJJJ-MM-TT oder null sein."
        try:
            if date.fromisoformat(antwort["datum"]).year < 2000:
                return "datum darf nicht vor 2000 liegen."
        except ValueError:
            return "datum muss JJJJ-MM-TT oder null sein."
    if not isinstance(antwort["fristen"], list):
        return "fristen muss eine Liste sein."
    for frist in antwort["fristen"]:
        if not isinstance(frist, dict):
            return "jede Frist muss ein JSON-Objekt sein."
        if frist.get("art") not in FRISTARTEN:
            return f"Frist-art muss eine von {', '.join(sorted(FRISTARTEN))} sein."
        if frist.get("datum") is not None:
            if not isinstance(frist["datum"], str):
                return "Frist-datum muss JJJJ-MM-TT oder null sein."
            try:
                date.fromisoformat(frist["datum"])
            except ValueError:
                return "Frist-datum muss JJJJ-MM-TT oder null sein."
        if not isinstance(frist.get("text", ""), str):
            return "Frist-text muss ein Text sein."
    sicherheit = antwort["sicherheit"]
    if isinstance(sicherheit, bool) or not isinstance(sicherheit, (int, float)):
        return "sicherheit muss eine Zahl zwischen 0 und 1 sein."
    if not 0 <= sicherheit <= 1:
        return "sicherheit muss zwischen 0 und 1 liegen."
    if not isinstance(antwort["grund"], str) or not antwort["grund"].strip():
        return "grund darf nicht leer sein."
    return None


def _erste_zeile(text: str) -> str:
    """Nimmt die erste sinnvolle, nicht zu kurze Zeile als Gegenüber-Kandidat."""
    for zeile in text.splitlines()[:8]:
        kandidat = re.sub(r"\s+", " ", zeile).strip(" :-")
        ist_zahlenzeile = re.fullmatch(r"[\d.,€ ]+", kandidat)
        if len(kandidat) >= 3 and not _zeilendatum(kandidat) and not ist_zahlenzeile:
            return kandidat[:80]
    return "Unbekannt"


def _monate_aus_text(text: str) -> int | None:
    """Liest eine Monatsangabe (Ziffer oder ausgeschrieben) aus einem Fristtext."""
    treffer = re.search(r"(\d+)\s*Monat", text, re.I)
    if treffer:
        return int(treffer[1])
    for wort, zahl in ZAHLWOERTER.items():
        if re.search(rf"\b{wort}\b\s*Monat", text, re.I):
            return zahl
    return None


def _bezieht_sich_auf_ablauf(text: str) -> bool:
    """Erkennt, ob eine Kündigungsfrist sich auf ein bekanntes Laufzeitende bezieht."""
    klein = text.lower()
    return any(wort in klein for wort in BEZUGSWOERTER)


def monate_abzueglich(datum: date, monate: int) -> date:
    """Zieht Monate von einem Datum ab und klemmt den Tag auf den letzten
    Tag des Zielmonats.

    So bleibt die Rechnung auch am Monatsende und über Schaltjahre hinweg
    korrekt: 31.03. minus 1 Monat wird der 28.02. (oder 29.02. im
    Schaltjahr), nicht der 31.02.
    """
    monatsindex = datum.month - 1 - monate
    jahr = datum.year + monatsindex // 12
    monat = monatsindex % 12 + 1
    letzter_tag = calendar.monthrange(jahr, monat)[1]
    return date(jahr, monat, min(datum.day, letzter_tag))


def berechne_fristen(fristen: list[dict]) -> list[dict]:
    """Berechnet aus einer festen Ablauf-Frist und einer Monatsangabe im Text
    das Kündigungsdatum.

    Der Vertrag verbietet dem Modell, selbst zu rechnen (ARCHITEKTUR.md).
    Fehlt eine eindeutige Angabe, bleibt das Datum null und die Frist steht
    als "prüfen" da.
    """
    ablauf_daten = [
        date.fromisoformat(f["datum"])
        for f in fristen
        if f.get("art") == "ablauf" and f.get("datum")
    ]
    ergebnis = []
    for frist in fristen:
        frist = dict(frist)
        frist.setdefault("text", "")
        hat_kein_datum = frist.get("art") == "kuendigung" and not frist.get("datum")
        if hat_kein_datum and ablauf_daten:
            monate = _monate_aus_text(frist["text"])
            if monate is not None and _bezieht_sich_auf_ablauf(frist["text"]):
                neues_datum = monate_abzueglich(ablauf_daten[0], monate)
                frist["datum"] = neues_datum.isoformat()
        ergebnis.append(frist)
    return ergebnis


def _rueckfall(text: str, dateiname: str) -> dict:
    """Ordnet ein Dokument ohne Modell ein: Stichwörter, sonst vorsichtig unsicher.

    Für URTEIL_BACKEND=ohne und für Tests. Findet die Rückfall keine bekannten
    Stichwörter, bleibt die Sicherheit niedrig und das Dokument landet unsortiert.
    """
    suchraum = f"{text} {dateiname}".lower()
    art = None
    for stichwoerter, kandidat in STICHWORT_ARTEN:
        if any(wort in suchraum for wort in stichwoerter):
            art = kandidat
            break
    if art is None and any(wort in suchraum for wort in BELEGWOERTER):
        art = "beleg"
    if art is None:
        datum = _belegdatum(text)
        return {
            "art": "sonstiges",
            "bereich": "betrieb",
            "gegenueber": _erste_zeile(text),
            "titel": "Dokument",
            "datum": datum.isoformat() if datum else None,
            "fristen": [],
            "sicherheit": 0.3,
            "grund": "Ohne Modell kein bekanntes Stichwort gefunden.",
        }
    datum = _belegdatum(text)
    return {
        "art": art,
        "bereich": "betrieb",
        "gegenueber": _erste_zeile(text),
        "titel": art.capitalize(),
        "datum": datum.isoformat() if datum else None,
        "fristen": [],
        "sicherheit": 0.85,
        "grund": "Stichwort ohne Modell erkannt.",
    }


def dokument_einordnen(text: str, dateiname: str) -> dict:
    """Ordnet einen Dokumenttext über das Urteil oder die Regel-Rückfallfunktion
    ein und lässt anschließend ausschließlich den Code die Fristen berechnen."""
    auftrag = vorlage("dokument", text=text[:6000], dateiname=dateiname)
    antwort = frage(
        auftrag,
        zweck="dokument",
        pruefe=pruefe,
        rueckfall=lambda: _rueckfall(text, dateiname),
    )
    antwort = dict(antwort)
    antwort["fristen"] = berechne_fristen(antwort.get("fristen") or [])
    return antwort


def _dokument_ziel(eintrag: dict, ext: str, unsicher: bool) -> Path:
    """Ermittelt den Zielpfad nach dem Ablagevertrag für Dokumente."""
    dok_ordner = konfig("belege").get("dokumente", {}).get("ordner", "Dokumente")
    basis = ablage_ordner() / dok_ordner
    datum = eintrag.get("datum") or "ohne-Datum"
    ext = ext if ext.startswith(".") else f".{ext}"
    if unsicher:
        titel = sauber(eintrag.get("titel") or "Dokument")[:40]
        name = f"{datum}_{titel}"
        dateiname = f"{name[:120 - len(ext)].rstrip('-')}{ext.lower()}"
        return basis / "Unsortiert" / dateiname
    art_ordner = ART_ORDNER.get(eintrag["art"], "Sonstiges")
    gegenueber = sauber(eintrag.get("gegenueber") or "Unbekannt")[:40]
    titel = sauber(eintrag.get("titel") or eintrag["art"])[:40]
    name = f"{datum}_{titel}"
    dateiname = f"{name[:120 - len(ext)].rstrip('-')}{ext.lower()}"
    return basis / art_ordner / gegenueber / dateiname


def _eingang_dateien() -> list[Path]:
    """Alle unterstützten Dateien im Dokumente-Eingang, nicht rekursiv, ohne
    versteckte Dateien."""
    cfg = konfig("belege").get("dokumente", {})
    ordner = erweitert(cfg.get("eingang", "~/Belege/Dokumente-Eingang"))
    if not ordner.is_dir():
        return []
    return sorted(
        datei
        for datei in ordner.iterdir()
        if datei.is_file()
        and not datei.name.startswith(".")
        and datei.suffix.lower() in ENDUNGEN
    )


def _verarbeite_datei(datei: Path, index: dict, echt: bool) -> None:
    """Ordnet eine einzelne Datei ein und legt sie mit ``echt`` ab oder
    verschiebt sie."""
    from .text import auslesen

    sha = _sha(datei)
    if sha in index:
        pfad_bekannt = index[sha].get("pfad", "der Ablage")
        print(f"{datei.name}: liegt schon unter {pfad_bekannt}")
        return
    text = auslesen(datei)
    eintrag = dokument_einordnen(text.text, datei.name)
    if eintrag["art"] == "beleg":
        handy = erweitert(konfig("belege").get("quellen", {}).get("handy_ordner", ""))
        ziel_pfad = kern.freier_name(handy / datei.name)
        if not echt:
            print(
                f"würde verschieben: {datei.name} → {ziel_pfad} "
                "(Beleg, der Belegweg holt ihn ab)"
            )
            return
        handy.mkdir(parents=True, exist_ok=True)
        shutil.move(str(datei), str(ziel_pfad))
        ereignis(
            "abgelegt", f"{datei.name} ist ein Beleg und liegt jetzt in {handy}.",
            quelle="dokumente",
        )
        print(f"{datei.name}  →  {ziel_pfad} (Beleg)")
        return
    unsicher = float(eintrag["sicherheit"]) < SICHERHEITSSCHWELLE
    ziel_pfad = _dokument_ziel(eintrag, datei.suffix, unsicher)
    if not echt:
        try:
            relativ = ziel_pfad.relative_to(ablage_ordner())
        except ValueError:
            relativ = ziel_pfad
        art_text = "unsicher, Unsortiert" if unsicher else eintrag["art"]
        print(f"würde ablegen: {datei.name} → {relativ} ({art_text})")
        return
    ziel_pfad = kern.freier_name(ziel_pfad)
    ziel_pfad.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(datei, ziel_pfad)
    gespeichert = {
        "pfad": str(ziel_pfad.relative_to(ablage_ordner())),
        "art": eintrag["art"],
        "bereich": eintrag["bereich"],
        "gegenueber": eintrag["gegenueber"],
        "titel": eintrag["titel"],
        "datum": eintrag["datum"],
        "fristen": eintrag["fristen"],
        "text": text.text[:6000],
        "abgelegt": not unsicher,
    }
    index[sha] = gespeichert
    _speichere(index)
    art_ereignis = "unsortiert" if unsicher else "abgelegt"
    ereignis(
        art_ereignis, f"{datei.name} liegt jetzt unter {gespeichert['pfad']}.",
        quelle="dokumente",
    )
    print(f"{datei.name}  →  {gespeichert['pfad']}")


def befehl(args) -> int:
    """`belege dokumente [datei …] [--echt]`: Eingangsordner oder genannte
    Dateien einordnen."""
    echt = _echt(args)
    ziele = [erweitert(z) for z in (getattr(args, "ziel", None) or [])]
    dateien = ziele if ziele else _eingang_dateien()
    if not dateien:
        cfg = konfig("belege").get("dokumente", {})
        ordner = erweitert(cfg.get("eingang", "~/Belege/Dokumente-Eingang"))
        print(f"Keine Dokumente gefunden in {ordner}.")
        return 0
    index = _index()
    for datei in dateien:
        if not datei.is_file():
            print(f"Nicht gefunden: {datei}. Prüfe den Dateinamen.")
            continue
        try:
            _verarbeite_datei(datei, index, echt)
        except Exception as fehler:  # noqa: BLE001
            meldung = f"Konnte {datei.name} nicht verarbeiten: {fehler}"
            if echt:
                ereignis("fehler", meldung, quelle="dokumente")
            print(meldung)
    return 0


def _alle_fristen() -> list[dict]:
    """Baut eine flache Liste aller Fristen mit Bezug zu ihrem Dokument."""
    alle = []
    for sha, eintrag in _index().items():
        for frist in eintrag.get("fristen", []):
            alle.append(
                {
                    **frist,
                    "sha": sha,
                    "gegenueber": eintrag.get("gegenueber", "Unbekannt"),
                    "titel": eintrag.get("titel", ""),
                    "pfad": eintrag.get("pfad", ""),
                }
            )
    return alle


def fristen_liste(tage: int = 365) -> dict:
    """Kommende Fristen (mit Datum, im Fenster) und alle unklaren ("prüfen")."""
    heute = jetzt().date()
    grenze = heute + timedelta(days=tage)
    kommend, pruefen = [], []
    for frist in _alle_fristen():
        if not frist.get("datum"):
            pruefen.append(frist)
            continue
        try:
            datum = date.fromisoformat(frist["datum"])
        except ValueError:
            pruefen.append(frist)
            continue
        if heute <= datum <= grenze:
            kommend.append(frist)
    kommend.sort(key=lambda f: f["datum"])
    return {"kommend": kommend, "pruefen": pruefen}


def suchen(abfrage: str = "", max: int = 10) -> list[dict]:
    """Sucht Dokumente über Gegenüber, Titel, Art und den gespeicherten Text."""
    abfrage_klein = abfrage.lower().strip()
    treffer = []
    for eintrag in _index().values():
        felder = ("gegenueber", "titel", "art", "text")
        heuhaufen = " ".join(str(eintrag.get(feld, "")) for feld in felder).lower()
        if abfrage_klein and abfrage_klein not in heuhaufen:
            continue
        treffer.append(
            {
                "pfad": eintrag.get("pfad"),
                "art": eintrag.get("art"),
                "gegenueber": eintrag.get("gegenueber"),
                "titel": eintrag.get("titel"),
                "datum": eintrag.get("datum"),
                "fristen": eintrag.get("fristen", []),
                "auszug": str(eintrag.get("text", ""))[:300],
            }
        )
        if len(treffer) >= max:
            break
    return treffer


def _ics_escape(wert: str) -> str:
    """Escaped Komma, Semikolon, Backslash und Zeilenumbrüche nach RFC 5545."""
    return (
        str(wert)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_fold(zeile: str) -> str:
    """Faltet eine Zeile auf höchstens 75 Oktette, wie RFC 5545 es verlangt."""
    roh = zeile.encode("utf-8")
    if len(roh) <= 75:
        return zeile
    teile = []
    rest = roh
    erster = True
    while rest:
        breite = 75 if erster else 74
        stueck = rest[:breite]
        # Nie mitten in einem mehrbytigen UTF-8-Zeichen schneiden: so lange
        # kürzen, bis das Stück wieder für sich allein gültiges UTF-8 ist.
        while stueck:
            try:
                stueck.decode("utf-8")
                break
            except UnicodeDecodeError:
                stueck = stueck[:-1]
        teile.append(stueck)
        rest = rest[len(stueck):]
        erster = False
    return "\r\n ".join(t.decode("utf-8") for t in teile)


def _ics_zusammenfassung(frist: dict) -> str:
    namen = {
        "kuendigung": "Kündigung", "ablauf": "Ablauf",
        "zahlung": "Zahlung", "termin": "Termin",
    }
    art = namen.get(frist.get("art", ""), "Frist")
    titel = frist.get("titel", "")
    zusammenfassung = f"{art}: {frist.get('gegenueber', 'Unbekannt')}, {titel}"
    return zusammenfassung.rstrip(" –")


def baue_ics(fristen: list[dict], erinnern_tage: int) -> str:
    """Baut eine ganztägige .ics-Datei von Hand, ohne zusätzliche Abhängigkeit.

    UID ist stabil aus Fingerabdruck und Fristart, damit ein erneuter Import
    in den Kalender die Termine aktualisiert statt sie zu verdoppeln.
    """
    zeilen = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//belege//dokumente//DE", "CALSCALE:GREGORIAN",
    ]
    from datetime import timezone

    stempel = jetzt().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for frist in fristen:
        if not frist.get("datum"):
            continue
        # Stabil über Läufe, eindeutig auch bei zwei Fristen gleicher Art
        # im selben Dokument.
        merkmal = f"{frist.get('art', 'frist')}|{frist['datum']}"
        kurz = hashlib.sha256(merkmal.encode()).hexdigest()[:8]
        uid = f"{frist['sha'][:16]}-{frist.get('art', 'frist')}-{kurz}@belege"
        zusammenfassung = _ics_zusammenfassung(frist)
        dtstart = frist["datum"].replace("-", "")
        zeilen += [
            "BEGIN:VEVENT",
            _ics_fold(f"UID:{uid}"),
            f"DTSTAMP:{stempel}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            _ics_fold(f"SUMMARY:{_ics_escape(zusammenfassung)}"),
            _ics_fold(f"DESCRIPTION:{_ics_escape(frist.get('text', ''))}"),
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            _ics_fold(f"DESCRIPTION:{_ics_escape(zusammenfassung)}"),
            f"TRIGGER:-P{int(erinnern_tage)}D",
            "END:VALARM",
            "END:VEVENT",
        ]
    zeilen.append("END:VCALENDAR")
    return "\r\n".join(zeilen) + "\r\n"


def befehl_fristen(args) -> int:
    """`belege fristen [--tage N] [--echt]`: kommende Fristen zeigen, mit
    ``--echt`` als .ics."""
    tage = getattr(args, "tage", None) or 365
    daten = fristen_liste(tage)
    if not daten["kommend"] and not daten["pruefen"]:
        print(
            "Keine Fristen im Dokumentverzeichnis. "
            "Erst `belege dokumente --echt` ausführen."
        )
        return 0
    for frist in daten["kommend"]:
        gegenueber = frist.get("gegenueber", "")
        titel = frist.get("titel", "")
        print(f"{frist['datum']}  {gegenueber}, {titel}: {frist.get('text', '')}")
    for frist in daten["pruefen"]:
        gegenueber = frist.get("gegenueber", "")
        titel = frist.get("titel", "")
        print(f"prüfen  {gegenueber}, {titel}: {frist.get('text', '')}")
    if not _echt(args):
        print("trocken: Mit --echt entsteht fristen.ics zum Import in deinen Kalender.")
        return 0
    dok_cfg = konfig("belege").get("dokumente", {})
    erinnern_tage = dok_cfg.get("erinnern_tage", 28)
    text = baue_ics(daten["kommend"], erinnern_tage)
    ziel = ablage_ordner() / dok_cfg.get("ordner", "Dokumente") / "fristen.ics"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8", newline="")
    print(f"ok: {ziel}")
    return 0
