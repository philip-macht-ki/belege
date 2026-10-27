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
    """Treffer nur bei mindestens zwei Kategorien; einzelne Wörter reichen nie."""
    hay = f"{text}\n{name}\n{absender}".lower()
    merkmale = []
    if any(w in hay for w in KATALOG): merkmale.append("Branchen-/Adressverzeichnis")
    if any(w in hay for w in FORMULAR): merkmale.append("Eintragungs-/Offertenformular")
    if any(w in hay for w in RUECK) or FAX.search(hay): merkmale.append("Rücksendung/Fax")
    if any(w in hay for w in DOMAINS): merkmale.append("bekannte Abofallen-Domain")
    return len(merkmale) >= 2, "; ".join(merkmale)


def aktive_pdf_inhalte(datei: Path) -> tuple[bool, str]:
    if datei.suffix.lower() != ".pdf": return False, ""
    try: roh = datei.read_bytes()
    except OSError as exc: return True, f"PDF nicht lesbar: {exc}"
    marker = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/XFA")
    gefunden = [m.decode() for m in marker if m in roh]
    if b"/OpenAction" in roh and (b"/JavaScript" in roh or b"/JS" in roh):
        gefunden.append("/OpenAction mit JS")
    return bool(gefunden), ", ".join(gefunden)
