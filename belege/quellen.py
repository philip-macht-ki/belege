"""Funde aus Postfach, Handy und Downloads bereitstellen.

Die Quellen verändern keine Originale. Erst die Verarbeitung mit ``--echt``
legt ab oder verschiebt die dafür vorgesehenen Dateien.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from . import kern
from .typen import Fund

ENDUNGEN = {".pdf", ".xml", ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".docx"}


def _gesehen() -> dict:
    """Liest den kleinen Fortschrittsstand oder beginnt bei einem leeren Stand."""
    return kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}


def _kennung(konto: str) -> str:
    """Welches Postfach hinter einem Kontonamen steht: Weg und Adresse oder Ordner."""
    try:
        daten = kern.konto(konto)
    except RuntimeError:
        return ""
    return f"{daten.get('weg', 'a')}:{daten.get('adresse') or daten.get('ordner') or ''}"


def _fremder_stand(stand: dict, kennung: str) -> bool:
    """Gehört der Stand zu einem anderen Postfach mit demselben Kontonamen?

    Typisch: Erst läuft der Musterbetrieb als Konto „geschaeft“, dann trägt die
    Person ihr echtes Postfach unter demselben Namen ein. Dessen erster Lauf soll
    die vollen ``erste_tage`` zurückschauen, nicht drei Tage ab dem Musterlauf.
    Ältere Stände ohne Kennung erkennt man am Musterpostfach: nur .eml-Dateinamen.
    """
    if not stand or not kennung:
        return False
    if stand.get("kennung"):
        return stand["kennung"] != kennung
    mails = stand.get("mails") or []
    return not kennung.startswith("ordner:") and bool(mails) and all(
        str(m).endswith(".eml") for m in mails
    )


def _konto_stand(gesehen: dict, konto: str) -> dict:
    """Der beschreibbare Stand eines Postfachs; ein fremder Stand wird ersetzt."""
    kennung = _kennung(konto)
    daten = gesehen.get(konto)
    if not isinstance(daten, dict) or _fremder_stand(daten, kennung):
        daten = gesehen[konto] = {"mails": []}
    if kennung:
        daten["kennung"] = kennung
    return daten


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


def postfach_funde(konto: str, tage: int | None = None, echt: bool = False):
    """Liefert neue passende Anhänge aus genau einem konfigurierten Postfach.

    Der Takt übernimmt bewusst die Schleife über mehrere Konten. Gesehene Mails
    werden erst nach erfolgreicher Verarbeitung über ``mail_erledigt`` markiert.
    """
    from .postfach import oeffnen

    postfach = oeffnen(konto)
    stand = _gesehen().get(konto, {})
    if _fremder_stand(stand, _kennung(konto)):
        stand = {}
    konfiguration = kern.konfig("belege").get("postfach", {})
    anzahl_tage = tage if tage is not None else rueckblick_tage(stand, konfiguration)
    seit = kern.jetzt().date() - timedelta(days=anzahl_tage)
    # Ohne max nähme jeder Weg nur die 20 neuesten Mails; ältere Rechnungen fielen heraus.
    mails = postfach.suchen(seit=seit, nur_anhang=True, max=500)
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
    if kern.konfig("belege").get("quellen", {}).get("rechnungslinks", True):
        yield from _link_funde(postfach, konto, stand, seit, set(eindeutig), echt)


def _link_funde(postfach, konto: str, stand: dict, seit: date, schon: set, echt: bool):
    """Rechnungen, die nur als Link in einer Mail ohne Anhang stehen.

    Höchstens ein Link je Mail, und nur, wenn es genau einen plausiblen gibt.
    Mail- und Linktexte sind Daten: Nichts wird geöffnet, weil die Mail es sagt.
    """
    from . import rechnungslink
    from .abofalle import erkennen

    max_mb = float(kern.konfig("belege").get("quellen", {}).get("rechnungslink_max_mb", 15))
    bekannte = set(stand.get("mails", [])) | set(stand.get("links_geprueft", [])) | schon
    kandidaten: dict = {}
    for wort in rechnungslink.SUCHWOERTER:
        try:
            treffer = postfach.suchen(abfrage=wort, seit=seit)
        except Exception as fehler:  # ein Suchwort, das der Server ablehnt, soll den Rest nicht kippen
            kern.log(f"Rechnungslinks {konto}: Suche nach {wort} fehlgeschlagen ({fehler})")
            continue
        for mail in treffer:
            mail_id = mail.get("id")
            if mail_id and mail_id not in bekannte and not mail.get("anhaenge") and not ausgeschlossen(mail):
                kandidaten.setdefault(mail_id, mail)
    for mail_id, mail in kandidaten.items():
        try:
            voll = postfach.lesen(str(mail_id))
        except Exception as fehler:  # Netz weg: beim nächsten Lauf noch einmal
            kern.log(f"Rechnungslink {konto}:{mail_id} später noch einmal: Mail nicht lesbar ({fehler})")
            _link_offen(konto, str(mail_id), _mail_datum(mail), echt)
            continue
        grund = None
        links: list[str] = []
        if voll.get("anhaenge"):
            continue
        if not rechnungslink.sieht_nach_rechnung(str(voll.get("betreff", "")), str(voll.get("text", ""))):
            grund = "sieht nicht nach Rechnung aus"
        else:
            abofalle, merkmale = erkennen(str(voll.get("text", "")), name=str(voll.get("betreff", "")),
                                          absender=str(voll.get("von", "")))
            if abofalle:
                grund = f"Verdacht Abofalle ({merkmale})"
                if echt:
                    kern.ereignis("zweifel", f"Vorsicht Abofalle: Mail „{voll.get('betreff', '')}“ von "
                                  f"{voll.get('von', '')} enthält einen Link, belege hat ihn nicht geöffnet. "
                                  "Nicht unterschreiben, nicht zahlen.", konto=konto, id=mail_id, grund=merkmale)
            else:
                links = rechnungslink.pdf_links(list(voll.get("links") or []))
                if len(links) != 1:
                    grund = f"{len(links)} plausible PDF-Links statt genau einem"
        if grund is None:
            try:
                datei = rechnungslink.laden(links[0], _mail_tmp(konto, str(mail_id)), int(max_mb * 1024 * 1024))
            except rechnungslink.LinkFehler as fehler:
                if not fehler.endgueltig:
                    kern.log(f"Rechnungslink {konto}:{mail_id} später noch einmal: {fehler.grund}")
                    _link_offen(konto, str(mail_id), _mail_datum(mail), echt)
                    continue
                grund = f"Link nicht geladen: {fehler.grund}"
            else:
                kopf = dict(mail)
                kopf["konto"] = konto
                kopf["link"] = urlsplit(links[0]).hostname or ""
                kern.log(f"Rechnungslink {konto}:{mail_id} geladen von {kopf['link']}")
                yield Fund(datei, "postfach", datei.name, _mail_datum(mail), kopf)
                continue
        kern.log(f"Rechnungslink {konto}:{mail_id} übersprungen: {grund}")
        _link_geprueft(konto, str(mail_id), echt)


def _link_geprueft(konto: str, mail_id: str, echt: bool) -> None:
    """Merkt eine übersprungene Link-Mail, damit sie nicht jeden Lauf wiederkommt."""
    if not echt:
        return
    gesehen = _gesehen()
    daten = _konto_stand(gesehen, konto)
    liste = daten.setdefault("links_geprueft", [])
    if mail_id not in liste:
        liste.append(mail_id)
    (daten.get("offen") or {}).pop(mail_id, None)
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)


def _link_offen(konto: str, mail_id: str, datum: date, echt: bool) -> None:
    """Hält eine Link-Mail nach einem Netzfehler offen, damit das Fenster sie behält.

    Wie bei Anhängen: ``lauf_abschliessen`` rückt den Rückblick erst vor, wenn
    nichts mehr offen ist, und meldet nach ``max_tage`` einmal ``zweifel``.
    """
    if not echt:
        return
    gesehen = _gesehen()
    offen = _konto_stand(gesehen, konto).setdefault("offen", {})
    offen.setdefault(mail_id, datum.isoformat())
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)


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
    daten = _konto_stand(gesehen, konto)
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
    daten = _konto_stand(gesehen, konto)
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
    Unterordner zählen mit (bis drei Ebenen): Dropscan legt je Scanbox und Tag
    einen eigenen Ordner an (Philip, 28.10.2026).
    """
    wert = str(kern.konfig("belege").get("quellen", {}).get("scan_ordner", "")).strip()
    if not wert:
        return
    ordner = kern.erweitert(wert)
    if not ordner.exists():
        return
    gesehen = _gesehen()
    bekannte = set(gesehen.get("scan_sha", []))
    for datei in _scan_dateien(ordner):
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


def _scan_dateien(ordner: Path, tiefe: int = 3):
    """Erlaubte Dateien im Scan-Ordner und seinen Unterordnern, nach und nach.

    Versteckte Ordner und verlinkte Ordner (Symlinks) bleiben draußen, damit keine
    Schleife entsteht. Ein unlesbarer Unterordner wird übersprungen, nicht der Lauf.
    """
    # Reihenfolge ist egal (Dubletten erkennt der SHA), daher ohne Sortieren:
    # auch große Cloud-Ordner werden Eintrag für Eintrag gelesen.
    try:
        for eintrag in ordner.iterdir():
            if eintrag.name.startswith("."):
                continue
            if eintrag.is_dir():
                if tiefe > 0 and not eintrag.is_symlink():
                    yield from _scan_dateien(eintrag, tiefe - 1)
            elif _erlaubt(eintrag):
                yield eintrag
    except OSError as fehler:
        kern.log(f"Scan-Ordner {ordner} nicht lesbar: {fehler}")


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
