"""Weg B: einmalige Anmeldung beim eigenen Google-Projekt.

Legt zwei getrennte Zugänge an: `<konto>_lesen.json` (Mails lesen, Labels
setzen) und `<konto>_schreiben.json` (Entwürfe, Senden). Getrennt, damit
ein späterer Rechtewechsel beim Schreiben den laufenden Lesezugang nicht
ungültig macht. Anleitung: einrichten_weg_b.md.
"""
from __future__ import annotations

import os

from . import kern

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


def befehl(args) -> int:
    """`belege anmelden --konto <name> [--rechte lesen|schreiben|beides]`."""
    name = getattr(args, "konto", None) or kern.konto()["name"]
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
