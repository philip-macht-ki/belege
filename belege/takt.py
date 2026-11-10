"""Die regelmäßigen Läufe.

`belege takt` holt Belege aus dem Postfach und dem Handy-Ordner und lässt den
Wächter über neue Mails schauen. `belege tag` räumt den Downloads-Ordner auf und
schickt den Tagesbericht. Jeder Schritt wird einzeln abgefangen: Scheitert einer,
laufen die anderen trotzdem, und der Fehler steht im Bericht.
"""
from __future__ import annotations

import argparse
import importlib
import os
import signal
import threading
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta

from .einrichten import auffrischen as _starter_auffrischen
from .kern import CloudGesperrt, Ergebnis, Sperre, echt, einmal_taeglich, ereignis, konfig, konten, lesen, log, netz_da, netzfehler, pfad, schreiben, jetzt


def _weiterreichen(args) -> argparse.Namespace:
    """Nur die Schalter, die Unterbefehle kennen, damit keiner über Fremdes stolpert."""
    return argparse.Namespace(
        echt=echt(args),
        tage=getattr(args, "tage", None),
        konto=getattr(args, "konto", None),
        ziel=[],
    )


def _postfach_konten(args) -> list[str]:
    gewuenscht = getattr(args, "konto", None)
    return [k["name"] for k in konten()
            if k.get("belege", True) and (not gewuenscht or k.get("name") == gewuenscht)]


def _funde(name: str, args) -> list:
    """Sammelt die Funde einer Quelle (postfach, handy oder downloads)."""
    quellen = importlib.import_module("belege.quellen")
    if name != "postfach":
        quelle = getattr(quellen, f"{name}_funde")
        return list(quelle(echt=echt(args))) if name == "scan" else list(quelle())
    funde = []
    for konto in _postfach_konten(args):
        funde.extend(quellen.postfach_funde(konto, getattr(args, "tage", None), echt(args)))
    return funde


def quelle_abarbeiten(name: str, args) -> list[Ergebnis]:
    """Verarbeitet alle Funde einer Quelle und meldet erledigte Mails zurück.

    Eine Mail gilt erst als erledigt, wenn keiner ihrer Anhänge mit einem Fehler
    endete. So wird ein Anhang, der heute scheitert, morgen noch einmal versucht.
    """
    verarbeiten = importlib.import_module("belege.verarbeiten")
    funde = _funde(name, args)
    ergebnisse = []
    for fund in funde:
        try:
            ergebnisse.append(verarbeiten.verarbeite(fund, echt(args)))
        except CloudGesperrt as fehler:
            meldung = str(fehler)
            log(meldung)
            ereignis("cloud_gesperrt", meldung, quelle=fund.quelle, datei=fund.name)
            ergebnisse.append(Ergebnis("cloud_gesperrt", meldung, {"quelle": fund.quelle}))

    if name == "postfach":
        quellen = importlib.import_module("belege.quellen")
        je_mail: dict[tuple[str, str], bool] = {}
        for fund, ergebnis in zip(funde, ergebnisse):
            if not fund.mail:
                continue
            schluessel = (fund.mail["konto"], fund.mail["id"])
            # Ein Befund (etwa „Unsortiert“) ist noch keine vollständige Ablage.
            # Die Mail bleibt dann unverändert und kommt beim nächsten Lauf wieder.
            je_mail[schluessel] = je_mail.get(schluessel, True) and ergebnis.status in {"ok", "nichts"}
        for (konto, mail_id), alles_gut in je_mail.items():
            if alles_gut:
                quellen.mail_erledigt(konto, mail_id, echt(args))
        # Offene Mails bleiben im Suchfenster; erst ohne offene rückt der Rückblick vor.
        daten = {(f.mail["konto"], f.mail["id"]): f.eingang.isoformat() for f in funde if f.mail}
        for konto in _postfach_konten(args):
            liegen = {i: daten[(k, i)] for (k, i), gut in je_mail.items() if k == konto and not gut}
            quellen.lauf_abschliessen(konto, liegen, echt(args))
    return ergebnisse


def _zusammenfassung(ergebnisse: list[Ergebnis]) -> str:
    """Eine Zeile wie "3 abgelegt, 1 zum Ansehen, 2 ohne Handlung, 0 Fehler"."""
    zaehler = Counter(e.status for e in ergebnisse)
    zeile = (
        f"{zaehler['ok']} abgelegt, {zaehler['befund']} zum Ansehen, "
        f"{zaehler['nichts']} ohne Handlung, {zaehler['fehler']} Fehler"
    )
    return zeile + (f", {zaehler['spaeter']} warten aufs Netz" if zaehler["spaeter"] else "")


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
        if name == "aufraeumen":
            cfg = konfig("belege").get("aufraeumen", {})
            if not cfg.get("an"):
                return "aus", []
            code = importlib.import_module("belege.postfach_agent").laufen(_weiterreichen(args), nur_faellig=True)
            return ("ok" if not code else f"Exit {code}"), []
        if name == "nachsortieren":
            ergebnisse = importlib.import_module("belege.nachsortieren").lauf(echt(args))
            return _zusammenfassung(ergebnisse), ergebnisse
        if name == "bericht":
            code = importlib.import_module("belege.bericht").befehl(_weiterreichen(args))
            return ("ok" if not code else f"Exit {code}"), []
        ergebnisse = quelle_abarbeiten(name, args)
        if any(e.status == "spaeter" for e in ergebnisse) and netz_da():
            # Netz da, aber das Modell antwortet nicht (abgemeldet, Kontingent): ein
            # echter Fehler, sonst meldete das Lebenszeichen „alles gut“.
            return f"fehler: Modell nicht erreichbar, {_zusammenfassung(ergebnisse)}", ergebnisse
        return _zusammenfassung(ergebnisse), ergebnisse
    except Exception as fehler:  # noqa: BLE001
        meldung = str(fehler)
        if name == "postfach" and any(w in meldung.lower() for w in ("authenticationfailed", "login failed", "invalid_grant", " 401", "lehnt den zugang ab")):
            meldung = ("Die Anmeldung bei einem Postfach klappt nicht mehr. Hast du dein Passwort geändert oder das App-Passwort gelöscht? "
                       "Sag deinem Claude: Verbinde mein Postfach neu.")
        log(f"fehler in {name}: {meldung}\n{traceback.format_exc(limit=3)}")
        if netzfehler(fehler):
            # Zug, Hotel-WLAN, VPN: kein Fehler, nur einmal am Tag eine freundliche Zeile.
            if echt(args):
                einmal_taeglich("offline", "Dein Mac war ohne Netz. Liegengebliebenes wird nachgeholt.")
            return f"offline: {name}", []
        if echt(args):
            ereignis("fehler", f"{name}: {fehler}")
        return f"fehler: {meldung}", []


# Ein Lauf darf höchstens so lange dauern (`[takt].max_minuten`), dann wird er beendet.
MAX_MINUTEN = 120
# Ab dieser Dauer steht ein Hinweis im Tagesbericht.
WARNEN_AB_MINUTEN = 60
# Bleibt der Lauf trotz Grenze stehen (etwa in C-Code ohne Signal), beendet die Wache
# den Prozess so viele Sekunden später hart. launchd startet dann wieder normal.
NOTAUS_NACH = 300


class LaufZuLang(BaseException):
    """Die Laufzeitgrenze ist erreicht.

    Bewusst keine ``Exception``: Die Schritte fangen ``Exception`` ab und liefen
    sonst einfach weiter. So endet der ganze Lauf, Sperren werden aber freigegeben.
    """


def _max_minuten() -> float:
    try:
        wert = float(konfig("belege").get("takt", {}).get("max_minuten", MAX_MINUTEN))
    except (TypeError, ValueError):
        return MAX_MINUTEN
    return wert if wert > 0 else MAX_MINUTEN


@contextmanager
def _zeitgrenze(sekunden: float, name: str, echt_lauf: bool):
    """Beendet einen Lauf nach `sekunden` mit ``LaufZuLang`` statt ihn hängen zu lassen.

    Auf dem Mac per SIGALRM im Hauptfaden; das unterbricht auch einen blockierten
    Socket. Unter Windows (kein SIGALRM) und als letzte Rettung beendet eine Wache
    den Prozess hart, nachdem sie den Fehler ins Protokoll geschrieben hat.
    """
    alarm = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    minuten = round(sekunden / 60)

    def notaus():
        meldung = f"{name}: Lauf hing länger als {minuten} Minuten und wurde hart beendet."
        try:
            log(meldung)
            if echt_lauf:
                ereignis("fehler", meldung)
        finally:
            os._exit(3)

    wache = threading.Timer(sekunden + (NOTAUS_NACH if alarm else 0), notaus)
    wache.daemon = True
    wache.start()
    alt = None
    if alarm:
        def ausloesen(_signum, _frame):
            raise LaufZuLang(f"{name}: Lauf nach {minuten} Minuten abgebrochen (Grenze [takt].max_minuten).")

        alt = signal.signal(signal.SIGALRM, ausloesen)
        signal.setitimer(signal.ITIMER_REAL, sekunden)
    try:
        yield
    finally:
        if alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, alt)
        wache.cancel()


def _lauf(args, schritte: tuple[str, ...], sperre: str) -> bool:
    """Führt mehrere Schritte nacheinander aus, jeden für sich abgesichert.

    Gibt zurück, ob alle Schritte ohne Fehler durchliefen. Der ganze Lauf hat eine
    harte Zeitgrenze; ein Lauf über einer Stunde steht als Hinweis im Tagesbericht.
    """
    fehlerfrei = True
    beginn = time.monotonic()
    try:
        if _starter_auffrischen():
            log("Modell-Starter in ~/.local/bin auf den neuen Stand gebracht.")
    except Exception as fehler:  # noqa: BLE001 – der Lauf selbst geht vor
        log(f"Modell-Starter nicht aufgefrischt: {fehler}")
    aktiv = None
    try:
        with _zeitgrenze(_max_minuten() * 60, sperre, echt(args)), Sperre(sperre):
            for name in schritte:
                aktiv = name
                zustand, _ = _schritt(name, args)
                print(f"{name}: {zustand}")
                fehlerfrei = fehlerfrei and not zustand.startswith(("fehler", "Exit"))
    except RuntimeError:
        print("nichts: Ein Lauf ist schon aktiv.")
    except LaufZuLang as grenze:
        fehlerfrei = False
        meldung = f"{grenze} Zuletzt lief der Schritt {aktiv}."
        log(f"fehler in {sperre}: {meldung}\n{traceback.format_exc(limit=6)}")
        print(f"fehler: {meldung}")
        if echt(args):
            ereignis("fehler", meldung, schritt=aktiv)
    minuten = (time.monotonic() - beginn) / 60
    if minuten > WARNEN_AB_MINUTEN:
        log(f"{sperre}: Lauf dauerte {minuten:.0f} Minuten.")
        if echt(args):
            ereignis("langsam", f"Ein Lauf ({sperre}) dauerte {minuten:.0f} Minuten.",
                     lauf=sperre, minuten=round(minuten), schritt=aktiv)
    return fehlerfrei


def lebenszeichen(wach: bool = False) -> None:
    """Meldet einen Lauf an die Adresse aus `[takt] lebenszeichen`.

    ``wach=True`` zu Beginn jedes Laufs: „Der Mac ist an“, mit dem Gerätetyp.
    Ohne Schalter nach einem fehlerfreien Lauf: „alles erledigt“. Aus beidem
    unterscheidet der Dienst „Mac war zu“ (beim MacBook nur ein freundlicher
    Hinweis nach Tagen) von „Mac ist an, aber der Lauf scheitert“ (Alarm).
    """
    import urllib.request

    adresse = str(konfig("belege").get("takt", {}).get("lebenszeichen", "")).strip()
    if not adresse.startswith("https://"):
        return
    if wach:
        from .rechner import art

        adresse += ("&" if "?" in adresse else "?") + f"art=wach&geraet={art()}"
    try:
        urllib.request.urlopen(adresse, timeout=10).close()
    except Exception as fehler:  # noqa: BLE001 - ein fehlendes Netz stoppt keinen Lauf
        log(f"Lebenszeichen nicht gesendet: {fehler}")


def _laufstand(name: str) -> str:
    return str((lesen(pfad("arbeit", "gesehen.json"), {}) or {}).get("lauf", {}).get(name, ""))


def _nachholen_eingerichtet(name: str) -> bool:
    """Nur Läufe nachholen, deren Ziel in der Einrichtung vorhanden ist."""
    cfg = konfig("belege")
    if name == "tag":
        bericht = cfg.get("bericht", {})
        return bool(bericht.get("an") or (konten() or [{}])[0].get("adresse"))
    if name == "monat":
        uebergabe = cfg.get("uebergabe", {})
        return bool(uebergabe.get("adresse") or uebergabe.get("ordner"))
    return pfad("arbeit", "posten.json").exists()


def _alte_laeufe_merken() -> None:
    """Übernimmt vorhandene Altmerker, ohne nach einem Update alte Läufe zu duplizieren."""
    gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
    lauf = gesehen.setdefault("lauf", {})
    geaendert = False
    if "tag" not in lauf and gesehen.get("bericht"):
        lauf["tag"] = str(gesehen["bericht"])
        geaendert = True
    if "monat" not in lauf and (gesehen.get("uebergabe") or gesehen.get("monatsmail")):
        lauf["monat"] = jetzt().isoformat(timespec="seconds")
        geaendert = True
    if "posten" not in lauf and any(str(s).startswith("posten:") for s in (gesehen.get("gesendet_teile") or {})):
        lauf["posten"] = jetzt().isoformat(timespec="seconds")
        geaendert = True
    if geaendert:
        schreiben(pfad("arbeit", "gesehen.json"), gesehen)


def _versuch_merken(name: str) -> bool:
    """Höchstens ein fehlgeschlagener Nachholversuch je Stunde."""
    gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
    alt = str((gesehen.get("nachholversuch", {}) or {}).get(name, ""))
    try:
        from datetime import datetime
        if jetzt() - datetime.fromisoformat(alt) < timedelta(hours=1):
            return False
    except ValueError:
        pass
    gesehen.setdefault("nachholversuch", {})[name] = jetzt().isoformat(timespec="seconds")
    schreiben(pfad("arbeit", "gesehen.json"), gesehen)
    return True


def _faelliger_tag() -> bool:
    zeit = str(konfig("belege").get("takt", {}).get("tag_uhrzeit", "21:00"))
    stunde, minute = (int(x) for x in zeit.split(":"))
    nun = jetzt()
    soll = nun.replace(hour=stunde, minute=minute, second=0, microsecond=0)
    if nun < soll:
        soll -= timedelta(days=1)
    return not _laufstand("tag") or _laufstand("tag")[:10] < soll.date().isoformat()


def _faelliger_monat() -> bool:
    nun = jetzt()
    return nun.day >= 3 and (nun.day > 3 or (nun.hour, nun.minute) >= (9, 0)) and _laufstand("monat")[:7] != nun.strftime("%Y-%m")


def _faellige_posten() -> bool:
    nun = jetzt()
    tage = [d for d in (1, 15) if nun.day > d or (nun.day == d and (nun.hour, nun.minute) >= (7, 0))]
    if not tage:
        return False
    return _laufstand("posten")[:10] < nun.replace(day=tage[-1]).date().isoformat()


def _nachholen(args) -> None:
    """Startet nach einem ausgeschalteten Mac jeden fälligen Kalenderlauf einmal."""
    from argparse import Namespace
    if not echt(args):
        return
    _alte_laeufe_merken()
    laeufe = (("tag", _faelliger_tag, lambda: _lauf(args, ("downloads", "nachsortieren", "bericht"), "tag")),
              ("monat", _faelliger_monat, lambda: importlib.import_module("belege.monat").befehl(Namespace(echt=True, monat=None, uebergabe=True, anfragen=False, auszug=None, ziel=[]))),
              ("posten", _faellige_posten, lambda: importlib.import_module("belege.posten").mail(True)))
    for name, faellig, ausfuehren in laeufe:
        if not _nachholen_eingerichtet(name) or not faellig() or not _versuch_merken(name):
            continue
        try:
            ok = ausfuehren() == 0 if name != "tag" else bool(ausfuehren())
            if ok and name == "tag":
                gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
                gesehen.setdefault("lauf", {})["tag"] = jetzt().isoformat(timespec="seconds")
                schreiben(pfad("arbeit", "gesehen.json"), gesehen)
        except Exception as fehler:  # Ein Nachholfehler stoppt den normalen Takt nicht.
            ereignis("fehler", f"Nachholen {name}: {fehler}")
            log(f"Nachholen {name} fehlgeschlagen: {fehler}")


def befehl(args) -> int:
    """`belege takt`: Postfach, Handy, Papierpost, Wächter und Opt-in-Aufräumen."""
    if echt(args):
        lebenszeichen(wach=True)
    schritte = ("postfach", "handy", "scan", "waechter")
    if konfig("belege").get("aufraeumen", {}).get("an"):
        schritte += ("aufraeumen",)
    if _lauf(args, schritte, "takt") and echt(args):
        lebenszeichen()
    _nachholen(args)
    return 0


def befehl_tag(args) -> int:
    """`belege tag`: Downloads-Ordner, Unsortiert nachsortieren, dann Tagesbericht."""
    ok = _lauf(args, ("downloads", "nachsortieren", "bericht"), "tag")
    if ok and echt(args):
        gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
        gesehen.setdefault("lauf", {})["tag"] = jetzt().isoformat(timespec="seconds")
        schreiben(pfad("arbeit", "gesehen.json"), gesehen)
    return 0
