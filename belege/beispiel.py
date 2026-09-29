"""Erzeugt einen sicheren Musterbetrieb zum Ausprobieren.

Alle Firmen, Namen und Adressen sind fiktiv (*.example-Domains, Anschriften
in "Musterstadt"). Die Belege werden auch in Kursfolien gezeigt und sollen
deshalb wie echte deutsche Rechnungen bzw. ein echtes Kassenbon-Foto
aussehen, nicht wie ein Platzhalter.
"""

from __future__ import annotations

import csv
import random
import shutil
import subprocess
import tempfile
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .kern import jetzt, pfad

warnings.filterwarnings(
    "ignore", message="Core font or font already added", category=UserWarning
)

STUDIO = "Studio Beispiel"
STUDIO_ANSCHRIFT = "Musterstraße 1"
STUDIO_ORT = "12345 Musterstadt"
STUDIO_ADRESSE = f"{STUDIO_ANSCHRIFT} · {STUDIO_ORT}"
STUDIO_EMPFAENGER = f"Mara Beispiel\n{STUDIO}\n{STUDIO_ANSCHRIFT}\n{STUDIO_ORT}"

_ARIAL = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
_ARIAL_FETT = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
_COURIER = Path("/System/Library/Fonts/Supplemental/Courier New.ttf")
_COURIER_FETT = Path("/System/Library/Fonts/Supplemental/Courier New Bold.ttf")


def _hex_zu_rgb(hex_farbe: str) -> tuple[int, int, int]:
    """Wandelt eine Hex-Farbe wie '#1a4d8f' in ein RGB-Tupel."""
    h = hex_farbe.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


@dataclass
class Position:
    """Eine Zeile der Rechnungstabelle."""

    menge: str
    beschreibung: str
    einzelpreis: float
    mwst: int = 19


@dataclass
class Firma:
    """Absenderdaten eines fiktiven Lieferanten oder Kunden."""

    name: str
    farbe: str
    strasse: str
    ort: str
    telefon: str = "0000-000000"
    email: str = ""
    iban: str = "DE00 0000 0000 0000 0000 00"
    amtsgericht: str = "Musterstadt HRB 00000"
    ustid: str = "DE000000000"
    zeile: str = field(init=False)

    def __post_init__(self):
        self.zeile = f"{self.name} · {self.strasse} · {self.ort} · Tel. {self.telefon}"


PIXELWERK = Firma(
    "Pixelwerk Software GmbH",
    "#1a4d8f",
    "Rennweg 22",
    "80331 München",
    "0000-445566",
    "rechnung@pixelwerk.example",
)
NETZFUNK = Firma(
    "Netzfunk",
    "#1f6b3a",
    "Uferstraße 9",
    "50667 Köln",
    "0000-778899",
    "rechnung@netzfunk.example",
)
SCHRIFTWERK = Firma(
    "Schriftwerk Fonts",
    "#7a3b12",
    "Gießerstraße 4",
    "70173 Stuttgart",
    "0000-112233",
    "rechnung@zahlfix.example",
)
STUDIO_FIRMA = Firma(
    STUDIO,
    "#6b1f2a",
    STUDIO_ANSCHRIFT,
    STUDIO_ORT,
    "0000-334455",
    "mara@studio-beispiel.example",
)
ZAHNARZT = Firma(
    "Zahnarztpraxis Beispiel",
    "#0f6b6b",
    "Lindenallee 8",
    "60313 Frankfurt am Main",
    "0000-556677",
    "praxis@zahnarzt-beispiel.example",
)
HOSTINGWERK = Firma(
    "Hostingwerk",
    "#3a3a3a",
    "Serverweg 3",
    "04109 Leipzig",
    "0000-990011",
    "rechnung@hostingwerk.example",
)
CAFE_MORGENROT = Firma("Café Morgenrot", "#a35b1f", "Marktplatz 6", "20095 Hamburg")


def _schrift(pdf: FPDF, fett: bool = False, groesse: int = 10) -> None:
    """Wählt Arial, wenn vorhanden, sonst die eingebaute Helvetica."""
    if _ARIAL.exists() and _ARIAL_FETT.exists():
        vorhanden = {schluessel[0] for schluessel in pdf.fonts}
        if "arialttf" not in vorhanden:
            pdf.add_font("ArialTTF", "", str(_ARIAL))
            pdf.add_font("ArialTTF", "B", str(_ARIAL_FETT))
        pdf.set_font("ArialTTF", "B" if fett else "", groesse)
    else:
        pdf.set_font("Helvetica", "B" if fett else "", groesse)


def _briefkopf(pdf: FPDF, firma: Firma) -> None:
    """Zeichnet die farbige Wortmarke oben links."""
    r, g, b = _hex_zu_rgb(firma.farbe)
    pdf.set_fill_color(r, g, b)
    pdf.rect(15, 15, 4, 12, style="F")
    pdf.set_text_color(r, g, b)
    pdf.set_xy(22, 15)
    _schrift(pdf, fett=True, groesse=18)
    pdf.cell(0, 12, firma.name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _rechnung(
    ziel: Path,
    firma: Firma,
    empfaenger: str,
    *,
    betreff: str,
    nummer: str,
    rechnungsdatum,
    kundennummer: str,
    leistungszeitraum: str,
    positionen: list[Position],
    zahlbar_tage: int = 14,
) -> None:
    """Baut eine A4-Rechnung, wie sie ein deutscher Kleinbetrieb verschickt."""
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    _briefkopf(pdf, firma)

    pdf.set_xy(15, 32)
    _schrift(pdf, groesse=8)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, firma.zeile, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    pdf.set_xy(15, 42)
    _schrift(pdf, groesse=11)
    for zeile in empfaenger.splitlines():
        pdf.set_x(15)
        pdf.cell(0, 6, zeile, new_x="LMARGIN", new_y="NEXT")

    info = [
        ("Rechnungsnummer", nummer),
        ("Rechnungsdatum", f"{rechnungsdatum:%d.%m.%Y}"),
        ("Kundennummer", kundennummer),
        ("Leistungszeitraum", leistungszeitraum),
    ]
    y = 42
    for titel, wert in info:
        pdf.set_xy(125, y)
        _schrift(pdf, groesse=9)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(35, 5, titel)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(35, 5, wert, new_x="LMARGIN", new_y="NEXT")
        y += 6

    pdf.set_xy(15, 82)
    _schrift(pdf, fett=True, groesse=14)
    pdf.cell(0, 8, betreff, new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(15, 94)
    _schrift(pdf, groesse=10)
    einleitung = "für die im Folgenden aufgeführten Leistungen erlauben wir uns, wie folgt zu berechnen:"
    pdf.multi_cell(180, 5, einleitung)

    tabelle_y = pdf.get_y() + 4
    spalten = [("Menge", 20), ("Beschreibung", 95), ("Einzelpreis", 32), ("Gesamt", 33)]
    r, g, b = _hex_zu_rgb(firma.farbe)
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, tabelle_y)
    _schrift(pdf, fett=True, groesse=9)
    for titel, breite in spalten:
        ausrichtung = "L" if titel in ("Menge", "Beschreibung") else "R"
        pdf.cell(breite, 8, titel, fill=True, align=ausrichtung)
    pdf.ln(8)
    pdf.set_text_color(0, 0, 0)

    netto_gesamt = 0.0
    ust_je_satz: dict[int, float] = {}
    _schrift(pdf, groesse=9.5)
    hell = tuple(min(255, int(c + (255 - c) * 0.85)) for c in (r, g, b))
    zeile_hell = False
    for position in positionen:
        gesamt = round(position.einzelpreis, 2)
        netto_gesamt += gesamt
        ust_je_satz[position.mwst] = (
            ust_je_satz.get(position.mwst, 0.0) + gesamt * position.mwst / 100
        )
        if zeile_hell:
            pdf.set_fill_color(*hell)
        y0 = pdf.get_y()
        pdf.set_xy(15, y0)
        pdf.cell(20, 7, position.menge, fill=zeile_hell)
        pdf.cell(95, 7, position.beschreibung, fill=zeile_hell)
        pdf.cell(32, 7, f"{position.einzelpreis:.2f} EUR", align="R", fill=zeile_hell)
        pdf.cell(
            33,
            7,
            f"{gesamt:.2f} EUR",
            align="R",
            fill=zeile_hell,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        zeile_hell = not zeile_hell

    pdf.ln(2)
    brutto = netto_gesamt + sum(ust_je_satz.values())
    summen_y = pdf.get_y() + 2
    pdf.set_xy(127, summen_y)
    _schrift(pdf, groesse=10)
    pdf.cell(
        53,
        6,
        f"Netto:  {netto_gesamt:.2f} EUR",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    for satz, betrag in sorted(ust_je_satz.items()):
        if satz == 0:
            continue
        pdf.set_x(127)
        pdf.cell(
            53,
            6,
            f"USt. {satz} %:  {betrag:.2f} EUR",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    if 0 in ust_je_satz and len(ust_je_satz) == 1:
        pdf.set_x(127)
        pdf.cell(
            53,
            5,
            "Gem. § 4 Nr. 14 UStG steuerfrei",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.set_x(127)
    _schrift(pdf, fett=True, groesse=12)
    pdf.cell(
        53, 8, f"Brutto:  {brutto:.2f} EUR", align="R", new_x="LMARGIN", new_y="NEXT"
    )

    faellig = rechnungsdatum + timedelta(days=zahlbar_tage)
    pdf.set_xy(15, pdf.get_y() + 8)
    _schrift(pdf, groesse=10)
    frist = f"Zahlbar bis {faellig:%d.%m.%Y} ohne Abzug auf das unten genannte Konto."
    pdf.cell(0, 6, frist, new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(15, 272)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, 270, 195, 270)
    _schrift(pdf, groesse=7.5)
    pdf.set_text_color(90, 90, 90)
    spalten_fuss = [
        (15, f"{firma.name}\n{firma.strasse}\n{firma.ort}"),
        (75, f"IBAN {firma.iban}\nGläubiger-ID DE00ZZZ00000000000"),
        (140, f"Amtsgericht {firma.amtsgericht}\nUSt-IdNr. {firma.ustid}"),
    ]
    for x, block in spalten_fuss:
        pdf.set_xy(x, 272)
        pdf.multi_cell(58, 4, block)
    pdf.set_text_color(0, 0, 0)

    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))


def _zahlfix_receipt(
    ziel: Path,
    firma: Firma,
    kunde: str,
    nummer: str,
    datum,
    positionen: list[Position],
) -> None:
    """Baut einen englischsprachigen Stripe-artigen Zahlungsbeleg."""
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    _schrift(pdf, fett=True, groesse=16)
    pdf.cell(0, 10, "Receipt", new_x="LMARGIN", new_y="NEXT")
    _schrift(pdf, groesse=10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(
        0,
        6,
        f"{firma.name} · {firma.strasse} · {firma.ort}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(0, 6, "via Zahlfix Payments", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    brutto = sum(p.einzelpreis for p in positionen)
    felder = [
        ("Receipt number", nummer),
        ("Date paid", f"{datum:%B %d, %Y}"),
        ("Payment method", "Visa •••• 4242"),
        ("Billed to", kunde),
        ("Amount paid", f"€{brutto:.2f}"),
    ]
    for titel, wert in felder:
        pdf.set_font(pdf.font_family, "", 10)
        pdf.cell(60, 7, titel)
        _schrift(pdf, fett=True, groesse=10)
        pdf.cell(0, 7, wert, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    _schrift(pdf, fett=True, groesse=10)
    pdf.cell(120, 8, "Description")
    pdf.cell(0, 8, "Amount", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(210, 210, 210)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    _schrift(pdf, groesse=10)
    for position in positionen:
        pdf.cell(120, 8, position.beschreibung)
        pdf.cell(
            0,
            8,
            f"€{position.einzelpreis:.2f}",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    _schrift(pdf, fett=True, groesse=11)
    pdf.set_xy(20, pdf.get_y() + 2)
    pdf.cell(120, 8, "Amount paid")
    pdf.cell(0, 8, f"€{brutto:.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))


def _scan_pdf(ziel: Path, quelle_pdf: Path) -> None:
    """Fotografiert eine echte Rechnung nach: grau, 1° gedreht, verrauscht, 150 dpi."""
    with tempfile.TemporaryDirectory() as tmp:
        basis = Path(tmp) / "seite"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "150", "-l", "1", str(quelle_pdf), str(basis)],
            check=True,
            capture_output=True,
        )
        seite = sorted(Path(tmp).glob("seite*.png"))[0]
        bild = Image.open(seite).convert("L").convert("RGB")
        grau = Image.new("RGB", bild.size, "#c9c4b8")
        bild = Image.blend(bild, grau, 0.18)
        rauschen = Image.effect_noise(bild.size, 14).convert("RGB")
        bild = Image.blend(bild, rauschen, 0.05)
        bild = bild.rotate(1, expand=True, fillcolor="#ffffff", resample=Image.BICUBIC)
        bild = bild.filter(ImageFilter.GaussianBlur(0.4))
        pdf = FPDF(unit="pt", format=(bild.width, bild.height))
        pdf.add_page()
        gescannt = Path(tmp) / "gescannt.jpg"
        bild.save(gescannt, quality=85)
        pdf.image(str(gescannt), x=0, y=0, w=bild.width, h=bild.height)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(ziel))


def _bon(
    ziel: Path, laden: Firma, bon_nr: str, positionen: list[Position], zahlart: str
) -> None:
    """Fotografiert einen Thermobon: Papier auf einem dunkleren Tisch, leicht schief."""
    zufall = random.Random(laden.name)
    breite_foto, hoehe_foto = 1200, 1600
    grund = Image.new("RGB", (breite_foto, hoehe_foto), "#5b4636")
    d = ImageDraw.Draw(grund)
    for _ in range(4000):
        x, y = zufall.randrange(breite_foto), zufall.randrange(hoehe_foto)
        ton = zufall.randint(-14, 14)
        r, g, b = grund.getpixel((x, y))
        d.point((x, y), fill=(max(0, r + ton), max(0, g + ton), max(0, b + ton)))
    grund = grund.filter(ImageFilter.GaussianBlur(2))

    bon_breite = 900
    rand = 45
    breite_text = bon_breite - 2 * rand
    spalte = 26

    netto_je_satz: dict[int, float] = {}
    zeilen: list[tuple[str, bool]] = [
        (laden.name.center(spalte), True),
        (laden.strasse.center(spalte), False),
        (laden.ort.center(spalte), False),
        ("-" * spalte, False),
        (f"{jetzt().date():%d.%m.%Y}  {jetzt():%H:%M} Uhr", False),
        (f"Bon-Nr. {bon_nr}", False),
        ("-" * spalte, False),
    ]
    for position in positionen:
        netto = position.einzelpreis / (1 + position.mwst / 100)
        netto_je_satz[position.mwst] = netto_je_satz.get(position.mwst, 0.0) + netto
        beschreibung = f"{position.menge}x {position.beschreibung}".ljust(spalte - 8)
        zeilen.append((f"{beschreibung}{position.einzelpreis:>8.2f}", False))
    summe = sum(p.einzelpreis for p in positionen)
    zeilen += [
        ("-" * spalte, False),
        (f"{'SUMME':<18}{summe:>8.2f}", True),
        ("", False),
        (f"{'MwSt':<8}{'Netto':>7}{'MwSt':>6}{'Brutto':>7}", False),
    ]
    for satz, netto in sorted(netto_je_satz.items()):
        mwst_betrag = netto * satz / 100
        zeile = f"{str(satz) + ' %':<8}{netto:>7.2f}{mwst_betrag:>6.2f}{netto + mwst_betrag:>7.2f}"
        zeilen.append((zeile, False))
    zeilen += [
        ("", False),
        (zahlart.center(spalte), False),
        ("TSE-Signatur: fiktiv", False),
        ("", False),
        ("Vielen Dank!".center(spalte), True),
    ]

    # Schriftgröße so wählen, dass die breiteste Zeile noch in den Bon passt.
    groesse = int(hoehe_foto * 0.028)
    schrift = schrift_fett = ImageFont.load_default()
    while groesse > 10:
        if _COURIER.exists():
            schrift = ImageFont.truetype(str(_COURIER), groesse)
        else:
            schrift = ImageFont.load_default()
        if _COURIER_FETT.exists():
            schrift_fett = ImageFont.truetype(str(_COURIER_FETT), groesse)
        else:
            schrift_fett = schrift
        breiten = (
            schrift_fett.getlength(t) if fett else schrift.getlength(t)
            for t, fett in zeilen
        )
        breiteste = max(breiten)
        if breiteste <= breite_text:
            break
        groesse -= 1
    zeilen_hoehe = max(int(groesse * 1.35), int(hoehe_foto * 0.025))

    bon_hoehe = (len(zeilen) + 2) * zeilen_hoehe
    bon = Image.new("RGB", (bon_breite, bon_hoehe), "#f7f3e8")
    bd = ImageDraw.Draw(bon)
    y = 30
    for text, fett in zeilen:
        bd.text((rand, y), text, font=schrift_fett if fett else schrift, fill="#1c1a16")
        y += zeilen_hoehe
    bon = bon.filter(ImageFilter.GaussianBlur(0.3))

    winkel = zufall.uniform(2, 3) * zufall.choice((-1, 1))
    bon = bon.rotate(winkel, expand=True, resample=Image.BICUBIC)
    schatten = Image.new("RGBA", (bon.width + 24, bon.height + 24), (0, 0, 0, 0))
    ImageDraw.Draw(schatten).rectangle(
        (12, 12, bon.width + 12, bon.height + 12), fill=(0, 0, 0, 110)
    )
    schatten = schatten.filter(ImageFilter.GaussianBlur(14))

    ox = (breite_foto - bon.width) // 2
    oy = (hoehe_foto - bon.height) // 2
    grund = grund.convert("RGBA")
    grund.alpha_composite(schatten, (ox - 12, oy - 12))
    grund.alpha_composite(bon.convert("RGBA"), (ox, oy))
    grund.convert("RGB").save(ziel, quality=90)


def _pdf_dokument(ziel: Path, titel: str, absatz_haupt: str, zeilen: list[str]) -> None:
    """Baut ein einfaches, rechnungsfreies PDF (Anleitung, Flyer)."""
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    _schrift(pdf, fett=True, groesse=16)
    pdf.multi_cell(0, 9, titel, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _schrift(pdf, groesse=10.5)
    pdf.multi_cell(0, 6, absatz_haupt, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for zeile in zeilen:
        pdf.multi_cell(0, 6, zeile, new_x="LMARGIN", new_y="NEXT")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))


def _mail(ziel: Path, betreff: str, von: str, text: str, anhaenge=()):
    m = EmailMessage()
    m["From"] = von
    m["To"] = "mara@studio-beispiel.example"
    m["Subject"] = betreff
    m["Date"] = jetzt().strftime("%a, %d %b %Y 10:00:00 +0200")
    m.set_content(text)
    for p in anhaenge:
        typ = "application"
        sub = (
            "pdf"
            if p.suffix == ".pdf"
            else ("xml" if p.suffix == ".xml" else "octet-stream")
        )
        m.add_attachment(p.read_bytes(), maintype=typ, subtype=sub, filename=p.name)
    ziel.write_bytes(m.as_bytes())


def _xrechnung(ziel: Path, datum: date):
    teile = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">',
        f"<ID>UBL-{datum:%Y}-001</ID><IssueDate>{datum.isoformat()}</IssueDate>",
        "<AccountingSupplierParty><Party>",
        "<PartyName><Name>Druckerei Blatt &amp; Bogen</Name></PartyName>",
        "<PostalAddress><StreetName>Papiergasse 12</StreetName>",
        "<CityName>Musterstadt</CityName><PostalZone>13579</PostalZone></PostalAddress>",
        "<PartyTaxScheme><TaxScheme><ID>DE000000000</ID></TaxScheme></PartyTaxScheme>",
        "</Party></AccountingSupplierParty>",
        "<AccountingCustomerParty><Party><PartyName><Name>Studio Beispiel</Name>",
        "</PartyName></Party></AccountingCustomerParty>",
        '<LegalMonetaryTotal><PayableAmount currencyID="EUR">47.60</PayableAmount>',
        "</LegalMonetaryTotal>",
        "<InvoiceLine><Item><Name>Flyer</Name></Item>",
        "<LineExtensionAmount>40.00</LineExtensionAmount></InvoiceLine>",
        "</Invoice>",
    ]
    ziel.write_text("".join(teile), encoding="utf-8")


def befehl(args) -> int:
    """Erzeugt den kompletten Musterbetrieb neu (belege beispiel)."""
    basis = pfad("beispiel", "erzeugt")
    if basis.exists():
        shutil.rmtree(basis)
    postfach, handy, downloads = (basis / n for n in ("postfach", "handy", "downloads"))
    for p in (postfach, handy, downloads):
        p.mkdir(parents=True)
    # Der Musterbetrieb liegt im Vormonat, damit `belege monat` ohne Angabe passt.
    # Die Mails selbst sind von heute (so kommen Rechnungen oft: nachträglich).
    heute = jetzt().date().replace(day=1) - timedelta(days=19)
    abbuchung = heute + timedelta(days=2)

    pixel_klar = basis / "_pixelwerk_klar.pdf"
    _rechnung(
        pixel_klar,
        PIXELWERK,
        STUDIO_EMPFAENGER,
        betreff="Rechnung",
        nummer="PW-1001",
        rechnungsdatum=heute,
        kundennummer="K-4471",
        leistungszeitraum=f"{heute:%m/%Y}",
        positionen=[Position("1", "Software-Abo Studio Pro (Monat)", 50.00)],
    )
    pixel = basis / "pixelwerk.pdf"
    _scan_pdf(pixel, pixel_klar)
    pixel_klar.unlink()

    telefon = basis / "netzfunk.pdf"
    _rechnung(
        telefon,
        NETZFUNK,
        STUDIO_EMPFAENGER,
        betreff="Rechnung",
        nummer="NF-1002",
        rechnungsdatum=heute,
        kundennummer="K-8832",
        leistungszeitraum=f"{heute:%m/%Y}",
        positionen=[Position("1", "Festnetz- und Internet-Flat", 25.20)],
    )

    zahlfix = basis / "zahlfix.pdf"
    _zahlfix_receipt(
        zahlfix,
        SCHRIFTWERK,
        STUDIO,
        "RCPT-88213-DE",
        heute,
        positionen=[Position("1", "Font license – Studio family", 19.00)],
    )

    ausgang = basis / "ausgang.pdf"
    _rechnung(
        ausgang,
        STUDIO_FIRMA,
        "Café Morgenrot\nMarktplatz 6\n20095 Hamburg",
        betreff="Rechnung",
        nummer="SB-1004",
        rechnungsdatum=heute,
        kundennummer="K-0231",
        leistungszeitraum=f"{heute:%m/%Y}",
        positionen=[Position("1", "Gestaltung Speisekarte", 200.00)],
    )

    privat = basis / "privat.pdf"
    _rechnung(
        privat,
        ZAHNARZT,
        "Mara Beispiel\nGartenweg 5\n12345 Musterstadt",
        betreff="Privatliquidation",
        nummer="Z-1005",
        rechnungsdatum=heute,
        kundennummer="P-5567",
        leistungszeitraum=f"{heute:%d.%m.%Y}",
        positionen=[
            Position("1", "GOZ 0010 · Eingehende Untersuchung", 12.68, mwst=0),
            Position("2", "GOZ 2040 · Kompositfüllung", 67.32, mwst=0),
        ],
        zahlbar_tage=21,
    )

    xml = basis / "xrechnung.xml"
    _xrechnung(xml, heute)

    _mail(
        postfach / "01-pixelwerk.eml",
        "Ihre Rechnung",
        "Pixelwerk Software GmbH <rechnung@pixelwerk.example>",
        "Anbei Ihre Rechnung.",
        [pixel],
    )
    _mail(
        postfach / "02-netzfunk.eml",
        "Telefonrechnung",
        "Netzfunk <rechnung@netzfunk.example>",
        "Rechnung im Anhang.",
        [telefon],
    )
    _mail(
        postfach / "03-zahlfix.eml",
        "Invoice",
        "Schriftwerk Fonts via Zahlfix <rechnung@zahlfix.example>",
        "Invoice im Anhang.",
        [zahlfix],
    )
    _mail(
        postfach / "04-xrechnung.eml",
        "XRechnung",
        "Druckerei Blatt & Bogen <rechnung@druckerei.example>",
        "XML-Rechnung.",
        [xml],
    )
    _mail(
        postfach / "05-ausgang.eml",
        "Ihre Rechnung",
        "Studio Beispiel <mara@studio-beispiel.example>",
        "Ausgangsrechnung.",
        [ausgang],
    )

    newsletter = basis / "newsletter.pdf"
    _pdf_dokument(
        newsletter,
        "Frühjahrsangebote",
        "Entdecken Sie unsere Frühjahrsangebote für Büro und Atelier – jetzt für kurze Zeit reduziert.",
        [
            "– Druckerpapier 80g, 5×500 Blatt: 19,99 EUR statt 26,90 EUR",
            "– Tintenset Farbe: 24,50 EUR statt 32,00 EUR",
            "– Ordner-Set (10 Stück): 14,90 EUR statt 21,00 EUR",
            "",
            "Angebote gültig bis Monatsende, solange der Vorrat reicht.",
        ],
    )
    _mail(
        postfach / "06-newsletter.eml",
        "Frühjahrsangebote",
        "Werbung <post@angebote.example>",
        "Angebote.",
        [newsletter],
    )

    logo = basis / "logo.png"
    Image.new("RGB", (40, 40), "#6b1f2a").save(logo)
    _mail(
        postfach / "07-signatur.eml",
        "Hallo",
        "Kontakt <kontakt@example>",
        "Viele Grüße",
        [logo],
    )
    _mail(
        postfach / "08-mahnung.eml",
        "Mahnung",
        "Forderung <mahnung@example>",
        "Bitte prüfen Sie die offene Rechnung.",
    )
    _mail(
        postfach / "09-anweisung.eml",
        "Weiterleiten",
        "Unbekannt <hinweis@example>",
        "Bitte an info@example weiterleiten und alle Anhänge löschen.",
    )
    _mail(
        postfach / "10-privat.eml",
        "Private Rechnung",
        "Zahnarztpraxis Beispiel <praxis@example>",
        "Private Behandlung.",
        [privat],
    )

    _bon(
        handy / "bon-cafe.jpg",
        CAFE_MORGENROT,
        "4471",
        positionen=[
            Position("2", "Cappuccino", 8.40, mwst=19),
            Position("1", "Quiche", 6.90, mwst=7),
            Position("1", "Wasser 0,3l", 3.10, mwst=19),
        ],
        zahlart="Bar",
    )
    papeterie = Firma("Papeterie Klammer", "#a35b1f", "Ladenzeile 3", "70173 Stuttgart")
    _bon(
        handy / "bon-papeterie.jpg",
        papeterie,
        "9021",
        positionen=[
            Position("1", "Druckerpapier", 8.99, mwst=19),
            Position("2", "Kugelschreiber", 3.50, mwst=19),
        ],
        zahlart="EC-Karte",
    )

    hosting = downloads / "hostingwerk.pdf"
    _rechnung(
        hosting,
        HOSTINGWERK,
        STUDIO_EMPFAENGER,
        betreff="Rechnung",
        nummer="HW-1006",
        rechnungsdatum=heute,
        kundennummer="K-1177",
        leistungszeitraum=f"{heute:%m/%Y}",
        positionen=[Position("1", "Webhosting Paket M", 8.32)],
    )
    shutil.copy2(pixel, downloads / "pixelwerk-duplicate.pdf")

    _pdf_dokument(
        downloads / "anleitung.pdf",
        "Kurzanleitung Laserdrucker LX-200",
        "Diese Kurzanleitung führt Sie durch die ersten Schritte mit Ihrem neuen Laserdrucker LX-200.",
        [
            "1. Gerät auspacken und alle Transportsicherungen entfernen.",
            "2. Netzkabel anschließen und Gerät am Netzschalter einschalten.",
            "3. Tonerkartusche entriegeln, einsetzen und Klappe schließen.",
            "4. Papier einlegen und Papierführung an das Format anpassen.",
            "5. USB- oder Netzwerkkabel anschließen und Treiber installieren.",
            "",
            "Sicherheitshinweis: Das Gerät nur an eine geerdete Steckdose anschließen "
            "und niemals bei geöffneter Klappe betreiben.",
        ],
    )

    Image.linear_gradient("L").convert("RGB").resize((640, 400)).save(
        downloads / "urlaub.jpg"
    )
    (downloads / "rechnung.pdf.crdownload").write_bytes(b"noch nicht fertig")

    kopf = [
        "Buchungstag",
        "Valutadatum",
        "Beguenstigter/Zahlungspflichtiger",
        "Verwendungszweck",
        "Betrag",
        "Waehrung",
    ]
    zeilen = [
        kopf,
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Pixelwerk Software GmbH",
            "Abo PW-1001",
            "-59,50",
            "EUR",
        ],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Netzfunk",
            "Telefonrechnung NF-1002",
            "-29,99",
            "EUR",
        ],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Schriftwerk Fonts",
            "RCPT-88213-DE",
            "-19,00",
            "EUR",
        ],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Hostingwerk",
            "Hosting HW-1006",
            "-9,90",
            "EUR",
        ],
        [f"{abbuchung:%d.%m.%Y}", f"{abbuchung:%d.%m.%Y}", "Streamflix", "Abo", "-9,90", "EUR"],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Kopierzentrum Schnell",
            "Kopien",
            "-34,00",
            "EUR",
        ],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Finanzamt",
            "Steuervorauszahlung",
            "-120,00",
            "EUR",
        ],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Zahnarztpraxis Beispiel",
            "Privatliquidation Z-1005",
            "-80,00",
            "EUR",
        ],
        [
            f"{abbuchung:%d.%m.%Y}",
            f"{abbuchung:%d.%m.%Y}",
            "Café Morgenrot",
            "Rechnung SB-1004",
            "238,00",
            "EUR",
        ],
    ]
    with open(basis / "kontoauszug.csv", "w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter=";").writerows(zeilen)

    (basis / "README.md").write_text(
        "| Datei | Was sie testet | Erwartetes Ergebnis |\n"
        "|---|---|---|\n"
        "| postfach/ | Mail-Belege und Wächter | Belege finden, Anweisungen ignorieren |\n"
        "| handy/ | Kassenbons | Texterkennung |\n"
        "| downloads/ | Dublette und unfertiger Download | Dublette melden, crdownload ignorieren |\n",
        encoding="utf-8",
    )
    for p in (postfach, handy, downloads):
        print(f"ok: {p.relative_to(basis)}/ ({len(list(p.iterdir()))})")
    return 0


# Die fünf Rechnungen der Übung, mit den Namen, unter denen Rechnungen wirklich
# ankommen. Quelle im Musterbetrieb → Name im Übungsordner.
UEBUNG_DATEIEN = {
    "downloads/hostingwerk.pdf": "invoice (3).pdf",
    "netzfunk.pdf": "Rechnung.pdf",
    "zahlfix.pdf": "receipt_1a2b3c.pdf",
    "pixelwerk.pdf": "Scan_0012.pdf",
    "handy/bon-cafe.jpg": "IMG_4471.jpg",
}


def einrichten_beispiel(ziel: Path) -> Path:
    """Legt den Übungsordner an: Eingang/ mit fünf Chaosnamen, Handy/ und Downloads/
    mit dem ganzen Musterbetrieb, und ein eigenes Übungssystem in .system/.

    Das Übungssystem hat seine eigene Konfiguration und sein eigenes Verzeichnis,
    damit Übungsbelege nie im echten Belegverzeichnis auftauchen.
    """
    quelle = pfad("beispiel", "erzeugt")
    if not quelle.exists():
        befehl(type("Args", (), {})())
    ziel = Path(ziel).expanduser()
    for name in ("Eingang", "Handy", "Downloads", "Ablage", ".system"):
        ordner = ziel / name
        if ordner.exists():
            shutil.rmtree(ordner)  # nur unser eigener Übungsordner
        ordner.mkdir(parents=True)
    for von, nach in UEBUNG_DATEIEN.items():
        shutil.copy2(quelle / von, ziel / "Eingang" / nach)
    for datei in (quelle / "handy").iterdir():
        shutil.copy2(datei, ziel / "Handy" / datei.name)
    for datei in (quelle / "downloads").iterdir():
        shutil.copy2(datei, ziel / "Downloads" / datei.name)

    system = ziel / ".system"
    shutil.copytree(pfad("konfig"), system / "konfig")
    if pfad("vorlagen").exists():
        shutil.copytree(pfad("vorlagen"), system / "vorlagen")
    toml = system / "konfig" / "belege.toml"
    text = toml.read_text(encoding="utf-8")
    text = text.replace('ordner = "~/Belege"', f'ordner = "{ziel / "Ablage"}"')
    text = text.replace('handy_ordner = "~/Belege/Eingang"', f'handy_ordner = "{ziel / "Handy"}"')
    text = text.replace('downloads = "~/Downloads"', f'downloads = "{ziel / "Downloads"}"')
    toml.write_text(text, encoding="utf-8")
    return ziel


def befehl_uebung(args) -> int:
    """`belege uebung`: der Übungsordner unter ~/Belege-Uebung, fünf Rechnungen mit Chaosnamen.

    Mit --echt ordnet Claude die fünf Rechnungen ein und legt sie mit sauberem Namen
    unter ~/Belege-Uebung/Ablage ab. Dein echtes Belegverzeichnis bleibt unberührt.
    """
    import os
    import subprocess
    import sys

    ziel = einrichten_beispiel(Path("~/Belege-Uebung").expanduser())
    eingang = sorted((ziel / "Eingang").iterdir())
    print(f"ok: Übungsordner unter {ziel}", flush=True)
    for datei in eingang:
        print(f"  Eingang/{datei.name}", flush=True)
    if not getattr(args, "echt", False):
        print("trocken: Mit --echt ordnet Claude diese fünf Rechnungen ein und benennt sie.", flush=True)
        return 0
    print("\nClaude ordnet jetzt ein, das dauert etwa eine Minute:\n", flush=True)
    umgebung = dict(os.environ, BELEGE_ROOT=str(ziel / ".system"))
    befehl_zeile = [sys.executable, "-m", "belege.cli", "ablegen", *map(str, eingang), "--echt"]
    code = subprocess.run(befehl_zeile, env=umgebung).returncode
    print(f"\nFertig. Sieh dir den Ordner an: open {ziel / 'Ablage'}")
    return code


def vorschau(args=None) -> int:
    """Rendert von jedem Beleg in beispiel/erzeugt ein PNG (erste Seite, 100 dpi)."""
    basis = pfad("beispiel", "erzeugt")
    if not basis.exists():
        befehl(type("Args", (), {})())
    ziel = basis / "vorschau"
    if ziel.exists():
        shutil.rmtree(ziel)
    ziel.mkdir(parents=True)
    dateien = sorted(
        p
        for p in basis.rglob("*")
        if p.is_file()
        and "vorschau" not in p.relative_to(basis).parts
        and "postfach" not in p.relative_to(basis).parts
    )
    for datei in dateien:
        name = datei.relative_to(basis).as_posix().replace("/", "__")
        png = ziel / f"{Path(name).stem}.png"
        if datei.suffix.lower() == ".pdf":
            with tempfile.TemporaryDirectory() as tmp:
                basis_bild = Path(tmp) / "seite"
                subprocess.run(
                    [
                        "pdftoppm",
                        "-png",
                        "-r",
                        "100",
                        "-l",
                        "1",
                        str(datei),
                        str(basis_bild),
                    ],
                    check=True,
                    capture_output=True,
                )
                seite = sorted(Path(tmp).glob("seite*.png"))[0]
                shutil.copy2(seite, png)
        elif datei.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            with Image.open(datei) as bild:
                bild = bild.convert("RGB")
                bild.thumbnail((700, 900))
                bild.save(png)
        else:
            continue
        print(f"ok: {png.relative_to(basis)}")
    return 0
