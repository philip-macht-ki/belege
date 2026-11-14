"""Nachsortieren: was in Unsortiert liegt, ein zweites Mal ansehen.

Läuft täglich im Lauf `belege tag` vor dem Bericht und von Hand als
`belege nachsortieren [--echt]`. Je Datei in `<ablage>/Unsortiert/` und
`<ablage>/<Dokumente>/Unsortiert/`:

1. Mailbild (Logo, Banner, Siegel, Produktfoto ohne Dokumenttext) oder
   eindeutige Werbung → `<ablage>/Unsortiert/Zu löschen/`. Verschoben, nie
   gelöscht; leeren tut die Person selbst.
2. Sonst derselbe Belegweg wie bei Handy-Fotos (`verarbeiten.verarbeite`),
   zuerst trocken. Nur wenn er die Datei jetzt außerhalb von Unsortiert ablegen
   würde, wird echt abgelegt. Eine unklare Firma entscheidet dabei der Lieferant,
   wenn er im Belegverzeichnis bisher nur bei einer eigenen Firma vorkommt.
3. Was unsicher bleibt, bleibt liegen und steht einmal im Tagesbericht unter
   „Bitte ansehen“.

Die Prüfung auf Mailbild und Werbung liest Bilder nur lokal (Apple Vision,
Tesseract), nie über die Claude-Stufe. Danach gelten die Regeln des Belegwegs.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import kern
from .kern import Ergebnis, ablage_ordner, konfig

ZU_LOESCHEN = "Zu löschen"
BELEGWORTE = ("rechnung", "invoice", "quittung", "beleg", "betrag", "summe", "gesamt", "mwst", "ust", "iban",
              "zahlbar", "gutschrift", "kundennummer", "vertragsnummer", "steuernummer")
# Zwei Werbezeichen und kein Belegwort: dann ist es Werbung, kein Schreiben.
WERBEZEICHEN = ("newsletter", "abmelden", "unsubscribe", "gutschein", "coupon", "rabatt", "bestellvorschlag",
                "prospekt", "jetzt bestellen", "jetzt kaufen", "nur für kurze zeit", "angebot gültig", "aktionspreis",
                "gratis dazu", "geschenkset", "payback")
DATUM_VORN = re.compile(r"^(20\d\d)-(\d\d)-(\d\d)_(.+)$")


def _an() -> bool:
    return bool(konfig("belege").get("nachsortieren", {}).get("an", True))


def ordner() -> list[Path]:
    """Die beiden Unsortiert-Ordner, die es tatsächlich gibt."""
    dok = str(konfig("belege").get("dokumente", {}).get("ordner", "Dokumente"))
    kandidaten = [ablage_ordner() / "Unsortiert", ablage_ordner() / dok / "Unsortiert"]
    return [o for o in kandidaten if o.is_dir()]


def _woerter(text: str) -> list[str]:
    """Echte Wörter: Logos und Produktfotos liefern per Texterkennung nur Zeichensalat."""
    return [w for w in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", text)
            if re.search(r"[aeiouäöüy]", w.lower()) and not re.search(r"(.)\1\1", w)]


def _belegwort(text: str) -> bool:
    klein = text.lower()
    return any(w in klein for w in BELEGWORTE) or bool(re.search(r"\d+,\d{2}\s*(€|eur)", klein))


def _bildtext(datei: Path) -> str:
    """Nur lokal: Apple Vision, sonst Tesseract. Nie die Claude-Stufe."""
    from . import text as texte

    for leser in (texte._vision, texte._tesseract):
        try:
            gelesen = leser(datei)
        except Exception:  # noqa: BLE001 - eine fehlende Stufe ist kein Fehler
            gelesen = ""
        if len(_woerter(gelesen)) >= 25:
            return gelesen
    return gelesen


def _ist_bild(datei: Path) -> bool:
    from .text import BILDENDUNGEN

    return datei.suffix.lower() in BILDENDUNGEN | {".gif", ".webp"}


def mailbild(datei: Path, text: str | None = None) -> str:
    """Grund, wenn die Datei ein Bild ohne eigenen Inhalt ist, sonst ''."""
    if not _ist_bild(datei):
        return ""
    if datei.stat().st_size < 20 * 1024:
        return "Bild unter 20 KB (Signatur oder Logo)"
    text = _bildtext(datei) if text is None else text
    if len(_woerter(text)) < 25 and not _belegwort(text):
        return "Bild ohne Dokumenttext (Logo, Banner oder Produktfoto)"
    return ""


def werbung(text: str) -> str:
    """Grund, wenn der Text eindeutig Werbung ist, sonst ''."""
    klein = text.lower()
    treffer = [w for w in WERBEZEICHEN if w in klein]
    if len(treffer) >= 2 and not re.search(r"rechnungs-?\s?(nr|nummer)|kundennummer|vertragsnummer|zu zahlen|fällig|iban",
                                           klein):
        return "Werbung (" + ", ".join(treffer[:3]) + ")"
    return ""


def _fund(datei: Path):
    """Fund wie aus dem Handy-Ordner; Datum und Name ohne den Unsortiert-Vorsatz."""
    from .typen import Fund

    m = DATUM_VORN.match(datei.name)
    if m:
        try:
            eingang = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return Fund(datei, "handy", m.group(4), eingang, verschieben=True)
        except ValueError:
            pass
    return Fund(datei, "handy", datei.name, date.fromtimestamp(datei.stat().st_mtime), verschieben=True)


def _in_unsortiert(pfad: str) -> bool:
    try:
        teile = Path(pfad).relative_to(ablage_ordner()).parts
    except ValueError:
        teile = Path(pfad).parts
    return "Unsortiert" in teile


def _gemeldet() -> set[str]:
    return set((kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}).get("nachsortieren_gemeldet", []))


def _merken(sha: str) -> None:
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    gesehen["nachsortieren_gemeldet"] = sorted(set(gesehen.get("nachsortieren_gemeldet", [])) | {sha})
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)


def _weg(datei: Path, grund: str, echt: bool) -> Ergebnis:
    ziel = kern.freier_name(ablage_ordner() / "Unsortiert" / ZU_LOESCHEN / datei.name)
    if not echt:
        print(f"würde nach Unsortiert/{ZU_LOESCHEN} schieben: {datei.name} ({grund})")
        return Ergebnis("nichts", f"Würde nach {ziel} schieben.", {"pfad": str(ziel), "status": "zu_loeschen"})
    ziel.parent.mkdir(parents=True, exist_ok=True)
    kern.cloud_verschieben(datei, ziel, beschreibung=f"{datei.name} nach {ZU_LOESCHEN}")
    kern.ereignis("aussortiert", f"{datei.name}: {grund}", pfad=str(ziel))
    return Ergebnis("ok", f"Nach {ziel} geschoben ({grund}).", {"pfad": str(ziel), "status": "zu_loeschen"})


def _mailtext_name(datei: Path) -> bool:
    """Erkennt die deterministisch benannten PDFs aus einem Mailtext."""
    m = DATUM_VORN.match(datei.name)
    name = m.group(4) if m else datei.name
    return bool(re.match(r"rechnung-aus-mailtext(?:_\d+)?\.pdf$", name, re.I))


def _kopie(datei: Path, merker: dict) -> str:
    """Prüft billige SHA-Kopien vor jeder normalen Nachsortierung."""
    from .verarbeiten import _sha

    sha = _sha(datei)
    andere = (kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}).get(sha, {})
    pfad = andere.get("pfad")
    if pfad:
        ziel = ablage_ordner() / str(pfad)
        if ziel.exists() and ziel.resolve() != datei.resolve():
            return f"Kopie von {ziel.name}"
    if sha in merker["sha"]:
        return f"Kopie von {merker['sha'][sha]}"
    merker["sha"][sha] = datei.name
    if _mailtext_name(datei):
        from .text import auslesen

        text = auslesen(datei).text.strip()
        if not text:  # unlesbar ist nicht „gleich“
            return ""
        if text in merker["mailtext"]:
            return f"Kopie von {merker['mailtext'][text]}"
        merker["mailtext"][text] = datei.name
    return ""


def eine(datei: Path, echt: bool, merker: dict | None = None) -> Ergebnis:
    """Eine Datei aus Unsortiert nachsortieren."""
    from . import verarbeiten

    merker = merker if merker is not None else {"sha": {}, "mailtext": {}}
    grund = _kopie(datei, merker)
    if grund:
        return _weg(datei, grund, echt)

    bildtext = _bildtext(datei) if _ist_bild(datei) and datei.stat().st_size >= 20 * 1024 else ""
    grund = mailbild(datei, bildtext if _ist_bild(datei) else None)
    if grund:
        return _weg(datei, grund, echt)
    if _ist_bild(datei):
        text = bildtext
    else:
        from .text import auslesen

        text = auslesen(datei).text
    grund = werbung(text)
    if grund:
        return _weg(datei, grund, echt)
    fund = _fund(datei)
    probe = verarbeiten.verarbeite(fund, False, nachsortieren=True)
    ziel = str(probe.daten.get("pfad", "")) if probe.daten else ""
    if probe.status in {"spaeter", "fehler"}:
        return probe
    if not ziel or _in_unsortiert(ziel) or probe.daten.get("status") == "unsortiert":
        sha = verarbeiten._sha(datei)
        meldung = f"{datei.name} bleibt in Unsortiert, auch der zweite Blick war unsicher."
        if echt and sha not in _gemeldet():
            kern.ereignis("unsortiert", f"{datei.name} liegt weiter in Unsortiert. Wohin gehört es?",
                          pfad=str(datei), grund="nachsortieren")
            _merken(sha)
        return Ergebnis("befund", meldung, {"pfad": str(datei), "status": "unsortiert"})
    if not echt:
        return probe
    return verarbeiten.verarbeite(fund, True, nachsortieren=True)


def lauf(echt: bool) -> list[Ergebnis]:
    """Alle Dateien der Unsortiert-Ordner; Unterordner wie „Zu löschen“ bleiben draußen."""
    if not _an():
        return []
    from .quellen import _erlaubt

    ergebnisse = []
    for o in ordner():
        merker = {"sha": {}, "mailtext": {}}
        for datei in sorted(o.iterdir()):
            if not _erlaubt(datei):
                continue
            try:
                ergebnisse.append(eine(datei, echt, merker))
            except kern.CloudGesperrt as fehler:
                # Der Cloud-Ordner synchronisiert gerade: kein Fehler, der nächste Lauf versucht es wieder.
                if echt:
                    kern.ereignis("cloud_gesperrt", str(fehler), quelle="nachsortieren", datei=datei.name)
                ergebnisse.append(Ergebnis("cloud_gesperrt", str(fehler)))
            except OSError as fehler:
                kern.log(f"nachsortieren: {datei.name} gerade nicht lesbar: {fehler}")
                ergebnisse.append(Ergebnis("spaeter", f"{datei.name} gerade nicht lesbar."))
    return ergebnisse


def befehl(args) -> int:
    """`belege nachsortieren [--echt]`: Unsortiert ein zweites Mal ansehen."""
    from collections import Counter

    ergebnisse = lauf(kern.echt(args))
    if not ergebnisse:
        print("nichts: Unsortiert ist leer." if _an() else "nichts: [nachsortieren] an = false.")
        return 0
    zaehler = Counter(e.status for e in ergebnisse)
    print(f"{zaehler['ok']} abgelegt oder aussortiert, {zaehler['befund']} bleiben zum Ansehen, "
          f"{zaehler['nichts']} trocken geplant, {zaehler['fehler']} Fehler")
    return 0
