"""`belege erkennen <adresse>`: Wo liegt das Postfach, welcher Weg passt?

„Ich habe Outlook“ sagt nichts darüber, wo ein Postfach liegt. Outlook ist oft nur
das Programm, das Postfach liegt bei einem Hoster und geht mit Passwort (Weg A).
Dieser Befehl schaut auf die Adresse und den MX-Eintrag und sagt in wenigen
Zeilen: Art, Weg, Server und den nächsten Befehl. Er meldet sich nirgends an und
ändert nichts.
"""

from __future__ import annotations

import socket
import ssl

from . import postfach

# Lesbare Namen zu den Kennungen in postfach.HOSTER_NACH_MX.
HOSTER_NAMEN = {
    "google.com": "Google Workspace",
    "googlemail.com": "Google Workspace",
    "ionos.": "IONOS",
    "kundenserver.de": "IONOS",
    "rzone.de": "Strato",
    "udag.de": "united-domains",
    "kasserver.com": "all-inkl",
    "your-server.de": "Hetzner",
    "mailbox.org": "mailbox.org",
    "posteo.de": "Posteo",
    "icloud.com": "iCloud (eigene Domain)",
    "kabsi.at": "Kabelplus",
    "a1.net": "A1",
    "mymagenta.at": "Magenta",
    "ispgateway.de": "domainfactory",
    "agenturserver.de": "Mittwald",
    "1blu.de": "1blu",
}

BEKANNTE_NAMEN = {
    "gmail.com": "Gmail",
    "googlemail.com": "Gmail",
    "gmx.de": "GMX",
    "gmx.net": "GMX",
    "web.de": "web.de",
    "t-online.de": "T-Online",
    "icloud.com": "iCloud",
    "me.com": "iCloud",
    "mac.com": "iCloud",
    "mailbox.org": "mailbox.org",
    "freenet.de": "freenet",
    "posteo.de": "Posteo",
    "posteo.net": "Posteo",
}

PASSWORT_HINWEIS = {
    "Gmail": "Braucht ein App-Passwort: myaccount.google.com/apppasswords (vorher Bestätigung in zwei Schritten).",
    "Google Workspace": "Braucht ein App-Passwort; der Admin muss App-Passwörter erlauben.",
    "GMX": "In den Mail-Einstellungen zuerst IMAP einschalten, dann App-Passwort anlegen.",
    "web.de": "In den Mail-Einstellungen zuerst IMAP einschalten, dann App-Passwort anlegen.",
    "T-Online": "Im E-Mail-Center ein Passwort für E-Mail-Programme anlegen.",
    "iCloud": "Braucht ein app-spezifisches Passwort: account.apple.com, Anmelden und Sicherheit.",
    "Kabelplus": "Normales Mailpasswort. Anmeldename ist die Mailboxnummer (etwa x1234a00), nicht die Adresse: beim Postfach als benutzer eintragen. Sie steht im E-Mailmanager unter „Einstellungen für Mail-Client“.",
    "Mittwald": "Normales Mailpasswort. Anmeldename ist der Postfachname (etwa p123456p1), nicht die Adresse: beim Postfach als benutzer eintragen.",
    "1blu": "Normales Mailpasswort. Anmeldename ist der Postfachname, nicht die Adresse: beim Postfach als benutzer eintragen.",
}


def _imap_antwortet(host: str, port: int = 993) -> bool:
    """Grüßt dort ein IMAP-Server über TLS? Meldet sich nicht an."""
    try:
        with socket.create_connection((host, port), timeout=5) as roh:
            with ssl.create_default_context().wrap_socket(roh, server_hostname=host) as tls:
                return tls.recv(200).startswith(b"* OK")
    except (OSError, ssl.SSLError, UnicodeError):
        return False


def _smtp_antwortet(host: str) -> str:
    """Erst 465 (TLS), dann 587. Gibt host:port zurück oder ""."""
    try:
        with socket.create_connection((host, 465), timeout=5) as roh:
            with ssl.create_default_context().wrap_socket(roh, server_hostname=host) as tls:
                if tls.recv(200).startswith(b"220"):
                    return f"{host}:465"
    except (OSError, ssl.SSLError, UnicodeError):
        pass
    try:
        with socket.create_connection((host, 587), timeout=5) as roh:
            if roh.recv(200).startswith(b"220"):
                return f"{host}:587"
    except (OSError, UnicodeError):
        pass
    return ""


def _ausprobieren(domain: str, mx_liste: list[str]) -> tuple[str, str]:
    """Übliche Servernamen der Domain und des MX-Hosters ausprobieren."""
    basen = [domain]
    if mx_liste:
        basis = ".".join(mx_liste[0].split(".")[-2:])
        if basis not in basen:
            basen.append(basis)
    imap = next(
        (f"{h}:993" for b in basen for h in (f"imap.{b}", f"mail.{b}") if _imap_antwortet(h)),
        "",
    )
    smtp = ""
    if imap:
        for b in basen:
            for h in (f"smtp.{b}", f"mail.{b}"):
                smtp = _smtp_antwortet(h)
                if smtp:
                    break
            if smtp:
                break
    return imap, smtp


def erkennen(adresse: str, ausprobieren: bool = True) -> dict:
    """Art, Weg, Server und nächster Schritt zu einer Mailadresse."""
    adresse = adresse.strip().lower()
    domain = adresse.rsplit("@", 1)[-1] if "@" in adresse else ""
    labels = domain.split(".")
    if len(labels) < 2 or not all(labels) or any(" " in x for x in labels):
        raise ValueError(f"{adresse!r} ist keine Mailadresse.")
    ergebnis = {"adresse": adresse, "art": "", "weg": "", "imap_server": "", "smtp_server": "", "hinweis": "", "sicher": True}

    from .microsoft import _privat

    if _privat(adresse):
        ergebnis.update(
            art="Microsoft, privates Konto (Outlook.com)",
            weg="microsoft",
            hinweis="Kein Passwort für belege. Einmal im Browser anmelden und selbst zustimmen, einen Admin gibt es nicht.",
        )
        return ergebnis

    if domain in BEKANNTE_NAMEN:
        name = BEKANNTE_NAMEN[domain]
        imap, smtp = postfach._server(domain, {})
        ergebnis.update(
            art=name, weg="a", imap_server=f"{imap[0]}:{imap[1]}", smtp_server=f"{smtp[0]}:{smtp[1]}",
            hinweis=PASSWORT_HINWEIS.get(name, "Normales Mailpasswort oder App-Passwort des Anbieters."),
        )
        return ergebnis

    if not postfach._namensaufloesung_da():
        raise RuntimeError("Gerade keine Internetverbindung, bitte gleich noch einmal.")
    mx_liste = postfach._mx(domain)
    if any(mx.endswith(("protection.outlook.com", "outlook.com")) for mx in mx_liste):
        ergebnis.update(
            art="Microsoft 365 (Firmenpostfach)",
            weg="microsoft",
            hinweis=(
                "Kein Passwort für belege. Einmal im Browser anmelden. Ein Admin der Firma "
                "setzt dabei einmal den Haken „Im Namen Ihrer Organisation zustimmen“; "
                "Selbstständige sind meist selbst Admin. Sonst gibt "
                "`belege anmelden --microsoft <name> --admin-link` einen Link für den Admin."
            ),
        )
        return ergebnis

    for mx in mx_liste:
        for kennung, imap, smtp in postfach.HOSTER_NACH_MX:
            if postfach.hoster_passt(mx, kennung):
                name = HOSTER_NAMEN.get(kennung, kennung)
                ergebnis.update(
                    art=f"eigene Domain bei {name}", weg="a",
                    imap_server=imap.replace("{mx}", mx), smtp_server=smtp.replace("{mx}", mx),
                    hinweis=PASSWORT_HINWEIS.get(name, "Normales Mailpasswort, Anmeldename ist meist die volle Mailadresse."),
                )
                return ergebnis

    imap, smtp = postfach._ispdb(domain)
    if not (imap and smtp) and mx_liste:
        imap, smtp = postfach._ispdb(".".join(mx_liste[0].split(".")[-2:]))
    if imap and smtp:
        ergebnis.update(
            art="eigene Domain (Server aus der Thunderbird-Anbieterliste)", weg="a",
            imap_server=imap, smtp_server=smtp,
            hinweis="Normales Mailpasswort, Anmeldename ist meist die volle Mailadresse.",
        )
        return ergebnis

    if ausprobieren:
        imap, smtp = _ausprobieren(domain, mx_liste)
        if imap and smtp:
            ergebnis.update(
                art="eigene Domain (Server durch Ausprobieren gefunden)", weg="a",
                imap_server=imap, smtp_server=smtp, sicher=False,
                hinweis=(
                    "Die Server antworten, sind aber nur ausprobiert. In der Hilfe des Anbieters "
                    "gegenprüfen und danach mit `belege pruefen` bestätigen."
                ),
            )
            return ergebnis

    ergebnis.update(
        art="unbekannt" + (f" (MX {mx_liste[0]})" if mx_liste else " (kein MX-Eintrag)"),
        weg="a", sicher=False,
        hinweis=(
            "Den Anbieter fragen oder in seiner Hilfe unter IMAP nachschlagen und beim Postfach "
            "imap_server und smtp_server mit Port eintragen."
        ),
    )
    return ergebnis


def naechster_schritt(ergebnis: dict, name: str = "<name>") -> str:
    if ergebnis["weg"] == "microsoft":
        return f'weg = "microsoft" beim Postfach eintragen, dann: uv run belege anmelden --microsoft {name}'
    if ergebnis["imap_server"]:
        # Bekannte und erkannte Server findet belege selbst; nur ausprobierte eintragen.
        server = ""
        if not ergebnis["sicher"]:
            server = f' (imap_server = "{ergebnis["imap_server"]}", smtp_server = "{ergebnis["smtp_server"]}" eintragen)'
        return f'weg = "a" beim Postfach{server}, dann Passwort speichern: uv run belege anmelden --schluesselbund {name}'
    return "Server beim Anbieter nachschlagen und eintragen, dann uv run belege pruefen"


def befehl(args) -> int:
    ziel = list(getattr(args, "ziel", []) or [])
    if not ziel:
        print("Aufruf: uv run belege erkennen <mailadresse>")
        return 2
    try:
        ergebnis = erkennen(ziel[0])
    except (ValueError, RuntimeError) as fehler:
        print(f"fehler: {fehler}")
        return 2
    name = getattr(args, "konto", None) or "<name>"
    print(f"Postfach: {ergebnis['adresse']}")
    print(f"Liegt bei: {ergebnis['art']}")
    weg = {"microsoft": "Weg Microsoft (Anmeldung im Browser)", "a": "Weg A (IMAP mit Passwort)"}[ergebnis["weg"]]
    print(f"Weg: {weg}")
    if ergebnis["imap_server"]:
        print(f"Server: {ergebnis['imap_server']} (IMAP), {ergebnis['smtp_server']} (SMTP)")
    print(f"Hinweis: {ergebnis['hinweis']}")
    print(f"Nächster Schritt: {naechster_schritt(ergebnis, name)}")
    return 0
