"""Einzelne Funde sicher einordnen und ablegen."""
from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

from . import kern
from .typen import Einordnung, Fund, Text


MAX_MB = 50


def _sha(datei: Path) -> str:
    """Berechnet den Fingerabdruck vor jeder Texterkennung oder Ablage, in Blöcken."""
    pruefsumme = hashlib.sha256()
    with open(datei, "rb") as offen:
        for block in iter(lambda: offen.read(1 << 20), b""):
            pruefsumme.update(block)
    return pruefsumme.hexdigest()


def _index() -> dict:
    """Liest das Belegverzeichnis und schützt vor kaputtem JSON mit einem leeren Verzeichnis."""
    return kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}


def _speichere_index(index: dict) -> None:
    """Schreibt jeden Fortschritt sofort atomar, damit ein Abbruch nichts vergisst."""
    kern.schreiben(kern.pfad("arbeit", "index.json"), index)


def _aus_xml(daten: dict, fund: Fund) -> Einordnung:
    """Baut die sichere Einordnung einer ZUGFeRD-Rechnung aus ihren XML-Feldern."""
    from .einordnen import _aus_xml

    xml_datei = daten["xml_datei"]
    xml_fund = Fund(xml_datei, fund.quelle, xml_datei.name, fund.eingang)
    einordnung = _aus_xml(xml_fund)
    if einordnung is None:
        raise ValueError("Die eingebettete XML-Rechnung ist nicht lesbar.")
    return einordnung


def _zugferd(fund: Fund) -> tuple[Einordnung, Text] | None:
    """Liest eine eingebettete ZUGFeRD-XML, ohne das PDF selbst zu verändern."""
    from facturx import get_xml_from_pdf
    from .xrechnung import zugferd_in

    if fund.datei.suffix.lower() != ".pdf" or not zugferd_in(fund.datei):
        return None
    xml = get_xml_from_pdf(fund.datei.read_bytes(), check_xsd=False)
    if not xml:
        raise ValueError("Im ZUGFeRD-PDF wurde keine XML-Rechnung gefunden.")
    xml_datei = kern.pfad("arbeit", "tmp", f"{_sha(fund.datei)}.xml")
    xml_datei.parent.mkdir(parents=True, exist_ok=True)
    xml_datei.write_bytes(xml)
    from .xrechnung import lesen, sichttext

    daten = lesen(xml_datei)
    daten["xml_datei"] = xml_datei
    einordnung = _aus_xml(daten, fund)
    return einordnung, Text(sichttext(daten), "xml", 1)


def _begleit_einordnung(fund: Fund, text: Text, index: dict) -> tuple[Einordnung, Path] | None:
    """Findet zu einem Begleit-PDF die XML-Rechnung derselben Mail und Nummer."""
    if fund.datei.suffix.lower() != ".pdf" or not fund.mail:
        return None
    mail_id = fund.mail.get("id")
    for eintrag in index.values():
        xml = eintrag.get("xml")
        if not xml or (eintrag.get("mail") or {}).get("id") != mail_id:
            continue
        xml_pfad = kern.ablage_ordner() / xml
        try:
            from .xrechnung import lesen

            nummer = str(lesen(xml_pfad).get("nummer", ""))
        except (OSError, ValueError):
            continue
        if nummer and nummer in text.text:
            datum = date.fromisoformat(eintrag["datum"])
            einordnung = Einordnung(
                True, eintrag["art"], eintrag["bereich"], datum, eintrag["lieferant"],
                eintrag["beschreibung"], eintrag.get("betrag"), eintrag["waehrung"],
                eintrag["sicherheit"], "Begleit-PDF zur E-Rechnung.", "xml",
            )
            return einordnung, xml_pfad.with_name(f"{xml_pfad.stem}_Begleit.pdf")
    return None


def verarbeite(fund: Fund, echt: bool) -> kern.Ergebnis:
    """Verarbeitet einen Fund vom Fingerabdruck bis zum Indexeintrag.

    Unsichere Downloads bleiben liegen, und alle echten Erfolge werden sofort
    im Index gespeichert, damit ein Abbruch keinen bereits bearbeiteten Fund verliert.
    """
    try:
        if fund.datei.stat().st_size > MAX_MB * 1024 * 1024:
            ergebnis = kern.Ergebnis(
                "befund",
                f"{fund.name} ist größer als {MAX_MB} MB und bleibt, wo es ist. Bitte selbst ansehen.",
            )
            if echt:
                kern.ereignis("zweifel", ergebnis.meldung, datei=fund.name)
            return ergebnis
        fingerabdruck = _sha(fund.datei)
        index = _index()
        if fingerabdruck in index:
            pfad = index[fingerabdruck].get("pfad", "der Ablage")
            ergebnis = kern.Ergebnis("nichts", f"Liegt schon unter {pfad}.", {"pfad": pfad})
            if echt and fund.quelle == "downloads":
                gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
                gemeldet = set(gesehen.get("downloads_gemeldet", []))
                if fingerabdruck not in gemeldet:
                    kern.ereignis("doppelt", f"{fund.name} liegt schon unter {pfad}, kannst du löschen",
                                  quelle=fund.quelle)
                    gesehen["downloads_gemeldet"] = sorted(gemeldet | {fingerabdruck})
                    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
            elif echt:
                kern.ereignis("doppelt", ergebnis.meldung, quelle=fund.quelle)
            return ergebnis
        begleit = None
        zugferd = _zugferd(fund)
        if zugferd:
            einordnung, text = zugferd
        else:
            from .text import auslesen
            from .einordnen import einordnen

            text = auslesen(fund.datei)
            begleit = _begleit_einordnung(fund, text, index)
            einordnung = begleit[0] if begleit else einordnen(fund, text)
        if fund.quelle == "postfach" and not einordnung.ist_beleg:
            return kern.Ergebnis("nichts", "Kein Beleg erkannt; die Mail bleibt unverändert.")
        if fund.quelle == "downloads" and not einordnung.ist_beleg:
            return kern.Ergebnis("nichts", f"{fund.name} ist kein Beleg und bleibt in Downloads.")
        if fund.quelle == "downloads" and einordnung.sicherheit == "niedrig":
            ergebnis = kern.Ergebnis(
                "befund", f"{fund.name} sieht nach einem Beleg aus, ist aber unsicher. Bleibt in Downloads."
            )
            if echt:
                kern.ereignis("zweifel", ergebnis.meldung, datei=fund.name)
            return ergebnis
        from .ablegen import ablegen

        ergebnis = ablegen(fund, einordnung, text, echt)
        if not echt:
            ziel = Path(ergebnis.daten.get("pfad", ""))
            try:
                relativ = ziel.relative_to(kern.ablage_ordner())
            except ValueError:
                relativ = ziel
            print(f"würde ablegen: {fund.name} → {relativ} ({einordnung.sicherheit}, {einordnung.quelle})")
            return ergebnis
        ziel = Path(ergebnis.daten["pfad"])
        if begleit and ergebnis.status in {"ok", "befund"}:
            begleit_ziel = begleit[1]
            nummer = 2
            while begleit_ziel.exists():
                begleit_ziel = begleit[1].with_name(f"{begleit[1].stem}_{nummer}.pdf")
                nummer += 1
            shutil.move(str(ziel), str(begleit_ziel))
            ziel = begleit_ziel
            ergebnis.daten["pfad"] = str(ziel)
        xml = None
        if fund.datei.suffix.lower() == ".xml" and ziel.with_suffix(".pdf").exists():
            xml = str(ziel.relative_to(kern.ablage_ordner()))
            ziel = ziel.with_suffix(".pdf")
        daten = {
            "pfad": str(ziel.relative_to(kern.ablage_ordner())),
            **einordnung.als_dict(),
            "status": ergebnis.daten["status"],
            "quelle": fund.quelle,
            "mail": fund.mail,
            "am": kern.jetzt().isoformat(),
            "xml": xml,
        }
        index[fingerabdruck] = daten
        _speichere_index(index)
        original = getattr(fund, "handy_original", None)
        if original and Path(original).exists():
            erledigt = Path(original).parent / "_erledigt"
            erledigt.mkdir(exist_ok=True)
            shutil.move(str(original), str(kern.freier_name(erledigt / Path(original).name)))
        if echt:
            art = "abgelegt" if daten["status"] == "abgelegt" else "unsortiert"
            text = f"{fund.name} liegt jetzt unter {daten['pfad']}"
            kern.ereignis(art, text, quelle=fund.quelle, pfad=daten["pfad"], datum=daten.get("datum"),
                          lieferant=daten.get("lieferant"), betrag=daten.get("betrag"))
        return ergebnis
    except Exception as fehler:  # noqa: BLE001
        meldung = f"Konnte {fund.name} nicht verarbeiten: {fehler}"
        if echt:
            kern.ereignis("fehler", meldung, quelle=fund.quelle)
        return kern.Ergebnis("fehler", meldung)


def befehl_ablegen(args) -> int:
    """Legt ausdrücklich angegebene Dateien von Hand ab und zeigt je Datei das Ergebnis."""
    dateien = [Path(wert).expanduser() for wert in getattr(args, "ziel", [])]
    if not dateien:
        print("Bitte nenne mindestens eine Datei, zum Beispiel: belege ablegen Rechnung.pdf")
        return 2
    echt = kern.echt(args)
    for datei in dateien:
        if not datei.is_file():
            print(f"Nicht gefunden: {datei}. Prüfe den Dateinamen.")
            continue
        fund = Fund(datei, "handy", datei.name, date.fromtimestamp(datei.stat().st_mtime))
        ergebnis = verarbeite(fund, echt)
        if ergebnis.status in {"ok", "befund"} and echt:
            ziel = Path(ergebnis.daten.get("pfad", ""))
            try:
                ziel = ziel.relative_to(kern.ablage_ordner())
            except ValueError:
                pass
            print(f"{datei.name}  →  {ziel}", flush=True)
        elif ergebnis.status not in {"ok", "befund"}:
            print(f"{datei.name}: {ergebnis.meldung}", flush=True)
    return 0
