"""Postfächer über App-Passwort, Gmail oder lokale .eml-Dateien."""

from __future__ import annotations

import base64
import email
import html
import imaplib
import json
import os
import re
import smtplib
import subprocess
import urllib.parse
from datetime import date, timedelta
from email import policy
from email.header import decode_header, make_header
from email.utils import parseaddr
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import kern

ANMELDE_HINWEIS = (
    "Anmeldung abgelehnt. Häufigste Ursachen: App-Passwort falsch kopiert, IMAP im "
    "Webmailer nicht eingeschaltet (GMX/web.de), bei Google Workspace hat der Admin "
    "App-Passwörter gesperrt."
)


def imap_ablage_ordner_gueltig(ordner: str) -> bool:
    """Erlaubt nur sichere, einzelne IMAP-Ordnernamen für CREATE/MOVE."""
    return bool(ordner.strip() and len(ordner) <= 100 and '"' not in ordner and not any(ord(c) < 32 or ord(c) == 127 for c in ordner))


def ziel_gesperrt(name: str) -> bool:
    """Erkennt Papierkorb- und Spam-Ziele aller unterstützten Postfachwege."""
    # Ohne Leerzeichen, Binde- und Unterstriche: „Junk-E-Mail“, „Junk E-Mail“ und „junkemail“ sind dasselbe.
    # IMAP trennt Ebenen auch mit „.“ (INBOX.Trash), darum auch dort teilen.
    teile = [re.sub(r"[\s_-]+", "", teil).casefold() for teil in re.split(r"[/.\\]", str(name)) if teil.strip()]
    gesperrt = {
        "trash", "bin", "papierkorb", "spam", "junk", "junkemail", "junkmail", "deleted", "deleteditems",
        "deletedmessages", "gelöscht", "gelöschteelemente", "gelöschteobjekte", "gelöschtenachrichten",
        "spamverdacht", "unerwünscht",
    }
    return any(teil in gesperrt for teil in teile)


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
        zeitpunkt = parsedate_to_datetime(nachricht.get("Date"))
        if zeitpunkt.tzinfo is not None:
            zeitpunkt = zeitpunkt.astimezone(kern.zone())
        return zeitpunkt.date().isoformat()
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
        "antwort_an": parseaddr(_text(nachricht.get("Reply-To") or nachricht.get("From")))[1],
        "message_id": _text(nachricht.get("Message-ID")).strip(),
    }


def _newsletter_kopf(headers: dict) -> bool:
    """Erkennt Newsletter ausschließlich an den übergebenen RFC-Kopfdaten."""
    kopf = {str(name).lower(): str(wert) for name, wert in headers.items()}
    return bool(
        kopf.get("list-unsubscribe")
        or kopf.get("list-id")
        or kopf.get("precedence", "").lower() in {"bulk", "list"}
    )


def _newsletter(nachricht) -> bool:
    """Übergibt die RFC-Kopfdaten einer Nachricht an die gemeinsame Erkennung."""
    return _newsletter_kopf(dict(nachricht.items()))


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

    def nach_ablage(self, ident: str, art: str, ordner: str) -> str:
        """Behandelt eine vollständig abgelegte Mail; Standard bleibt folgenlos."""
        return "nicht unterstützt"

    def posteingang(self, seit: date | None, max: int, text: bool = False, zustand: bool = False, beantwortet: bool = False) -> list[dict]:
        """Meldet fehlende Posteingangs-Unterstützung, statt alle Ordner zu suchen."""
        kern.log("Dieser Postfachweg unterstützt den Posteingang nicht.")
        return []

    def ordnung(self) -> dict:
        """Liest sichtbare Ordner und Labels, ohne etwas zu verändern."""
        return {"ordner": [], "labels": [], "labels_sichtbar": False, "hinweis": ""}

    def zuordnung(self, tage: int = 90, je_ordner: int = 200) -> dict:
        """Liefert Absender aus der vorhandenen Ordnung, wenn verfügbar."""
        return {}

    def aufraeumen(self, ident: str, aktion: str, name: str = "") -> str:
        """Führt eine ausdrücklich erlaubte, nicht löschende Postfachaktion aus."""
        return "nicht unterstützt"

    def entwurf(self, an, betreff, text, anhaenge, antwort_auf=None):
        """Legt einen Entwurf an; Backends können ihn an eine Mail anhängen."""
        raise NotImplementedError

    def zurueckholen(self, eintrag: dict) -> str:
        """Holt eine protokollierte Aktion zurück, ohne je eine Mail zu löschen."""
        return "nicht unterstützt"


class AktionErgebnis(str):
    """Textkompatibles Aktionsergebnis mit der Kennung nach einem MOVE."""
    def __new__(cls, text: str, neue_id: str = ""):
        wert = super().__new__(cls, text)
        wert.neue_id = neue_id
        return wert


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

    def posteingang(self, seit: date | None = None, max: int = 20, text: bool = False, zustand: bool = False, beantwortet: bool = False) -> list[dict]:
        """Liest lokale .eml-Dateien als Test-Posteingang ohne Datumszwang."""
        treffer = []
        for datei, nachricht in self._alle():
            kopf = _kopf(nachricht, datei.name)
            if seit:
                try:
                    if date.fromisoformat(kopf["datum"]) < seit:
                        continue
                except (TypeError, ValueError):
                    pass
            kopf["newsletter"] = _newsletter(nachricht)
            if text:
                kopf["text"] = _inhalt(nachricht)[:4000]
            if zustand:
                kopf["zustand"] = {"beantwortet": False, "erledigt": False, "gelesen": False, "markierungen": []}
            treffer.append(kopf)
            if len(treffer) >= max:
                break
        return treffer

    def ordnung(self) -> dict:
        """Liest die optionale Testordnung aus dem Mailordner."""
        datei = self.ordner / "ordnung.json"
        daten = json.loads(datei.read_text(encoding="utf-8")) if datei.exists() else {}
        return {"ordner": list(daten.get("ordner", [])), "labels": list(daten.get("labels", [])), "labels_sichtbar": bool(daten.get("labels_sichtbar", True)), "hinweis": str(daten.get("hinweis", ""))}

    def zuordnung(self, tage: int = 90, je_ordner: int = 200) -> dict:
        """Liest Testzuordnungen aus der optionalen Ordnungsdatei."""
        datei = self.ordner / "ordnung.json"
        daten = json.loads(datei.read_text(encoding="utf-8")) if datei.exists() else {}
        return dict(daten.get("zuordnung", {}))

    def aufraeumen(self, ident: str, aktion: str, name: str = "") -> str:
        """Notiert lokale Aktionen, ohne die zugrunde liegenden .eml-Dateien anzufassen."""
        import json

        if aktion in {"ordner", "label"} and ziel_gesperrt(name):
            return "nicht verschoben (Papierkorb/Spam ist gesperrt)"

        ziel = kern.pfad("arbeit", "postfach-ordner-aktionen.jsonl")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        with ziel.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": ident, "aktion": aktion, "name": name}, ensure_ascii=False) + "\n")
        return f"{aktion}: {name}".rstrip(": ")

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

    def entwurf(self, an, betreff, text, anhaenge, antwort_auf=None):
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
            teile = _imap_list_zeile(zeile)
            if teile and flag.lower() in teile[0]:
                return teile[2]
        # Thunderbird/klassische IMAP-Server markieren Archive oft nicht.
        for zeile in zeilen or []:
            teile = _imap_list_zeile(zeile)
            if teile and _mutf7(teile[2]).rsplit(teile[1] or "/", 1)[-1].lower() in {x.lower() for x in namen}:
                return teile[2]
        return namen[0]

    def _zielordner(self, verbindung, name: str) -> str:
        """Übersetzt sichtbare Pfade in die Hierarchie und legt Ebenen sicher an."""
        if not hasattr(verbindung, "list"):
            verbindung.create(_imap_quote(_mutf7_encode(name)))
            return _mutf7_encode(name)
        status, zeilen = verbindung.list()
        infos = [_imap_list_zeile(z) for z in (zeilen or [])]
        infos = [x for x in infos if x]
        trenner = next((x[1] for x in infos if x[1]), "/")
        teile = [x for x in name.replace("\\", "/").split("/") if x]
        if not teile:
            return ""
        # Courier/Strato: alle persönlichen Ordner liegen unter INBOX.
        vorhandene = [_mutf7(x[2]) for x in infos]
        praefix = "INBOX" if vorhandene and all(x.upper() == "INBOX" or x.upper().startswith("INBOX" + trenner.upper()) for x in vorhandene) else ""
        sichtbar = trenner.join(([praefix] if praefix else []) + teile)
        stufen = sichtbar.split(trenner)
        aktuell = []
        vorhandene_klein = {_mutf7(x[2]).lower(): x[2] for x in infos}
        for stufe in stufen:
            aktuell.append(stufe)
            klar = trenner.join(aktuell)
            roh = vorhandene_klein.get(klar.lower())
            if roh is None:
                verbindung.create(_imap_quote(_mutf7_encode(klar)))
                roh = _mutf7_encode(klar)
                vorhandene_klein[klar.lower()] = roh
            aktuell[-1] = _mutf7(roh).split(trenner)[-1]
        return vorhandene_klein.get(sichtbar.lower(), _mutf7_encode(sichtbar))

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

        Ohne `imap_ordner` beim Konto alle Ordner außer Gesendet, Papierkorb, Spam
        und Entwürfen: Mailprogramme mit Filtern verschieben Rechnungen sofort in
        Unterordner. Mit `imap_ordner` nur INBOX und die genannten Ordner.
        """
        verbindung = self._imap()
        # Mit nur_anhang zählt max die Treffer je Ordner; zusammen höchstens 500.
        grenze = 500 if nur_anhang else max
        try:
            treffer = []
            schon = set()  # Gmail zeigt Labels als Ordner: dieselbe Mail nur einmal
            if "imap_ordner" in self.konto:
                ordnerliste = _imap_ordnerliste(self.konto)
            else:
                ordnerliste = _imap_alle_ordner(verbindung)
            for ordner in ordnerliste:
                try:
                    if verbindung.select(_imap_quote(ordner), readonly=True)[0] != "OK":
                        kern.log(f"IMAP-Ordner {ordner} nicht gefunden, übersprungen.")
                        continue
                    _, daten = self._suche(verbindung, _imap_kriterien(abfrage, seit))
                except (imaplib.IMAP4.error, RuntimeError) as fehler:
                    if ordner == "INBOX":
                        raise
                    # Ein einzelner sperriger Ordner hält die übrige Suche nicht auf.
                    kern.log(f"IMAP-Ordner {ordner} übersprungen: {fehler}")
                    continue
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
                    kennung = str(nachricht.get("Message-ID") or "").strip()
                    if kennung and kennung in schon:
                        continue
                    kopf = _kopf(nachricht, f"{ordner}:{uid.decode()}")
                    # Der Kopf allein kennt keine Anhänge; die stehen in BODYSTRUCTURE.
                    kopf["anhaenge"] = kopf["anhaenge"] or _imap_anhaenge(roh)
                    if nur_anhang and not kopf["anhaenge"]:
                        continue
                    kopf["auszug"] = _inhalt(nachricht)[:300]
                    treffer.append(kopf)
                    if kennung:
                        schon.add(kennung)
                    gefunden += 1
                    if gefunden >= grenze:
                        break
            treffer.sort(key=lambda kopf: kopf.get("datum", ""), reverse=True)
            return treffer[:grenze]
        finally:
            verbindung.logout()

    def posteingang(self, seit: date | None = None, max: int = 20, text: bool = False, zustand: bool = False, beantwortet: bool = False) -> list[dict]:
        """Liest nur INBOX per PEEK und liefert die neuesten Nachrichten zuerst."""
        verbindung = self._imap()
        try:
            if verbindung.select("INBOX", readonly=True)[0] != "OK":
                return []
            _, daten = self._suche(verbindung, _imap_kriterien("", seit))
            treffer = []
            uids = (daten[0].split() if daten and daten[0] else [])[-max:][::-1]
            for uid in uids:
                teile = "BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE REPLY-TO MESSAGE-ID LIST-UNSUBSCRIBE LIST-ID PRECEDENCE)] BODYSTRUCTURE"
                if text:
                    teile += " BODY.PEEK[]"
                if zustand:
                    teile += " FLAGS"
                _, roh = verbindung.uid(
                    "fetch",
                    uid,
                    f"({teile})",
                )
                nachricht = _imap_nachricht(roh)
                if not nachricht:
                    continue
                kopf = _kopf(nachricht, f"INBOX:{uid.decode()}")
                kopf["anhaenge"] = _imap_anhaenge(roh)
                kopf["newsletter"] = _newsletter(nachricht)
                if text:
                    kopf["text"] = _inhalt(nachricht)[:4000]
                if zustand:
                    flags_text = b" ".join(
                        teil[0] if isinstance(teil, tuple) and isinstance(teil[0], bytes)
                        else str(teil[0] if isinstance(teil, tuple) else teil).encode()
                        for teil in roh or []
                    )
                    gefunden = re.search(rb"FLAGS \(([^)]*)\)", flags_text, re.I)
                    # imaplib.ParseFlags braucht das Wort FLAGS davor, sonst liefert es nichts.
                    flags = gefunden.group(1).split() if gefunden else []
                    flags = [x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x) for x in flags]
                    markierungen = [x for x in flags if not x.startswith("\\")]
                    marker = str(kern.konfig("belege").get("aufraeumen", {}).get("erledigt_markierung", "Erledigt"))
                    kopf["zustand"] = {"beantwortet": "\\Answered" in flags, "erledigt": bool(marker and any(x.lower() == marker.lower() for x in markierungen)), "gelesen": "\\Seen" in flags, "markiert": "\\Flagged" in flags, "markierungen": markierungen}
                treffer.append(kopf)
            return treffer
        finally:
            verbindung.logout()

    def ordnung(self) -> dict:
        """Liest IMAP-Ordner und mögliche Keywords nur lesend."""
        verbindung = self._imap()
        try:
            _, zeilen = verbindung.list()
            sichtbar = _imap_sichtbar(zeilen)
            ordner = []
            for zeile in zeilen or []:
                teile = _imap_list_zeile(zeile)
                if not teile:
                    continue
                flags, _, name = teile
                if name.upper() != "INBOX" and not flags & _IMAP_SONDER:
                    ordner.append(sichtbar.get(name, _mutf7(name)))
            verbindung.select("INBOX", readonly=True)
            _, flags = verbindung.response("PERMANENTFLAGS")
            roh = b" ".join(x if isinstance(x, bytes) else str(x).encode() for x in (flags or []))
            innen = re.search(rb"\(([^)]*)\)", roh)
            werte = (innen.group(1) if innen else roh).split()
            werte = [x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x) for x in werte]
            labels = [x for x in werte if not x.startswith("\\")]
            return {"ordner": ordner, "labels": labels, "labels_sichtbar": False, "keywords_erlaubt": "\\*" in werte, "hinweis": "Thunderbird zeigt eigene Labels als Schlagwörter; Apple Mail, iPhone und die meisten Webmailer zeigen sie nicht. Nimm dort lieber ordner:."}
        finally:
            verbindung.logout()

    def aufraeumen(self, ident: str, aktion: str, name: str = "") -> str:
        """Verschiebt nur bei IMAP-MOVE; Labels setzen ein harmloses Keyword."""
        ordner_alt, uid = ident.rsplit(":", 1)
        verbindung = self._imap()
        try:
            if verbindung.select(_imap_quote(ordner_alt), readonly=False)[0] != "OK":
                return "nicht verschoben (IMAP SELECT fehlgeschlagen)"
            if ziel_gesperrt(name):
                return "nicht verschoben (Papierkorb/Spam ist gesperrt)"
            if aktion == "label":
                keyword = re.sub(r"[^A-Za-z0-9_-]", "-", name)[:50]
                typ, _ = verbindung.uid("store", uid, "+FLAGS", f"({keyword})")
                if typ == "OK":
                    return f"mit Label {name} markiert"
                return "nicht markiert (IMAP STORE fehlgeschlagen)"
            ziel = name if aktion == "ordner" else self._ordner("\\Archive", ["Archive", "Archives", "Archiv"])
            if not imap_ablage_ordner_gueltig(ziel):
                return "nicht verschoben (Ordnername ist ungültig)"
            typ, daten = verbindung.capability()
            faehig = typ == "OK" and b"MOVE" in b" ".join(
                d if isinstance(d, bytes) else str(d).encode() for d in (daten or [])
            ).upper()
            if not faehig:
                return "nicht verschoben (Server kann kein MOVE)"
            ziel = self._zielordner(verbindung, ziel)
            typ, daten = verbindung.uid("move", uid, _imap_quote(ziel))
            if typ != "OK":
                return "nicht verschoben (IMAP MOVE fehlgeschlagen)"
            neue_uid = _copyuid(daten)
            if not neue_uid:
                neue_uid = self._ziel_uid_nach_message_id(verbindung, ziel, ident)
            return AktionErgebnis(f"nach {_mutf7(ziel)} verschoben", f"{_mutf7(ziel)}:{neue_uid}" if neue_uid else "")
        finally:
            verbindung.logout()

    def zurueckholen(self, eintrag: dict) -> str:
        if eintrag.get("aktion") == "label":
            # Ein Label ist ein Keyword an derselben Mail; zurück heißt: Keyword wieder weg.
            ordner, uid = str(eintrag.get("id", "")).rsplit(":", 1)
            keyword = re.sub(r"[^A-Za-z0-9_-]", "-", str(eintrag.get("ziel", "")))[:50]
            verbindung = self._imap()
            try:
                if verbindung.select(_imap_quote(_mutf7_encode(ordner)), readonly=False)[0] != "OK":
                    return "nicht zurückgeholt (IMAP SELECT fehlgeschlagen)"
                typ, _ = verbindung.uid("store", uid, "-FLAGS", f"({keyword})")
                return f"Label {eintrag.get('ziel', '')} entfernt" if typ == "OK" else "nicht zurückgeholt (IMAP STORE fehlgeschlagen)"
            finally:
                verbindung.logout()
        ident = str(eintrag.get("neue_id") or "")
        if ":" not in ident:
            return "nicht zurückgeholt (Zielkennung fehlt)"
        ordner, uid = ident.rsplit(":", 1)
        verbindung = self._imap()
        try:
            if verbindung.select(_imap_quote(_mutf7_encode(ordner)), readonly=False)[0] != "OK":
                return "nicht zurückgeholt (IMAP SELECT fehlgeschlagen)"
            typ, _ = verbindung.uid("move", uid, "INBOX")
            return "in Posteingang zurückgeholt" if typ == "OK" else "nicht zurückgeholt (IMAP MOVE fehlgeschlagen)"
        finally:
            verbindung.logout()

    def zuordnung(self, tage: int = 90, je_ordner: int = 200) -> dict:
        """Liest Absender aus bis zu 30 IMAP-Ordnern mit gemeinsamem Mailbudget."""
        verbindung, ergebnis, rest = self._imap(), {}, 3000
        try:
            seit = (date.today() - timedelta(days=tage)).strftime("%d-%b-%Y")
            sichtbar = _imap_sichtbar(verbindung.list()[1])
            # Der Posteingang ist kein Ziel, sonst schlüge labels „ordner: INBOX“ vor.
            for ordner in [x for x in _imap_alle_ordner(verbindung) if x.upper() != "INBOX"][:30]:
                if rest <= 0 or verbindung.select(_imap_quote(ordner), readonly=True)[0] != "OK":
                    continue
                _, daten = verbindung.uid("search", None, "SINCE", seit)
                uids = (daten[0].split() if daten and daten[0] else [])[-min(je_ordner, rest):]
                absender = []
                for uid in uids:
                    _, roh = verbindung.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                    nachricht = _imap_nachricht(roh)
                    if nachricht:
                        absender.append(parseaddr(str(nachricht.get("From", "")))[1].lower())
                rest -= len(uids)
                ergebnis[sichtbar.get(ordner, _mutf7(ordner))] = [x for x in absender if x]
        finally:
            verbindung.logout()
        return {"ordner": ergebnis, "labels": {}}

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

    def nach_ablage(self, ident: str, art: str, ordner: str) -> str:
        if not imap_ablage_ordner_gueltig(ordner):
            return "nicht markiert (nach_ablage_ordner ist ungültig)"
        ordner_alt, uid = ident.rsplit(":", 1)
        verbindung = self._imap()
        try:
            typ, _ = verbindung.select(_imap_quote(ordner_alt), readonly=False)
            if typ != "OK":
                return "nicht markiert (IMAP SELECT fehlgeschlagen)"
            typ, _ = verbindung.uid("store", uid, "+FLAGS", "(\\Seen belege-erledigt)")
            if typ != "OK":
                return "nicht markiert (IMAP UID STORE fehlgeschlagen)"
            if art != "verschieben":
                return "als gelesen und mit belege-erledigt markiert"
            typ, daten = verbindung.capability()
            faehig = typ == "OK" and b"MOVE" in b" ".join(d if isinstance(d, bytes) else str(d).encode() for d in (daten or [])).upper()
            if not faehig:
                return "nur markiert (Server unterstützt IMAP MOVE nicht)"
            typ, _ = verbindung.create(_imap_quote(ordner))
            if typ != "OK":
                return "nur markiert (IMAP CREATE fehlgeschlagen)"
            typ, _ = verbindung.uid("move", uid, _imap_quote(ordner))
            if typ != "OK":
                return "nur markiert (IMAP MOVE fehlgeschlagen)"
            return f"nach {ordner} verschoben"
        finally:
            verbindung.logout()

    def _ziel_uid_nach_message_id(self, verbindung, ziel: str, ident: str) -> str:
        nachricht = self._fetch_mail(ident)
        message_id = str(nachricht.get("Message-ID") or "").strip()
        if not message_id or verbindung.select(_imap_quote(ziel), readonly=True)[0] != "OK":
            return ""
        typ, daten = verbindung.uid("search", None, "HEADER", "Message-ID", message_id)
        return (daten[0].split()[-1].decode() if typ == "OK" and daten and daten[0] else "")

    def entwurf(self, an, betreff, text, anhaenge, antwort_auf=None):
        """Legt einen Entwurf im IMAP-Entwurfsordner ab."""
        verbindung = self._imap()
        try:
            ordner = self._ordner(
                "\\Drafts", ["Entwürfe", "Drafts", "[Gmail]/Entwürfe"]
            )
            ordner = self._zielordner(verbindung, ordner)
            nachricht = _nachricht(an, betreff, text, anhaenge, self.adresse)
            if antwort_auf and antwort_auf.get("message_id"):
                nachricht["In-Reply-To"] = antwort_auf["message_id"]
                nachricht["References"] = antwort_auf["message_id"]
            verbindung.append(
                ordner,
                "\\Draft",
                None,
                nachricht.as_bytes(),
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


# Sonderordner nach RFC 6154; dort liegen keine eingehenden Rechnungen (\\All wäre doppelt).
_IMAP_SONDER = {"\\sent", "\\trash", "\\junk", "\\archive", "\\drafts", "\\all", "\\flagged", "\\important", "\\noselect", "\\nonexistent"}
# Für Server ohne Sonderkennzeichen: übliche Namen, deutsch und englisch, kleingeschrieben.
_IMAP_AUSLASSEN = {
    "sent", "sent items", "sent messages", "sent mail", "gesendet", "gesendete elemente",
    "gesendete objekte", "gesendete nachrichten", "trash", "deleted", "deleted items",
    "deleted messages", "papierkorb", "gelöscht", "gelöschte elemente", "gelöschte objekte",
    "junk", "junk e-mail", "junk-e-mail", "spam", "spamverdacht", "unerwünscht", "drafts",
    "entwürfe", "outbox", "postausgang", "notes", "notizen", "templates", "vorlagen",
    "calendar", "kalender", "contacts", "kontakte", "tasks", "aufgaben", "journal",
    "all mail", "alle nachrichten", "starred", "markiert", "important", "wichtig",
}


def _mutf7(name: str) -> str:
    """Dekodiert IMAP-Ordnernamen (modifiziertes UTF-7, RFC 3501), etwa Entw&APw-rfe."""
    def teil(treffer):
        kern_text = treffer.group(1)
        if not kern_text:
            return "&"
        roh = kern_text.replace(",", "/")
        roh += "=" * (-len(roh) % 4)
        try:
            return base64.b64decode(roh).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return treffer.group(0)
    return re.sub(r"&([A-Za-z0-9+,]*)-", teil, name)


def _mutf7_encode(name: str) -> str:
    """Kodiert IMAP-Ordnernamen nach RFC 3501 5.1.3 (modified UTF-7)."""
    teile, nicht_ascii = [], []
    def flush():
        if nicht_ascii:
            roh = "".join(nicht_ascii).encode("utf-16-be")
            teile.append("&" + base64.b64encode(roh).decode().rstrip("=").replace("/", ",") + "-")
            nicht_ascii.clear()
    for zeichen in name:
        if "\x20" <= zeichen <= "\x7e" and zeichen != "&":
            flush()
            teile.append(zeichen)
        elif zeichen == "&":
            flush()
            teile.append("&-")
        else:
            nicht_ascii.append(zeichen)
    flush()
    return "".join(teile)


def _copyuid(daten) -> str:
    """Liest die Ziel-UID aus einer UIDPLUS COPYUID-Antwort."""
    roh = b" ".join(x if isinstance(x, bytes) else str(x).encode() for x in (daten or []))
    treffer = re.search(rb"COPYUID\s+\d+\s+[^ ]+\s+([^ )]+)", roh, re.I)
    return treffer.group(1).decode("ascii", "replace").split(",")[-1] if treffer else ""


def _imap_list_zeile(zeile) -> tuple[set[str], str, str] | None:
    """Zerlegt eine LIST-Antwort in Kennzeichen, Trennzeichen und Ordnernamen."""
    if isinstance(zeile, tuple):  # Name als Literal {n}
        kopf, name = zeile[0].decode("utf-8", "replace"), zeile[1].decode("utf-8", "replace")
        treffer = re.match(r'\((.*?)\)\s+(NIL|"(?:[^"\\]|\\.)*")', kopf)
        if not treffer:
            return None
        flags, trenner = treffer.group(1), treffer.group(2)
    else:
        text = zeile.decode("utf-8", "replace") if isinstance(zeile, bytes) else str(zeile)
        treffer = re.match(r'\((.*?)\)\s+(NIL|"(?:[^"\\]|\\.)*")\s+(.*)$', text)
        if not treffer:
            return None
        flags, trenner, name = treffer.groups()
        name = name.strip()
        if name.startswith('"') and name.endswith('"'):
            name = re.sub(r'\\(.)', r"\1", name[1:-1])
    trenner = "" if trenner == "NIL" else re.sub(r'\\(.)', r"\1", trenner.strip('"'))
    return {f.lower() for f in flags.split()}, trenner, name


def _imap_sichtbar(zeilen) -> dict[str, str]:
    """Ordnet jedem IMAP-Rohnamen den Pfad zu, den Nutzer in Regeln schreiben:
    dekodiert, mit „/“ als Trenner und ohne INBOX-Präfix bei Courier/Strato.
    Genau diese Schreibweise löst ImapPostfach._zielordner wieder auf."""
    infos = [x for x in (_imap_list_zeile(z) for z in (zeilen or [])) if x]
    trenner = next((x[1] for x in infos if x[1]), "/")
    klar = {x[2]: _mutf7(x[2]) for x in infos}
    praefix = bool(klar) and all(n.upper() == "INBOX" or n.upper().startswith("INBOX" + trenner.upper()) for n in klar.values())
    sichtbar = {}
    for roh, name in klar.items():
        if praefix and name.upper().startswith("INBOX" + trenner.upper()):
            name = name[len("INBOX" + trenner):]
        sichtbar[roh] = name.replace(trenner, "/") if trenner != "/" else name
    return sichtbar


def _imap_alle_ordner(verbindung) -> list[str]:
    """INBOX und jeder Ordner, in dem eingehende Post liegen kann."""
    try:
        status, zeilen = verbindung.list()
    except Exception as fehler:  # noqa: BLE001 – dann eben nur der Posteingang
        kern.log(f"IMAP-Ordnerliste nicht lesbar, nur INBOX: {fehler}")
        return ["INBOX"]
    if status != "OK":
        return ["INBOX"]
    ordner = ["INBOX"]
    for zeile in zeilen or []:
        teile = _imap_list_zeile(zeile)
        if not teile:
            continue
        flags, trenner, name = teile
        if not name or name.upper() == "INBOX" or flags & _IMAP_SONDER:
            continue
        stufen = [_mutf7(s).strip().lower() for s in (name.split(trenner) if trenner else [name])]
        if any(stufe in _IMAP_AUSLASSEN for stufe in stufen) or stufen[0] == "[gmail]" and len(stufen) == 1:
            continue
        if name not in ordner:
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

    def posteingang(self, seit: date | None = None, max: int = 20, text: bool = False, zustand: bool = False, beantwortet: bool = False) -> list[dict]:
        """Liest den Gmail-Posteingang seitenweise, höchstens ``max`` Nachrichten."""
        query = "in:inbox" + (f" after:{seit.isoformat()}" if seit else "")
        dienst = self._dienst()
        ergebnis = []
        seite = None
        while len(ergebnis) < max:
            parameter = {
                "userId": "me",
                "q": query,
                "maxResults": min(500, max - len(ergebnis)),
            }
            if seite:
                parameter["pageToken"] = seite
            antwort = dienst.users().messages().list(**parameter).execute()
            for eintrag in antwort.get("messages", []):
                mail = dienst.users().messages().get(
                    userId="me",
                    id=eintrag["id"],
                    format="raw" if text else "metadata",
                    metadataHeaders=["From", "To", "Subject", "Date", "Reply-To", "Message-ID", "List-Unsubscribe", "List-Id", "Precedence"],
                ).execute()
                if text:
                    nachricht = email.message_from_bytes(base64.urlsafe_b64decode(mail["raw"] + "==="), policy=policy.default)
                    kopf = _kopf(nachricht, eintrag["id"])
                    kopf["anhaenge"] = _anhaenge(nachricht)
                    headers = dict(nachricht.items())
                else:
                    kopf = _gmail_metadata(mail)
                    # Gmail liefert den Textanfang (snippet) mit; der Postfach-Agent sieht ihn nie.
                    kopf.pop("auszug", None)
                    headers = {x["name"]: x["value"] for x in mail.get("payload", {}).get("headers", [])}
                kopf["newsletter"] = _newsletter_kopf(headers)
                kopf["thread_id"] = mail.get("threadId", "")
                if text:
                    kopf["text"] = _inhalt(nachricht)[:4000]
                if zustand:
                    if not hasattr(self, "_labelnamen"):
                        self._labelnamen = {x.get("id"): x.get("name", "") for x in dienst.users().labels().list(userId="me").execute().get("labels", [])}
                    labels = mail.get("labelIds", [])
                    markierungen = [self._labelnamen.get(x, x) for x in labels]
                    marker = str(kern.konfig("belege").get("aufraeumen", {}).get("erledigt_markierung", "Erledigt"))
                    ist_beantwortet = False
                    if beantwortet and mail.get("threadId"):
                        if not hasattr(self, "_thread_antworten"):
                            self._thread_antworten = {}
                        thread = self._thread_antworten.get(mail["threadId"])
                        if thread is None:
                            thread = dienst.users().threads().get(userId="me", id=mail["threadId"], format="minimal").execute()
                            self._thread_antworten[mail["threadId"]] = thread
                        datum = int(mail.get("internalDate", 0) or 0)
                        ist_beantwortet = any("SENT" in x.get("labelIds", []) and int(x.get("internalDate", 0) or 0) > datum for x in thread.get("messages", []))
                    kopf["zustand"] = {"beantwortet": ist_beantwortet, "erledigt": any(x.lower() == marker.lower() for x in markierungen), "gelesen": "UNREAD" not in labels, "markiert": "STARRED" in labels, "markierungen": markierungen}
                ergebnis.append(kopf)
                if len(ergebnis) >= max:
                    break
            seite = antwort.get("nextPageToken")
            if not seite:
                break
        return ergebnis

    def ordnung(self) -> dict:
        """Liest eigene Gmail-Labels ohne Änderungen."""
        labels = self._dienst().users().labels().list(userId="me").execute().get("labels", [])
        eigene = [x.get("name", "") for x in labels if x.get("type") == "user"]
        rest = max(0, len(eigene) - 30)
        return {"ordner": [], "labels": eigene, "labels_sichtbar": True, "hinweis": f"{rest} weitere Labels nicht ausgewertet" if rest else ""}

    def zuordnung(self, tage: int = 90, je_ordner: int = 200) -> dict:
        """Liest Absender je Gmail-Label innerhalb eines festen Budgets."""
        dienst, ergebnis, seit, rest = self._dienst(), {}, date.today() - timedelta(days=tage), 3000
        for label in self.ordnung()["labels"][:30]:
            if rest <= 0:
                break
            antwort = dienst.users().messages().list(userId="me", q=f'label:"{label}" after:{seit.isoformat()}', maxResults=je_ordner).execute()
            absender = []
            for eintrag in antwort.get("messages", [])[:min(je_ordner, rest)]:
                mail = dienst.users().messages().get(userId="me", id=eintrag["id"], format="metadata", metadataHeaders=["From"]).execute()
                absender.append(parseaddr(_gmail_metadata(mail).get("von", ""))[1].lower())
            rest -= len(absender)
            ergebnis[label] = absender
        return {"ordner": {}, "labels": ergebnis}

    def aufraeumen(self, ident: str, aktion: str, name: str = "") -> str:
        """Entfernt höchstens INBOX oder ergänzt ein Gmail-Label."""
        if aktion == "archivieren":
            dienst = self._dienst()
            dienst.users().messages().modify(userId="me", id=ident, body={"removeLabelIds": ["INBOX"]}).execute()
            return AktionErgebnis("archiviert", ident)
        if ziel_gesperrt(name):
            return "nicht verschoben (Papierkorb/Spam ist gesperrt)"
        dienst = self._dienst()
        labels = dienst.users().labels().list(userId="me").execute().get("labels", [])
        label = next((x for x in labels if x.get("name") == name), None)
        if label is None:
            label = dienst.users().labels().create(userId="me", body={"name": name}).execute()
        body = {"addLabelIds": [label["id"]]}
        if aktion == "ordner":
            body["removeLabelIds"] = ["INBOX"]
        dienst.users().messages().modify(userId="me", id=ident, body=body).execute()
        return AktionErgebnis(f"nach {name} verschoben" if aktion == "ordner" else f"mit Label {name} markiert", ident)

    def zurueckholen(self, eintrag: dict) -> str:
        dienst, ident = self._dienst(), str(eintrag["id"])
        body = {"addLabelIds": ["INBOX"]} if eintrag.get("aktion") in {"archivieren", "ordner"} else {}
        if eintrag.get("aktion") in {"ordner", "label"}:
            labels = dienst.users().labels().list(userId="me").execute().get("labels", [])
            label = next((x for x in labels if x.get("name") == eintrag.get("ziel")), None)
            if label:
                body["removeLabelIds"] = [label["id"]]
        dienst.users().messages().modify(userId="me", id=ident, body=body).execute()
        return "in Posteingang zurückgeholt"

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

    def entwurf(self, an, betreff, text, anhaenge, antwort_auf=None):
        """Legt über die Gmail-API einen Entwurf an."""
        nachricht = _nachricht(an, betreff, text, anhaenge, self.adresse)
        if antwort_auf and antwort_auf.get("message_id"):
            message_id = str(antwort_auf["message_id"])
            nachricht["In-Reply-To"] = message_id
            nachricht["References"] = message_id
        roh = base64.urlsafe_b64encode(
            nachricht.as_bytes()
        ).decode()
        antwort = (
            self._dienst(True)
            .users()
            .drafts()
            .create(userId="me", body={"message": {"raw": roh, **({"threadId": antwort_auf["thread_id"]} if antwort_auf and antwort_auf.get("thread_id") else {})}})
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
        self.nach_ablage(ident, "markieren", label)

    def nach_ablage(self, ident: str, art: str, ordner: str) -> str:
        if ziel_gesperrt(ordner):
            return "nicht verschoben (Papierkorb/Spam ist gesperrt)"
        dienst = self._dienst()
        labels = dienst.users().labels().list(userId="me").execute().get("labels", [])
        label = next((x for x in labels if x.get("name") == ordner), None)
        if label is None:
            label = dienst.users().labels().create(userId="me", body={"name": ordner}).execute()
        body = {"addLabelIds": [label["id"]], "removeLabelIds": ["INBOX"] if art == "verschieben" else []}
        dienst.users().messages().modify(userId="me", id=ident, body=body).execute()
        return ("archiviert und " if art == "verschieben" else "") + f"mit Label {ordner} markiert"


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
