"""Tagesbericht und Status.

Der Bericht liest ausschließlich `arbeit/ereignisse/`, nie das Postfach. Was
dort nicht steht, ist nicht passiert. Er geht als kurze Mail an dich selbst.
"""
from __future__ import annotations

import os
import subprocess
from collections import Counter
from datetime import datetime

from .kern import echt, ereignisse, jetzt, konfig, konten, lesen, pfad, schreiben

ARTEN = ("abgelegt", "unsortiert", "zweifel", "doppelt", "waechter", "waechter_sofort",
         "gesendet", "entwurf", "monat", "jahr", "update", "fehler", "vertraulich", "offline", "dokument")


def _gesehen() -> dict:
    return lesen(pfad("arbeit", "gesehen.json"), {}) or {}


def neue_ereignisse() -> list[dict]:
    """Ereignisse seit dem letzten gesendeten Bericht (höchstens gestern und heute)."""
    seit = None
    stand = _gesehen().get("bericht")
    if stand:
        try:
            seit = datetime.fromisoformat(stand)
        except ValueError:
            seit = None
    return [e for e in ereignisse(seit) if e.get("art") in ARTEN]


def _zeile_beleg(e: dict) -> str:
    """"04.10. Pixelwerk 59,50 €" aus einem Ereignis `abgelegt`."""
    d = e.get("daten", {})
    teile = []
    if d.get("datum"):
        try:
            teile.append(datetime.fromisoformat(d["datum"]).strftime("%d.%m."))
        except ValueError:
            teile.append(str(d["datum"]))
    if d.get("lieferant"):
        teile.append(str(d["lieferant"]))
    if d.get("betrag") is not None:
        teile.append(f"{float(d['betrag']):.2f} €".replace(".", ","))
    return "- " + (" ".join(teile) or e.get("text", ""))


FRIST_NAMEN = {"kuendigung": "Kündigung", "ablauf": "Ablauf", "zahlung": "Zahlung", "termin": "Termin"}


def _zeile_dokument(e: dict) -> str:
    """"Vertrag: Telekom, Handyvertrag (Kündigung bis 30.09.2027)" aus einem Ereignis `dokument`."""
    d = e.get("daten", {})
    if d.get("vertraulich"):
        return "- " + e.get("text", "")
    art = str(d.get("dokumentart", "")).capitalize().replace("Behoerde", "Behörde")
    zeile = f"- {art}: " + ", ".join(str(x) for x in (d.get("gegenueber"), d.get("titel")) if x)
    frist = d.get("frist") or {}
    if frist.get("datum"):
        try:
            datum = datetime.fromisoformat(frist["datum"]).strftime("%d.%m.%Y")
        except ValueError:
            datum = str(frist["datum"])
        zeile += f" ({FRIST_NAMEN.get(frist.get('art'), 'Frist')} bis {datum})"
    return zeile


def text_und_betreff(liste: list[dict]) -> tuple[str, str]:
    """Baut den Mailtext in Absätzen und einen Betreff mit den wichtigsten Zahlen."""
    if not liste:
        return "Heute nichts Neues.", "Belege: heute nichts Neues"

    gruppen: dict[str, list[dict]] = {art: [] for art in ARTEN}
    for e in liste:
        gruppen[e["art"]].append(e)

    absaetze: list[str] = []
    if gruppen["abgelegt"]:
        nach_firma: dict[str, list[dict]] = {}
        for e in gruppen["abgelegt"]:
            nach_firma.setdefault(str(e.get("daten", {}).get("firma") or "Betrieb"), []).append(e)
        teile = []
        for name, ereignisse_firma in nach_firma.items():
            kopf = f"{name} ({len(ereignisse_firma)})" if len(nach_firma) > 1 else None
            zeilen = [_zeile_beleg(e) for e in ereignisse_firma]
            teile.append((kopf + "\n" if kopf else "") + "\n".join(zeilen))
        absaetze.append(f"Abgelegt ({len(gruppen['abgelegt'])})\n" + "\n".join(teile))

    if gruppen["dokument"]:
        zeilen = [_zeile_dokument(e) for e in gruppen["dokument"]]
        absaetze.append(f"Dokumente abgelegt ({len(zeilen)})\n" + "\n".join(zeilen))

    # Befunde bekannter Anbieter stehen schon in der Aufräumliste; nicht täglich wiederholen.
    zweifel = [e for e in gruppen["zweifel"] if e.get("daten", {}).get("pruefung_neu") is not False]
    ansehen = gruppen["unsortiert"] + zweifel + gruppen["vertraulich"]
    befund = [e for e in gruppen["zweifel"] if e.get("daten", {}).get("pruefung", {}).get("status") == "befund"]
    if befund:
        zeilen = []
        for e in befund:
            d = e.get("daten", {})
            if d.get("pruefung_neu") is False:
                continue
            try:
                from .aufraeumen import schluessel, zustand
                status = (zustand().get("anbieter", {}).get(schluessel(str(d.get("lieferant") or "")), {}) or {}).get("status")
                if status == "ignorieren":
                    continue
            except OSError:
                pass
            if not d.get("lieferant"):  # reines Entwurfsereignis nicht doppelt nennen
                continue
            betrag = f" {float(d['betrag']):.2f} €".replace(".", ",") if d.get("betrag") is not None else ""
            punkte = ", ".join(d.get("pruefung", {}).get("punkte", []))
            zeilen.append(f"- {d.get('lieferant', 'Unbekannt')}{betrag}: {punkte} (Entwurf: {'ja' if d.get('entwurf') else 'nein'})")
        if zeilen:
            absaetze.append("Rechnungen mit Befund\n" + "\n".join(zeilen))
    if ansehen:
        zeilen = ["- Firma unklar: " + e.get("text", "") if e.get("daten", {}).get("grund") == "Firma unklar" else "- " + e.get("text", "") for e in ansehen]
        absaetze.append("Bitte ansehen\n" + "\n".join(zeilen))

    if gruppen["doppelt"]:
        zeilen = ["- " + e.get("text", "") for e in gruppen["doppelt"]]
        absaetze.append("Liegt schon abgelegt, kannst du löschen\n" + "\n".join(zeilen))

    waechter = gruppen["waechter_sofort"] + gruppen["waechter"]
    if waechter:
        zeilen = ["- " + e.get("text", "") for e in waechter]
        absaetze.append("Aus deinem Postfach\n" + "\n".join(zeilen))

    raus = gruppen["gesendet"] + gruppen["entwurf"]
    if raus:
        zeilen = ["- " + e.get("text", "") for e in raus]
        absaetze.append("Gesendet und Entwürfe\n" + "\n".join(zeilen))

    if gruppen["monat"]:
        zeilen = ["- " + e.get("text", "") for e in gruppen["monat"]]
        absaetze.append("Monatsabschluss\n" + "\n".join(zeilen))

    if gruppen["offline"]:
        absaetze.append("Ohne Netz\n- " + gruppen["offline"][-1].get("text", "")
                        + "\nDas ist kein Fehler. Du musst nichts tun.")

    if gruppen["update"]:
        absaetze.append("Belege-Update\n" + "\n".join("- " + e.get("text", "") for e in gruppen["update"]))

    if gruppen["fehler"]:
        zeilen = ["- Etwas ist schiefgelaufen: " + e.get("text", "") for e in gruppen["fehler"]]
        roh = "\n".join(e.get("text", "") for e in gruppen["fehler"]).splitlines()[-5:]
        absaetze.append(
            "Fehler\n" + "\n".join(zeilen)
            + "\nSag deinem Claude: Prüfe den Fehler im Belege-Protokoll und behebe ihn."
            + "\n\nFür Claude/Technik\n" + "\n".join(roh)
        )

    zahlen = [f"{len(gruppen['abgelegt'])} abgelegt"]
    if gruppen["dokument"]:
        zahlen.append(f"{len(gruppen['dokument'])} Dokumente")
    if ansehen:
        zahlen.append(f"{len(ansehen)} zum Ansehen")
    if gruppen["fehler"]:
        zahlen.append(f"{len(gruppen['fehler'])} Fehler")
    return "\n\n".join(absaetze), "Belege: " + ", ".join(zahlen)


def empfaenger() -> str:
    """[bericht].an, sonst die Adresse des ersten Postfachs."""
    an = konfig("belege").get("bericht", {}).get("an", "")
    if an:
        return an
    alle = konten()
    return alle[0].get("adresse", "") if alle else ""


def befehl(args) -> int:
    """`belege bericht`: ohne --echt nur anzeigen, mit --echt an dich selbst senden."""
    # Die erste Zusammenfassung läuft einmal am Ende eines echten Tageslaufs;
    # auch ohne Befund merken wir das, damit später keine Überraschungsmail kommt.
    if echt(args) and konfig("belege").get("pruefung", {}).get("an", False):
        from argparse import Namespace
        from .aufraeumen import befehl as aufraeumen, zustand
        try:
            if not zustand().get("erste_liste"):
                aufraeumen(Namespace(monate=3, vorschau=None, echt=True))
        except Exception as fehler:  # Der Tagesbericht geht trotzdem raus.
            from .kern import ereignis
            ereignis("fehler", f"Aufräumliste der Rechnungsprüfung nicht erstellt: {fehler}")
    liste = neue_ereignisse()
    text, betreff = text_und_betreff(liste)
    if not liste and not konfig("belege").get("bericht", {}).get("leer_senden", False):
        print("nichts: Heute nichts Neues, kein Bericht.")
        return 0
    if not echt(args):
        print(f"{betreff}\n\n{text}")
        return 0

    from .senden import senden

    ergebnis = senden(empfaenger(), betreff, text, [], True)
    if ergebnis.status == "ok":
        # Nur ein wirklich gesendeter Bericht gilt als zugestellt; sonst kommen die
        # Ereignisse beim nächsten Mal wieder.
        gesehen = _gesehen()
        gesehen["bericht"] = jetzt().isoformat(timespec="seconds")
        schreiben(pfad("arbeit", "gesehen.json"), gesehen)
    print(f"{ergebnis.status}: {ergebnis.meldung}")
    return 0 if ergebnis.gut else 1


def zeitplan_an() -> bool:
    """Ist der regelmäßige Lauf bei launchd angemeldet?"""
    r = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/de.belege.takt"],
        capture_output=True,
    )
    return r.returncode == 0


def befehl_status(args) -> int:
    """`belege status`: Belege je Monat, die letzten Ereignisse, Zeitplan an oder aus."""
    index = lesen(pfad("arbeit", "index.json"), {}) or {}
    je_monat: dict[str, Counter] = {}
    for eintrag in index.values():
        monat = str(eintrag.get("datum") or "ohne Datum")[:7]
        je_monat.setdefault(monat, Counter())[eintrag.get("status", "abgelegt")] += 1

    if not je_monat:
        print("Noch keine Belege abgelegt.")
    for monat, zaehler in sorted(je_monat.items()):
        print(f"{monat}: {zaehler['abgelegt']} abgelegt, {zaehler['unsortiert']} unsortiert")

    letzte = ereignisse()[-10:]
    if letzte:
        print("\nZuletzt:")
    for e in letzte:
        print(f"{e.get('zeit', '')[11:16]} {e.get('art')}: {e.get('text')}")

    print("\nZeitplan: " + ("an" if zeitplan_an() else "aus"))
    return 0
