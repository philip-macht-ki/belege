"""Ampeltest für die Belegablage."""

from __future__ import annotations
import json, os, shutil, stat, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path
from .kern import ablage_ordner, jetzt, konfig, konten, pfad

SYNC = (
    "Library/CloudStorage",
    "Mobile Documents",
    "Dropbox",
    "OneDrive",
    "Google Drive",
)


def _sync(p):
    return any(x in str(Path(p).expanduser()) for x in SYNC)


def _imap(k):
    import imaplib

    pw = os.environ.get("PASSWORT_" + str(k.get("name", "")).upper())
    if not pw:
        raise RuntimeError("Passwort fehlt in .env")
    server = (
        k.get("imap_server") or "imap." + str(k.get("adresse", "")).partition("@")[2]
    )
    p = imaplib.IMAP4_SSL(server, 993, timeout=15)
    try:
        p.login(k.get("adresse", ""), pw)
    finally:
        try:
            p.logout()
        except Exception:
            pass


def befehl(args) -> int:
    """Prüft die Voraussetzungen für die Belegablage mit einer klaren Ampel.

    Gelbe und rote Zeilen sagen kurz, was als Nächstes zu tun ist.
    """
    rot = False

    def z(f, text, hinweis=None):
        nonlocal rot
        rot |= f == "ROT"
        print(f"{f}: {text}" + (f" -> {hinweis}" if hinweis and f != "GRUEN" else ""))

    try:
        z(
            "GRUEN" if sys.version_info >= (3, 11) else "ROT",
            f"Python {sys.version.split()[0]}",
            "Python 3.11 oder neuer installieren.",
        )
    except Exception as e:
        z("ROT", f"Python nicht prüfbar: {e}")
    z(
        "GRUEN" if shutil.which("uv") else "ROT",
        "uv verfügbar" if shutil.which("uv") else "uv fehlt",
        "uv installieren: https://docs.astral.sh/uv/",
    )
    for tool in ("pdftotext", "pdftoppm"):
        z(
            "GRUEN" if shutil.which(tool) else "GELB",
            f"{tool} verfügbar" if shutil.which(tool) else f"{tool} fehlt",
            "brew install poppler, sag deinem Claude: Installiere poppler",
        )
    try:
        from .text import stufen_verfuegbar

        ok = "vision" in stufen_verfuegbar()
        z(
            "GRUEN" if ok else "GELB",
            "Apple Vision verfügbar" if ok else "Apple Vision nicht verfügbar",
            "Nur auf macOS verfügbar; sonst wird eine andere Texterkennung genutzt.",
        )
    except Exception as e:
        z(
            "GELB",
            f"Apple Vision nicht verfügbar: {e}",
            "Nur auf macOS verfügbar; sonst wird eine andere Texterkennung genutzt.",
        )
    try:
        backend = os.environ.get(
            "URTEIL_BACKEND",
            konfig("belege").get("urteil", {}).get("backend", "claude"),
        )
        ok = backend != "claude" or bool(shutil.which("claude"))
        z(
            "GRUEN" if ok else "ROT",
            f"Urteil {backend} verfügbar" if ok else "Claude fehlt",
            "Claude Code installieren oder Urteil-Backend ändern.",
        )
    except Exception as e:
        z("ROT", f"Urteil nicht prüfbar: {e}")
    try:
        cfg = konfig("belege")
        name = cfg.get("betrieb", {}).get("name")
        z(
            "GELB" if name == "Studio Beispiel" else "GRUEN",
            "Betrieb: noch Musterwerte"
            if name == "Studio Beispiel"
            else "Betrieb eingetragen",
            "Namen und USt-IdNr. in konfig/belege.toml eintragen.",
        )
        z(
            "GRUEN" if cfg.get("konto") else "ROT",
            "Mindestens ein Postfach eingetragen"
            if cfg.get("konto")
            else "Kein Postfach eingetragen",
            "In konfig/belege.toml einen [[konto]]-Block eintragen.",
        )
    except Exception as e:
        z("ROT", f"Konfiguration fehlerhaft: {e}")
    try:
        a = ablage_ordner()
        if not a.exists():
            raise RuntimeError("Ordner fehlt")
        probe = a / ".belege-schreibtest"
        probe.touch()
        probe.unlink()
        z("GRUEN", "Ablageordner vorhanden und beschreibbar")
        z(
            "GRUEN" if _sync(a) else "GELB",
            "Ablage wird in die Cloud gesichert"
            if _sync(a)
            else "Ablage wird nicht in die Cloud gesichert",
            "Ablage in einen Cloud-Ordner legen.",
        )
    except Exception as e:
        z(
            "ROT",
            f"Ablageordner nicht nutzbar: {e}",
            "Ordner anlegen und Schreibrechte prüfen.",
        )
    z(
        "ROT" if _sync(pfad()) else "GRUEN",
        "Repo liegt in einem Sync-Ordner"
        if _sync(pfad())
        else "Repo liegt nicht im Sync-Ordner",
        "Repo außerhalb von iCloud, Dropbox und Drive verschieben: Sync-Konflikte zerstören Zugänge.",
    )
    try:
        for k in konten():
            name = str(k.get("name", "Postfach"))
            weg = k.get("weg")
            if weg == "a":
                try:
                    _imap(k)
                    z("GRUEN", f"Postfach {name}: Anmeldung klappt")
                except Exception as e:
                    z(
                        "ROT",
                        f"Postfach {name}: Anmeldung fehlgeschlagen",
                        f"Anbieter, Server und App-Passwort prüfen ({e}).",
                    )
            elif weg == "b":
                g = pfad("arbeit", "geheim")
                ok = (g / f"{name}_lesen.json").exists() and (
                    g / f"{name}_schreiben.json"
                ).exists()
                if ok:
                    try:
                        from google.auth.transport.requests import Request
                        from google.oauth2.credentials import Credentials

                        zugang = g / f"{name}_lesen.json"
                        credentials = Credentials.from_authorized_user_file(str(zugang))
                        if credentials.expired and credentials.refresh_token:
                            credentials.refresh(Request(timeout=5))
                        z("GRUEN", f"Postfach {name}: Google-Zugang erneuert")
                    except Exception:
                        z(
                            "ROT",
                            f"Postfach {name}: Google-Zugang nicht erneuerbar",
                            "Google-Projekt auf In Produktion stellen und binnen 7 Tagen neu anmelden.",
                        )
                else:
                    z(
                        "ROT",
                        f"Postfach {name}: Google-Zugänge fehlen",
                        f"belege anmelden --konto {name} --rechte beides ausführen.",
                    )
            else:
                z(
                    "GELB",
                    f"Postfach {name}: Musterpostfach",
                    "Für echte Mails Weg A oder B einrichten.",
                )
    except Exception as e:
        z("ROT", f"Postfächer nicht prüfbar: {e}")
    try:
        q = konfig("belege").get("quellen", {})
        for key, label in (
            ("handy_ordner", "Handy-Ordner"),
            ("downloads", "Downloads"),
        ):
            ok = Path(q.get(key, " ")).expanduser().exists()
            z(
                "GRUEN" if ok else "GELB",
                f"{label} vorhanden" if ok else f"{label} fehlt",
                "Ordner anlegen oder Pfad in konfig/belege.toml korrigieren.",
            )
    except Exception as e:
        z("GELB", f"Quellen nicht prüfbar: {e}")
    try:
        cfg = konfig("belege")
        ue = cfg.get("uebergabe", {})
        adr = ue.get("adresse", "")
        erlaubt = cfg.get("senden", {}).get("erlaubt", [])
        if adr and adr not in erlaubt:
            z(
                "ROT",
                "Übergabe-Adresse ist nicht erlaubt",
                "Adresse zu [senden].erlaubt hinzufügen, sonst wird die Monatsübergabe nur Entwurf.",
            )
        elif not erlaubt:
            z("GELB", "Keine erlaubte Sendeadresse", "[senden].erlaubt ausfüllen.")
        else:
            z("GRUEN", "Sendeadressen eingetragen")
        if "sevdesk" in adr.lower():
            z(
                "GELB",
                "sevDesk-Adresse erkannt",
                "sevDesk nimmt nur Mails von deiner dort hinterlegten Adresse an.",
            )
        if "datev" in adr.lower():
            z(
                "GRUEN" if ue.get("nur_pdf_tif") else "ROT",
                "DATEV-Format gesetzt"
                if ue.get("nur_pdf_tif")
                else "DATEV-Format fehlt",
                "DATEV nimmt nur PDF/TIF, nur_pdf_tif = true setzen.",
            )
    except Exception as e:
        z("GELB", f"Senden nicht prüfbar: {e}")
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/de.belege.takt"],
            capture_output=True,
            timeout=5,
        )
        z(
            "GRUEN" if r.returncode == 0 else "GELB",
            "Zeitplan geladen" if r.returncode == 0 else "Zeitplan nicht geladen",
            "belege zeitplan an ausführen.",
        )
    except Exception as e:
        z("GELB", f"Zeitplan nicht prüfbar: {e}", "belege zeitplan an ausführen.")
    try:
        env = pfad(".env")
        z(
            "GELB"
            if env.exists() and stat.S_IMODE(env.stat().st_mode) != 0o600
            else "GRUEN",
            ".env hat nicht die Rechte 600"
            if env.exists() and stat.S_IMODE(env.stat().st_mode) != 0o600
            else ".env-Dateirechte in Ordnung",
            "chmod 600 .env ausführen.",
        )
    except Exception as e:
        z("GELB", f".env-Rechte nicht prüfbar: {e}")
    try:
        neueste = None
        for f in pfad("arbeit", "ereignisse").glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                if "takt" in e.get("text", "").lower():
                    neueste = max(
                        neueste or datetime.min.replace(tzinfo=jetzt().tzinfo),
                        datetime.fromisoformat(e["zeit"]),
                    )
        if neueste and jetzt() - neueste > timedelta(hours=2):
            z(
                "GELB",
                "Letzter Takt-Lauf ist älter als zwei Stunden",
                "Zeitplan und Protokoll prüfen.",
            )
        elif neueste:
            z("GRUEN", "Letzter Takt-Lauf aktuell")
    except Exception as e:
        z("GELB", f"Letzten Takt-Lauf nicht prüfbar: {e}")
    return int(rot)
