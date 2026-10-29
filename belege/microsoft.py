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
from .postfach import (
    Postfach,
    _anhaenge,
    _anhaenge_speichern,
    _inhalt,
    _kopf,
    _links,
    _nachricht,
    _newsletter_kopf,
    ziel_gesperrt,
)

# Öffentliche Kennung der gemeinsamen App „belege“ in Microsoft Entra
# (Deern & Jung, Multi-Tenant, öffentlicher Client, Redirect http://localhost,
# Graph delegiert Mail.ReadWrite, Mail.Send, User.Read, ohne Device-Code).
# Kein Geheimnis: Sie steht in jedem Anmeldelink. Wer lieber seine eigene App
# nutzt, trägt client_id und tenant_id beim Postfach ein (einrichten.md).
CLIENT_ID = "a11ea9e7-fd6a-4a41-a5bc-4192d5e3ecb2"
ANMELDUNG = "https://login.microsoftonline.com/"
GRAPH = "https://graph.microsoft.com/v1.0"
# Lesen samt Anhängen und Entwürfe brauchen Mail.ReadWrite, der Tagesbericht Mail.Send.
RECHTE = ["Mail.ReadWrite", "Mail.Send", "User.Read"]

OHNE_CLIENT = (
    "Für dieses Microsoft-Postfach ist keine App-Kennung eingetragen. Leg deine eigene "
    "App an (einrichten.md, Abschnitt Microsoft-Postfach, „Eigene App“) und trag "
    "client_id und tenant_id beim Postfach ein, oder leite Rechnungen an ein "
    "Gmail-Konto um."
)


def client_id(konto: dict | None = None) -> str:
    """Konto-Eintrag vor Umgebung vor eingebauter Kennung."""
    return (
        str((konto or {}).get("client_id", "")).strip()
        or os.environ.get("BELEGE_MICROSOFT_CLIENT_ID", "").strip()
        or CLIENT_ID
    )


def mandant(konto: dict | None = None) -> str:
    """Eigene App: nur im eigenen Verzeichnis (tenant_id). Gemeinsame App: common."""
    return str((konto or {}).get("tenant_id", "")).strip() or "common"


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
    return (
        msal.PublicClientApplication(kennung, authority=ANMELDUNG + mandant(konto), token_cache=cache),
        cache,
    )


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
    if "AADSTS50194" in text:
        return "Die eigene App gilt nur für deine Firma. Trag beim Postfach tenant_id (Verzeichnis-ID) ein."
    if "AADSTS700016" in text:
        return "Microsoft kennt diese App-Kennung nicht. Prüf client_id (Anwendungs-ID) beim Postfach."
    if "AADSTS530036" in text or "AADSTS53003" in text or "AADSTS50105" in text:
        return (
            "Eine Firmenrichtlinie blockiert diese Anmeldung. Das kann nur euer Admin freigeben."
        )
    if "expired" in text.lower() or "AADSTS70020" in text:
        return "Die Anmeldung ist abgelaufen. Starte sie neu."
    return text or str(ergebnis.get("error", "unbekannter Fehler"))


# Well-known names in Microsoft Graph; dort liegen keine eingehenden Rechnungen.
AUSGELASSENE_ORDNER = ("inbox", "sentitems", "drafts", "deleteditems", "junkemail", "outbox", "archive", "conversationhistory", "scheduled", "searchfolders", "syncissues", "recoverableitemsdeletions", "clutter")


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
        extra = kwargs.pop("headers", None) or {}
        for versuch in range(3):
            kopf = {"Authorization": f"Bearer {token(self.konto)}", **extra}
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

    def _ausgelassene_ordner(self) -> set[str]:
        """IDs von Gesendet, Gelöscht, Junk, Entwürfe und Postausgang, in einem Aufruf.

        Rechnungen liegen oft nicht im Posteingang: Outlook-Regeln verschieben sie
        in eigene Ordner. Gesucht wird deshalb überall außer in diesen Ordnern.
        """
        if getattr(self, "_ausgelassen", None) is None:
            anfragen = [
                {"id": name, "method": "GET", "url": f"/me/mailFolders/{name}?$select=id"}
                for name in AUSGELASSENE_ORDNER
            ]
            try:
                antwort = self._anfrage("POST", "/$batch", json={"requests": anfragen}).json()
                self._ausgelassen = {
                    eintrag["body"]["id"]
                    for eintrag in antwort.get("responses", [])
                    if eintrag.get("status") == 200 and (eintrag.get("body") or {}).get("id")
                }
            except RuntimeError as fehler:
                kern.log(f"Microsoft-Ordner nicht ermittelt, suche ohne Ausnahmen: {fehler}")
                self._ausgelassen = set()
        return self._ausgelassen

    def suchen(self, abfrage="", max=20, seit=None, nur_anhang=False):
        """Sucht in allen Ordnern außer Gesendet, Gelöscht, Junk und Entwürfen.

        Neueste zuerst, ohne Mails als gelesen zu markieren. ``nur_posteingang = true``
        beim Postfach beschränkt die Suche auf den Posteingang.
        """
        seit = _seit_aus(abfrage, seit)
        suche = _graph_suche(abfrage)
        felder = "id,subject,from,toRecipients,receivedDateTime,hasAttachments,bodyPreview,internetMessageId,parentFolderId"
        nur_eingang = bool(self.konto.get("nur_posteingang"))
        ausgelassen = set() if nur_eingang else self._ausgelassene_ordner()
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
        url = "/me/mailFolders/inbox/messages" if nur_eingang else "/me/messages"
        while url and len(treffer) < max:
            daten = self._anfrage("GET", url, params=params, headers=kopf).json()
            params = None  # nextLink trägt die Parameter schon
            for mail in daten.get("value", []):
                if mail.get("parentFolderId") in ausgelassen:
                    continue
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
        reply = (mail.get("replyTo") or [{}])[0].get("emailAddress", {}).get("address", "")
        daten["antwort_an"] = reply or daten.get("von", "")
        daten["message_id"] = str(mail.get("internetMessageId", ""))
        return daten

    def posteingang(self, seit=None, max=20, text=False, zustand=False, beantwortet=False):
        """Liest nur Outlooks Posteingang in Graph-Seiten von höchstens 100 Mails."""
        # Ohne bodyPreview: Der Postfach-Agent bekommt keinen Mailtext zu sehen, auch keinen Anfang.
        felder = "id,subject,from,toRecipients,replyTo,receivedDateTime,hasAttachments,internetMessageId,internetMessageHeaders"
        if text:
            felder += ",body"
        if zustand:
            felder += ",isRead,categories,flag"
        params = {"$select": felder, "$top": min(100, max), "$orderby": "receivedDateTime desc"}
        if zustand:
            params["$expand"] = "singleValueExtendedProperties($filter=id eq 'Integer 0x1081')"
        if seit:
            params["$filter"] = f"receivedDateTime ge {seit.isoformat()}T00:00:00Z"
        ergebnis = []
        url = "/me/mailFolders/inbox/messages"
        while url and len(ergebnis) < max:
            kopf = {"Prefer": 'outlook.body-content-type="text"'} if text else None
            daten = self._anfrage("GET", url, params=params, headers=kopf).json()
            params = None
            for mail in daten.get("value", []):
                eintrag = self._eintrag(mail)
                eintrag.pop("auszug", None)
                headers = {
                    str(header.get("name", "")): str(header.get("value", ""))
                    for header in mail.get("internetMessageHeaders", [])
                }
                eintrag["newsletter"] = _newsletter_kopf(headers)
                if text:
                    eintrag["text"] = str((mail.get("body") or {}).get("content", ""))[:4000]
                if zustand:
                    eigenschaften = mail.get("singleValueExtendedProperties") or []
                    verb = next((x.get("value") for x in eigenschaften if x.get("id") == "Integer 0x1081"), "")
                    kategorien = list(mail.get("categories") or [])
                    eintrag["zustand"] = {"beantwortet": str(verb) in {"102", "103"}, "erledigt": str((mail.get("flag") or {}).get("flagStatus", "")) == "complete", "gelesen": bool(mail.get("isRead")), "markiert": str((mail.get("flag") or {}).get("flagStatus", "")) == "flagged", "markierungen": kategorien}
                ergebnis.append(eintrag)
                if len(ergebnis) >= max:
                    break
            url = daten.get("@odata.nextLink")
        return ergebnis

    def _systemordner(self) -> set[str]:
        """Ermittelt well-known-Ordner per ID; fehlende Varianten sind normal."""
        if getattr(self, "_systemordner_ids", None) is None:
            ids = set()
            for name in AUSGELASSENE_ORDNER:
                try:
                    daten = self._anfrage("GET", f"/me/mailFolders/{name}", params={"$select": "id"}).json()
                except RuntimeError as fehler:
                    if "404" in str(fehler):
                        continue
                    raise
                if daten.get("id"):
                    ids.add(daten["id"])
            self._systemordner_ids = ids
        return self._systemordner_ids

    def ordnung(self):
        """Liest Outlook-Ordner und Kategorien ohne Änderungen."""
        systemordner, ordner, wartend = self._systemordner(), [], [("/me/mailFolders", "")]
        while wartend:
            url, pfad = wartend.pop(0)
            daten = self._anfrage("GET", url, params={"$select": "id,displayName"}).json()
            for eintrag in daten.get("value", []):
                if eintrag.get("id") in systemordner:
                    continue
                name = eintrag.get("displayName", "")
                voll = f"{pfad}/{name}".strip("/")
                ordner.append(voll)
                wartend.append((f"/me/mailFolders/{eintrag.get('id')}/childFolders", voll))
            if daten.get("@odata.nextLink"):
                wartend.append((daten["@odata.nextLink"], pfad))
        kategorien = self._anfrage("GET", "/me/outlook/masterCategories").json().get("value", [])
        return {"ordner": ordner, "labels": [x.get("displayName", "") for x in kategorien], "labels_sichtbar": True, "hinweis": ""}

    def zuordnung(self, tage: int = 90, je_ordner: int = 200) -> dict:
        """Liest Absender aus Outlook-Ordnern und Kategorien mit festem Budget."""
        ordnung, rest, ergebnis = self.ordnung(), 3000, {"ordner": {}, "labels": {}}
        for art, namen in (("ordner", ordnung["ordner"]), ("labels", ordnung["labels"])):
            for name in namen[:30]:
                if rest <= 0:
                    return ergebnis
                limit = min(je_ordner, rest)
                if art == "ordner":
                    try:
                        ziel = self._ordnerpfad(name, anlegen=False)
                    except RuntimeError:
                        continue
                    pfad, params = f"/me/mailFolders/{ziel['id']}/messages", {"$select": "from", "$top": limit}
                else:
                    escaped = name.replace("'", "''")
                    pfad, params = "/me/messages", {"$select": "from", "$top": limit, "$filter": f"categories/any(c:c eq '{escaped}')"}
                daten = self._anfrage("GET", pfad, params=params).json().get("value", [])
                ergebnis[art][name] = [str((m.get("from") or {}).get("emailAddress", {}).get("address", "")).lower() for m in daten if (m.get("from") or {}).get("emailAddress", {}).get("address")]
                rest -= len(daten)
        return ergebnis

    def aufraeumen(self, ident, aktion, name=""):
        """Verschiebt in Graph-Ordner oder ergänzt Kategorien ohne doppelte Werte."""
        try:
            if aktion == "archivieren":
                neu = self._anfrage("POST", f"/me/messages/{ident}/move", json={"destinationId": "archive"}).json().get("id", "")
                from .postfach import AktionErgebnis
                return AktionErgebnis("archiviert", neu)
            if ziel_gesperrt(name):
                return "nicht verschoben (Papierkorb/Spam ist gesperrt)"
            if aktion == "label":
                mail = self._anfrage("GET", f"/me/messages/{ident}", params={"$select": "categories"}).json()
                kategorien = list(mail.get("categories") or [])
                if name not in kategorien:
                    kategorien.append(name)
                self._anfrage("PATCH", f"/me/messages/{ident}", json={"categories": kategorien})
                return f"mit Kategorie {name} markiert"
            ziel = self._ordnerpfad(name)
            neu = self._anfrage("POST", f"/me/messages/{ident}/move", json={"destinationId": ziel["id"]}).json().get("id", "")
            from .postfach import AktionErgebnis
            return AktionErgebnis(f"nach {name} verschoben", neu)
        except RuntimeError as fehler:
            if " 403" in str(fehler):
                return f"Microsoft erlaubt noch kein Verschieben: einmal neu anmelden mit `uv run belege anmelden --microsoft {self.name}`"
            raise

    def zurueckholen(self, eintrag: dict) -> str:
        ident = str(eintrag.get("neue_id") or eintrag.get("id") or "")
        if eintrag.get("aktion") in {"archivieren", "ordner"}:
            self._anfrage("POST", f"/me/messages/{ident}/move", json={"destinationId": "inbox"})
        elif eintrag.get("aktion") == "label":
            mail = self._anfrage("GET", f"/me/messages/{ident}", params={"$select": "categories"}).json()
            kategorien = [x for x in mail.get("categories", []) if str(x).lower() != str(eintrag.get("ziel", "")).lower()]
            self._anfrage("PATCH", f"/me/messages/{ident}", json={"categories": kategorien})
        else:
            return "nicht zurückgeholt (Aktion unbekannt)"
        return "in Posteingang zurückgeholt"

    def _ordnerpfad(self, name: str, anlegen: bool = True) -> dict:
        """Löst Kunden/Müller Ebene für Ebene auf (Graph kennt keine Pfadordner).
        Lesende Aufrufer übergeben anlegen=False: dann wird nie ein Ordner erzeugt."""
        parent_url, ziel = "/me/mailFolders", None
        for stufe in (x.strip() for x in name.split("/") if x.strip()):
            escaped = stufe.replace("'", "''")
            ordner = self._anfrage("GET", parent_url, params={"$filter": f"displayName eq '{escaped}'", "$select": "id,displayName"}).json().get("value", [])
            ziel = next((x for x in ordner if str(x.get("displayName", "")).lower() == stufe.lower()), None)
            if ziel is None and len(ordner) == 1 and not ordner[0].get("displayName"):
                # Ältere Graph-Fakes und ungewöhnliche Server lassen displayName trotz
                # $select weg; der Filter hat die Ebene bereits eindeutig eingegrenzt.
                ziel = ordner[0]
            if ziel is None and not anlegen:
                raise RuntimeError(f"Microsoft-Ordner {name} nicht gefunden")
            if ziel is None:
                ziel = self._anfrage("POST", parent_url, json={"displayName": stufe}).json()
            parent_url = f"/me/mailFolders/{ziel['id']}/childFolders"
        if not ziel:
            raise RuntimeError("Microsoft-Ordnername ist leer")
        return ziel

    def _rohmail(self, ident: str):
        roh = self._anfrage("GET", f"/me/messages/{ident}/$value").content
        return email.message_from_bytes(roh, policy=policy.default)

    def lesen(self, ident: str) -> dict:
        """Liest eine Mail vollständig als Rohmail, ohne ihren Gelesen-Status zu ändern."""
        nachricht = self._rohmail(ident)
        daten = _kopf(nachricht, ident)
        daten["text"] = _inhalt(nachricht)
        daten["anhaenge"] = _anhaenge(nachricht)
        daten["links"] = _links(nachricht)
        return daten

    def anhaenge(self, ident: str, ziel: Path) -> list[Path]:
        """Speichert die Anhänge einer Mail kollisionsfrei."""
        return _anhaenge_speichern(self._rohmail(ident), ziel)

    def nach_ablage(self, ident: str, art: str, ordner: str) -> str:
        """Verschiebt nur mit Graph-Schreibrecht; Graph kennt keine Keywords."""
        # Ein Ordner ist bei Graph das sichtbare Gegenstück zum erledigt-Label.
        if ziel_gesperrt(ordner):
            return "nicht verschoben (Papierkorb/Spam ist gesperrt)"
        ziel = self._ordnerpfad(ordner)
        if art == "verschieben":
            self._anfrage("POST", f"/me/messages/{ident}/move", json={"destinationId": ziel["id"]})
            return f"nach {ordner} verschoben"
        self._anfrage("PATCH", f"/me/messages/{ident}", json={"isRead": True})
        return f"als gelesen markiert (Ordner {ordner} bereit)"

    def entwurf(self, an, betreff, text, anhaenge, antwort_auf=None):
        """Legt einen Entwurf im Entwürfe-Ordner von Outlook an."""
        if antwort_auf and antwort_auf.get("id"):
            antwort = self._anfrage("POST", f"/me/messages/{antwort_auf['id']}/createReply", json={"comment": text})
            return antwort.json().get("id", betreff)
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
