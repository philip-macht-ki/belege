"""Fünf erfundene Musterdokumente für `belege dokumente` (Modul bh8).

Alle Firmen, Namen und Zahlen sind frei erfunden. Die Texte sind absichtlich so
geschrieben, dass ein Modell (oder ein Mensch) Art, Gegenüber, Titel und
Fristen eindeutig herauslesen kann, ohne selbst etwas ausrechnen zu müssen:
Laufzeitende und Kündigungsfrist stehen als zwei getrennte, klare Sätze da.
"""
from __future__ import annotations

from pathlib import Path

from .beispiel import _pdf_dokument


def dokumente_beispiel(ziel: Path) -> list[Path]:
    """Erzeugt die fünf Musterdokumente unter ``ziel`` und gibt ihre Pfade zurück."""
    ziel = Path(ziel).expanduser()
    ziel.mkdir(parents=True, exist_ok=True)
    dateien: list[Path] = []

    def schreibe(name: str, titel: str, absatz: str, zeilen: list[str]) -> None:
        pfad = ziel / name
        _pdf_dokument(pfad, titel, absatz, zeilen)
        dateien.append(pfad)

    schreibe(
        "mietvertrag-buero.pdf",
        "Mietvertrag über Geschäftsräume",
        "Zwischen Hausverwaltung Beispiel, Rathausplatz 2, 40213 Düsseldorf "
        "(Vermieter) und Studio Beispiel, Musterstraße 1, 12345 Musterstadt "
        "(Mieter) wird folgender Mietvertrag über Büroräume geschlossen.",
        [
            "§ 1 Mietobjekt: Vermietet werden Büroräume im Erdgeschoss, "
            "Musterstraße 1, 12345 Musterstadt.",
            "§ 2 Mietzeit: Das Mietverhältnis beginnt am 01.01.2024 und "
            "läuft bis zum 31.12.2027.",
            "§ 3 Kündigung: Eine ordentliche Kündigung ist mit einer Frist "
            "von 3 Monaten zum Ende der Laufzeit möglich.",
            "§ 4 Miete: Die monatliche Miete beträgt 850,00 EUR zzgl. Nebenkosten.",
            "",
            "Musterstadt, den 15.01.2024",
        ],
    )

    schreibe(
        "handyvertrag.pdf",
        "Mobilfunkvertrag Business Flat M",
        "Anbieter: Netzfunk Mobil, Fernmeldeweg 9, 50667 Köln. "
        "Kunde: Studio Beispiel, Musterstraße 1, 12345 Musterstadt.",
        [
            "Tarif: Business Flat M, monatlicher Grundpreis 24,90 EUR.",
            "Mindestlaufzeit: Der Vertrag läuft bis zum 14.03.2027.",
            "Kündigungsfrist: Die Kündigungsfrist beträgt 1 Monat zum "
            "Ende der Laufzeit.",
            "",
            "Köln, den 14.03.2025",
        ],
    )

    schreibe(
        "berufshaftpflicht-versicherungsschein.pdf",
        "Versicherungsschein Berufshaftpflicht",
        "Versicherer: Assekuranz Beispiel AG, Policenweg 4, 80331 München. "
        "Versicherungsnehmer: Studio Beispiel. Schein-Nr. VS-2024-77123.",
        [
            "Versicherungsbeginn: 01.01.2024.",
            "Hauptfälligkeit: jeweils zum 01.01., die Versicherung "
            "verlängert sich jährlich um ein weiteres Jahr, wenn nicht "
            "gekündigt wird.",
            "Kündigung: Der Vertrag kann mit einer Frist von 3 Monaten "
            "vor Ablauf gekündigt werden.",
            "Jahresbeitrag: 312,00 EUR.",
            "",
            "München, den 20.12.2023",
        ],
    )

    schreibe(
        "finanzamt-vorauszahlungsbescheid.pdf",
        "Vorauszahlungsbescheid zur Einkommensteuer",
        "Finanzamt Beispiel, Amtsstraße 1, 12345 Musterstadt. "
        "Steuernummer 000/000/00000, Studio Beispiel.",
        [
            "Für das Jahr 2026 setzen wir folgende Vorauszahlung fest.",
            "Die Vorauszahlung in Höhe von 640,00 EUR ist am 10.12.2026 fällig.",
            "Bitte überweisen Sie den Betrag fristgerecht auf das "
            "angegebene Konto.",
            "",
            "Musterstadt, den 10.11.2026",
        ],
    )

    schreibe(
        "rechnung-pixelwerk.pdf",
        "Rechnung",
        "Pixelwerk Software GmbH, Rechnungsnummer PW-2077, "
        "Rechnungsdatum 05.09.2026. An: Studio Beispiel, "
        "Musterstraße 1, 12345 Musterstadt.",
        [
            "Pos. 1  Software-Abo Studio Pro (Monat)   50,00 EUR",
            "",
            "Gesamtbetrag: 50,00 EUR",
            "Zahlbar innerhalb von 14 Tagen.",
        ],
    )

    return dateien
