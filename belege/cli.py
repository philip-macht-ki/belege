"""Einstieg für uv run belege; Fachmodule werden erst beim Aufruf geladen."""

from __future__ import annotations

import argparse
import importlib
import sys

BEFEHLE = {
    "pruefen": ("pruefen", "befehl", "Selbsttest der Einrichtung"),
    "pruefung": ("pruefung", "befehl", "Eine Rechnung trocken auf Pflichtangaben prüfen"),
    "fehlerbericht": ("fehlerbericht", "befehl", "Geschwärzten Diagnosebericht erstellen"),
    "status": ("bericht", "befehl_status", "Kurzübersicht"),
    "beispiel": ("beispiel", "befehl", "Musterbetrieb anlegen"),
    "takt": ("takt", "befehl", "Postfach, Handy und Wächter abarbeiten"),
    "rechner": ("rechner", "befehl", "Zeigen, welcher Mac das ist (MacBook oder Dauerrechner)"),
    "tag": ("takt", "befehl_tag", "Downloads und Tagesbericht abarbeiten"),
    "postfach": ("takt", "befehl_postfach", "Nur das Postfach abarbeiten"),
    "handy": ("takt", "befehl_handy", "Nur den Handy-Ordner abarbeiten"),
    "downloads": ("takt", "befehl_downloads", "Nur Downloads abarbeiten"),
    "bericht": ("bericht", "befehl", "Tagesbericht erstellen"),
    "monat": ("monat", "befehl", "Monatsabgleich und Übergabe"),
    "posten": ("posten", "befehl", "Offene Posten und Rückfragen"),
    "moneymoney": ("moneymoney", "befehl", "Optional: Kontoumsätze aus MoneyMoney als CSV holen"),
    "anmelden": ("anmelden", "befehl", "Postfach-Zugang einrichten (App-Passwort, Google, Microsoft)"),
    "einrichten-claude": ("einrichten", "befehl", "Claude-Starter für den Zeitplan einrichten"),
    "einrichten-urteil": ("einrichten", "befehl_urteil", "Starter für das eingestellte Urteil einrichten"),
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
    "jahr": ("jahr", "befehl", "Jahresabgleich, Lücken und Paket für den Steuerberater"),
    "dokumente": ("dokumente", "befehl", "Verträge, Versicherungen und Briefe einordnen und ablegen"),
    "fristen": ("dokumente", "befehl_fristen", "Fristen aus Verträgen zeigen und für den Kalender ausgeben"),
    "notfall": ("notfall", "befehl", "Notfallordner erstellen"),
    "aktualisieren": ("update", "befehl", "Verbesserungen sicher einspielen"),
}


# Befehle, die mit --echt ablegen, verschieben oder senden. Sie laufen nur auf dem
# Rechner aus [rechner] erlaubt.
OHNE_WARTEN = {"takt", "postfach", "handy", "downloads"}
SCHREIBEND = {"takt", "tag", "postfach", "handy", "downloads", "monat", "moneymoney", "ablegen", "dokumente", "jahr", "posten", "pruefung"}


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
    argumente.add_argument("--testordner", metavar="PFAD", help="MoneyMoney: alle CSVs in diesen Ordner statt in den Auszugsordner")
    argumente.add_argument("--uebergabe", action="store_true")
    argumente.add_argument("--anfragen", action="store_true")
    argumente.add_argument("--zwischenstand", action="store_true")
    argumente.add_argument("--mail", action="store_true")
    argumente.add_argument("--antworten", action="store_true")
    argumente.add_argument("--tage", type=int)
    argumente.add_argument("--monate", type=int, default=3)
    argumente.add_argument("--vorschau", metavar="DATEI")
    argumente.add_argument("--rechte", choices=("lesen", "schreiben", "beides"))
    argumente.add_argument("--schluesselbund", metavar="NAME", help="App-Passwort verdeckt im macOS-Schlüsselbund speichern")
    argumente.add_argument("--microsoft", metavar="NAME", help="Microsoft-Postfach im Browser anmelden")
    argumente.add_argument("--jahr")
    argumente.add_argument("--paket", action="store_true")
    argumente.add_argument("--automatisch", action="store_true", help="Nur Updates ohne eigenen Schritt einspielen")
    return argumente


def main(argv: list[str] | None = None) -> int:
    """Leitet einen Befehl an sein Fachmodul weiter und erklärt fehlende Teile."""
    args = parser().parse_args(argv)
    modul, funktion, _ = BEFEHLE[args.befehl]
    # `belege pruefung <datei>` bleibt trocken; nur die Aufräumliste sendet.
    schreibend = args.befehl in SCHREIBEND and args.echt and (args.befehl != "pruefung" or args.ziel[:1] == ["aufraeumen"])
    if schreibend:
        from .kern import fremder_rechner, log, rechner

        erlaubt = fremder_rechner()
        if erlaubt:
            log(f"nichts: Rechner-Sperre. Dieser Rechner heißt {rechner()}, ablegen darf nur {erlaubt}.")
            return 0
    try:
        befehl = getattr(importlib.import_module(f"belege.{modul}"), funktion)
        if schreibend:
            from .kern import Gesamtsperre

            # Beim Aufwachen starten mehrere Zeitpläne zugleich. Sie laufen nacheinander;
            # der 15-Minuten-Takt wartet nicht, er kommt ohnehin gleich wieder.
            warten = 0 if args.befehl in OHNE_WARTEN else 30 * 60
            with Gesamtsperre(warten) as frei:
                if not frei:
                    print(f"nichts: {args.befehl} übersprungen, ein anderer Lauf ist noch aktiv.")
                    return 0
                return int(befehl(args) or 0)
        return int(befehl(args) or 0)
    except ModuleNotFoundError as fehler:
        print(
            f"Dieser Befehl ist noch nicht eingerichtet: {fehler.name}. "
            "Sag deinem Claude: Installiere das fehlende Zusatzpaket oder Modul.",
            file=sys.stderr,
        )
        return 2
    except Exception as fehler:  # Jeder Befehl hinterlässt einen sichtbaren Befund.
        from .kern import ereignis
        ereignis("fehler", f"{args.befehl}: {fehler}")
        print(f"fehler: {args.befehl}: {fehler}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
