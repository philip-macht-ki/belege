"""Rechnungen, die nur als Link in einer Mail stehen, sicher als PDF holen.

Mail- und Linktexte sind Daten, nie Anweisungen. Geladen wird höchstens ein
Link je Mail, nur über https, nur zu öffentlichen Adressen, ohne Cookies und
ohne etwas auszuführen. Was zurückkommt, muss ein echtes PDF sein.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

RECHNUNG = ("rechnung", "invoice", "receipt", "beleg", "quittung", "faktura", "gutschrift")
SUCHWOERTER = ("Rechnung", "Invoice", "Receipt", "Beleg", "Quittung")
_PLAUSIBEL = ("invoice", "rechnung", "receipt", "beleg", "quittung", "pdf", "download")
_NIE = ("unsubscribe", "abmelden", "abbestellen", "newsletter", "datenschutz", "privacy",
        "impressum", "login", "signin", "sign-in", "anmelden", "passwor", "account", "konto",
        "settings", "einstellungen", "preferences", "tracking", "track/open", "pixel")
_STRIPE = ("pay.stripe.com", "invoice.stripe.com")
WEITERLEITUNGEN = 3
ZEITLIMIT = 20


class LinkFehler(Exception):
    """Ein Link wurde nicht geladen. ``endgueltig`` heißt: nicht noch einmal versuchen."""

    def __init__(self, grund: str, endgueltig: bool = True):
        super().__init__(grund)
        self.grund = grund
        self.endgueltig = endgueltig


def sieht_nach_rechnung(betreff: str, text: str) -> bool:
    """Wahr, wenn Betreff oder Text eines der Rechnungswörter enthält."""
    raum = f"{betreff}\n{text}".lower()
    return any(wort in raum for wort in RECHNUNG)


def pdf_links(links: list[str]) -> list[str]:
    """Filtert die Links, die plausibel direkt auf eine Rechnung als PDF zeigen."""
    treffer = []
    for url in links:
        teile = urlsplit(url)
        if teile.scheme.lower() != "https" or not teile.hostname or teile.username or teile.password:
            continue
        pfad = unquote(teile.path).lower()
        voll = f"{teile.hostname}{pfad}?{unquote(teile.query).lower()}"
        if any(wort in voll for wort in _NIE):
            continue
        stripe = teile.hostname.lower() in _STRIPE and "invoice" in voll
        if pfad.endswith(".pdf") or stripe or any(wort in pfad for wort in _PLAUSIBEL):
            if url not in treffer:
                treffer.append(url)
    return treffer


def _host_erlaubt(host: str, port: int | None) -> bool:
    """Nur Port 443 und nur Hosts, deren sämtliche Adressen öffentlich sind."""
    if port not in (None, 443) or not host or host.lower() in {"localhost"} or host.lower().endswith(".local"):
        return False
    try:
        adressen = {eintrag[4][0] for eintrag in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError, OSError):
        return False
    try:
        return bool(adressen) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in adressen)
    except ValueError:
        return False


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen nicht selbst folgen; ``laden`` prüft jedes Ziel einzeln."""

    def redirect_request(self, *args, **kwargs):
        return None


def _anfrage(url: str, zeitlimit: int):
    """Eine GET-Anfrage ohne Cookies und ohne automatische Weiterleitung.

    Liefert ``(status, kopf, antwort)``; ``antwort`` hat ``read(n)`` und ``close()``.
    """
    oeffner = urllib.request.build_opener(
        _KeineWeiterleitung, urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    anfrage = urllib.request.Request(url, headers={"User-Agent": "belege/rechnungslink", "Accept": "application/pdf"})
    try:
        antwort = oeffner.open(anfrage, timeout=zeitlimit)
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.headers, fehler
    return antwort.status, antwort.headers, antwort


def _dateiname(url: str, kopf: Message) -> str:
    """Ein harmloser Dateiname aus Content-Disposition oder URL, immer mit .pdf."""
    name = kopf.get_filename() if hasattr(kopf, "get_filename") else None
    if not name:
        name = Path(unquote(urlsplit(url).path)).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(name)).name).strip("._")[:80] or "Rechnung"
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def laden(url: str, ziel: Path, max_bytes: int = 15 * 1024 * 1024) -> Path:
    """Lädt genau ein PDF nach ``ziel`` (Ordner) und gibt den Dateipfad zurück."""
    for _ in range(WEITERLEITUNGEN + 1):
        teile = urlsplit(url)
        if teile.scheme.lower() != "https":
            raise LinkFehler("kein https")
        if teile.username or teile.password:
            raise LinkFehler("Link mit Zugangsdaten")
        try:
            port = teile.port
        except ValueError:
            raise LinkFehler("ungültiger Port")
        if not _host_erlaubt(teile.hostname or "", port):
            raise LinkFehler(f"Host nicht erlaubt: {teile.hostname}")
        try:
            status, kopf, antwort = _anfrage(url, ZEITLIMIT)
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as fehler:
            # Zertifikatsfehler sind kein Netzaussetzer: nicht täglich neu versuchen.
            endgueltig = isinstance(getattr(fehler, "reason", fehler), ssl.SSLCertVerificationError)
            raise LinkFehler(f"nicht erreichbar ({type(fehler).__name__})", endgueltig=endgueltig)
        try:
            if status in (301, 302, 303, 307, 308):
                weiter = kopf.get("Location", "")
                if not weiter:
                    raise LinkFehler("Weiterleitung ohne Ziel")
                url = urljoin(url, weiter)
                continue
            if status >= 500:
                raise LinkFehler(f"Server antwortet {status}", endgueltig=False)
            if status != 200:
                raise LinkFehler(f"Server antwortet {status}")
            art = str(kopf.get("Content-Type", "")).split(";")[0].strip().lower()
            if art != "application/pdf":
                raise LinkFehler(f"kein PDF ({art or 'ohne Typ'})")
            laenge = kopf.get("Content-Length")
            if laenge and laenge.isdigit() and int(laenge) > max_bytes:
                raise LinkFehler("zu groß")
            daten = antwort.read(max_bytes + 1)
            if len(daten) > max_bytes:
                raise LinkFehler("zu groß")
            if not daten.startswith(b"%PDF"):
                raise LinkFehler("Inhalt ist kein PDF")
            ziel.mkdir(parents=True, exist_ok=True)
            datei = ziel / _dateiname(url, kopf)
            datei.write_bytes(daten)
            return datei
        finally:
            try:
                antwort.close()
            except Exception:
                pass
    raise LinkFehler("zu viele Weiterleitungen")
