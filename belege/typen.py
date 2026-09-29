"""Die drei Typen, die zwischen den Teilen wandern. Felder siehe ARCHITEKTUR.md."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


@dataclass
class Fund:
    """Eine Datei, die ein Beleg sein könnte."""

    datei: Path
    quelle: str  # "postfach" | "handy" | "downloads" | "beispiel"
    name: str
    eingang: date
    mail: dict | None = None  # {"konto","id","von","von_name","betreff","datum"}
    verschieben: bool = False


@dataclass
class Text:
    """Ausgelesener Belegtext samt Herkunft und Seitenzahl.

    Die Metadaten machen die Qualität der Texterkennung nachvollziehbar.
    """

    text: str
    stufe: str  # Texterkennungsstufe, etwa "pdftotext", "vision" oder "leer"
    seiten: int = 0


@dataclass
class Einordnung:
    """Die geprüften Angaben, nach denen ein Fund abgelegt wird.

    Sie halten die Entscheidung und ihre Sicherheit für den weiteren Ablauf fest.
    """

    ist_beleg: bool
    art: str  # "eingang" | "ausgang" | "sonstige"
    bereich: str  # "betrieb" | "privat"
    datum: date | None
    lieferant: str
    beschreibung: str
    betrag: float | None
    waehrung: str
    sicherheit: str  # "hoch" | "mittel" | "niedrig"
    grund: str
    quelle: str  # "regel" | "urteil" | "xml" | "rueckfall"

    def als_dict(self) -> dict:
        """Gibt die Einordnung in einem JSON-tauglichen Wörterbuch zurück.

        Das Datum wird dafür als ISO-Text gespeichert.
        """
        d = asdict(self)
        d["datum"] = self.datum.isoformat() if self.datum else None
        return d
