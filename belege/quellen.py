"""Funde aus Postfach, Handy und Downloads bereitstellen.

Die Quellen verändern keine Originale. Erst die Verarbeitung mit ``--echt``
legt ab oder verschiebt die dafür vorgesehenen Dateien.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
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


def ausgeschlossen(mail: dict) -> bool:
    """Prüft Ausschlüsse vor dem Herunterladen von Mailanhängen und vor dem Wächter."""
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
    anzahl_tage = tage if tage is not None else rueckblick_tage(stand, konfiguration)
    seit = kern.jetzt().date() - timedelta(days=anzahl_tage)
    mails = postfach.suchen(seit=seit, nur_anhang=True)
    if getattr(postfach, "weg", "") == "b":
        mails.extend(postfach.mit_label(str(konfiguration.get("label", "Beleg"))))
    bekannte = set(stand.get("mails", []))
    eindeutig = {mail.get("id"): mail for mail in mails if mail.get("id")}
    for mail_id, mail in eindeutig.items():
        if mail_id in bekannte or ausgeschlossen(mail):
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


def rueckblick_tage(stand: dict, konfiguration: dict) -> int:
    """Wie weit das Postfach zurückgelesen wird.

    Ab dem letzten vollständig erledigten Lauf, nicht fest drei Tage: War das
    MacBook eine Woche zu, holt der erste Lauf danach die ganze Woche nach.
    Mindestens ``laufend_tage`` (3), höchstens ``max_tage`` (60). Ohne Stand
    beginnt es mit ``erste_tage`` (30).
    """
    minimum = int(konfiguration.get("laufend_tage", 3))
    maximum = int(konfiguration.get("max_tage", 60))
    letzter = stand.get("lauf") or stand.get("stand")
    if not letzter and not stand.get("offen"):
        return min(int(konfiguration.get("erste_tage", 30)), maximum)
    try:
        seit = datetime.fromisoformat(str(letzter)).date() if letzter else kern.jetzt().date()
    except ValueError:
        seit = kern.jetzt().date() - timedelta(days=minimum)
    # Liegengebliebene Mails (Netz weg, Fehler) bleiben im Fenster, solange sie offen sind.
    for datum in (stand.get("offen") or {}).values():
        try:
            seit = min(seit, date.fromisoformat(str(datum)[:10]))
        except ValueError:
            continue
    return max(minimum, min(maximum, (kern.jetzt().date() - seit).days + 2))


def lauf_abschliessen(konto: str, liegen: dict[str, str], echt: bool) -> None:
    """Schreibt nach einem Postfachlauf fort, welche Mails noch offen sind.

    ``liegen`` sind Mail-IDs mit Maildatum, deren Funde diesmal nicht erledigt
    wurden. Der Rückblick rückt nur vor, wenn keine Mail mehr offen ist. Eine
    Mail, die länger offen ist als ``max_tage``, fiele aus dem Suchfenster: Sie
    wird einmal als „zweifel“ gemeldet und dann losgelassen, nie still verloren.
    """
    if not echt:
        return
    gesehen = _gesehen()
    daten = gesehen.setdefault(konto, {"mails": []})
    erledigt = set(daten.get("mails", []))
    offen = {i: d for i, d in (daten.get("offen") or {}).items() if i not in erledigt}
    offen.update(liegen)
    maximum = int(kern.konfig("belege").get("postfach", {}).get("max_tage", 60))
    grenze = kern.jetzt().date() - timedelta(days=maximum - 2)
    for mail_id, datum in list(offen.items()):
        try:
            zu_alt = date.fromisoformat(str(datum)[:10]) < grenze
        except ValueError:
            zu_alt = True
        if zu_alt:
            kern.ereignis("zweifel", f"Eine Mail vom {datum} im Postfach {konto} ließ sich {maximum} Tage lang "
                          "nicht verarbeiten. Bitte den Anhang selbst ansehen und ablegen.", konto=konto, id=mail_id)
            del offen[mail_id]
            # Als gesehen merken, sonst käme sie über ein Label (Weg B) jeden Lauf wieder.
            daten.setdefault("mails", []).append(mail_id)
    daten["offen"] = offen
    if not offen:
        daten["lauf"] = kern.jetzt().isoformat()
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)


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


def scan_funde():
    """Liefert Papierpost aus einem Scan-Ordner als Kopie, nie als Verschiebung.

    Scan-Dienste verwalten ihre Originale selbst. Die Kopie im Arbeitsordner hat
    denselben SHA-Fingerabdruck; dadurch merkt der normale Ablageweg Dubletten.
    """
    wert = str(kern.konfig("belege").get("quellen", {}).get("scan_ordner", "")).strip()
    if not wert:
        return
    ordner = kern.erweitert(wert)
    if not ordner.exists():
        return
    gesehen = _gesehen()
    bekannte = set(gesehen.get("scan_sha", []))
    for datei in sorted(ordner.iterdir()):
        if not _erlaubt(datei):
            continue
        sha = _sha(datei)
        if sha in bekannte:
            continue
        ziel = kern.pfad("arbeit", "tmp", "scan", f"{sha}{datei.suffix.lower()}")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if not ziel.exists():
            ziel.write_bytes(datei.read_bytes())
        bekannte.add(sha)
        gesehen["scan_sha"] = sorted(bekannte)
        kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
        yield Fund(ziel, "scan", datei.name, date.fromtimestamp(datei.stat().st_mtime))


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
