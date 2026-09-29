"""Postfächer über App-Passwort, Gmail oder lokale .eml-Dateien."""

from __future__ import annotations

import base64
import email
import html
import imaplib
import os
import re
import smtplib
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
        self.passwort = os.environ.get("PASSWORT_" + self.name.upper())
        if not self.passwort:
            raise RuntimeError(
                f"Trag das App-Passwort für {self.name} in .env ein, siehe einrichten.md"
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
            verbindung.select(ordner, readonly=True)
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
        """Durchsucht IMAP ohne Mails als gelesen zu markieren."""
        verbindung = self._imap()
        try:
            verbindung.select("INBOX", readonly=True)
            _, daten = self._suche(verbindung, _imap_kriterien(abfrage, seit))
            uids = (daten[0].split() if daten and daten[0] else [])[-max:][::-1]
            treffer = []
            for uid in uids:
                _, roh = verbindung.uid(
                    "fetch",
                    uid,
                    "(BODY.PEEK[HEADER] BODYSTRUCTURE BODY.PEEK[TEXT]<0.2000>)",
                )
                nachricht = _imap_nachricht(roh)
                if nachricht is None:
                    continue
                kopf = _kopf(nachricht, f"INBOX:{uid.decode()}")
                if nur_anhang and not kopf["anhaenge"]:
                    continue
                kopf["auszug"] = _inhalt(nachricht)[:300]
                treffer.append(kopf)
            return treffer
        finally:
            verbindung.logout()

    def lesen(self, ident: str) -> dict:
        """Liest eine IMAP-Mail vollständig, ohne ihren Gelesen-Status zu ändern."""
        nachricht = self._fetch_mail(ident)
        daten = _kopf(nachricht, ident)
        daten["text"] = _inhalt(nachricht)
        daten["anhaenge"] = _anhaenge(nachricht)
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
            "Microsoft-Postfächer gehen seit 2026 nur mit OAuth, nicht mit App-Passwort."
        )
    bekannte = {
        "gmail.com": ("imap.gmail.com:993", "smtp.gmail.com:465"),
        "googlemail.com": ("imap.gmail.com:993", "smtp.gmail.com:465"),
        "gmx.de": ("imap.gmx.net:993", "mail.gmx.net:587"),
        "web.de": ("imap.web.de:993", "smtp.web.de:587"),
    }
    imap, smtp = bekannte.get(
        domain, (konto.get("imap_server", ""), konto.get("smtp_server", ""))
    )
    if not imap or not smtp:
        raise RuntimeError(
            "IMAP- und SMTP-Server fehlen in konfig/belege.toml. Trag sie beim Postfach ein."
        )
    return _adresse_port(imap, 993), _adresse_port(smtp, 465)


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
