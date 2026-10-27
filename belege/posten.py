"""Offene Konto-Posten: beständiger Zustand, Rückfragen und Antworten."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from . import kern


def posten_id(buchung: dict) -> str:
    """Eine Buchung unabhängig von Dateiname und Reihenfolge wiedererkennen."""
    zweck = re.sub(r"\s+", " ", str(buchung.get("zweck", "")).strip().lower())
    roh = "|".join((str(buchung.get("konto", "")), str(buchung.get("datum", "")),
                    f"{float(buchung.get('betrag', 0)):.2f}", zweck))
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()


def laden() -> dict:
    return kern.lesen(kern.pfad("arbeit", "posten.json"), {}) or {}


def fortschreiben(buchungen: list[dict]) -> dict:
    """Übernimmt neue Ergebnisse, ohne menschliche Klärungen zurückzusetzen."""
    zustand = laden()
    fest = {"zugeordnet", "nachgeholt", "angefragt", "wartet_mensch", "geklaert", "regel"}
    for buchung in buchungen:
        ident = posten_id(buchung)
        alt = zustand.get(ident, {})
        eintrag = {**alt, **{k: v for k, v in buchung.items() if k != "status"}}
        eintrag["id"] = ident
        if alt.get("status") in fest:
            pass
        elif str(buchung.get("status", "")).startswith("zugeordnet"):
            eintrag["status"] = "zugeordnet"
            eintrag["beleg"] = buchung.get("beleg") or buchung.get("beleg_pfad", "")
        elif buchung.get("status") == "gefunden":
            eintrag["status"] = "nachgeholt"
            eintrag["quelle"] = buchung.get("quelle", "")
        elif buchung.get("status") in {"fehlt", "pruefen"}:
            eintrag["status"] = "offen" if buchung.get("status") == "fehlt" else "wartet_mensch"
            if buchung.get("status") == "pruefen":
                eintrag.setdefault("grund", buchung.get("hinweis", "Zuordnung unklar"))
                eintrag.setdefault("seit", kern.jetzt().date().isoformat())
        else:
            eintrag["status"] = buchung.get("status", "offen")
        zustand[ident] = eintrag
    kern.schreiben(kern.pfad("arbeit", "posten.json"), zustand)
    return zustand


def mailtext(zustand: dict) -> str:
    offen = [x for x in zustand.values() if x.get("status") in {"offen", "wartet_mensch"}]
    if not offen:
        return "Hallo,\n\nes gibt derzeit keine offenen Posten.\n"
    zeilen = ["Hallo,", "", "bitte ordne nur diese offenen Posten zu:", ""]
    for x in sorted(offen, key=lambda e: (e.get("datum", ""), e["id"])):
        vorschlag = "Bitte Beleg suchen oder kurz einordnen."
        if x.get("zweck"):
            vorschlag = f"Vorschlag: Beleg bei {x.get('name', 'dem Lieferanten')} bzw. zum Verwendungszweck suchen."
        zeilen += [f"- {x.get('datum', '')} · {abs(float(x.get('betrag', 0))):.2f} € · {x.get('name', '')}",
                   f"  {vorschlag}", f"  Antwort: [{x['id'][:8]}] privat | kein Beleg | liegt bei | andere Firma", ""]
    return "\n".join(zeilen)


def _zieladresse() -> str:
    cfg = kern.konfig("belege")
    return str(cfg.get("bericht", {}).get("an") or (kern.konten() or [{}])[0].get("adresse", ""))


def mail(echt: bool) -> int:
    from .senden import senden
    zustand = laden()
    text = mailtext(zustand)
    if not echt:
        print(text)
        return 0
    r = senden(_zieladresse(), "[Belege-Posten] Offene Posten", text, [], True, fortschritt=f"posten:{kern.jetzt():%Y-%m-%d}")
    print(f"{r.status}: {r.meldung}")
    return 0 if r.gut else 1


def antworten() -> int:
    """Liest ausschließlich Mails mit unserem Betreff-Token und übernimmt klare Antworten."""
    from .postfach import oeffnen
    zustand = laden()
    postfach = oeffnen()
    for kopf in postfach.suchen("betreff:[Belege-Posten]", max=100):
        nachricht = postfach.lesen(kopf["id"])
        text = f"{kopf.get('betreff', '')}\n{nachricht.get('text', '')}".lower()
        for kurz in re.findall(r"\[([0-9a-f]{8})\]", text):
            treffer = [x for ident, x in zustand.items() if ident.startswith(kurz)]
            if len(treffer) != 1:
                continue
            eintrag = treffer[0]
            if "privat" in text:
                eintrag.update(status="geklaert", grund="privat", seit=date.today().isoformat())
            elif "kein beleg" in text or "keinen beleg" in text:
                eintrag.update(status="geklaert", grund="ohne_beleg", seit=date.today().isoformat())
            elif "andere firma" in text:
                eintrag.update(status="geklaert", grund="andere_firma", seit=date.today().isoformat())
            elif "liegt bei" in text:
                eintrag.update(status="wartet_mensch", grund="Beleg liegt bei", seit=date.today().isoformat())
    # Nur Vorschlag, nie Regel automatisch aktivieren.
    geklaert = [x for x in zustand.values() if x.get("status") == "geklaert"]
    namen = {x.get("name", "") for x in geklaert if x.get("name")}
    vorschlaege = []
    for name in sorted(namen):
        if sum(x.get("name") == name for x in geklaert) >= 2:
            vorschlaege.append(f'[[regel]]\nmuster = "{name}"\naktion = "ohne_beleg"\n')
    if vorschlaege:
        ziel = kern.pfad("arbeit", "regel_vorschlaege.toml")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text("# Nur Vorschläge, nicht automatisch wirksam.\n\n" + "\n".join(vorschlaege), encoding="utf-8")
    kern.schreiben(kern.pfad("arbeit", "posten.json"), zustand)
    print(f"ok: {len(zustand)} Posten geprüft.")
    return 0


def befehl(args) -> int:
    if getattr(args, "antworten", False):
        return antworten()
    if getattr(args, "mail", False):
        return mail(kern.echt(args))
    for x in laden().values():
        print(f"{x['id'][:8]} {x.get('status', '')} {x.get('datum', '')} {x.get('name', '')}")
    return 0
