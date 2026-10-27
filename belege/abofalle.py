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
_AKTION = re.compile(rb"/S\s*/(JavaScript|Launch)\b")
_JS_CODE = re.compile(rb"/JS\s*[(<]")
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
    gefunden += [m.decode("ascii") for m in (b"/RichMedia", b"/XFA") if m in roh]
    try:
        from pypdf import PdfReader
        leser = PdfReader(str(datei), strict=False)
        wurzel = leser.trailer["/Root"]
        namen = wurzel.get("/Names", {})
        if "/JavaScript" in namen and "/JavaScript-Aktion" not in gefunden:
            gefunden.append("/JavaScript-Aktion")
        fremd = [n for n in leser.attachments if not n.lower().endswith(".xml")]
        if fremd:
            gefunden.append("eingebettete Datei: " + ", ".join(fremd[:3]))
    except Exception:
        # Nicht auswertbar: nur sperren, wenn roh eine eingebettete Datei steht.
        if b"/EmbeddedFile" in roh:
            gefunden.append("/EmbeddedFile (nicht auswertbar)")
    return bool(gefunden), ", ".join(gefunden)
