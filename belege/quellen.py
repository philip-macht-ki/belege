"""Funde aus Postfach, Handy und Downloads bereitstellen.

Die Quellen verändern keine Originale. Erst die Verarbeitung mit ``--echt``
legt ab oder verschiebt die dafür vorgesehenen Dateien.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

from . import kern
from .typen import Fund

ENDUNGEN = {".pdf", ".xml", ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".docx"}


def _gesehen() -> dict:
    """Liest den kleinen Fortschrittsstand oder beginnt bei einem leeren Stand."""
    return kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}


def _mail_datum(mail: dict) -> date:
    """Liest das Maildatum und nimmt bei einem defekten Datum den heutigen Tag."""
    try:
        return date.fromisoformat(str(mail.get("datum", ""))[:10])
    except ValueError:
        return kern.jetzt().date()


def _erlaubt(datei: Path) -> bool:
    """Prüft die vereinbarten Beleg-Endungen und überspringt versteckte Dateien."""
    return datei.is_file() and not datei.name.startswith(".") and datei.suffix.lower() in ENDUNGEN


def _ausgeschlossen(mail: dict) -> bool:
    """Prüft Ausschlüsse vor dem Herunterladen von Mailanhängen."""
    suchraum = " ".join(str(mail.get(name, "")) for name in ("von", "von_name", "betreff")).lower()
    muster = kern.konfig("regeln").get("ausschluss", [])
    return any(str(wert).lower() in suchraum for wert in muster)


def _mail_tmp(konto: str, mail_id: str) -> Path:
    """Bildet aus der Mail-ID einen sicheren, gut lesbaren temporären Ordnernamen."""
    sicher = "".join(zeichen if zeichen.isalnum() or zeichen in "-_" else "_" for zeichen in mail_id)
    return kern.pfad("arbeit", "tmp", f"{konto}-{sicher}")


def postfach_funde(konto: str, tage: int | None = None):
    """Liefert neue passende Anhänge aus genau einem konfigurierten Postfach.

    Der Takt übernimmt bewusst die Schleife über mehrere Konten. Gesehene Mails
    werden erst nach erfolgreicher Verarbeitung über ``mail_erledigt`` markiert.
    """
    from .postfach import oeffnen

    postfach = oeffnen(konto)
    stand = _gesehen().get(konto, {})
    konfiguration = kern.konfig("belege").get("postfach", {})
    anzahl_tage = tage
    if anzahl_tage is None:
        anzahl_tage = int(konfiguration.get("laufend_tage", 3) if stand.get("stand") else
                           konfiguration.get("erste_tage", 30))
    seit = kern.jetzt().date() - timedelta(days=anzahl_tage)
    mails = postfach.suchen(seit=seit, nur_anhang=True)
    if getattr(postfach, "weg", "") == "b":
        mails.extend(postfach.mit_label(str(konfiguration.get("label", "Beleg"))))
    bekannte = set(stand.get("mails", []))
    eindeutig = {mail.get("id"): mail for mail in mails if mail.get("id")}
    for mail_id, mail in eindeutig.items():
        if mail_id in bekannte or _ausgeschlossen(mail):
            continue
        ziel = _mail_tmp(konto, str(mail_id))
        dateien = postfach.anhaenge(str(mail_id), ziel)
        for datei in dateien:
            if not _erlaubt(datei):
                continue
            if datei.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}:
                if datei.stat().st_size < 20 * 1024:
                    continue
            kopf = dict(mail)
            kopf["konto"] = konto
            yield Fund(datei, "postfach", datei.name, _mail_datum(mail), kopf)


def mail_erledigt(konto: str, mail_id: str, echt: bool):
    """Merkt eine vollständig verarbeitete Mail nur mit ``--echt`` als erledigt vor."""
    if not echt:
        return
    gesehen = _gesehen()
    daten = gesehen.setdefault(konto, {"mails": []})
    mails = daten.setdefault("mails", [])
    if mail_id not in mails:
        mails.append(mail_id)
    daten["stand"] = kern.jetzt().isoformat()
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    from .postfach import oeffnen

    postfach = oeffnen(konto)
    if getattr(postfach, "weg", "") == "b":
        label = str(kern.konfig("belege").get("postfach", {}).get("label", "Beleg"))
        postfach.label_erledigt(mail_id, f"{label}/erledigt")


def handy_funde():
    """Liefert alle sichtbaren Dateien aus dem Handy-Ordner, ohne sie zu verschieben."""
    ordner = kern.erweitert(kern.konfig("belege").get("quellen", {}).get("handy_ordner", ""))
    if not ordner.exists():
        return
    for datei in sorted(ordner.iterdir()):
        if not _erlaubt(datei):
            continue
        eingang = date.fromtimestamp(datei.stat().st_mtime)
        if datei.suffix.lower() != ".heic":
            yield Fund(datei, "handy", datei.name, eingang, verschieben=True)
            continue
        ziel = kern.pfad("arbeit", "tmp", f"{datei.stem}.jpg")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        kern.lauf(["sips", "-s", "format", "jpeg", str(datei), "--out", str(ziel)])
        fund = Fund(ziel, "handy", f"{datei.stem}.jpg", eingang, verschieben=True)
        fund.handy_original = datei
        yield fund


def _sha(datei: Path) -> str:
    """Berechnet den stabilen Fingerabdruck einer Download-Datei."""
    return hashlib.sha256(datei.read_bytes()).hexdigest()


def downloads_funde():
    """Liefert fertige Downloads und meldet bekannte Dubletten genau einmal."""
    konfiguration = kern.konfig("belege").get("quellen", {})
    if not konfiguration.get("downloads_an", True):
        return
    ordner = kern.erweitert(konfiguration.get("downloads", ""))
    if not ordner.exists():
        return
    grenze = kern.jetzt().timestamp() - 600
    for datei in sorted(ordner.iterdir()):
        if not _erlaubt(datei) or datei.stat().st_mtime > grenze:
            continue
        eingang = date.fromtimestamp(datei.stat().st_mtime)
        yield Fund(datei, "downloads", datei.name, eingang, verschieben=True)
