"""Einstieg für uv run belege; Fachmodule werden erst beim Aufruf geladen."""

from __future__ import annotations

import argparse
import importlib
import sys

BEFEHLE = {
    "pruefen": ("pruefen", "befehl", "Selbsttest der Einrichtung"),
    "status": ("bericht", "befehl_status", "Kurzübersicht"),
    "beispiel": ("beispiel", "befehl", "Musterbetrieb anlegen"),
    "takt": ("takt", "befehl", "Postfach, Handy und Wächter abarbeiten"),
    "tag": ("takt", "befehl_tag", "Downloads und Tagesbericht abarbeiten"),
    "postfach": ("takt", "befehl_postfach", "Nur das Postfach abarbeiten"),
    "handy": ("takt", "befehl_handy", "Nur den Handy-Ordner abarbeiten"),
    "downloads": ("takt", "befehl_downloads", "Nur Downloads abarbeiten"),
    "bericht": ("bericht", "befehl", "Tagesbericht erstellen"),
    "monat": ("monat", "befehl", "Monatsabgleich und Übergabe"),
    "anmelden": ("anmelden", "befehl", "Google-Zugang einrichten"),
    "mcp": ("mcp_server", "befehl", "Lokalen Postfach-Server starten"),
    "zeitplan": ("zeitplan", "befehl", "Zeitplan an, aus oder zeigen"),
    "verbrauch": ("urteil", "befehl_verbrauch", "Modellurteile der letzten Tage"),
    "ablegen": (
        "verarbeiten",
        "befehl_ablegen",
        "Dateien von Hand einordnen und ablegen",
    ),
    "suchen": ("postfach", "befehl_suchen", "Postfach durchsuchen"),
    "waechter": ("waechter", "befehl", "Neue Mails gegen deine Wächter-Regeln prüfen"),
    "uebung": ("beispiel", "befehl_uebung", "Übungsordner mit Musterbelegen anlegen"),
    "vergleich": ("text", "befehl_vergleich", "Datei als PDF gegen Text: was kostet mehr?"),
}


def parser() -> argparse.ArgumentParser:
    """Erstellt die gemeinsame Kommandozeilenhilfe für alle Belege-Befehle."""
    argumente = argparse.ArgumentParser(
        prog="belege", description="Deine Belege sortieren sich selbst"
    )
    argumente.add_argument("befehl", choices=sorted(BEFEHLE), metavar="befehl")
    argumente.add_argument("ziel", nargs="*", help="Datei, Suchtext oder Unterbefehl")
    argumente.add_argument(
        "--echt", action="store_true", help="Wirklich ändern oder senden"
    )
    argumente.add_argument("--konto")
    argumente.add_argument("--monat")
    argumente.add_argument("--auszug")
    argumente.add_argument("--uebergabe", action="store_true")
    argumente.add_argument("--anfragen", action="store_true")
    argumente.add_argument("--tage", type=int)
    argumente.add_argument("--rechte", choices=("lesen", "schreiben", "beides"))
    return argumente


def main(argv: list[str] | None = None) -> int:
    """Leitet einen Befehl an sein Fachmodul weiter und erklärt fehlende Teile."""
    args = parser().parse_args(argv)
    modul, funktion, _ = BEFEHLE[args.befehl]
    try:
        befehl = getattr(importlib.import_module(f"belege.{modul}"), funktion)
        return int(befehl(args) or 0)
    except ModuleNotFoundError as fehler:
        print(
            f"Dieser Befehl ist noch nicht eingerichtet: {fehler.name}. "
            "Sag deinem Claude: Installiere das fehlende Zusatzpaket oder Modul.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
