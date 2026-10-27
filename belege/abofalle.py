"""Konservative Schutzregeln für Adressbuch-/Branchenbuch-Abofallen."""
from __future__ import annotations

import re
from pathlib import Path

KATALOG = ("branchenbuch", "firmenverzeichnis", "gewerbeverzeichnis", "adressbuch")
FORMULAR = ("eintragungsofferte", "offerten nummer", "offerten-nummer", "eintragungsart",
            "eintragungsantrag", "korrekturabzug")
RUECK = ("rücksendung", "ruecksendung", "servicefax", "per fax", "zurückfaxen",
         "zurueckfaxen", "return@", "antwort per fax")
DOMAINS = ("businesseintrag.info",)
FAX = re.compile(r"(?:00|\+)4(?:1|3)\D*(?:\d[\s-]*){6,}")


def erkennen(text: str, *, name: str = "", absender: str = "") -> tuple[bool, str]:
    """Treffer erst bei mehreren unabhängigen Merkmalen; einzelne Wörter reichen nie."""
    hay = f"{text}\n{name}\n{absender}".lower()
    merkmale = []
    if any(w in hay for w in KATALOG): merkmale.append("Branchen-/Adressverzeichnis")
    if any(w in hay for w in FORMULAR): merkmale.append("Eintragungs-/Offertenformular")
    if any(w in hay for w in RUECK) or FAX.search(hay): merkmale.append("Rücksendung/Fax")
    if any(w in hay for w in DOMAINS): merkmale.append("bekannte Abofallen-Domain")
    # Drei Merkmale, oder zwei mit bekannter Abofallen-Domain: Eine echte, bestellte
    # Rechnung eines Verzeichnisverlags nennt selten Offertenformular UND Rückfax.
    bekannt = "bekannte Abofallen-Domain" in merkmale
    return len(merkmale) >= 3 or (bekannt and len(merkmale) >= 2), "; ".join(merkmale)


_AKTION = re.compile(rb"/S\s*/(JavaScript|Launch)\b")
_JS_CODE = re.compile(rb"/JS\s*[(<]")
_AKTIONSTYPEN = {"/JavaScript": "/JavaScript-Aktion", "/Launch": "/Launch-Aktion"}


def _objektbaum_pruefen(leser, gefunden: list[str], grenze: int = 50000) -> None:
    """Läuft vom Katalog aus durch alle erreichbaren Objekte, auch in komprimierten
    Objektströmen: OpenAction, AA, Seiten- und Annotationsaktionen, Namensbäume."""
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    gesehen: set[tuple[int, int]] = set()
    stapel = [leser.trailer["/Root"]]
    schritte = 0
    while stapel and schritte < grenze:
        schritte += 1
        obj = stapel.pop()
        if isinstance(obj, IndirectObject):
            schluessel = (obj.idnum, obj.generation)
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            try:
                obj = obj.get_object()
            except Exception:
                continue
        if isinstance(obj, DictionaryObject):
            art = obj.get("/S")
            if art in _AKTIONSTYPEN and _AKTIONSTYPEN[art] not in gefunden:
                gefunden.append(_AKTIONSTYPEN[art])
            if "/JS" in obj and "/JavaScript-Aktion" not in gefunden:
                gefunden.append("/JavaScript-Aktion")
            for name in ("/RichMedia", "/XFA"):
                if (name in obj or obj.get("/Subtype") == name) and name not in gefunden:
                    gefunden.append(name)
            for wert in obj.values():
                if isinstance(wert, (IndirectObject, DictionaryObject, ArrayObject)):
                    stapel.append(wert)
        elif isinstance(obj, ArrayObject):
            stapel.extend(w for w in obj if isinstance(w, (IndirectObject, DictionaryObject, ArrayObject)))
    if stapel:
        gefunden.append("zu viele Objekte zum Prüfen")


def aktive_pdf_inhalte(datei: Path) -> tuple[bool, str]:
    """Findet PDF-Aktionen, die nicht an DATEV geschickt werden dürfen.

    E-Rechnungen (ZUGFeRD/Factur-X, XRechnung im PDF) tragen ihre Daten als
    eingebettete XML-Datei; das ist erlaubt. Gesperrt werden JavaScript- und
    Launch-Aktionen, RichMedia, XFA-Formulare und eingebettete Nicht-XML-Dateien.
    """
    if datei.suffix.lower() != ".pdf":
        return False, ""
    try:
        roh = datei.read_bytes()
    except OSError as exc:
        return True, f"PDF nicht lesbar: {exc}"
    gefunden = sorted({f"/{m.decode()}-Aktion" for m in _AKTION.findall(roh)})
    if _JS_CODE.search(roh) and "/JavaScript-Aktion" not in gefunden:
        gefunden.append("/JavaScript-Aktion")
    gefunden += [m.decode("ascii") for m in (b"/RichMedia", b"/XFA") if m in roh and m.decode("ascii") not in gefunden]
    try:
        import logging
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        leser = PdfReader(str(datei), strict=False)
        _objektbaum_pruefen(leser, gefunden)
        fremd = [n for n in leser.attachments if not n.lower().endswith(".xml")]
        if fremd:
            gefunden.append("eingebettete Datei: " + ", ".join(fremd[:3]))
    except Exception:
        # Nicht auswertbar: nur sperren, wenn roh eine eingebettete Datei steht.
        if b"/EmbeddedFile" in roh:
            gefunden.append("/EmbeddedFile (nicht auswertbar)")
    return bool(gefunden), ", ".join(gefunden)
