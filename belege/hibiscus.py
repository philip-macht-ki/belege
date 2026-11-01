"""Optional: Kontoumsätze aus Hibiscus/Jameica als CSV schreiben.

Es werden ausschließlich die dokumentierten XML-RPC-Lesemethoden
``hibiscus.xmlrpc.konto.find`` und ``hibiscus.xmlrpc.umsatz.list`` verwendet.
Der lokale Jameica-Dienst muss bereits laufen und die Umsätze selbst abrufen;
dieses Modul löst weder einen Abruf noch Zahlungsaufträge aus.
"""
from __future__ import annotations

import base64
import csv
import io
import os
import ssl
import subprocess
import tempfile
import urllib.error
import xmlrpc.client
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from . import kern
from .moneymoney import AMEX_SPALTEN, BANK_SPALTEN, FORMATE, letzter_tag, monate
from .plattform import ist_windows

URL = "https://127.0.0.1:8080/xmlrpc/"
_SCHLUESSELBUND_SERVICE = "belege-hibiscus"
_SCHLUESSELBUND_KONTO = "jameica"


class HibiscusFehler(RuntimeError):
    """Ein absichtlich allgemein gehaltener Verbindungsfehler ohne Geheimnisse."""


class _LokalerTransport(xmlrpc.client.SafeTransport):
    """TLS-Prüfung und Basic-Auth nur für den festen lokalen Jameica-Dienst."""

    def __init__(self, passwort: str):
        super().__init__(context=ssl._create_unverified_context())
        self._auth = base64.b64encode(("admin:" + passwort).encode("utf-8")).decode("ascii")

    def send_headers(self, connection, headers):
        super().send_headers(connection, headers)
        connection.putheader("Authorization", "Basic " + self._auth)


def einstellungen() -> dict:
    """Liest die optionale Hibiscus-Konfiguration; fehlt sie, ist Hibiscus aus."""
    try:
        return kern.konfig("hibiscus")
    except FileNotFoundError:
        return {"an": False}


def _passwort_datei() -> Path:
    return kern.pfad("arbeit", "geheim", "hibiscus_master_passwort.txt")


def passwort() -> str | None:
    """Liest das Jameica-Master-Passwort intern, nie aus der Konfiguration."""
    if ist_windows():
        datei = _passwort_datei()
        if not datei.exists():
            return None
        script = "$s=Get-Content -LiteralPath $args[0] | ConvertTo-SecureString; $b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try {[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)}"
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script, "--", str(datei)], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.rstrip("\n") if r.returncode == 0 and r.stdout else None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", _SCHLUESSELBUND_SERVICE, "-a", _SCHLUESSELBUND_KONTO, "-w"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.rstrip("\n") if r.returncode == 0 and r.stdout else None


def passwort_speichern() -> int:
    """Fragt das Master-Passwort verdeckt ab und speichert es wie ein App-Passwort."""
    if ist_windows():
        ziel = _passwort_datei()
        ziel.parent.mkdir(parents=True, exist_ok=True)
        script = ("Add-Type -AssemblyName Microsoft.VisualBasic; "
                  "$p=[Microsoft.VisualBasic.Interaction]::InputBox('Jameica-Master-Passwort einfügen', 'Belege'); "
                  "if($p){$p | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $args[0] -NoNewline; exit 0}; exit 1")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script, "--", str(ziel)], capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as fehler:
            print(f"fehler: Passwort-Dialog nicht geöffnet: {fehler}")
            return 1
        if r.returncode:
            print("nichts: Master-Passwort-Eingabe abgebrochen.")
            return 0
        print("ok: Jameica-Master-Passwort geschützt für diesen Windows-Benutzer gespeichert.")
        return 0
    script = ('tell application "System Events" to activate\n'
              'display dialog "Jameica-Master-Passwort einfügen" default answer "" with hidden answer buttons {"Abbrechen", "Speichern"} default button "Speichern" cancel button "Abbrechen"')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as fehler:
        print(f"fehler: Schlüsselbund-Dialog nicht geöffnet: {fehler}")
        return 1
    if r.returncode:
        print("nichts: Master-Passwort-Eingabe abgebrochen.")
        return 0
    geheim = r.stdout.rsplit("text returned:", 1)[-1].strip()
    if not geheim:
        print("nichts: Kein Master-Passwort eingegeben.")
        return 0
    try:
        gespeichert = subprocess.run(["security", "add-generic-password", "-U", "-s", _SCHLUESSELBUND_SERVICE, "-a", _SCHLUESSELBUND_KONTO, "-w", geheim], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as fehler:
        print(f"fehler: Master-Passwort nicht im Schlüsselbund gespeichert: {fehler}")
        return 1
    if gespeichert.returncode:
        print("fehler: Master-Passwort nicht im Schlüsselbund gespeichert.")
        return 1
    print("ok: Jameica-Master-Passwort im Schlüsselbund gespeichert.")
    return 0


def verbindung(geheim: str) -> xmlrpc.client.ServerProxy:
    """Der einzige Endpunkt ist Loopback; nur dort ist das Jameica-Zertifikat erlaubt."""
    return xmlrpc.client.ServerProxy(URL, transport=_LokalerTransport(geheim), allow_none=True)


def _aufruf(geheim: str, methode: str, *argumente):
    try:
        server = verbindung(geheim)
        ziel = server
        for teil in methode.split("."):
            ziel = getattr(ziel, teil)
        return ziel(*argumente)
    except (OSError, ssl.SSLError, urllib.error.URLError, xmlrpc.client.ProtocolError) as fehler:
        # Ein HTTP 401 ist absichtlich nicht genauer: weder Passwort noch Antwort ausgeben.
        if isinstance(fehler, xmlrpc.client.ProtocolError) and fehler.errcode in {401, 403}:
            raise HibiscusFehler("Jameica-Master-Passwort wurde nicht akzeptiert.") from fehler
        raise HibiscusFehler("Jameica ist nicht erreichbar. Starte Jameica und prüfe, ob die XML-RPC-Plugins laufen.") from fehler
    except xmlrpc.client.Fault as fehler:
        raise HibiscusFehler("Hibiscus-XML-RPC antwortet nicht wie erwartet. Prüfe die aktivierten Dienste konto und umsatz.") from fehler


def konten_hibiscus(geheim: str) -> list[dict]:
    return list(_aufruf(geheim, "hibiscus.xmlrpc.konto.find"))


def umsaetze_hibiscus(geheim: str, konto_id, von: date, bis: date) -> list[dict]:
    optionen = {"konto_id": str(konto_id), "datum:min": von.isoformat(), "datum:max": bis.isoformat()}
    return list(_aufruf(geheim, "hibiscus.xmlrpc.umsatz.list", optionen))


def _ohne_leer(wert: str) -> str:
    return "".join(str(wert).split()).upper()


def finde(konten: list[dict], kennung: str) -> dict | None:
    gesucht = _ohne_leer(kennung)
    treffer = [k for k in konten if any(_ohne_leer(k.get(feld, "")) == gesucht or _ohne_leer(k.get(feld, "")).endswith(gesucht) for feld in ("iban", "kontonummer"))]
    return treffer[0] if gesucht and len(treffer) == 1 else None


def _tag(wert) -> date:
    text = str(wert).strip()
    if "." in text:
        return date.fromisoformat("-".join(reversed(text.split("."))))
    return date.fromisoformat(text[:10])


def _betrag(wert) -> Decimal:
    text = str(wert).strip().replace(".", "").replace(",", ".")
    return Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _komma(wert: Decimal) -> str:
    return format(wert, ".2f").replace(".", ",")


def csv_inhalt(format: str, umsaetze: list[dict], konto: str = "", waehrung: str = "EUR") -> bytes:
    aus = io.StringIO(newline="")
    if format in {"amex", "kreditkarte"}:
        schreiber = csv.DictWriter(aus, fieldnames=AMEX_SPALTEN)
        schreiber.writeheader()
        for u in umsaetze:
            schreiber.writerow({"Datum": f"{_tag(u['datum']):%d.%m.%Y}", "Beschreibung": " ".join(x for x in (str(u.get("empfaenger_name", "")).strip(), str(u.get("zweck", "")).strip()) if x), "Betrag": _komma(-_betrag(u["betrag"])), "Konto": konto})
    elif format == "bank":
        schreiber = csv.DictWriter(aus, fieldnames=BANK_SPALTEN, delimiter=";", quoting=csv.QUOTE_ALL)
        schreiber.writeheader()
        for u in umsaetze:
            schreiber.writerow({"Buchungstag": f"{_tag(u['datum']):%d.%m.%Y}", "Valutadatum": f"{_tag(u.get('valuta') or u['datum']):%d.%m.%Y}", "Buchungstext": u.get("art", ""), "Verwendungszweck": u.get("zweck", ""), "Beguenstigter/Zahlungspflichtiger": u.get("empfaenger_name", ""), "Kontonummer/IBAN": u.get("empfaenger_konto", ""), "BIC (SWIFT-Code)": u.get("empfaenger_blz", ""), "Betrag": _komma(_betrag(u["betrag"])), "Waehrung": waehrung or "EUR", "Konto": konto})
    else:
        raise ValueError(f"unbekanntes Format {format!r}, erlaubt: {', '.join(FORMATE)}")
    return b"\xef\xbb\xbf" + aus.getvalue().encode("utf-8")


def dateiname(eintrag: dict, erster: date) -> str:
    name = "".join(z if z.isalnum() or z in "-_" else "_" for z in str(eintrag.get("name") or "Konto"))
    return f"{erster:%Y-%m}_{name}_Hibiscus.csv"


def ordner(eintrag: dict, testordner: str | None) -> Path:
    if testordner:
        return kern.erweitert(testordner)
    standard = kern.konfig("belege").get("monat", {}).get("auszuege", "~/Belege/Kontoauszuege")
    return kern.erweitert(eintrag.get("ordner") or standard)


def schreiben(ziel: Path, inhalt: bytes) -> bool:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists() and ziel.read_bytes() == inhalt:
        return False
    with tempfile.NamedTemporaryFile(dir=ziel.parent, delete=False) as datei:
        datei.write(inhalt)
        temp = datei.name
    os.replace(temp, ziel)
    return True


def befehl_konten() -> int:
    geheim = passwort()
    if not geheim:
        print("fehler: Jameica-Master-Passwort fehlt. Speichere es mit: belege hibiscus passwort")
        return 2
    try:
        bekannt = konten_hibiscus(geheim)
    except HibiscusFehler as fehler:
        print(f"fehler: {fehler}")
        return 1
    for konto in bekannt:
        print(f"{konto.get('bezeichnung', '')} | {konto.get('iban') or konto.get('kontonummer', '')}")
    return 0


def befehl(args) -> int:
    """`belege hibiscus [konten|passwort] [--echt] [--testordner PFAD]`."""
    ziel = (getattr(args, "ziel", None) or [""])[0]
    if ziel == "passwort":
        return passwort_speichern()
    if ziel == "konten":
        return befehl_konten()
    cfg = einstellungen()
    eintraege = cfg.get("konto", [])
    if not cfg.get("an") and not getattr(args, "testordner", None):
        print("nichts: Hibiscus ist aus. Einschalten in konfig/hibiscus.toml, siehe einrichten_hibiscus.md.")
        return 0
    if not eintraege:
        print("fehler: In konfig/hibiscus.toml steht noch kein [[konto]].")
        return 2
    falsch = [e.get("name", "?") for e in eintraege if e.get("format") not in FORMATE]
    if falsch:
        print(f"fehler: Format fehlt oder unbekannt bei {', '.join(falsch)}. Erlaubt: {', '.join(FORMATE)}.")
        return 2
    geheim = passwort()
    if not geheim:
        print("fehler: Jameica-Master-Passwort fehlt. Speichere es mit: belege hibiscus passwort")
        return 2
    try:
        bekannt = konten_hibiscus(geheim)
    except HibiscusFehler as fehler:
        text = str(fehler)
        kern.ereignis("monat", text)
        print(f"fehler: {text}")
        return 1
    echt = kern.echt(args)
    liste = monate(int(cfg.get("monate", 2)), kern.jetzt().date())
    fehler_gesamt = 0
    for eintrag in eintraege:
        name = str(eintrag.get("name", "Konto"))
        konto = finde(bekannt, str(eintrag.get("kennung", "")))
        if not konto:
            print(f"fehler: Hibiscus: Konto {name} nicht gefunden oder nicht eindeutig. Prüfe die Kennung in konfig/hibiscus.toml.")
            fehler_gesamt += 1
            continue
        try:
            alle = umsaetze_hibiscus(geheim, konto["id"], liste[-1], letzter_tag(liste[0]))
        except (HibiscusFehler, KeyError) as fehler:
            print(f"fehler: Umsätze von {name} nicht lesbar: {fehler}")
            fehler_gesamt += 1
            continue
        for erster in liste:
            ende = letzter_tag(erster)
            zeilen = sorted((u for u in alle if erster <= _tag(u["datum"]) <= ende), key=lambda u: _tag(u["datum"]))
            ausgabe = ordner(eintrag, getattr(args, "testordner", None)) / dateiname(eintrag, erster)
            if not echt:
                print(f"trocken: würde schreiben {ausgabe} ({len(zeilen)} Buchungen)")
                continue
            neu = schreiben(ausgabe, csv_inhalt(eintrag["format"], zeilen, str(eintrag.get("kennung", "")), str(konto.get("waehrung", "EUR"))))
            print(f"{'ok' if neu else 'gleich'}: {ausgabe} ({len(zeilen)} Buchungen)")
    return 1 if fehler_gesamt else 0
