"""Einzelne Funde sicher einordnen und ablegen."""
from __future__ import annotations

import hashlib
import re
import shutil
from datetime import date
from pathlib import Path

from . import kern
from .dokumente import VertraulichGescheitert
from .urteil import Unerreichbar
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


def _zugferd(fund: Fund) -> tuple[Einordnung, Text, dict] | None:
    """Liest eine eingebettete ZUGFeRD-XML, ohne das PDF selbst zu verändern."""
    from facturx import get_xml_from_pdf
    from .xrechnung import zugferd_in

    if fund.datei.suffix.lower() != ".pdf" or not zugferd_in(fund.datei):
        return None
    xml = get_xml_from_pdf(fund.datei.read_bytes(), check_xsd=False)
    if isinstance(xml, tuple):  # factur-x liefert (dateiname, xml_bytes)
        xml = xml[1]
    if not xml:
        raise ValueError("Im ZUGFeRD-PDF wurde keine XML-Rechnung gefunden.")
    xml_datei = kern.pfad("arbeit", "tmp", f"{_sha(fund.datei)}.xml")
    xml_datei.parent.mkdir(parents=True, exist_ok=True)
    xml_datei.write_bytes(xml)
    from .xrechnung import lesen, sichttext

    daten = lesen(xml_datei)
    daten["xml_datei"] = xml_datei
    einordnung = _aus_xml(daten, fund)
    return einordnung, Text(sichttext(daten), "xml", 1), daten


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
                eintrag["sicherheit"], "Begleit-PDF zur E-Rechnung.", "xml", eintrag.get("firma", ""),
            )
            return einordnung, xml_pfad.with_name(f"{xml_pfad.stem}_Begleit.pdf")
    return None


def _ohne_text() -> Einordnung:
    """Ein Dokument, von dem der Mac lokal keinen Text lesen konnte.

    Es geht nicht zur Texterkennung in die Cloud (es könnte ein Arztbrief sein),
    sondern nach Unsortiert und in den Bericht unter „Bitte ansehen“.
    """
    return Einordnung(
        ist_beleg=True, art="eingang", bereich="betrieb", datum=None, lieferant="Unbekannt",
        beschreibung="ohne-Text", betrag=None, waehrung="EUR", sicherheit="niedrig",
        grund="Kein Text lesbar; nur auf deinem Mac geprüft. Bitte selbst ansehen.", quelle="rueckfall",
    )


def _original_erledigt(fund: Fund) -> None:
    """Ein umgewandeltes HEIC-Original aus dem Handy-Ordner nach _erledigt schieben."""
    original = getattr(fund, "handy_original", None)
    if original and Path(original).exists():
        erledigt = Path(original).parent / "_erledigt"
        erledigt.mkdir(exist_ok=True)
        shutil.move(str(original), str(kern.freier_name(erledigt / Path(original).name)))


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
        from .dokumente import schon_abgelegt

        dokument = schon_abgelegt(fingerabdruck)
        if fingerabdruck in index or dokument:
            pfad = dokument[0] if dokument else index[fingerabdruck].get("pfad", "der Ablage")
            abgelegte_firma = kern.firma_von(index[fingerabdruck]) if fingerabdruck in index else None
            name = "Ein vertrauliches Dokument" if dokument and dokument[1] else fund.name
            firma_hinweis = f" ({abgelegte_firma})" if abgelegte_firma else ""
            ergebnis = kern.Ergebnis("nichts", f"Liegt schon unter {pfad}{firma_hinweis}.", {"pfad": pfad, "firma": abgelegte_firma})
            if echt and fund.quelle == "downloads":
                gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
                gemeldet = set(gesehen.get("downloads_gemeldet", []))
                if fingerabdruck not in gemeldet:
                    kern.ereignis("doppelt", f"{name} liegt schon unter {pfad}{firma_hinweis}, kannst du löschen",
                                  quelle=fund.quelle, firma=abgelegte_firma)
                    gesehen["downloads_gemeldet"] = sorted(gemeldet | {fingerabdruck})
                    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
            elif echt:
                kern.ereignis("doppelt", ergebnis.meldung, quelle=fund.quelle, firma=abgelegte_firma)
            return ergebnis
        begleit = None
        geheim = None
        from .abofalle import aktive_pdf_inhalte, erkennen as abofalle_erkennen
        aktiv, aktiv_grund = aktive_pdf_inhalte(fund.datei)
        if aktiv:
            # Aus der Quelle nehmen, damit Handy- und Downloads-Ordner sie nicht jeden Lauf neu melden.
            from .ablegen import abofalle_ablegen
            hinweis = "Nicht als Beleg abgelegt und nicht an DATEV oder den Steuerberater gegeben; öffne sie nur, wenn du den Absender kennst."
            ergebnis = abofalle_ablegen(fund, aktiv_grund, echt, ordner="Vorsicht Datei prüfen", status="aktiv", hinweis=hinweis)
            if echt:
                ziel = Path(ergebnis.daten["pfad"])
                kern.ereignis("zweifel", f"Vorsicht, PDF mit aktiven Inhalten ({aktiv_grund}): {fund.name} liegt unter {ziel}. {hinweis}",
                              quelle=fund.quelle, pfad=str(ziel), grund=aktiv_grund)
            return ergebnis
        from .text import pdf_defekt
        if pdf_defekt(fund.datei):
            from .ablegen import ablegen
            from .typen import Text
            einordnung = _ohne_text()
            einordnung.grund = "Datei beschädigt oder unvollständig heruntergeladen"
            ergebnis = ablegen(fund, einordnung, Text("", "defekt", 0), echt)
            if echt:
                kern.ereignis("zweifel", f"{fund.name}: Datei beschädigt oder unvollständig heruntergeladen. Bitte ansehen.", quelle=fund.quelle)
            return ergebnis
        zugferd = _zugferd(fund)
        xml_daten = None
        if zugferd:
            # E-Rechnung: eingeordnet ohne Modell, aber der Merker zählt für die MCP-Suche.
            from .vertraulich import pruefen

            einordnung, text, *zugferd_xml = zugferd
            xml_daten = zugferd_xml[0] if zugferd_xml else None
            geheim = pruefen(f"{einordnung.lieferant} {einordnung.beschreibung} {text.text}", fund.name, fund.mail,
                             modell=False)
        else:
            from .text import auslesen
            from .einordnen import einordnen

            from .vertraulich import pruefen

            text = auslesen(fund.datei, mail=fund.mail)
            geheim = pruefen(text.text, fund.name, fund.mail)
            begleit = _begleit_einordnung(fund, text, index)
            if begleit:
                einordnung = begleit[0]
            elif text.stufe == "ohne_text":
                einordnung = _ohne_text()
            else:
                # Ohne Text (Texterkennung aus, Foto ohne Schrift) ist nichts prüfbar: auch dann lokal.
                einordnung = einordnen(fund, text, nur_lokal=geheim.vertraulich or not text.text.strip())
        abofalle, grund = abofalle_erkennen(text.text, name=fund.name,
                                             absender=str((fund.mail or {}).get("von", "")))
        if abofalle:
            from .ablegen import abofalle_ablegen
            ergebnis = abofalle_ablegen(fund, grund, echt)
            if echt:
                ziel = Path(ergebnis.daten["pfad"])
                kern.ereignis("zweifel", f"Vorsicht Abofalle: {fund.name} liegt unter {ziel}. Nicht unterschreiben, nicht zahlen.",
                              quelle=fund.quelle, pfad=str(ziel), grund=grund)
            return ergebnis
        if not einordnung.ist_beleg and not begleit:
            # Dokumentweiche: Vertrag, Versicherung, Brief einer Behörde oder Bank statt liegen lassen.
            from .dokumente import automatisch

            dokument = automatisch(fund, text, fingerabdruck, bool(geheim and geheim.vertraulich), echt)
            if dokument:
                if echt:
                    _original_erledigt(fund)
                return dokument
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

        pruefung = kern.konfig("belege").get("pruefung", {})
        firma_eindeutig = (
            einordnung.firma not in {"", "unklar"}
            and kern.firma(einordnung.firma) is not None
        )
        pruefbar = (
            pruefung.get("an", False)
            and einordnung.ist_beleg
            and einordnung.art == "eingang"
            and einordnung.bereich == "betrieb"
            and firma_eindeutig
            and not re.search(r"\b(dauerbeleg|bescheid|steuerbescheid|gebührenbescheid)\b", text.text, re.I)
        )
        befund = []
        notizen = []
        if pruefbar:
            from .pruefung import hinweise, pruefe
            if fund.datei.suffix.lower() == ".xml":
                try:
                    from .xrechnung import lesen
                    xml_daten = lesen(fund.datei)
                except (OSError, ValueError):
                    xml_daten = None
            absender = str((fund.mail or {}).get("von") or "")
            befund = pruefe(einordnung, text, xml=xml_daten, absender=absender)
            notizen = hinweise(einordnung, text, xml=xml_daten, absender=absender)
            if befund:
                from .ablegen import ablegen_befund
                ergebnis = ablegen_befund(fund, einordnung, befund, echt)
            else:
                ergebnis = ablegen(fund, einordnung, text, echt)
        else:
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
            "vertraulich": bool(geheim and geheim.vertraulich),
        }
        if pruefbar:
            daten["pruefung"] = {"status": "ok" if not befund else "befund", "punkte": befund}
            daten["hinweise"] = notizen
        if ergebnis.daten.get("befund"):
            befund_pfad = Path(ergebnis.daten["befund"])
            daten["befund"] = str(befund_pfad.relative_to(kern.ablage_ordner()))
        index[fingerabdruck] = daten
        _speichere_index(index)
        _original_erledigt(fund)
        if echt:
            entwurf_angelegt = False
            anbieter = None
            anbieter_neu = False
            from .pruefung import EU_OHNE_SATZ
            if pruefbar and (befund or EU_OHNE_SATZ in notizen):
                from .aufraeumen import aktualisieren, speichern, zustand
                stand = zustand()
                anbieter, anbieter_neu = aktualisieren({"lieferant": einordnung.lieferant, "punkte": befund,
                                                        "hinweise": notizen, "datum": str(einordnung.datum or fund.eingang)}, stand)
                speichern(stand)
            firma_eintrag = kern.firma(einordnung.firma) or {}
            eigene_empfaengerdaten = all(
                str(firma_eintrag.get(feld, "")).strip()
                for feld in ("name", "ust_id")
            )
            if (befund and anbieter and anbieter.get("weg") == "lieferant" and anbieter.get("status") == "offen"
                    and not anbieter.get("entwurf", False) and firma_eindeutig and eigene_empfaengerdaten
                    and pruefung.get("entwurf_an_absender", True)
                    and fund.mail and fund.mail.get("von")
                    and not any("unklar" in punkt.casefold() for punkt in befund)):
                from .senden import entwurf
                betreff = "Bitte um korrigierte Rechnung"
                datum_text = einordnung.datum.strftime("%d.%m.%Y") if einordnung.datum else "nicht erkennbar"
                mailtext = ("Guten Tag,\n\nbitte sende uns eine korrigierte Rechnung. "
                            "Bei der Prüfung fehlen oder weichen folgende Angaben ab:\n- " + "\n- ".join(befund)
                            + f"\n\nZur Zuordnung: Rechnungsnummer: nicht erkennbar, Datum: {datum_text}, Betrag: {einordnung.betrag or 'nicht erkennbar'} EUR."
                            + f"\n\nKorrekte Empfängerdaten: {firma_eintrag.get('name', '')}, USt-IdNr.: {firma_eintrag.get('ust_id', '')}.\n\nVielen Dank.")
                try:
                    entwurf(str(fund.mail["von"]), betreff, mailtext, [], True, fund.mail.get("konto"))
                    entwurf_angelegt = True
                    anbieter["entwurf"] = True
                    speichern(stand)
                except Exception as fehler:  # Der Beleg bleibt trotz Postfachfehler sicher abgelegt.
                    kern.ereignis("fehler", f"Entwurf zur Rechnungsprüfung nicht angelegt: {fehler}")
            # Ohne eingeschaltete Rechnungsprüfung bleibt die bisherige
            # Ereignisart unverändert; nur ein tatsächlicher Prüfungsbefund
            # ist ein Zweifel.
            art = "zweifel" if befund else ("abgelegt" if daten["status"] == "abgelegt" else "unsortiert")
            text = f"{fund.name} liegt jetzt unter {daten['pfad']}"
            kern.ereignis(art, text, quelle=fund.quelle, pfad=daten["pfad"], datum=daten.get("datum"),
                          lieferant=daten.get("lieferant"), betrag=daten.get("betrag"), firma=daten.get("firma"),
                          grund=daten.get("grund"), pruefung=daten.get("pruefung"), entwurf=entwurf_angelegt,
                          pruefung_neu=anbieter_neu)
            if geheim and geheim.vertraulich:
                kern.ereignis("vertraulich", f"{fund.name} nur auf deinem Mac gelesen ({geheim.grund}), "
                              f"liegt unter {daten['pfad']}. Bitte kurz ansehen, ob Name und Ordner stimmen.",
                              quelle=fund.quelle, pfad=daten["pfad"])
        return ergebnis
    except Unerreichbar as fehler:
        # Kein Netz oder Modell gestört: nichts ablegen, nichts als erledigt merken.
        meldung = f"{fund.name} wartet, weil das Modell nicht erreichbar war. Der nächste Lauf versucht es wieder."
        if echt:
            if kern.netzfehler(fehler):
                kern.einmal_taeglich("offline", "Dein Mac war ohne Netz. Liegengebliebene Belege werden nachgeholt.")
            else:
                kern.einmal_taeglich("fehler", f"Modell nicht erreichbar, Belege warten: {fehler}")
        return kern.Ergebnis("spaeter", meldung)
    except VertraulichGescheitert as fehler:
        if echt:
            kern.ereignis("fehler", str(fehler), quelle=fund.quelle)
        return kern.Ergebnis("fehler", str(fehler))
    except OSError as fehler:
        meldung, wartet = kern.datei_fehler(fund.name, fehler)
        if wartet:
            if echt:
                kern.einmal_taeglich("datei_wartet", "Mindestens eine Datei war noch nicht fertig aus dem "
                                     "Cloud-Ordner geladen und wird beim nächsten Lauf nachgeholt. Bleibt das "
                                     "über Tage so, stell den Ordner in Google Drive auf „Offline verfügbar“.")
            return kern.Ergebnis("spaeter", meldung)
        if echt:
            kern.ereignis("fehler", meldung, quelle=fund.quelle)
        return kern.Ergebnis("fehler", meldung)
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
