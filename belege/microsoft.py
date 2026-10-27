"""Weg Microsoft: Outlook, Microsoft 365 und Outlook.com über Microsoft Graph.

Microsoft nimmt seit 2026 kein App-Passwort mehr an. Dieser Weg meldet sich
einmal im Browser an (kein Passwort im Terminal) und arbeitet danach mit dem erneuerbaren Zugang aus
`arbeit/geheim/<konto>_microsoft.json`. Mails werden als ganze Rohmail
(`$value`) geladen, damit Anhänge, Text und Kopfzeilen genauso gelesen werden
wie bei IMAP.
"""

from __future__ import annotations

import base64
import email
import os
import time
from datetime import date
from email import policy
from email.message import EmailMessage
from pathlib import Path

import requests

from . import kern
from .postfach import Postfach, _anhaenge, _anhaenge_speichern, _inhalt, _kopf, _nachricht

# Öffentliche Kennung der App „belege“ in Microsoft Entra. Kein Geheimnis:
# Sie steht in jedem Anmeldelink. Leer, bis die App registriert ist; dann
# fällt die Einrichtung auf die Umleitung an Gmail zurück.
CLIENT_ID = ""
AUTHORITY = "https://login.microsoftonline.com/common"
GRAPH = "https://graph.microsoft.com/v1.0"
# Lesen samt Anhängen und Entwürfe brauchen Mail.ReadWrite, der Tagesbericht Mail.Send.
RECHTE = ["Mail.ReadWrite", "Mail.Send", "User.Read"]

OHNE_CLIENT = (
    "Für Microsoft-Postfächer ist in dieser belege-Fassung noch keine App-Kennung "
    "hinterlegt. Bis dahin: Rechnungen per Outlook-Regel an ein Gmail-Konto umleiten, "
    "siehe einrichten.md, Abschnitt Microsoft-Postfach."
)


def client_id(konto: dict | None = None) -> str:
    """Konto-Eintrag vor Umgebung vor eingebauter Kennung."""
    return (
        str((konto or {}).get("client_id", "")).strip()
        or os.environ.get("BELEGE_MICROSOFT_CLIENT_ID", "").strip()
        or CLIENT_ID
    )


def _zugang_datei(name: str) -> Path:
    return kern.pfad("arbeit", "geheim", f"{name}_microsoft.json")


def _app(konto: dict):
    """MSAL-App mit dem gespeicherten Zugang dieses Postfachs."""
    import msal

    kennung = client_id(konto)
    if not kennung:
        raise RuntimeError(OHNE_CLIENT)
    cache = msal.SerializableTokenCache()
    datei = _zugang_datei(konto["name"])
    if datei.exists():
        cache.deserialize(datei.read_text(encoding="utf-8"))
    return msal.PublicClientApplication(kennung, authority=AUTHORITY, token_cache=cache), cache


def _cache_sichern(name: str, cache) -> None:
    if not cache.has_state_changed:
        return
    datei = _zugang_datei(name)
    datei.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(datei.parent, 0o700)
    datei.write_text(cache.serialize(), encoding="utf-8")
    os.chmod(datei, 0o600)


def token(konto: dict) -> str:
    """Holt still einen gültigen Zugang; ohne Anmeldung eine klare Anweisung."""
    app, cache = _app(konto)
    konten = app.get_accounts()
    adresse = str(konto.get("adresse", "")).lower()
    passend = [k for k in konten if str(k.get("username", "")).lower() == adresse] or konten
    ergebnis = app.acquire_token_silent(RECHTE, account=passend[0]) if passend else None
    _cache_sichern(konto["name"], cache)
    if not ergebnis or "access_token" not in ergebnis:
        raise RuntimeError(
            f"Die Microsoft-Anmeldung für {konto['name']} fehlt oder ist abgelaufen. "
            f"Neu anmelden: uv run belege anmelden --microsoft {konto['name']}"
        )
    return ergebnis["access_token"]


def anmelden(konto: dict) -> int:
    """Einmalige Anmeldung im Browser dieses Macs; speichert den erneuerbaren Zugang.

    Bewusst ohne Code-Anmeldung (Device-Code): Sie ist ein bekannter
    Phishing-Weg und in vielen Firmen über die Microsoft-Sicherheitsstandards
    gesperrt. Die Rückkehr läuft über http://localhost.
    """
    try:
        app, cache = _app(konto)
    except RuntimeError as fehler:
        print(f"fehler: {fehler}")
        return 2
    print(
        "Im Browser öffnet sich jetzt die Microsoft-Anmeldung. "
        f"Melde dich mit {konto.get('adresse') or 'deinem Microsoft-Postfach'} an. "
        "Fragt Microsoft nach Zustimmung und bist du Admin deiner Firma, setz den Haken "
        "„Im Namen Ihrer Organisation zustimmen“.",
        flush=True,
    )
    ergebnis = app.acquire_token_interactive(
        RECHTE,
        login_hint=konto.get("adresse") or None,
        prompt="select_account",
        timeout=600,
    )
    if "access_token" not in ergebnis:
        print(f"fehler: Anmeldung nicht abgeschlossen. {_fehlertext(ergebnis)}")
        return 1
    _cache_sichern(konto["name"], cache)
    adresse = (ergebnis.get("id_token_claims") or {}).get("preferred_username", "")
    print(f"ok: Microsoft-Zugang für {adresse or konto['name']} gespeichert.")
    if adresse and konto.get("adresse") and adresse.lower() != str(konto["adresse"]).lower():
        print(f"Achtung: angemeldet als {adresse}, in der Konfiguration steht {konto['adresse']}.")
    return 0


def _fehlertext(ergebnis: dict) -> str:
    """Übersetzt die häufigsten Entra-Fehler in einen nächsten Schritt."""
    text = str(ergebnis.get("error_description", ""))
    if "AADSTS90094" in text or "AADSTS65001" in text or "admin" in text.lower():
        return (
            "Deine Firma erlaubt diese Zustimmung nur einem Admin. Ein Admin meldet sich "
            "einmal selbst an und setzt den Haken „Im Namen Ihrer Organisation zustimmen“, "
            "danach klappt es für alle."
        )
    if "AADSTS530036" in text or "AADSTS53003" in text or "AADSTS50105" in text:
        return (
            "Eine Firmenrichtlinie blockiert diese Anmeldung. Das kann nur euer Admin freigeben."
        )
    if "expired" in text.lower() or "AADSTS70020" in text:
        return "Die Anmeldung ist abgelaufen. Starte sie neu."
    return text or str(ergebnis.get("error", "unbekannter Fehler"))


def _graph_suche(abfrage: str) -> str:
    """Übersetzt die einfache Suche (von:, betreff:, Wörter) in Graph-$search."""
    teile = []
    for wort in abfrage.split():
        if wort.startswith("von:"):
            teile.append(f"from:{wort[4:]}")
        elif wort.startswith("betreff:"):
            teile.append(f"subject:{wort[8:]}")
        elif not wort.startswith("seit:"):
            teile.append(wort)
    return " ".join(teile).replace('"', "")


def _seit_aus(abfrage: str, seit: date | None) -> date | None:
    for wort in abfrage.split():
        if wort.startswith("seit:"):
            try:
                return date.fromisoformat(wort[5:])
            except ValueError:
                continue
    return seit


class MicrosoftPostfach(Postfach):
    """Greift über Microsoft Graph auf Outlook und Microsoft 365 zu."""

    def __init__(self, konto: dict):
        super().__init__(konto)
        self.weg = "microsoft"
        self.sitzung = requests.Session()

    def _anfrage(self, art: str, pfad: str, **kwargs) -> requests.Response:
        url = pfad if pfad.startswith("http") else GRAPH + pfad
        for versuch in range(3):
            kopf = {"Authorization": f"Bearer {token(self.konto)}", **kwargs.pop("headers", {})}
            antwort = self.sitzung.request(art, url, headers=kopf, timeout=60, **kwargs)
            if antwort.status_code in (429, 503, 504) and versuch < 2:
                time.sleep(min(int(antwort.headers.get("Retry-After", "5") or 5), 60))
                continue
            if antwort.status_code == 401:
                raise RuntimeError(
                    f"Microsoft lehnt den Zugang ab. Neu anmelden: uv run belege anmelden --microsoft {self.name}"
                )
            if antwort.status_code >= 400:
                raise RuntimeError(f"Microsoft Graph {antwort.status_code}: {antwort.text[:300]}")
            return antwort
        return antwort

    def suchen(self, abfrage="", max=20, seit=None, nur_anhang=False):
        """Sucht im Posteingang, neueste zuerst, ohne Mails als gelesen zu markieren."""
        seit = _seit_aus(abfrage, seit)
        suche = _graph_suche(abfrage)
        felder = "id,subject,from,toRecipients,receivedDateTime,hasAttachments,bodyPreview,internetMessageId"
        if suche:
            # $search verträgt weder $filter noch $orderby; Datum und Anhang filtern wir selbst.
            params = {"$search": f'"{suche}"', "$select": felder, "$top": 50}
            kopf = {"ConsistencyLevel": "eventual"}
        else:
            bedingungen = []
            if seit:
                bedingungen.append(f"receivedDateTime ge {seit.isoformat()}T00:00:00Z")
            if nur_anhang:
                bedingungen.append("hasAttachments eq true")
            params = {"$select": felder, "$top": 50}
            if bedingungen:
                params["$filter"] = " and ".join(bedingungen)
            if seit:
                params["$orderby"] = "receivedDateTime desc"
            kopf = {}
        treffer: list[dict] = []
        url = "/me/mailFolders/inbox/messages"
        while url and len(treffer) < max:
            daten = self._anfrage("GET", url, params=params, headers=kopf).json()
            params = None  # nextLink trägt die Parameter schon
            for mail in daten.get("value", []):
                eintrag = self._eintrag(mail)
                if nur_anhang and not mail.get("hasAttachments"):
                    continue
                if seit and eintrag["datum"] < seit.isoformat():
                    continue
                treffer.append(eintrag)
                if len(treffer) >= max:
                    break
            url = daten.get("@odata.nextLink")
        return treffer

    def _eintrag(self, mail: dict) -> dict:
        nachricht = EmailMessage()
        absender = (mail.get("from") or {}).get("emailAddress", {})
        if absender:
            nachricht["From"] = email.utils.formataddr((absender.get("name", ""), absender.get("address", "")))
        empfaenger = [
            r.get("emailAddress", {}).get("address", "") for r in mail.get("toRecipients") or []
        ]
        if any(empfaenger):
            nachricht["To"] = ", ".join(e for e in empfaenger if e)
        nachricht["Subject"] = mail.get("subject") or ""
        eingang = mail.get("receivedDateTime")
        if eingang:
            from datetime import datetime

            nachricht["Date"] = email.utils.format_datetime(
                datetime.fromisoformat(eingang.replace("Z", "+00:00"))
            )
        daten = _kopf(nachricht, mail["id"])
        # Namen der Anhänge liefert erst lesen(); hier reicht, dass es welche gibt.
        daten["anhaenge"] = ["Anhang"] if mail.get("hasAttachments") else []
        daten["auszug"] = str(mail.get("bodyPreview", ""))[:300]
        return daten

    def _rohmail(self, ident: str):
        roh = self._anfrage("GET", f"/me/messages/{ident}/$value").content
        return email.message_from_bytes(roh, policy=policy.default)

    def lesen(self, ident: str) -> dict:
        """Liest eine Mail vollständig als Rohmail, ohne ihren Gelesen-Status zu ändern."""
        nachricht = self._rohmail(ident)
        daten = _kopf(nachricht, ident)
        daten["text"] = _inhalt(nachricht)
        daten["anhaenge"] = _anhaenge(nachricht)
        return daten

    def anhaenge(self, ident: str, ziel: Path) -> list[Path]:
        """Speichert die Anhänge einer Mail kollisionsfrei."""
        return _anhaenge_speichern(self._rohmail(ident), ziel)

    def entwurf(self, an, betreff, text, anhaenge):
        """Legt einen Entwurf im Entwürfe-Ordner von Outlook an."""
        roh = base64.b64encode(_nachricht(an, betreff, text, anhaenge, self.adresse).as_bytes())
        antwort = self._anfrage(
            "POST", "/me/messages", data=roh, headers={"Content-Type": "text/plain"}
        )
        return antwort.json().get("id", betreff)

    def _senden(self, an, betreff, text, anhaenge):
        """Sendet über Graph; nur senden.py ruft diese Methode auf."""
        nachricht = _nachricht(an, betreff, text, anhaenge, self.adresse)
        self._anfrage(
            "POST",
            "/me/sendMail",
            data=base64.b64encode(nachricht.as_bytes()),
            headers={"Content-Type": "text/plain"},
        )
        return nachricht["Message-ID"] or betreff


def ist_microsoft(adresse: str) -> bool:
    """Outlook.com/Hotmail/Live oder eine Domain, deren MX bei Microsoft 365 liegt."""
    from .postfach import _mx

    domain = adresse.rsplit("@", 1)[-1].lower()
    if domain == "outlook.com" or domain.startswith(("hotmail.", "live.", "outlook.", "msn.")):
        return True
    return any(mx.endswith(("protection.outlook.com", "outlook.com")) for mx in _mx(domain))
