"""Die regelmäßigen Läufe.

`belege takt` holt Belege aus dem Postfach und dem Handy-Ordner und lässt den
Wächter über neue Mails schauen. `belege tag` räumt den Downloads-Ordner auf und
schickt den Tagesbericht. Jeder Schritt wird einzeln abgefangen: Scheitert einer,
laufen die anderen trotzdem, und der Fehler steht im Bericht.
"""
from __future__ import annotations

import argparse
import importlib
import traceback
from collections import Counter

from .kern import Ergebnis, Sperre, echt, ereignis, konfig, konten, log


def _weiterreichen(args) -> argparse.Namespace:
    """Nur die Schalter, die Unterbefehle kennen, damit keiner über Fremdes stolpert."""
    return argparse.Namespace(
        echt=echt(args),
        tage=getattr(args, "tage", None),
        konto=getattr(args, "konto", None),
        ziel=[],
    )


def _funde(name: str, args) -> list:
    """Sammelt die Funde einer Quelle (postfach, handy oder downloads)."""
    quellen = importlib.import_module("belege.quellen")
    if name != "postfach":
        return list(getattr(quellen, f"{name}_funde")())
    gewuenscht = getattr(args, "konto", None)
    funde = []
    for konto in konten():
        if not konto.get("belege", True):
            continue
        if gewuenscht and konto.get("name") != gewuenscht:
            continue
        funde.extend(quellen.postfach_funde(konto["name"], getattr(args, "tage", None)))
    return funde


def quelle_abarbeiten(name: str, args) -> list[Ergebnis]:
    """Verarbeitet alle Funde einer Quelle und meldet erledigte Mails zurück.

    Eine Mail gilt erst als erledigt, wenn keiner ihrer Anhänge mit einem Fehler
    endete. So wird ein Anhang, der heute scheitert, morgen noch einmal versucht.
    """
    verarbeiten = importlib.import_module("belege.verarbeiten")
    funde = _funde(name, args)
    ergebnisse = [verarbeiten.verarbeite(fund, echt(args)) for fund in funde]

    if name == "postfach":
        quellen = importlib.import_module("belege.quellen")
        je_mail: dict[tuple[str, str], bool] = {}
        for fund, ergebnis in zip(funde, ergebnisse):
            if not fund.mail:
                continue
            schluessel = (fund.mail["konto"], fund.mail["id"])
            je_mail[schluessel] = je_mail.get(schluessel, True) and ergebnis.gut
        for (konto, mail_id), alles_gut in je_mail.items():
            if alles_gut:
                quellen.mail_erledigt(konto, mail_id, echt(args))
    return ergebnisse


def _zusammenfassung(ergebnisse: list[Ergebnis]) -> str:
    """Eine Zeile wie "3 abgelegt, 1 zum Ansehen, 2 ohne Handlung, 0 Fehler"."""
    zaehler = Counter(e.status for e in ergebnisse)
    return (
        f"{zaehler['ok']} abgelegt, {zaehler['befund']} zum Ansehen, "
        f"{zaehler['nichts']} ohne Handlung, {zaehler['fehler']} Fehler"
    )


def _einzelschritt(name: str, args) -> int:
    """Führt genau eine Quelle aus, für `belege postfach|handy|downloads`."""
    try:
        ergebnisse = quelle_abarbeiten(name, args)
    except Exception as fehler:  # noqa: BLE001 - jeder Fehler soll lesbar ankommen
        if echt(args):
            ereignis("fehler", f"{name}: {fehler}")
        print(f"fehler: {name}: {fehler}")
        return 1
    vorsilbe = "ok" if echt(args) else "trocken"
    print(f"{vorsilbe}: {name}: {_zusammenfassung(ergebnisse)}")
    return 0


def befehl_postfach(args) -> int:
    """Nur das Postfach abarbeiten."""
    return _einzelschritt("postfach", args)


def befehl_handy(args) -> int:
    """Handy- und Papier-Eingang abarbeiten."""
    code = _einzelschritt("handy", args)
    return max(code, _einzelschritt("scan", args))


def befehl_downloads(args) -> int:
    """Nur den Downloads-Ordner abarbeiten."""
    return _einzelschritt("downloads", args)


def _schritt(name: str, args) -> tuple[str, list[Ergebnis]]:
    """Ein Schritt eines Laufs. Gibt einen Zustandstext und die Ergebnisse zurück."""
    try:
        if name == "waechter":
            code = importlib.import_module("belege.waechter").befehl(_weiterreichen(args))
            return ("ok" if not code else f"Exit {code}"), []
        if name == "bericht":
            code = importlib.import_module("belege.bericht").befehl(_weiterreichen(args))
            return ("ok" if not code else f"Exit {code}"), []
        ergebnisse = quelle_abarbeiten(name, args)
        return _zusammenfassung(ergebnisse), ergebnisse
    except Exception as fehler:  # noqa: BLE001
        log(f"fehler in {name}: {fehler}\n{traceback.format_exc(limit=3)}")
        if echt(args):
            ereignis("fehler", f"{name}: {fehler}")
        return f"fehler: {fehler}", []


def _lauf(args, schritte: tuple[str, ...], sperre: str) -> bool:
    """Führt mehrere Schritte nacheinander aus, jeden für sich abgesichert.

    Gibt zurück, ob alle Schritte ohne Fehler durchliefen.
    """
    fehlerfrei = True
    try:
        with Sperre(sperre):
            for name in schritte:
                zustand, _ = _schritt(name, args)
                print(f"{name}: {zustand}")
                fehlerfrei = fehlerfrei and not zustand.startswith(("fehler", "Exit"))
    except RuntimeError:
        print("nichts: Ein Lauf ist schon aktiv.")
    return fehlerfrei


def lebenszeichen() -> None:
    """Meldet einen fehlerfreien Lauf an die Adresse aus `[takt] lebenszeichen`.

    Bleibt die Meldung länger aus, schickt der Dienst dahinter eine Mail. So fällt
    ein stehengebliebener Zeitplan auf, auch wenn der Mac aus ist.
    """
    import urllib.request

    adresse = str(konfig("belege").get("takt", {}).get("lebenszeichen", "")).strip()
    if not adresse.startswith("https://"):
        return
    try:
        urllib.request.urlopen(adresse, timeout=10).close()
    except Exception as fehler:  # noqa: BLE001 - ein fehlendes Netz stoppt keinen Lauf
        log(f"Lebenszeichen nicht gesendet: {fehler}")


def befehl(args) -> int:
    """`belege takt`: Postfach, Handy, Papierpost und Wächter."""
    if _lauf(args, ("postfach", "handy", "scan", "waechter"), "takt") and echt(args):
        lebenszeichen()
    return 0


def befehl_tag(args) -> int:
    """`belege tag`: Downloads-Ordner, dann Tagesbericht."""
    _lauf(args, ("downloads", "bericht"), "tag")
    return 0
