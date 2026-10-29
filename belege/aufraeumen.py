"""Eine kleine, zustandsbehaftete Aufräumliste für wiederkehrende Rechnungsbefunde."""
from __future__ import annotations

import re
import tomllib
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import kern


def schluessel(name: str) -> str:
    wert = re.sub(r"\b(?:gmbh|ug|ag|kg|ohg|ltd|llc|inc|limited)\b", "", name.casefold())
    return re.sub(r"[^a-z0-9äöüß]", "", wert)


def anleitungen() -> list[dict]:
    datei = kern.pfad("vorlagen", "pruefung_anleitungen.toml")
    if not datei.exists():
        return []
    with datei.open("rb") as f:
        return tomllib.load(f).get("anbieter", [])


def _anleitung(name: str, titel: str = "") -> dict | None:
    heuhaufen = f"{name} {titel}".casefold()
    return next((a for a in anleitungen() if any(str(x).casefold() in heuhaufen for x in a.get("erkennen", []))), None)


def weg(lieferant: str, punkte: list[str], hinweise: list[str], titel: str = "") -> tuple[str, str]:
    if not punkte:
        return "hinweis", ""
    anleitung = _anleitung(lieferant, titel)
    empfaenger = all("empfänger" in p.casefold() or "anschrift" in p.casefold() for p in punkte)
    if empfaenger and anleitung:
        return "selbst", str(anleitung.get("klickweg", ""))
    return "lieferant", ""


def zustand() -> dict:
    return kern.lesen(kern.pfad("arbeit", "pruefung_anbieter.json"), {}) or {"erste_liste": None, "anbieter": {}}


def speichern(daten: dict) -> None:
    kern.schreiben(kern.pfad("arbeit", "pruefung_anbieter.json"), daten)


def aktualisieren(eintrag: dict, daten: dict | None = None) -> tuple[dict, bool]:
    """Übernimmt einen Befund und sagt, ob der Tagesbericht ihn einmal nennen soll."""
    daten = daten if daten is not None else zustand()
    anbieter = daten.setdefault("anbieter", {})
    name = str(eintrag.get("lieferant") or "Unbekannt")
    key = schluessel(name)
    punkte = list(eintrag.get("punkte") or [])
    hinweise = list(eintrag.get("hinweise") or [])
    datum = str(eintrag.get("datum") or date.today().isoformat())
    weg_name, _ = weg(name, punkte, hinweise, str(eintrag.get("titel") or ""))
    alt = anbieter.get(key)
    neu = alt is None
    neue_punkte = set(punkte) - set((alt or {}).get("probleme", []))
    if alt and alt.get("status") == "erledigt" and neue_punkte:
        alt["status"] = "offen"
        neu = True
    if alt and alt.get("status") == "ignorieren":
        return alt, False
    ziel = alt or {"name": name, "status": "offen", "entwurf": False, "erstmals": datum}
    ziel.update({"name": name, "weg": weg_name, "probleme": sorted(set(ziel.get("probleme", [])) | set(punkte)),
                 "rechnungen": int(ziel.get("rechnungen", 0)) + 1, "zuletzt": datum})
    anbieter[key] = ziel
    return ziel, bool(neu or neue_punkte)


def liste(eintraege: list[dict], daten: dict) -> tuple[str, str]:
    """Reine Darstellung; `daten` wird dabei absichtlich nicht verändert."""
    gruppen: dict[str, list[dict]] = defaultdict(list)
    gesammelt: dict[str, dict] = {}
    keine_belege: list[str] = []
    for e in eintraege:
        if e.get("kein_beleg"):
            keine_belege.append(str(e.get("lieferant") or e.get("mail_von") or "Unbekannt"))
            continue
        name = str(e.get("lieferant") or "Unbekannt")
        key = schluessel(name)
        bereits = key in gesammelt
        aus_zustand = bool(daten.get("anbieter", {}).get(key))
        z = gesammelt.get(key) or (daten.get("anbieter", {}).get(key) or {}).copy()
        if z.get("status") in {"erledigt", "ignorieren"}:
            continue
        punkte, hinweise = list(e.get("punkte") or []), list(e.get("hinweise") or [])
        art, klickweg = weg(name, punkte, hinweise, str(e.get("titel") or ""))
        z.update({"name": z.get("name", name), "rechnungen": int(z.get("rechnungen", 0)) + (1 if not aus_zustand else 0),
                  "probleme": sorted(set(z.get("probleme", [])) | set(punkte)), "weg": art, "klickweg": klickweg})
        gesammelt[key] = z
    for z in gesammelt.values():
        gruppen[z["weg"]].append(z)
    zeilen = ["Rechnungsprüfung: einmal aufräumen", ""]
    anzahl = sum(len(v) for v in gruppen.values())
    for art in ("selbst", "lieferant", "hinweis"):
        for z in sorted(gruppen[art], key=lambda x: (-x["rechnungen"], x["name"].casefold())):
            probleme = ", ".join(z.get("probleme") or ["Hinweise"])
            if art == "selbst":
                aktion = f"stellst du selbst um: {z['klickweg']}"
            elif art == "lieferant":
                aktion = "Lieferant anschreiben – ein Entwurf liegt in deinem Postfach, er geht nie von allein raus"
            else:
                aktion = "nur ein Hinweis für den Steuerberater, du musst nichts tun"
            zeilen.append(f"- {z['name']} ({z['rechnungen']} Rechnungen): {probleme} – {aktion}")
    if keine_belege:
        zeilen += ["", "Diese Absender schicken dir offenbar keine Rechnungen – sollen sie auf die Liste ‚nie Beleg‘?",
                   *[f"- {name}" for name in sorted(set(keine_belege))]]
    zeilen += ["", "Sag deinem Claude: ‚Meta ist erledigt‘ oder ‚SumUp ignorieren‘."]
    return f"Rechnungsprüfung: einmal aufräumen ({anzahl} Anbieter)", "\n".join(zeilen)


def _eintraege(monate: int) -> list[dict]:
    from datetime import timedelta
    grenze = (date.today() - timedelta(days=31 * monate)).isoformat()
    index = kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}
    return [{"lieferant": e.get("lieferant"), "punkte": (e.get("pruefung") or {}).get("punkte", []),
             "hinweise": e.get("hinweise", []), "datum": e.get("datum"), "betrag": e.get("betrag"),
             "mail_von": (e.get("mail") or {}).get("von"), "titel": e.get("beschreibung", "")}
            for e in index.values() if str(e.get("datum") or "") >= grenze and ((e.get("pruefung") or {}).get("status") == "befund" or e.get("hinweise"))]


def befehl(args) -> int:
    eintraege, daten = _eintraege(int(getattr(args, "monate", 3) or 3)), zustand()
    betreff, text = liste(eintraege, daten)
    vorschau = getattr(args, "vorschau", None)
    if vorschau:
        ziel = Path(vorschau)
        inhalt = f"Subject: {betreff}\n\n{text}" if ziel.suffix.lower() == ".eml" else f"# {betreff}\n\n{text}\n"
        ziel.write_text(inhalt, encoding="utf-8")
    elif getattr(args, "echt", False) and anzahl_aktiv(eintraege, daten):
        from .bericht import empfaenger
        from .senden import senden
        senden(empfaenger(), betreff, text, [], True)
    else:
        print(betreff + "\n\n" + text)
    if getattr(args, "echt", False):
        daten["erste_liste"] = kern.jetzt().isoformat()
        speichern(daten)
    return 0


def anzahl_aktiv(eintraege: list[dict], daten: dict) -> int:
    return sum(1 for e in eintraege if (daten.get("anbieter", {}).get(schluessel(str(e.get("lieferant") or "")), {}).get("status", "offen") not in {"erledigt", "ignorieren"}))


def anbieter_befehl(name: str = "", status: str = "") -> list[dict]:
    daten = zustand()
    if name and status:
        key = schluessel(name)
        if key not in daten.setdefault("anbieter", {}):
            daten["anbieter"][key] = {"name": name, "status": status, "weg": "lieferant", "probleme": [], "rechnungen": 0, "erstmals": "", "zuletzt": "", "entwurf": False}
        else:
            daten["anbieter"][key]["status"] = status
        speichern(daten)
    return [dict(schluessel=k, **v) for k, v in sorted(daten.get("anbieter", {}).items())]
