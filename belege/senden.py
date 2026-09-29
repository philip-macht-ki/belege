"""Der einzige erlaubte Weg, Nachrichten nach außen zu senden."""

from __future__ import annotations

from pathlib import Path

from . import kern


def _adresse(wert: str) -> str:
    """Gibt nur die normalisierte E-Mail-Adresse aus einem Empfängerfeld zurück."""
    from email.utils import parseaddr

    return parseaddr(wert)[1].lower()


def erlaubt(adresse: str) -> bool:
    """Prüft, ob eine Adresse automatisch angeschrieben werden darf.

    Genau ein Empfänger: "a@x.de, b@y.de" ist nie erlaubt, sonst ginge die Mail an
    beide, obwohl nur der erste geprüft wurde.
    """
    if any(zeichen in str(adresse) for zeichen in (",", ";", "\n", "\r")):
        return False
    ziel = _adresse(adresse)
    if not ziel or "@" not in ziel:
        return False
    konfiguration = kern.konfig("belege")
    eigene = [konto.get("adresse", "") for konto in kern.konten()]
    bericht = konfiguration.get("bericht", {}).get("an") or (
        eigene[0] if eigene else ""
    )
    erlaubte = [*konfiguration.get("senden", {}).get("erlaubt", []), bericht, *eigene]
    return ziel in {_adresse(wert) for wert in erlaubte if wert}


def _teile(anhaenge: list[Path]) -> list[list[Path]]:
    """Teilt Anhänge nach der konfigurierten Mailgröße und Höchstanzahl auf."""
    uebergabe = kern.konfig("belege").get("uebergabe", {})
    max_byte = int(uebergabe.get("max_mb", 20)) * 1024 * 1024
    max_anzahl = int(uebergabe.get("max_anhaenge", 50))
    teile: list[list[Path]] = []
    teil: list[Path] = []
    groesse = 0
    for anhang in map(Path, anhaenge):
        anhang_groesse = anhang.stat().st_size
        if teil and (len(teil) >= max_anzahl or groesse + anhang_groesse > max_byte):
            teile.append(teil)
            teil = []
            groesse = 0
        teil.append(anhang)
        groesse += anhang_groesse
    return teile + ([teil] if teil else [[]])


def _betreff(betreff: str, nummer: int, anzahl: int) -> str:
    """Ergänzt bei geteilten Sendungen den verständlichen Teil-Hinweis."""
    if anzahl == 1:
        return betreff
    return f"{betreff} (Teil {nummer} von {anzahl})"


def entwurf(
    an: str, betreff: str, text: str, anhaenge: list[Path], echt: bool, konto=None
) -> kern.Ergebnis:
    """Legt nur mit --echt einen Entwurf an und gibt seine IDs zurück."""
    if not echt:
        kern.log(f"würde Entwurf an {an} anlegen")
        return kern.Ergebnis(
            "nichts", f"Würde einen Entwurf an {an} anlegen.", {"ids": []}
        )
    from .postfach import oeffnen

    teile = _teile(anhaenge)
    postfach = oeffnen(konto)
    ids = []
    for nummer, teil in enumerate(teile, 1):
        ids.append(
            postfach.entwurf(an, _betreff(betreff, nummer, len(teile)), text, teil)
        )
    kern.ereignis("entwurf", f"Entwurf an {an} angelegt", an=an, ids=ids)
    return kern.Ergebnis("ok", f"Entwurf an {an} angelegt.", {"ids": ids})


def senden(
    an: str, betreff: str, text: str, anhaenge: list[Path], echt: bool, konto=None,
    fortschritt: str | None = None,
) -> kern.Ergebnis:
    """Sendet nur mit --echt an erlaubte Adressen, sonst entsteht ein Entwurf.

    fortschritt: ein Schlüssel wie "uebergabe:2026-08". Dann merkt sich senden je
    Teil, was schon draußen ist, und schickt bei einem neuen Versuch nur den Rest.
    """
    if not echt:
        kern.log(f"würde senden an {an}")
        return kern.Ergebnis("nichts", f"Würde an {an} senden.", {"ids": []})
    if not erlaubt(an):
        ergebnis = entwurf(an, betreff, text, anhaenge, True, konto)
        return kern.Ergebnis(
            "befund",
            f"{an} ist nicht freigegeben; deshalb entstand ein Entwurf.",
            ergebnis.daten,
        )
    from .postfach import oeffnen

    teile = _teile(anhaenge)
    postfach = oeffnen(konto)
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    erledigt = set(gesehen.get("gesendet_teile", {}).get(fortschritt, [])) if fortschritt else set()
    ids = []
    for nummer, teil in enumerate(teile, 1):
        if nummer in erledigt:
            continue
        ids.append(postfach._senden(an, _betreff(betreff, nummer, len(teile)), text, teil))
        if fortschritt:
            erledigt.add(nummer)
            gesehen.setdefault("gesendet_teile", {})[fortschritt] = sorted(erledigt)
            kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    kern.ereignis("gesendet", f"Mail an {an} gesendet", an=an, ids=ids)
    return kern.Ergebnis("ok", f"Mail an {an} gesendet.", {"ids": ids})
