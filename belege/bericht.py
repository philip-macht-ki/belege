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
         "gesendet", "entwurf", "monat", "fehler")


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


def text_und_betreff(liste: list[dict]) -> tuple[str, str]:
    """Baut den Mailtext in Absätzen und einen Betreff mit den wichtigsten Zahlen."""
    if not liste:
        return "Heute nichts Neues.", "Belege: heute nichts Neues"

    gruppen: dict[str, list[dict]] = {art: [] for art in ARTEN}
    for e in liste:
        gruppen[e["art"]].append(e)

    absaetze: list[str] = []
    if gruppen["abgelegt"]:
        zeilen = [_zeile_beleg(e) for e in gruppen["abgelegt"]]
        absaetze.append(f"Abgelegt ({len(zeilen)})\n" + "\n".join(zeilen))

    ansehen = gruppen["unsortiert"] + gruppen["zweifel"]
    if ansehen:
        zeilen = ["- " + e.get("text", "") for e in ansehen]
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

    if gruppen["fehler"]:
        zeilen = ["- " + e.get("text", "") for e in gruppen["fehler"]]
        absaetze.append(
            "Fehler\n" + "\n".join(zeilen)
            + "\nSag deinem Claude: Schau dir den Fehler im Belege-Protokoll an."
        )

    zahlen = [f"{len(gruppen['abgelegt'])} abgelegt"]
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
    liste = neue_ereignisse()
    text, betreff = text_und_betreff(liste)
    if not liste and not konfig("belege").get("bericht", {}).get("leer_senden", True):
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
