"""Postfächer über App-Passwort, Gmail oder lokale .eml-Dateien."""

from __future__ import annotations

import base64
import email
import html
import imaplib
import os
import re
import smtplib
import subprocess
import urllib.parse
from datetime import date
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import kern

ANMELDE_HINWEIS = (
    "Anmeldung abgelehnt. Häufigste Ursachen: App-Passwort falsch kopiert, IMAP im "
    "Webmailer nicht eingeschaltet (GMX/web.de), bei Google Workspace hat der Admin "
    "App-Passwörter gesperrt."
)


def schluesselbund_passwort(name: str) -> str | None:
    """Liest ein App-Passwort intern aus dem macOS-Schlüsselbund.

    `security -w` schreibt das Geheimnis nur in den von uns aufgefangenen
    Standardausgang. Es wird weder protokolliert noch an Aufrufer ausgegeben.
    """
    try:
        ergebnis = subprocess.run(
            ["security", "find-generic-password", "-s", "belege-postfach", "-a", name, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return ergebnis.stdout.rstrip("\n") if ergebnis.returncode == 0 and ergebnis.stdout else None


def passwort(name: str) -> str | None:
    """Nimmt den Schlüsselbund zuerst, die bisherige Umgebungsvariable als Rückfall."""
    return schluesselbund_passwort(name) or os.environ.get("PASSWORT_" + name.upper())


def _text(wert: str | None) -> str:
    """Dekodiert einen Mail-Kopf in lesbaren Unicode-Text."""
    return str(make_header(decode_header(wert or "")))


def _datum(nachricht) -> str:
    """Liest das Maildatum und nutzt heute, wenn der Kopf fehlt oder defekt ist."""
    try:
        return parsedate_to_datetime(nachricht.get("Date")).date().isoformat()
    except (IndexError, TypeError, ValueError):
        return date.today().isoformat()


def _kopf(nachricht, ident: str) -> dict:
    """Baut die einheitlichen Kopfdaten einer Nachricht auf."""
    von_name, von = email.utils.parseaddr(_text(nachricht.get("From")))
    anhaenge = [
        _text(teil.get_filename())
        for teil in nachricht.walk()
        if teil.get_content_disposition() == "attachment" and teil.get_filename()
    ]
    return {
        "id": ident,
        "von": von,
        "von_name": von_name,
        "an": _text(nachricht.get("To")),
        "betreff": _text(nachricht.get("Subject")),
        "datum": _datum(nachricht),
        "anhaenge": anhaenge,
    }


def _inhalt(nachricht) -> str:
    """Liest Klartext einer Mail, bei Bedarf als bereinigten HTML-Text."""
    teile = [
        teil
        for teil in nachricht.walk()
        if teil.get_content_type() == "text/plain" and not teil.is_multipart()
    ]
    if not teile:
        teile = [
            teil
            for teil in nachricht.walk()
            if teil.get_content_type() == "text/html" and not teil.is_multipart()
        ]
    if not teile:
        return ""
    teil = teile[0]
    try:
        wert = teil.get_content()
    except (AttributeError, LookupError, UnicodeError):
        wert = (teil.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if teil.get_content_type() == "text/html":
        wert = html.unescape(re.sub(r"<[^>]+>", " ", wert))
    return re.sub(r"[ \t]+", " ", wert).strip()[:20_000]


_URL = re.compile(r"https://[^\s\"'<>()\[\]{}]+", re.IGNORECASE)


def _links(nachricht) -> list[str]:
    """Sammelt https-Links aus Text- und HTML-Teilen, eindeutig, höchstens 50.

    Nur gelesen, nie geöffnet: Was mit einem Link geschieht, entscheidet
    ``rechnungslink.py`` nach festen Regeln, nie der Mailtext.
    """
    gefunden: list[str] = []
    for teil in nachricht.walk():
        if teil.is_multipart() or teil.get_content_type() not in {"text/plain", "text/html"}:
            continue
        if teil.get_content_disposition() == "attachment":
            continue
        try:
            wert = teil.get_content()
        except (AttributeError, LookupError, UnicodeError):
            wert = (teil.get_payload(decode=True) or b"").decode("utf-8", "replace")
        for url in _URL.findall(html.unescape(str(wert))):
            url = url.rstrip(".,;:!?")
            if url not in gefunden:
                gefunden.append(url)
            if len(gefunden) >= 50:
                return gefunden
    return gefunden


def _sicherer_name(name: str) -> str:
    """Entfernt Pfadbestandteile aus einem Anhangnamen."""
    return Path(name).name.replace("/", "_").replace("\\", "_") or "Anhang"


def _freier_pfad(ziel: Path, name: str) -> Path:
    """Gibt einen kollisionsfreien Anhangpfad mit _2, _3 und so weiter zurück."""
    basis = _sicherer_name(name)
    kandidat = ziel / basis
    nummer = 2
    while kandidat.exists():
        kandidat = ziel / f"{Path(basis).stem}_{nummer}{Path(basis).suffix}"
        nummer += 1
    return kandidat


def _nachricht(
    an: str, betreff: str, text: str, anhaenge: list[Path], von: str
) -> EmailMessage:
    """Erstellt eine versandfertige Nachricht inklusive lokaler Anhänge."""
    nachricht = EmailMessage()
    nachricht["From"] = von
    nachricht["To"] = an
    nachricht["Subject"] = betreff
    nachricht.set_content(text)
    for anhang in anhaenge:
        datei = Path(anhang)
        nachricht.add_attachment(
            datei.read_bytes(),
            maintype="application",
            subtype="octet-stream",
            filename=datei.name,
        )
    return nachricht


def _anhaenge(nachricht) -> list[dict]:
    """Liest Namen und Größen der Anhänge einer bereits geladenen Mail."""
    return [
        {
            "name": _text(teil.get_filename()),
            "groesse": len(teil.get_payload(decode=True) or b""),
        }
        for teil in nachricht.walk()
        if teil.get_content_disposition() == "attachment"
    ]


def _anhaenge_speichern(nachricht, ziel: Path) -> list[Path]:
    """Speichert Anhänge einer Nachricht mit kollisionsfreien Namen."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    gespeichert = []
    for teil in nachricht.walk():
        if teil.get_content_disposition() != "attachment":
            continue
        pfad = _freier_pfad(ziel, _text(teil.get_filename()))
        pfad.write_bytes(teil.get_payload(decode=True) or b"")
        gespeichert.append(pfad)
    return gespeichert


class Postfach:
    """Gemeinsame Schnittstelle für alle unterstützten Postfachwege."""

    def __init__(self, konto: dict):
        self.konto = konto
        self.name = konto["name"]
        self.adresse = konto.get("adresse", "")
        self.weg = konto.get("weg", "a")

    def mit_label(self, label: str) -> list[dict]:
        """Gibt Mails eines Labels zurück; andere Wege unterstützen keine Labels."""
        return []

    def label_erledigt(self, ident: str, label: str) -> None:
        """Markiert eine Mail als erledigt; andere Wege haben keine Labels."""
        return None


class OrdnerPostfach(Postfach):
    """Liest .eml-Dateien aus einem lokalen Ordner für Muster und Tests."""

    def __init__(self, konto: dict):
        super().__init__(konto)
        self.ordner = kern.erweitert(konto["ordner"])

    def _datei(self, ident: str) -> Path:
        return self.ordner / Path(ident).name

    def _alle(self):
        dateien = sorted(
            self.ordner.glob("*.eml"),
            key=lambda wert: wert.stat().st_mtime,
            reverse=True,
        )
        for datei in dateien:
            yield (
                datei,
                email.message_from_bytes(datei.read_bytes(), policy=policy.default),
            )

    def suchen(self, abfrage="", max=20, seit=None, nur_anhang=False):
        """Durchsucht lokale Beispielmails mit der einfachen Weg-A-Abfrage."""
        treffer = []
        for datei, nachricht in self._alle():
            kopf = _kopf(nachricht, datei.name)
            if not _passt(kopf, _inhalt(nachricht), abfrage, seit, nur_anhang):
                continue
            kopf["auszug"] = _inhalt(nachricht)[:300]
            treffer.append(kopf)
            if len(treffer) >= max:
                break
        return treffer

    def lesen(self, ident: str) -> dict:
        """Liest Kopf, Text und Anhanggrößen einer lokalen Mail."""
        nachricht = email.message_from_bytes(
            self._datei(ident).read_bytes(), policy=policy.default
        )
        daten = _kopf(nachricht, ident)
        daten["text"] = _inhalt(nachricht)
        daten["anhaenge"] = _anhaenge(nachricht)
        daten["links"] = _links(nachricht)
        return daten

    def anhaenge(self, ident: str, ziel: Path) -> list[Path]:
        """Speichert lokale Anhänge kollisionsfrei im gewünschten Zielordner."""
        nachricht = email.message_from_bytes(
            self._datei(ident).read_bytes(), policy=policy.default
        )
        return _anhaenge_speichern(nachricht, ziel)

    def _ablage(
        self, art: str, an: str, betreff: str, text: str, anhaenge: list[Path]
    ) -> str:
        ziel = kern.pfad(
            "arbeit", "postausgang", f"{art}-{kern.jetzt():%Y%m%d-%H%M%S-%f}.eml"
        )
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(
            _nachricht(an, betreff, text, anhaenge, self.adresse).as_bytes()
        )
        return ziel.name

    def entwurf(self, an, betreff, text, anhaenge):
        """Legt einen lokalen Entwurf ab, ohne ihn zu versenden."""
        return self._ablage("entwurf", an, betreff, text, anhaenge)

    def _senden(self, an, betreff, text, anhaenge):
        """Legt eine lokale gesendete Nachricht für Muster und Tests ab."""
        return self._ablage("gesendet", an, betreff, text, anhaenge)


def _passt(
    kopf: dict, text: str, abfrage: str, seit: date | None, nur_anhang: bool
) -> bool:
    """Prüft die einfache Suche für lokale Mails und IMAP-Metadaten."""
    suchraum = " ".join([kopf["von"], kopf["von_name"], kopf["betreff"], text]).lower()
    for wort in abfrage.split():
        if wort.startswith("von:"):
            if wort[4:].lower() not in f"{kopf['von']} {kopf['von_name']}".lower():
                return False
        elif wort.startswith("betreff:"):
            if wort[8:].lower() not in kopf["betreff"].lower():
                return False
        elif wort.startswith("seit:"):
            try:
                if date.fromisoformat(kopf["datum"]) < date.fromisoformat(wort[5:]):
                    return False
            except ValueError:
                continue
        elif wort.lower() not in suchraum:
            return False
    if seit and date.fromisoformat(kopf["datum"]) < seit:
        return False
    return not nur_anhang or bool(kopf["anhaenge"])


class ImapPostfach(Postfach):
    """Greift mit einem App-Passwort lesend und schreibend auf IMAP zu."""

    def __init__(self, konto: dict):
        super().__init__(konto)
        domain = self.adresse.rsplit("@", 1)[-1].lower()
        imap, smtp = _server(domain, konto)
        self.imap_host, self.imap_port = imap
        self.smtp_host, self.smtp_port = smtp
        self.passwort = passwort(self.name)
        if not self.passwort:
            raise RuntimeError(
                f"App-Passwort für {self.name} fehlt. Mit belege anmelden --schluesselbund {self.name} speichern."
            )

    def _imap(self):
        try:
            verbindung = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            verbindung.login(self.adresse, self.passwort)
            return verbindung
        except Exception as fehler:
            raise RuntimeError(f"{ANMELDE_HINWEIS} ({fehler})") from fehler

    def _fetch_mail(self, ident: str):
        ordner, uid = ident.rsplit(":", 1)
        verbindung = self._imap()
        try:
            verbindung.select(_imap_quote(ordner), readonly=True)
            _, daten = verbindung.uid("fetch", uid, "(BODY.PEEK[])")
        finally:
            verbindung.logout()
        return email.message_from_bytes(daten[0][1], policy=policy.default)

    def _ordner(self, flag: str, namen: list[str]) -> str:
        """Findet einen Special-Use-Ordner oder nutzt einen verständlichen Ersatznamen."""
        verbindung = self._imap()
        try:
            _, zeilen = verbindung.list()
        finally:
            verbindung.logout()
        for zeile in zeilen or []:
            text = (
                zeile.decode(errors="replace")
                if isinstance(zeile, bytes)
                else str(zeile)
            )
            if flag.lower() in text.lower():
                return text.rsplit('"', 2)[-2] if '"' in text else text.split()[-1]
        return namen[0]

    def _suche(self, verbindung, teile: list[str]):
        """Sucht mit UTF-8 und fällt bei Serverproblemen auf ASCII zurück."""
        if not teile:
            teile = ["ALL"]
        try:
            return verbindung.uid("search", "CHARSET", "UTF-8", *teile)
        except imaplib.IMAP4.error as fehler:
            ascii_teile = [teil.encode("ascii", "ignore").decode() for teil in teile]
            if ascii_teile == teile:
                raise RuntimeError(f"IMAP-Suche fehlgeschlagen: {fehler}") from fehler
            kern.log(
                "IMAP akzeptiert die Suchzeichen nicht. Suche wurde auf ASCII vereinfacht."
            )
            return verbindung.uid("search", None, *ascii_teile)

    def suchen(self, abfrage="", max=20, seit=None, nur_anhang=False):
        """Durchsucht IMAP ohne Mails als gelesen zu markieren.

        Neben INBOX auch die Ordner aus `imap_ordner` beim Konto, für Mailprogramme,
        deren Filter Rechnungen sofort in Unterordner verschieben.
        """
        verbindung = self._imap()
        # Mit nur_anhang zählt max die Treffer je Ordner; zusammen höchstens 500.
        grenze = 500 if nur_anhang else max
        try:
            treffer = []
            for ordner in _imap_ordnerliste(self.konto):
                if verbindung.select(_imap_quote(ordner), readonly=True)[0] != "OK":
                    kern.log(f"IMAP-Ordner {ordner} nicht gefunden, übersprungen.")
                    continue
                _, daten = self._suche(verbindung, _imap_kriterien(abfrage, seit))
                alle = daten[0].split() if daten and daten[0] else []
                uids = alle[-grenze:][::-1]
                gefunden = 0
                for uid in uids:
                    _, roh = verbindung.uid(
                        "fetch",
                        uid,
                        "(BODY.PEEK[HEADER] BODYSTRUCTURE BODY.PEEK[TEXT]<0.2000>)",
                    )
                    nachricht = _imap_nachricht(roh)
                    if nachricht is None:
                        continue
                    kopf = _kopf(nachricht, f"{ordner}:{uid.decode()}")
                    # Der Kopf allein kennt keine Anhänge; die stehen in BODYSTRUCTURE.
                    kopf["anhaenge"] = kopf["anhaenge"] or _imap_anhaenge(roh)
                    if nur_anhang and not kopf["anhaenge"]:
                        continue
                    kopf["auszug"] = _inhalt(nachricht)[:300]
                    treffer.append(kopf)
                    gefunden += 1
                    if gefunden >= grenze:
                        break
            treffer.sort(key=lambda kopf: kopf.get("datum", ""), reverse=True)
            return treffer[:grenze]
        finally:
            verbindung.logout()

    def lesen(self, ident: str) -> dict:
        """Liest eine IMAP-Mail vollständig, ohne ihren Gelesen-Status zu ändern."""
        nachricht = self._fetch_mail(ident)
        daten = _kopf(nachricht, ident)
        daten["text"] = _inhalt(nachricht)
        daten["anhaenge"] = _anhaenge(nachricht)
        daten["links"] = _links(nachricht)
        return daten

    def anhaenge(self, ident: str, ziel: Path) -> list[Path]:
        """Speichert die Anhänge einer IMAP-Mail kollisionsfrei."""
        return _anhaenge_speichern(self._fetch_mail(ident), ziel)

    def entwurf(self, an, betreff, text, anhaenge):
        """Legt einen Entwurf im IMAP-Entwurfsordner ab."""
        verbindung = self._imap()
        try:
            ordner = self._ordner(
                "\\Drafts", ["Entwürfe", "Drafts", "[Gmail]/Entwürfe"]
            )
            verbindung.append(
                ordner,
                "\\Draft",
                None,
                _nachricht(an, betreff, text, anhaenge, self.adresse).as_bytes(),
            )
        finally:
            verbindung.logout()
        return ordner

    def _senden(self, an, betreff, text, anhaenge):
        """Versendet eine Mail per SMTP; nur senden.py ruft diese Methode auf."""
        nachricht = _nachricht(an, betreff, text, anhaenge, self.adresse)
        if self.smtp_port == 465:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.adresse, self.passwort)
                server.send_message(nachricht)
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.adresse, self.passwort)
                server.send_message(nachricht)
        return nachricht["Message-ID"] or betreff


def _imap_nachricht(antwort):
    """Entnimmt die erste Nachrichten-Bytefolge aus einer IMAP-Fetch-Antwort."""
    for teil in antwort or []:
        if isinstance(teil, tuple) and isinstance(teil[1], bytes):
            return email.message_from_bytes(teil[1], policy=policy.default)
    return None


def _imap_ordnerliste(konto: dict) -> list[str]:
    """INBOX zuerst, dann die Zusatzordner aus `imap_ordner`, ohne Doppelte."""
    ordner = ["INBOX"]
    for name in konto.get("imap_ordner", []) or []:
        name = str(name).strip()
        if name and name not in ordner:
            ordner.append(name)
    return ordner


def _imap_quote(ordner: str) -> str:
    """Setzt Ordnernamen mit Leerzeichen oder Komma für IMAP in Anführungszeichen."""
    if ordner.startswith('"') or not re.search(r'[\s,()"\\]', ordner):
        return ordner
    return '"' + ordner.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_anhaenge(antwort) -> list[str]:
    """Liest Anhangnamen aus der BODYSTRUCTURE einer IMAP-Fetch-Antwort."""
    struktur = b" ".join(
        teil[0] if isinstance(teil, tuple) else teil
        for teil in antwort or []
        if isinstance(teil, (tuple, bytes))
    )
    namen = []
    for treffer in re.finditer(
        rb'"(?:FILENAME|NAME)\*?"\s+"((?:[^"\\]|\\.)*)"', struktur, re.IGNORECASE
    ):
        name = treffer.group(1).decode("utf-8", errors="replace")
        if "''" in name:  # RFC 2231: utf-8''Rechnung%20Nr.pdf
            name = urllib.parse.unquote(name.split("''", 1)[1])
        name = str(make_header(decode_header(name)))
        if name and name not in namen:
            namen.append(name)
    return namen


def _imap_kriterien(abfrage: str, seit: date | None) -> list[str]:
    """Übersetzt die einfache Weg-A-Suche in IMAP-Kriterien."""
    teile = []
    for wort in abfrage.split():
        if wort.startswith("von:"):
            teile.extend(["FROM", wort[4:]])
        elif wort.startswith("betreff:"):
            teile.extend(["SUBJECT", wort[8:]])
        elif wort.startswith("seit:"):
            try:
                teile.extend(
                    ["SINCE", date.fromisoformat(wort[5:]).strftime("%d-%b-%Y")]
                )
            except ValueError:
                continue
        else:
            teile.extend(["TEXT", wort])
    if seit:
        teile.extend(["SINCE", seit.strftime("%d-%b-%Y")])
    return teile


def _server(domain: str, konto: dict):
    """Leitet bekannte Mailanbieter zu ihren IMAP- und SMTP-Servern auf."""
    if domain == "outlook.com" or domain.startswith(("hotmail.", "live.")):
        raise RuntimeError(
            "Microsoft-Postfächer gehen seit 2026 nur mit OAuth, nicht mit App-Passwort. "
            'Trag beim Postfach weg = "microsoft" ein und melde dich mit '
            "belege anmelden --microsoft <name> an, siehe einrichten.md, Abschnitt Microsoft-Postfach."
        )
    bekannte = {
        "gmail.com": ("imap.gmail.com:993", "smtp.gmail.com:465"),
        "googlemail.com": ("imap.gmail.com:993", "smtp.gmail.com:465"),
        "gmx.de": ("imap.gmx.net:993", "mail.gmx.net:587"),
        "gmx.net": ("imap.gmx.net:993", "mail.gmx.net:587"),
        "web.de": ("imap.web.de:993", "smtp.web.de:587"),
        "t-online.de": ("secureimap.t-online.de:993", "securesmtp.t-online.de:465"),
        "icloud.com": ("imap.mail.me.com:993", "smtp.mail.me.com:587"),
        "me.com": ("imap.mail.me.com:993", "smtp.mail.me.com:587"),
        "mac.com": ("imap.mail.me.com:993", "smtp.mail.me.com:587"),
        "mailbox.org": ("imap.mailbox.org:993", "smtp.mailbox.org:465"),
        "freenet.de": ("mx.freenet.de:993", "mx.freenet.de:587"),
        "posteo.de": ("posteo.de:993", "posteo.de:465"),
        "posteo.net": ("posteo.de:993", "posteo.de:465"),
    }
    imap, smtp = bekannte.get(
        domain, (konto.get("imap_server", ""), konto.get("smtp_server", ""))
    )
    if not imap or not smtp:
        imap, smtp = server_erkennen(domain)
    if not imap or not smtp:
        raise RuntimeError(
            f"Für {domain} sind IMAP- und SMTP-Server nicht bekannt. Trag sie beim Postfach "
            "als imap_server und smtp_server in konfig/belege.toml ein; dein Mailanbieter "
            "nennt sie in seiner Hilfe unter IMAP oder E-Mail-Programm."
        )
    return _adresse_port(imap, 993), _adresse_port(smtp, 465)


# Eigene Domains liegen meist bei einem Hoster. Woran man ihn am MX-Eintrag erkennt
# und welche Server er für E-Mail-Programme nennt. "{mx}" heißt: derselbe Rechner
# wie der MX (all-inkl gibt jedem Kunden einen eigenen).
HOSTER_NACH_MX = (
    ("google.com", "imap.gmail.com:993", "smtp.gmail.com:465"),
    ("googlemail.com", "imap.gmail.com:993", "smtp.gmail.com:465"),
    ("ionos.", "imap.ionos.de:993", "smtp.ionos.de:465"),
    ("kundenserver.de", "imap.ionos.de:993", "smtp.ionos.de:465"),
    ("rzone.de", "imap.strato.de:993", "smtp.strato.de:465"),
    ("udag.de", "imap.udag.de:993", "smtp.udag.de:465"),
    ("kasserver.com", "{mx}:993", "{mx}:465"),
    ("your-server.de", "mail.your-server.de:993", "mail.your-server.de:465"),
    ("mailbox.org", "imap.mailbox.org:993", "smtp.mailbox.org:465"),
    ("posteo.de", "posteo.de:993", "posteo.de:465"),
    ("icloud.com", "imap.mail.me.com:993", "smtp.mail.me.com:587"),
)


def _mx(domain: str) -> list[str]:
    """Die MX-Rechner einer Domain, ohne Zusatzpaket über dig vom Mac."""
    try:
        r = subprocess.run(
            ["dig", "+short", "MX", domain], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [
        zeile.split()[-1].rstrip(".").lower()
        for zeile in r.stdout.splitlines()
        if zeile.strip()
    ]


def _ispdb(domain: str) -> tuple[str, str]:
    """Fragt die öffentliche Anbieterliste von Thunderbird nach IMAP und SMTP."""
    import urllib.request
    import xml.etree.ElementTree as ET

    try:
        with urllib.request.urlopen(
            f"https://autoconfig.thunderbird.net/v1.1/{domain}", timeout=10
        ) as antwort:
            baum = ET.fromstring(antwort.read())
    except Exception:  # noqa: BLE001 - keine Antwort heißt nur: nicht erkannt
        return "", ""

    def server(art: str, typ: str) -> str:
        for knoten in baum.iter(art):
            if knoten.get("type") == typ and knoten.findtext("socketType") == "SSL":
                return f"{knoten.findtext('hostname')}:{knoten.findtext('port')}"
        for knoten in baum.iter(art):
            if knoten.get("type") == typ:
                return f"{knoten.findtext('hostname')}:{knoten.findtext('port')}"
        return ""

    return server("incomingServer", "imap"), server("outgoingServer", "smtp")


def server_erkennen(domain: str) -> tuple[str, str]:
    """Erkennt IMAP und SMTP einer eigenen Domain am MX-Eintrag, sonst über Thunderbird.

    Gibt ("", "") zurück, wenn nichts sicher erkannt ist. Microsoft 365 bricht ab,
    weil es kein App-Passwort mehr annimmt.
    """
    mx_liste = _mx(domain)
    for mx in mx_liste:
        if mx.endswith(("protection.outlook.com", "outlook.com")):
            raise RuntimeError(
                f"{domain} liegt bei Microsoft 365. Microsoft-Postfächer gehen seit 2026 nur "
                'mit OAuth, nicht mit App-Passwort. Trag beim Postfach weg = "microsoft" ein, '
                "siehe einrichten.md, Abschnitt Microsoft-Postfach."
            )
        for kennung, imap, smtp in HOSTER_NACH_MX:
            if mx.endswith(kennung) or kennung.endswith(".") and kennung in mx:
                return imap.replace("{mx}", mx), smtp.replace("{mx}", mx)
    imap, smtp = _ispdb(domain)
    if not (imap and smtp) and mx_liste:
        # Thunderbird kennt oft nur den Hoster, nicht jede Kundendomain.
        imap, smtp = _ispdb(".".join(mx_liste[0].split(".")[-2:]))
    return imap, smtp


def _adresse_port(wert: str, standard: int) -> tuple[str, int]:
    """Trennt optionalen Serverport von einer Serveradresse."""
    host, trenner, port = wert.rpartition(":")
    return (host, int(port)) if trenner else (wert, standard)


class GmailPostfach(Postfach):
    """Greift über die Gmail-API mit getrennten Lese- und Schreibzugängen zu."""

    def _dienst(self, schreiben: bool = False):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        art = "schreiben" if schreiben else "lesen"
        zugang = kern.pfad("arbeit", "geheim", f"{self.name}_{art}.json")
        try:
            credentials = Credentials.from_authorized_user_file(str(zugang))
        except OSError as fehler:
            raise RuntimeError(
                f"Der Google-Zugang fehlt. Melde dich an: uv run belege anmelden --konto {self.name}"
            ) from fehler
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except Exception as fehler:
                raise RuntimeError(
                    "Der Google-Zugang ist abgelaufen. Häufigste Ursache: Das Google-Projekt steht noch "
                    "auf Test. Stelle es auf In Produktion und melde dich neu an: "
                    f"uv run belege anmelden --konto {self.name}"
                ) from fehler
            zugang.write_text(credentials.to_json(), encoding="utf-8")
            os.chmod(zugang, 0o600)
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def suchen(self, abfrage="", max=20, seit=None, nur_anhang=False):
        """Durchsucht Gmail und lädt je Treffer nur Metadaten statt der Mail zweimal."""
        query = abfrage.strip()
        if seit:
            query = f"{query} after:{seit.isoformat()}".strip()
        if nur_anhang:
            query = f"{query} has:attachment".strip()
        dienst = self._dienst()
        antwort = (
            dienst.users()
            .messages()
            .list(userId="me", q=query, maxResults=max)
            .execute()
        )
        return [
            _gmail_metadata(
                dienst.users()
                .messages()
                .get(userId="me", id=eintrag["id"], format="metadata")
                .execute()
            )
            for eintrag in antwort.get("messages", [])
        ]

    def lesen(self, ident: str) -> dict:
        """Liest eine Gmail-Mail vollständig, wenn ihr Text gebraucht wird."""
        roh = (
            self._dienst()
            .users()
            .messages()
            .get(userId="me", id=ident, format="raw")
            .execute()
        )
        nachricht = email.message_from_bytes(
            base64.urlsafe_b64decode(roh["raw"] + "==="), policy=policy.default
        )
        daten = _kopf(nachricht, ident)
        daten["text"] = _inhalt(nachricht)
        daten["anhaenge"] = _anhaenge(nachricht)
        daten["links"] = _links(nachricht)
        return daten

    def anhaenge(self, ident: str, ziel: Path) -> list[Path]:
        """Speichert Gmail-Anhänge kollisionsfrei im Zielordner."""
        return _anhaenge_speichern(
            email.message_from_bytes(
                base64.urlsafe_b64decode(
                    self._dienst()
                    .users()
                    .messages()
                    .get(userId="me", id=ident, format="raw")
                    .execute()["raw"]
                    + "==="
                ),
                policy=policy.default,
            ),
            ziel,
        )

    def entwurf(self, an, betreff, text, anhaenge):
        """Legt über die Gmail-API einen Entwurf an."""
        roh = base64.urlsafe_b64encode(
            _nachricht(an, betreff, text, anhaenge, self.adresse).as_bytes()
        ).decode()
        antwort = (
            self._dienst(True)
            .users()
            .drafts()
            .create(userId="me", body={"message": {"raw": roh}})
            .execute()
        )
        return antwort["id"]

    def _senden(self, an, betreff, text, anhaenge):
        """Sendet über die Gmail-API; nur senden.py ruft diese Methode auf."""
        roh = base64.urlsafe_b64encode(
            _nachricht(an, betreff, text, anhaenge, self.adresse).as_bytes()
        ).decode()
        antwort = (
            self._dienst(True)
            .users()
            .messages()
            .send(userId="me", body={"raw": roh})
            .execute()
        )
        return antwort["id"]

    def mit_label(self, label: str) -> list[dict]:
        """Sucht ein Gmail-Label mit korrekt quotierter Gmail-Abfrage."""
        return self.suchen(f'label:"{label.replace("/", "-")}"')

    def label_erledigt(self, ident: str, label: str) -> None:
        """Verschiebt ein Gmail-Label nach <Label>/erledigt."""
        return None


def _gmail_metadata(mail: dict) -> dict:
    """Übersetzt Gmail-Metadaten samt Anhangnamen in das gemeinsame Suchformat."""
    headers = {
        wert["name"].lower(): wert["value"]
        for wert in mail.get("payload", {}).get("headers", [])
    }
    nachricht = EmailMessage()
    for name, wert in headers.items():
        nachricht[name] = wert
    daten = _kopf(nachricht, mail["id"])
    daten["anhaenge"] = _gmail_anhaenge(mail.get("payload", {}))
    daten["auszug"] = str(mail.get("snippet", ""))[:300]
    return daten


def _gmail_anhaenge(payload: dict) -> list[str]:
    """Sammelt Anhangnamen rekursiv aus Gmail-Payload-Teilen."""
    namen = []
    for teil in payload.get("parts", []):
        if teil.get("filename"):
            namen.append(teil["filename"])
        namen.extend(_gmail_anhaenge(teil))
    return namen


def oeffnen(konto_name=None):
    """Öffnet das konfigurierte Postfach im passenden Zugriffsweg."""
    konto = kern.konto(konto_name)
    if konto.get("weg") == "microsoft":
        from .microsoft import MicrosoftPostfach

        return MicrosoftPostfach(konto)
    klassen = {"a": ImapPostfach, "b": GmailPostfach, "ordner": OrdnerPostfach}
    return klassen.get(konto.get("weg", "a"), ImapPostfach)(konto)


def befehl_suchen(args) -> int:
    """Gibt kurze Suchtreffer aus, auch wenn ein Maildatum fehlt oder fehlerhaft ist."""
    woerter = getattr(args, "woerter", []) or getattr(args, "ziel", [])
    for mail in oeffnen(getattr(args, "konto", None)).suchen(
        " ".join(woerter), seit=getattr(args, "seit", None)
    ):
        try:
            datum_text = date.fromisoformat(mail.get("datum", "")).strftime("%d.%m.")
        except ValueError:
            datum_text = "ohne Datum"
        anhang = " [Anhänge]" if mail.get("anhaenge") else ""
        absender = mail.get("von") or mail.get("von_name") or "ohne Absender"
        print(f"{datum_text} {absender}: {mail.get('betreff', '')}{anhang}")
    return 0
