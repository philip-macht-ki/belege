"""E-Rechnungen sicher lesen und als Sichtfassung ausgeben."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET


def _lokal(element: ET.Element) -> str:
    """Liefert den XML-Namen ohne optionalen Namensraum."""
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ET.Element) -> str:
    """Liefert den bereinigten Text eines XML-Elements."""
    return (element.text or "").strip()


def _erst(root: ET.Element, *namen: str) -> str:
    """Findet den ersten nicht leeren Text zu einem der Namen."""
    for element in root.iter():
        if _lokal(element) in namen and _text(element):
            return _text(element)
    return ""


def _alle(root: ET.Element, name: str) -> list[ET.Element]:
    """Findet alle XML-Elemente mit einem lokalen Namen."""
    return [element for element in root.iter() if _lokal(element) == name]


def _wurzel(datei: Path) -> ET.Element:
    """Liest eine harmlose XML-Datei ohne externe Entitäten."""
    roh = datei.read_bytes()
    if re.search(br"<!DOCTYPE|<!ENTITY", roh, re.I):
        raise ValueError("XML mit DOCTYPE oder ENTITY wird nicht verarbeitet.")
    return ET.fromstring(roh)


def _datum(wert: str) -> date:
    """Wandelt ein ISO- oder CII-Datum in ein Datum um."""
    ziffern = re.sub(r"[^0-9]", "", wert)
    return date.fromisoformat(f"{ziffern[:4]}-{ziffern[4:6]}-{ziffern[6:8]}")


def _zahl(wert: str) -> float:
    """Liest einen Betrag mit Punkt oder Komma."""
    return float(wert.replace(",", "."))


def _name(block: ET.Element) -> str:
    """Liest den Namen einer Partei aus ihrem XML-Block."""
    return _erst(block, "Name", "RegistrationName")


def _ust(block: ET.Element) -> str:
    """Liest eine USt-IdNr. aus dem XML-Block, wenn vorhanden."""
    for element in block.iter():
        if _lokal(element) in {"ID", "VATID"} and _text(element):
            return _text(element)
    return ""


def ist_erechnung(datei: Path) -> bool:
    """Prüft, ob eine XML-Datei CII, UBL-Rechnung oder -Gutschrift enthält."""
    try:
        return _lokal(_wurzel(Path(datei))) in {"CrossIndustryInvoice", "Invoice", "CreditNote"}
    except (OSError, ValueError, ET.ParseError):
        return False


def lesen(datei: Path) -> dict:
    """Liest die wichtigsten Felder aus einer CII- oder UBL-E-Rechnung."""
    root = _wurzel(Path(datei))
    typ = _lokal(root)
    if typ == "CrossIndustryInvoice":
        verkaeufer = next((e for e in root.iter() if _lokal(e) == "SellerTradeParty"), ET.Element("leer"))
        kaeufer = next((e for e in root.iter() if _lokal(e) == "BuyerTradeParty"), ET.Element("leer"))
        positionen = []
        for zeile in _alle(root, "IncludedSupplyChainTradeLineItem"):
            betrag = _zahl(_erst(zeile, "LineTotalAmount") or "0")
            positionen.append({"text": _erst(zeile, "Name"), "betrag": betrag})
        return {
            "nummer": _erst(root, "ID"), "datum": _datum(_erst(root, "DateTimeString")),
            "verkaeufer": _name(verkaeufer), "verkaeufer_ust": _ust(verkaeufer),
            "kaeufer": _name(kaeufer), "kaeufer_ust": _ust(kaeufer),
            "betrag": _zahl(_erst(root, "GrandTotalAmount")),
            "waehrung": next((e.attrib.get("currencyID", "EUR") for e in root.iter()
                               if _lokal(e) == "GrandTotalAmount"), "EUR"),
            "positionen": positionen, "syntax": "cii",
        }
    if typ not in {"Invoice", "CreditNote"}:
        raise ValueError("Keine unterstützte E-Rechnung (CII oder UBL).")
    verkaeufer_namen = {"AccountingSupplierParty", "SellerSupplierParty"}
    kaeufer_namen = {"AccountingCustomerParty", "BuyerCustomerParty"}
    verkaeufer = next((e for e in root.iter() if _lokal(e) in verkaeufer_namen), ET.Element("leer"))
    kaeufer = next((e for e in root.iter() if _lokal(e) in kaeufer_namen), ET.Element("leer"))
    positionen = []
    for zeile in _alle(root, "InvoiceLine"):
        betrag = _zahl(_erst(zeile, "LineExtensionAmount") or "0")
        positionen.append({"text": _erst(zeile, "Name"), "betrag": betrag})
    gesamt = _erst(root, "PayableAmount") or _erst(root, "TaxInclusiveAmount")
    return {
        "nummer": _erst(root, "ID"), "datum": _datum(_erst(root, "IssueDate")),
        "verkaeufer": _name(verkaeufer), "verkaeufer_ust": _ust(verkaeufer),
        "kaeufer": _name(kaeufer), "kaeufer_ust": _ust(kaeufer), "betrag": _zahl(gesamt),
        "waehrung": next((e.attrib.get("currencyID", "EUR") for e in root.iter()
                           if _lokal(e) in {"PayableAmount", "TaxInclusiveAmount"}), "EUR"),
        "positionen": positionen, "syntax": "ubl",
    }


def _euro(betrag, waehrung: str = "EUR") -> str:
    """47.6 → "47,60 €" (deutsches Format; andere Währungen mit ihrem Kürzel)."""
    text = f"{float(betrag or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €" if waehrung in ("EUR", "", None) else f"{text} {waehrung}"


def sichttext(daten: dict) -> str:
    """Baut aus E-Rechnungsfeldern einen lesbaren Text ohne Modellaufruf."""
    waehrung = daten.get("waehrung", "EUR")
    positionen = ", ".join(
        f"{position.get('text', 'Position')} {_euro(position.get('betrag', 0), waehrung)}"
        for position in daten.get("positionen", [])
    )
    datum = daten.get("datum", "")
    datum_text = datum.strftime("%d.%m.%Y") if hasattr(datum, "strftime") else str(datum)
    return (
        f"E-Rechnung Nummer {daten.get('nummer', '')}. Datum: {datum_text}. "
        f"Verkäufer: {daten.get('verkaeufer', '')}. Käufer: {daten.get('kaeufer', '')}. "
        f"Positionen: {positionen}. Gesamtbetrag: {_euro(daten.get('betrag', 0), waehrung)}."
    )


def sicht_pdf(daten: dict, xml_datei: Path, ziel: Path) -> None:
    """Erzeugt eine Sichtfassung, damit Menschen die XML-Rechnung lesen können."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    arial = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    if arial.exists():
        pdf.add_font("Arial", "", str(arial))
        pdf.set_font("Arial", size=11)
        eurozeichen = True
    else:  # ohne Unicode-Schrift kann die eingebaute Helvetica kein €
        pdf.set_font("Helvetica", size=11)
        eurozeichen = False
    sha = hashlib.sha256(Path(xml_datei).read_bytes()).hexdigest()
    kopf = f"Lesefassung einer E-Rechnung. Original: {Path(xml_datei).name}, SHA-256 {sha}."
    pdf.multi_cell(0, 6, kopf, wrapmode="CHAR")
    pdf.ln(5)
    text = sichttext(daten) if eurozeichen else sichttext(daten).replace("€", "EUR")
    for zeile in text.split(". "):
        pdf.multi_cell(0, 7, zeile.rstrip("."), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))


def zugferd_in(pdf: Path) -> bool:
    """Prüft grob, ob ein PDF einen bekannten ZUGFeRD-Anhang erwähnt."""
    try:
        roh = Path(pdf).read_bytes().lower()
    except OSError:
        return False
    return any(name in roh for name in (b"factur-x.xml", b"zugferd-invoice.xml", b"xrechnung.xml"))
