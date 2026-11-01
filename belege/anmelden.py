"""Weg B: einmalige Anmeldung beim eigenen Google-Projekt.

Legt zwei getrennte Zugänge an: `<konto>_lesen.json` (Mails lesen, Labels
setzen) und `<konto>_schreiben.json` (Entwürfe, Senden). Getrennt, damit
ein späterer Rechtewechsel beim Schreiben den laufenden Lesezugang nicht
ungültig macht. Anleitung: einrichten_weg_b.md.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import kern
from .plattform import ist_windows

RECHTE = {
    "lesen": ["https://www.googleapis.com/auth/gmail.modify"],
    "schreiben": ["https://www.googleapis.com/auth/gmail.compose"],
}

OHNE_CLIENT = """Die Datei arbeit/geheim/google_client.json fehlt.
Das ist der Schlüssel deines eigenen Google-Projekts. So kommt er dorthin:
1. In der Google Cloud Console ein Projekt anlegen und die Gmail-API einschalten.
2. Unter "Google Auth Platform" einen Client vom Typ "Desktop-App" erstellen.
3. Dessen JSON herunterladen.
4. Sag deinem Claude: Leg die Google-Client-Datei aus meinen Downloads für Weg B ab.
Die ganze Anleitung steht in einrichten_weg_b.md."""


def _schluesselbund(name: str) -> int:
    """Fragt ein App-Passwort verdeckt ab und gibt es direkt an security weiter.

    macOS `security` akzeptiert das Passwort nur als Argument von `-w`; es ist
    deshalb für die sehr kurze Laufzeit dieses Unterprozesses lokal sichtbar.
    Es wird nicht ausgegeben, geloggt oder in einer Datei abgelegt.
    """
    if ist_windows():
        return _windows_passwort(name)
    konto = kern.konto(name)
    adresse = konto.get("adresse", name)
    script = '''tell application "System Events" to activate
display dialog "App-Passwort für %s einfügen" default answer "" with hidden answer buttons {"Abbrechen", "Speichern"} default button "Speichern" cancel button "Abbrechen"''' % adresse.replace('"', "\\\"")
    try:
        dialog = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as fehler:
        print(f"fehler: Schlüsselbund-Dialog nicht geöffnet: {fehler}")
        return 1
    if dialog.returncode:
        print("nichts: App-Passwort-Eingabe abgebrochen.")
        return 0
    antwort = dialog.stdout.rsplit("text returned:", 1)[-1].strip()
    if not antwort:
        print("nichts: Kein App-Passwort eingegeben.")
        return 0
    try:
        gespeichert = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", "belege-postfach", "-a", name, "-w", antwort],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as fehler:
        print(f"fehler: App-Passwort nicht im Schlüsselbund gespeichert: {fehler}")
        return 1
    if gespeichert.returncode:
        print("fehler: App-Passwort nicht im Schlüsselbund gespeichert.")
        return 1
    print(f"ok: App-Passwort für {adresse} im Schlüsselbund gespeichert.")
    return 0


def _windows_passwort(name: str) -> int:
    """Speichert das Passwort DPAPI-verschlüsselt für den angemeldeten Windows-Nutzer."""
    konto = kern.konto(name)
    adresse = konto.get("adresse", name)
    ziel = kern.pfad("arbeit", "geheim", f"{name}_app_passwort.txt")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # Das Kennwort wird nur über die Pipe gelesen; weder Script noch Ausgabe enthalten es.
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "$p=[Microsoft.VisualBasic.Interaction]::InputBox('App-Passwort einfügen', 'Belege'); "
        "if($p){$p | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $args[0] -NoNewline; exit 0}; exit 1"
    )
    try:
        dialog = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script, "--", str(ziel)], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as fehler:
        print(f"fehler: Passwort-Dialog nicht geöffnet: {fehler}")
        return 1
    if dialog.returncode:
        print("nichts: App-Passwort-Eingabe abgebrochen.")
        return 0
    print(f"ok: App-Passwort für {adresse} geschützt für diesen Windows-Benutzer gespeichert.")
    return 0


def befehl(args) -> int:
    """`belege anmelden --konto <name> [--rechte lesen|schreiben|beides]`."""
    name = getattr(args, "konto", None) or kern.konto()["name"]
    if getattr(args, "microsoft", None):
        from .microsoft import anmelden

        return anmelden(kern.konto(args.microsoft))
    if getattr(args, "schluesselbund", None):
        return _schluesselbund(getattr(args, "schluesselbund"))
    rechte = getattr(args, "rechte", None) or "beides"
    geheim = kern.pfad("arbeit", "geheim")
    client = geheim / "google_client.json"
    if not client.exists():
        print(OHNE_CLIENT)
        return 2

    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    geheim.mkdir(parents=True, exist_ok=True)
    os.chmod(geheim, 0o700)
    arten = ["lesen", "schreiben"] if rechte == "beides" else [rechte]

    adresse = ""
    for art in arten:
        print(f"Im Browser öffnet sich jetzt die Google-Anmeldung für: {art}.")
        ablauf = InstalledAppFlow.from_client_secrets_file(str(client), RECHTE[art])
        zugang = ablauf.run_local_server(port=0, prompt="consent", access_type="offline")
        datei = geheim / f"{name}_{art}.json"
        datei.write_text(zugang.to_json(), encoding="utf-8")
        os.chmod(datei, 0o600)
        if art == "lesen":
            gmail = build("gmail", "v1", credentials=zugang, cache_discovery=False)
            adresse = gmail.users().getProfile(userId="me").execute().get("emailAddress", "")

    print(f"ok: Google-Zugang für {adresse or name} gespeichert ({', '.join(arten)}).")
    print(
        "Wichtig: Steht dein Google-Projekt noch auf 'Test', läuft der Zugang nach 7 Tagen ab. "
        "Stell es unter 'Zielgruppe' auf 'In Produktion'."
    )
    return 0
