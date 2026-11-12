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
import re
import signal
import threading
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta

from .einrichten import auffrischen as _starter_auffrischen
from .kern import CloudGesperrt, Ergebnis, Sperre, SperreBelegt, echt, einmal_taeglich, ereignis, konfig, konten, lesen, log, netz_da, netzfehler, pfad, schreiben, jetzt


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


def _lauf(args, schritte: tuple[str, ...], sperre: str) -> bool | None:
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
    except SperreBelegt:
        print("nichts: Ein Lauf ist schon aktiv.")
        # Die Sperre bedeutet nicht, dass der Lauf fehlgeschlagen ist.  Der
        # Nachholtakt darf es beim nächsten Viertelstunden-Takt erneut probieren.
        return None
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
    """Setzt die Startgrenze eines Updates ohne alte Solltermine nachzuholen."""
    gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
    lauf = gesehen.setdefault("lauf", {})
    geaendert = False
    if not re.fullmatch(r"\d{4}-\d{2}", str(gesehen.get("nachholen_ab_monat", ""))):
        gesehen["nachholen_ab_monat"] = jetzt().strftime("%Y-%m")
        geaendert = True
    nachholen_ab = gesehen.setdefault("nachholen_ab", {})
    # Der letzte Solltermin vor dem Update zählt für jeden Lauf als versucht.
    # Ein alter Bericht-/Mailmerker ist kein verlässlicher Termin und darf daher
    # keinen zusätzlichen Tageslauf auslösen.
    for name in ("tag", "monat", "posten"):
        if name not in lauf and not str(nachholen_ab.get(name, "")):
            nachholen_ab[name] = jetzt().isoformat(timespec="seconds")
            letzter = _letzter_solltermin(name)
            if letzter:
                lauf[name] = letzter.isoformat(timespec="seconds")
            geaendert = True
    if geaendert:
        schreiben(pfad("arbeit", "gesehen.json"), gesehen)


def _letzter_solltermin(name: str) -> datetime | None:
    """Der letzte Solltermin strikt vor jetzt, für die Update-Migration."""
    nun = jetzt()
    if name == "tag":
        stunde, minute = (int(x) for x in str(konfig("belege").get("takt", {}).get("tag_uhrzeit", "21:00")).split(":"))
        soll = nun.replace(hour=stunde, minute=minute, second=0, microsecond=0)
        return soll if soll < nun else soll - timedelta(days=1)
    if name == "monat":
        soll = _monat_termin()
        if soll >= nun:
            erster = nun.replace(day=1) - timedelta(days=1)
            tag = int(konfig("belege").get("uebergabe", {}).get("tag", 3))
            return erster.replace(day=min(tag, erster.day), hour=9, minute=0, second=0, microsecond=0)
        return soll
    soll = _posten_termin()
    if soll and soll < nun:
        return soll
    tag = 15 if nun.day > 15 else 1
    if tag == 15:
        return nun.replace(day=15, hour=7, minute=0, second=0, microsecond=0)
    letzter_monat = nun.replace(day=1) - timedelta(days=1)
    return letzter_monat.replace(day=15, hour=7, minute=0, second=0, microsecond=0)


def _termin_merken(name: str, termin: datetime) -> bool:
    """Merkt genau einen Versuch für einen konkreten Solltermin."""
    gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
    alt = _zeitwert(str((gesehen.get("laufversuch", {}) or {}).get(name, "")))
    if alt and alt >= termin:
        return False
    gesehen.setdefault("laufversuch", {})[name] = termin.isoformat(timespec="seconds")
    schreiben(pfad("arbeit", "gesehen.json"), gesehen)
    return True


def _zeitwert(wert: str) -> datetime | None:
    try:
        return datetime.fromisoformat(wert)
    except ValueError:
        return None


def _faellig(name: str, soll: datetime) -> bool:
    """Ist ``soll`` nach der Einrichtung fällig und noch nicht versucht?"""
    gelaufen = _zeitwert(_laufstand(name))
    if gelaufen and gelaufen >= soll:
        return False
    gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
    versuch = _zeitwert(str((gesehen.get("laufversuch", {}) or {}).get(name, "")))
    if versuch and versuch >= soll:
        return False
    ab = _zeitwert(str((gesehen.get("nachholen_ab", {}) or {}).get(name, "")))
    return not ab or soll >= ab


def _faelliger_tag() -> bool:
    soll = _tag_termin()
    return jetzt() >= soll + timedelta(minutes=30) and _faellig("tag", soll)


def _tag_termin() -> datetime:
    zeit = str(konfig("belege").get("takt", {}).get("tag_uhrzeit", "21:00"))
    stunde, minute = (int(x) for x in zeit.split(":"))
    nun = jetzt()
    soll = nun.replace(hour=stunde, minute=minute, second=0, microsecond=0)
    if nun < soll:
        soll -= timedelta(days=1)
    return soll


def _faelliger_monat() -> bool:
    soll = _monat_termin()
    return jetzt() >= soll + timedelta(minutes=30) and _faellig("monat", soll)


def _monat_termin() -> datetime:
    nun = jetzt()
    tag = int(konfig("belege").get("uebergabe", {}).get("tag", 3))
    naechster = (nun.replace(day=28) + timedelta(days=4)).replace(day=1)
    letzter_tag = (naechster - timedelta(days=1)).day
    return nun.replace(day=min(tag, letzter_tag), hour=9, minute=0, second=0, microsecond=0)


def _faellige_posten() -> bool:
    soll = _posten_termin()
    return soll is not None and jetzt() >= soll + timedelta(minutes=30) and _faellig("posten", soll)


def _posten_termin() -> datetime | None:
    nun = jetzt()
    tage = [d for d in (1, 15) if nun.day > d or (nun.day == d and (nun.hour, nun.minute) >= (7, 0))]
    if not tage:
        return None
    return nun.replace(day=tage[-1], hour=7, minute=0, second=0, microsecond=0)


def _termin_freigeben(name: str, termin: datetime) -> None:
    """Eine belegte Sperre ist kein Versuch und lässt denselben Termin offen."""
    gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
    if _zeitwert(str((gesehen.get("laufversuch", {}) or {}).get(name, ""))) == termin:
        del gesehen["laufversuch"][name]
        schreiben(pfad("arbeit", "gesehen.json"), gesehen)


def _nachholen(args) -> None:
    """Startet nach einem ausgeschalteten Mac jeden fälligen Kalenderlauf einmal."""
    from argparse import Namespace
    if not echt(args):
        return
    _alte_laeufe_merken()
    def begrenzt(name, lauf):
        try:
            with _zeitgrenze(_max_minuten() * 60, name, True), Sperre(name):
                return lauf()
        except LaufZuLang:
            return 1
        except SperreBelegt:
            return None

    def posten_lauf():
        monat_modul = importlib.import_module("belege.monat")
        posten_modul = importlib.import_module("belege.posten")
        zwischenstand = Namespace(echt=True, monat=None, uebergabe=False,
                                  zwischenstand=True, anfragen=False, auszug=None, ziel=[])
        if monat_modul.befehl(zwischenstand):
            return 1
        return posten_modul.befehl(Namespace(echt=True, mail=True, antworten=False))

    laeufe = (("tag", _faelliger_tag, _tag_termin, lambda: _lauf(args, ("downloads", "nachsortieren", "bericht"), "tag")),
              ("monat", _faelliger_monat, _monat_termin, lambda: begrenzt("monat", lambda: importlib.import_module("belege.monat").befehl(Namespace(echt=True, monat=None, uebergabe=True, anfragen=False, auszug=None, ziel=[])))),
              ("posten", _faellige_posten, _posten_termin, lambda: begrenzt("posten", posten_lauf)))
    for name, faellig, termin, ausfuehren in laeufe:
        soll = termin()
        if not _nachholen_eingerichtet(name) or not faellig() or not _termin_merken(name, soll):
            continue
        try:
            ergebnis = ausfuehren()
            if ergebnis is None:
                _termin_freigeben(name, soll)
                continue
            ok = ergebnis == 0 if name != "tag" else bool(ergebnis)
            if ok:
                gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
                # Nicht die Uhrzeit des Nachholens merken: erledigt wurde der
                # fällige Solltermin.  Der nächste Kalendertermin bleibt frei.
                gesehen.setdefault("lauf", {})[name] = soll.isoformat(timespec="seconds")
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
    termin = _tag_termin()
    if echt(args) and jetzt() >= termin:
        # Auch ein Kalenderlauf mit fehlerhaftem Schritt ist ein Versuch.  Der
        # Takt darf daraus keine Viertelstunden-Serie machen.  Hand- und
        # Kalenderläufe selbst werden dadurch nie übersprungen.
        _termin_merken("tag", termin)
    ok = _lauf(args, ("downloads", "nachsortieren", "bericht"), "tag")
    if ok and echt(args):
        # Ein Handlauf vor dem Termin erledigt keinen zukünftigen Kalenderlauf.
        if jetzt() >= termin:
            gesehen = lesen(pfad("arbeit", "gesehen.json"), {}) or {}
            gesehen.setdefault("lauf", {})["tag"] = termin.isoformat(timespec="seconds")
            schreiben(pfad("arbeit", "gesehen.json"), gesehen)
    return 0
