"""Rechnungen, die nur als Link in einer Mail stehen, sicher als PDF holen.

Mail- und Linktexte sind Daten, nie Anweisungen. Geladen wird höchstens ein
Link je Mail, nur über https, nur zu öffentlichen Adressen, ohne Cookies und
ohne etwas auszuführen. Was zurückkommt, muss ein echtes PDF sein.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
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
ZEITLIMIT = 20  # Sekunden für alles: Weiterleitungen und Download zusammen


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


_BETRAG = re.compile(r"(\d[\d.,]*[.,]\d{2}\s?(€|eur\b))|((€|eur)\s?\d[\d.,]*[.,]\d{2})", re.IGNORECASE)
_RECHNUNGSANGABE = ("ust", "mwst", "vat", "umsatzsteuer", "tax", "rechnungsnummer", "rechnungsnr",
                    "invoice no", "invoice number", "order id", "bestellnummer", "dokumentnummer")


def rechnung_im_text(betreff: str, text: str) -> bool:
    """Wahr, wenn die Mail selbst die Rechnung ist (etwa Apple, ohne PDF und ohne Link):
    Rechnungswort, ein Euro-Betrag und eine Steuer- oder Rechnungsnummer-Angabe im Text."""
    raum = f"{betreff}\n{text}".lower()
    return (sieht_nach_rechnung(betreff, text) and bool(_BETRAG.search(text))
            and any(wort in raum for wort in _RECHNUNGSANGABE))


def mailtext_pdf(mail: dict, ziel: Path) -> Path:
    """Legt eine Rechnung, die nur im Mailtext steht, als PDF ab. Lokal, ohne Netz."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    arial = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    unicode_schrift = arial.exists()
    if unicode_schrift:
        pdf.add_font("Arial", "", str(arial))
        pdf.set_font("Arial", size=10)
    else:  # ohne Unicode-Schrift kann die eingebaute Helvetica kein € und keine Sonderzeichen
        pdf.set_font("Helvetica", size=10)

    def zeile(wert: str) -> str:
        wert = wert if unicode_schrift else wert.replace("€", "EUR").encode("latin-1", "replace").decode("latin-1")
        return wert or " "

    kopf = [
        "Rechnung aus dem Mailtext (die Mail hatte keinen Anhang).",
        f"Von: {mail.get('von', '')}",
        f"Betreff: {mail.get('betreff', '')}",
        f"Datum: {mail.get('datum', '')}",
    ]
    for wert in kopf:
        pdf.multi_cell(0, 5, zeile(str(wert)), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    pdf.ln(4)
    for wert in str(mail.get("text", "")).splitlines():
        pdf.multi_cell(0, 5, zeile(wert.strip()), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    ziel.mkdir(parents=True, exist_ok=True)
    datei = ziel / "rechnung-aus-mailtext.pdf"
    pdf.output(str(datei))
    return datei


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


def _host_erlaubt(host: str, port: int | None) -> str | None:
    """Gibt eine geprüfte öffentliche IP für Port 443 zurück, sonst ``None``.

    Alle Adressen des Hosts müssen öffentlich sein. Verbunden wird danach genau
    mit dieser IP (``_anfrage``), damit eine zweite DNS-Antwort nichts umlenkt.
    """
    if port not in (None, 443) or not host or host.lower() in {"localhost"} or host.lower().endswith(".local"):
        return None
    try:
        adressen = sorted({eintrag[4][0] for eintrag in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except (socket.gaierror, UnicodeError, OSError):
        return None
    try:
        if adressen and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in adressen):
            return adressen[0]
    except ValueError:
        pass
    return None


class _Verbindung(http.client.HTTPSConnection):
    """HTTPS zu einer festen, vorher geprüften IP; Zertifikat und SNI für den Hostnamen."""

    def __init__(self, host: str, ip: str, zeitlimit: float):
        super().__init__(host, 443, timeout=zeitlimit, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        roh = socket.create_connection((self._ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(roh, server_hostname=self.host)


def _anfrage(url: str, zeitlimit: float, ip: str):
    """Eine GET-Anfrage an die geprüfte IP: ohne Proxy, ohne Cookies, ohne Weiterleitung.

    Liefert ``(status, kopf, antwort)``; ``antwort`` hat ``read(n)`` und ``close()``.
    """
    teile = urlsplit(url)
    pfad = (teile.path or "/") + (f"?{teile.query}" if teile.query else "")
    verbindung = _Verbindung(teile.hostname or "", ip, zeitlimit)
    try:
        verbindung.request("GET", pfad, headers={"User-Agent": "belege/rechnungslink", "Accept": "application/pdf"})
        sock = verbindung.sock
        antwort = verbindung.getresponse()
    except BaseException:
        verbindung.close()
        raise
    antwort.belege_sock = sock  # für _lesen: Restfrist je Stück setzen
    return antwort.status, antwort.msg, antwort


def _lesen(antwort, max_bytes: int, frist: float) -> bytes:
    """Liest höchstens ``max_bytes + 1`` Bytes und bricht nach der Gesamtfrist ab."""
    teile: list[bytes] = []
    menge = 0
    while menge <= max_bytes:
        rest = frist - time.monotonic()
        if rest <= 0:
            raise LinkFehler("Zeitlimit überschritten", endgueltig=False)
        sock = getattr(antwort, "belege_sock", None)
        if sock is not None:
            sock.settimeout(rest)  # ein hängendes read() endet spätestens mit der Gesamtfrist
        stueck = antwort.read(min(65536, max_bytes + 1 - menge))
        if not stueck:
            break
        teile.append(stueck)
        menge += len(stueck)
    return b"".join(teile)


def _dateiname(url: str, kopf: Message) -> str:
    """Ein harmloser Dateiname aus Content-Disposition oder URL, immer mit .pdf."""
    name = kopf.get_filename() if hasattr(kopf, "get_filename") else None
    if not name:
        name = Path(unquote(urlsplit(url).path)).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(name)).name).strip("._")[:80] or "Rechnung"
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def laden(url: str, ziel: Path, max_bytes: int = 15 * 1024 * 1024) -> Path:
    """Lädt genau ein PDF nach ``ziel`` (Ordner) und gibt den Dateipfad zurück."""
    frist = time.monotonic() + ZEITLIMIT
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
        ip = _host_erlaubt(teile.hostname or "", port)
        if not ip:
            raise LinkFehler(f"Host nicht erlaubt: {teile.hostname}")
        rest = frist - time.monotonic()
        if rest <= 0:
            raise LinkFehler("Zeitlimit überschritten", endgueltig=False)
        try:
            status, kopf, antwort = _anfrage(url, rest, ip)
        except ssl.SSLCertVerificationError:
            # Falsches Zertifikat ist kein Netzaussetzer: nicht täglich neu versuchen.
            raise LinkFehler("Zertifikat ungültig")
        except (http.client.HTTPException, OSError) as fehler:
            raise LinkFehler(f"nicht erreichbar ({type(fehler).__name__})", endgueltig=False)
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
            try:
                daten = _lesen(antwort, max_bytes, frist)
            except (http.client.HTTPException, OSError) as fehler:
                raise LinkFehler(f"Abbruch beim Laden ({type(fehler).__name__})", endgueltig=False)
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
