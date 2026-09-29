"""Wächter für neue Mails: meldet Regeln, ohne jemals Mail-Inhalte auszuführen."""

from __future__ import annotations

import subprocess
from email.utils import parseaddr
from datetime import datetime, timedelta

from . import kern


def regeln() -> list[dict]:
    """Liest klare Wächterregeln mit ihrem optionalen Sofort-Zusatz."""
    datei = kern.pfad("konfig", "waechter.md")
    zeilen = datei.read_text(encoding="utf-8").splitlines() if datei.exists() else []
    return [
        {"text": z[2:].removesuffix(", sofort"), "sofort": z.endswith(", sofort")}
        for z in zeilen
        if z.startswith("- ")
    ]


def pruefe(antwort, ids: set[str]) -> str | None:
    """Validiert ein Modellurteil streng gegen die Mails dieses Laufs."""
    if not isinstance(antwort, list):
        return "Die Antwort muss eine Liste sein."
    for eintrag in antwort:
        if not isinstance(eintrag, dict) or set(eintrag) != {
            "id",
            "regel",
            "sofort",
            "satz",
        }:
            return "Jeder Treffer braucht genau id, regel, sofort und satz."
        if eintrag["id"] not in ids:
            return "Eine id stammt nicht aus den geprüften Mails."
        if (
            not isinstance(eintrag["sofort"], bool)
            or len(str(eintrag["regel"])) > 80
            or len(str(eintrag["satz"])) > 200
        ):
            return "Regel, Satz oder sofort haben ein ungültiges Format."
    return None


def _rueckfall(mails: list[dict], regeln_liste: list[dict]) -> list[dict]:
    """Findet ohne Modell nur deutliche Regelwörter in Betreff und Mailtext."""
    treffer = []
    for mail in mails:
        text = f"{mail['betreff']} {mail['text']}".lower()
        for regel in regeln_liste:
            woerter = [w.lower() for w in regel["text"].split() if len(w) >= 5]
            stichwoerter = [w.rstrip("en") for w in woerter]
            if woerter and any(w in text for w in stichwoerter):
                treffer.append(
                    {
                        "id": mail["id"],
                        "regel": regel["text"][:80],
                        "sofort": regel["sofort"],
                        "satz": f"{mail['betreff']}: passt zu {regel['text']}"[:200],
                    }
                )
    return treffer


def _mitteilung(satz: str) -> None:
    """Zeigt eine lokale macOS-Mitteilung.

    Der Satz wird als Argument übergeben, nie in den AppleScript-Text eingesetzt:
    Er stammt mittelbar aus fremden Mails und darf kein Skript werden können.
    """
    subprocess.run(
        [
            "osascript",
            "-e", "on run argv",
            "-e", 'display notification (item 1 of argv) with title "Belege-Wächter"',
            "-e", "end run",
            "--", satz[:200],
        ],
        capture_output=True,
    )


def _eigene_mail(mail: dict, eigene: set[str]) -> bool:
    """Bericht und Wächter-Meldungen an sich selbst nie erneut prüfen (sonst Endlosschleife)."""
    von = parseaddr(mail.get("von", ""))[1].lower()
    return von in eigene and str(mail.get("betreff", "")).startswith("Belege")


def befehl(args) -> int:
    """Prüft neue Mails gegen konfig/waechter.md. Meldet nur, handelt nie.

    Jede Mail wird genau einmal geprüft (gemerkt über ihre ID). Ohne --echt wird
    nur angezeigt, was gemeldet würde.
    """
    echt = kern.echt(args)
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    alle_regeln = regeln()
    eigene = {str(k.get("adresse", "")).lower() for k in kern.konten()}
    from .postfach import oeffnen
    from .urteil import frage, vorlage

    for konto in kern.konten():
        if not konto.get("waechter"):
            continue
        schluessel = f"waechter:{konto['name']}"
        stand = gesehen.get(schluessel, {})
        bekannt = set(stand.get("ids", []))
        seit = (
            datetime.fromisoformat(stand["stand"]).date()
            if stand.get("stand")
            else kern.jetzt().date() - timedelta(days=1)
        )
        postfach = oeffnen(konto["name"])
        neue = [
            m for m in postfach.suchen(max=30, seit=seit)
            if m["id"] not in bekannt and not _eigene_mail(m, eigene)
        ]
        if not neue:
            continue
        mails = [{**m, "text": postfach.lesen(m["id"]).get("text", "")[:1500]} for m in neue]
        bloecke = "\n".join(
            f'<mail id="{m["id"]}">Von: {m["von"]}\nBetreff: {m["betreff"]}\n{m["text"]}</mail>'
            for m in mails
        )
        antwort = frage(
            vorlage("waechter", regeln="\n".join(f"- {r['text']}" for r in alle_regeln), mails=bloecke),
            zweck="waechter",
            rueckfall=lambda: _rueckfall(mails, alle_regeln),
            pruefe=lambda a: pruefe(a, {m["id"] for m in mails}),
        )
        nach_id = {m["id"]: m for m in mails}
        for treffer in antwort:
            # Ob sofort gemeldet wird, steht in der Regel, nicht im Ermessen des Modells.
            regel = next((r for r in alle_regeln if r["text"].lower() in treffer["regel"].lower()
                          or treffer["regel"].lower() in r["text"].lower()), None)
            if regel is not None:
                treffer["sofort"] = regel["sofort"]
            elif "verdächtig" not in treffer["regel"].lower():
                continue  # Modelle melden gern auch "keine Regel trifft zu"; das ist kein Treffer
            mail = nach_id[treffer["id"]]
            text = f"{treffer['satz']} (von {mail['von']}, Betreff: {mail['betreff']})"
            if not echt:
                print(f"würde melden{' sofort' if treffer['sofort'] else ''}: {text}")
                continue
            art = "waechter_sofort" if treffer["sofort"] else "waechter"
            kern.ereignis(art, text, id=treffer["id"], konto=konto["name"], regel=treffer["regel"])
            if treffer["sofort"]:
                _mitteilung(treffer["satz"])
                from .bericht import empfaenger
                from .senden import senden

                senden(empfaenger(), f"Belege-Wächter: {treffer['satz'][:120]}", text, [], True,
                       konto["name"])
        if echt:
            ids = list(bekannt | set(nach_id))[-500:]
            gesehen[schluessel] = {"stand": kern.jetzt().isoformat(timespec="seconds"), "ids": ids}
    if echt:
        kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    print("ok: Wächter geprüft." if echt else "trocken: Wächter geprüft, nichts gespeichert.")
    return 0
