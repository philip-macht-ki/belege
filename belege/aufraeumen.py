"""Eine kleine, zustandsbehaftete Aufräumliste für wiederkehrende Rechnungsbefunde."""
from __future__ import annotations

import re
import tomllib
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import kern


def schluessel(name: str) -> str:
    # Bekannte Anbieter heißen auf Rechnungen verschieden ("Meta Platforms Ireland Ltd").
    anleitung = _anleitung(name)
    if anleitung:
        name = str(anleitung.get("name", name))
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
    # Ganze Wörter: "Metallbau" ist nicht Meta.
    return next((a for a in anleitungen()
                 if any(re.search(rf"(?<!\w){re.escape(str(x).casefold())}(?!\w)", heuhaufen) for x in a.get("erkennen", []))), None)


def _steuerberater_hinweis(hinweise: list[str]) -> bool:
    from .pruefung import EU_OHNE_SATZ
    return EU_OHNE_SATZ in hinweise


def weg(lieferant: str, punkte: list[str], hinweise: list[str], titel: str = "") -> tuple[str, str]:
    """Genau ein Weg je Anbieter; `""` heißt: nichts zu melden."""
    if not punkte:
        return ("hinweis", "") if _steuerberater_hinweis(hinweise) else ("", "")
    anleitung = _anleitung(lieferant, titel)
    empfaenger = all("empfänger" in p.casefold() or "anschrift" in p.casefold() for p in punkte)
    if empfaenger and anleitung:
        return "selbst", str(anleitung.get("klickweg", ""))
    return "lieferant", ""


def zustand() -> dict:
    daten = kern.lesen(kern.pfad("arbeit", "pruefung_anbieter.json"), {})
    if not isinstance(daten, dict):
        daten = {}
    anbieter = daten.get("anbieter")
    daten["anbieter"] = {k: v for k, v in anbieter.items() if isinstance(v, dict)} if isinstance(anbieter, dict) else {}
    daten.setdefault("erste_liste", None)
    return daten


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
    gesammelt: dict[str, dict] = {}
    keine_belege: list[str] = []
    for e in eintraege:
        if e.get("kein_beleg"):
            keine_belege.append(str(e.get("lieferant") or e.get("mail_von") or "Unbekannt"))
            continue
        name = str(e.get("lieferant") or "Unbekannt")
        key = schluessel(name)
        bekannt = daten.get("anbieter", {}).get(key) or {}
        if bekannt.get("status") in {"erledigt", "ignorieren"}:
            continue
        z = gesammelt.setdefault(key, {"name": bekannt.get("name", name), "rechnungen": 0, "probleme": set(),
                                       "hinweise": set(), "entwurf": bool(bekannt.get("entwurf")), "titel": ""})
        z["rechnungen"] += 1
        z["probleme"] |= set(e.get("punkte") or [])
        z["hinweise"] |= set(e.get("hinweise") or [])
        z["titel"] = z["titel"] or str(e.get("titel") or "")
    gruppen: dict[str, list[dict]] = defaultdict(list)
    for z in gesammelt.values():
        art, klickweg = weg(z["name"], sorted(z["probleme"]), sorted(z["hinweise"]), z["titel"])
        if art:
            gruppen[art].append({**z, "klickweg": klickweg})
    anzahl = sum(len(v) for v in gruppen.values())
    zeilen = ["Hallo,", "", "die Rechnungsprüfung hat deine letzten Rechnungen durchgesehen. Hier steht jeder Anbieter "
              "nur einmal, mit genau einem Weg. Danach meldet sie sich nur noch bei Neuem.", ""]
    for art in ("selbst", "lieferant", "hinweis"):
        for z in sorted(gruppen[art], key=lambda x: (-x["rechnungen"], x["name"].casefold())):
            probleme = ", ".join(sorted(z["probleme"])) or "Reverse Charge ohne Pflichtsatz"
            if art == "selbst":
                aktion = f"stellst du selbst um: {z['klickweg']}"
            elif art == "lieferant" and z["entwurf"]:
                aktion = "Lieferant anschreiben – ein Entwurf liegt in deinem Postfach, er geht nie von allein raus"
            elif art == "lieferant":
                aktion = (f"Lieferant anschreiben – sag deinem Claude „Schreib {z['name']} wegen der Rechnung an“, "
                          "er legt einen Entwurf an, der nie von allein rausgeht")
            else:
                aktion = "nur ein Hinweis für den Steuerberater, du musst nichts tun"
            wort = "Rechnung" if z["rechnungen"] == 1 else "Rechnungen"
            zeilen.append(f"- {z['name']} ({z['rechnungen']} {wort}): {probleme} – {aktion}")
    if keine_belege:
        zeilen += ["", "Diese Absender schicken dir offenbar keine Rechnungen – sollen sie auf die Liste ‚nie Beleg‘?",
                   *[f"- {name}" for name in sorted(set(keine_belege))]]
    zeilen += ["", "Wenn du etwas erledigt hast, sag deinem Claude: „Meta ist erledigt“ oder „SumUp ignorieren“. "
               "Dann fragt die Prüfung dazu nicht mehr nach."]
    wort = "Anbieter"
    return f"Rechnungsprüfung: einmal aufräumen ({anzahl} {wort})", "\n".join(zeilen)


def anzahl_zeilen(eintraege: list[dict], daten: dict) -> int:
    return int(re.search(r"\((\d+) Anbieter\)", liste(eintraege, daten)[0]).group(1))


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
        if ziel.suffix.lower() == ".eml":
            from email.message import EmailMessage
            nachricht = EmailMessage()
            nachricht["Subject"] = betreff
            nachricht.set_content(text)
            ziel.write_bytes(bytes(nachricht))
        else:
            ziel.write_text(f"# {betreff}\n\n{text}\n", encoding="utf-8")
    elif getattr(args, "echt", False) and anzahl_zeilen(eintraege, daten):
        from .bericht import empfaenger
        from .senden import senden
        ergebnis = senden(empfaenger(), betreff, text, [], True)
        if ergebnis.status != "ok":
            kern.ereignis("fehler", f"Aufräumliste nicht gesendet: {ergebnis.meldung}")
            return 1
    else:
        print(betreff + "\n\n" + text)
    if getattr(args, "echt", False):
        daten["erste_liste"] = kern.jetzt().isoformat()
        speichern(daten)
    return 0


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
