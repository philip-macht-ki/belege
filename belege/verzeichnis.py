"""Belegverzeichnis pflegen: Einträge, deren Datei nicht mehr dort liegt.

Läuft täglich im Lauf `belege tag` vor dem Bericht und von Hand als
`belege verzeichnis [--echt]`. Der Index merkt nicht von selbst, wenn jemand
eine Datei in der Ablage löscht, umbenennt oder einen Firmenordner umbenennt.
Das passiert vor allem nach dem Hinweis „Möglicherweise doppelt … lösch eine der
beiden Dateien“. Der verwaiste Eintrag zählte danach weiter in Monat, Jahr und
MCP-Suche. Je Eintrag, dessen Datei fehlt:

1. Liegt eine Datei mit genau diesem Fingerabdruck (SHA-256) nebenan, ohne oder
   mit anderem ``_2``-Zusatz oder unter einem anderen Bereichsordner (etwa
   ``Betrieb/…`` → ``<Firma>/…``), zeigt der Eintrag danach auf sie.
2. Sonst: Gibt es einen anderen Eintrag mit vorhandener Datei, gleicher Firma,
   Art, Datum, Währung, Betrag und gleichem Lieferanten, ist der verwaiste
   Eintrag ein Duplikat und wird aus dem Index genommen. Der alte Eintrag wird
   vorher vollständig nach ``arbeit/verzeichnis_entfernt.jsonl`` geschrieben.
3. Ohne ein solches Duplikat bleibt der Eintrag stehen und steht einmal im
   Tagesbericht unter „Bitte ansehen“. Nie wird ein Eintrag ohne vorhandenes
   Duplikat entfernt.

Zeigen zwei Einträge auf dieselbe Datei und passt ihr Fingerabdruck nur zu einem,
gilt der andere ebenso als verwaist (Schritt 2 und 3). Dateien werden nie
verschoben, umbenannt oder gelöscht.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import kern
from .kern import Ergebnis, ablage_ordner

ENTFERNT = "verzeichnis_entfernt.jsonl"
# Fehlt mehr als dieser Anteil, ist eher die Ablage nicht erreichbar (Cloud-Ordner,
# externe Platte) als Dateien gelöscht. Dann wird nichts geändert, nur gemeldet.
HOECHSTENS_FEHLEND = 0.5
ZUSATZ = re.compile(r"^(?P<stamm>.+?)(?:_(?P<nummer>\d+))?$")


def _datei(eintrag: dict) -> Path | None:
    """Datei eines Eintrags, nur wenn der Pfad relativ ist und in der Ablage bleibt."""
    pfad = str(eintrag.get("pfad") or "")
    teil = Path(pfad)
    # anchor fängt auch Windows-Pfade wie "\\x.pdf" oder "C:x.pdf" ab, die nicht absolut heißen.
    if not pfad or teil.is_absolute() or teil.anchor or teil.drive or ".." in teil.parts:
        return None
    datei = ablage_ordner() / teil
    try:
        datei.resolve().relative_to(ablage_ordner().resolve())
    except (OSError, ValueError):
        return None
    return datei


def _pruefbar(eintrag: dict) -> bool:
    """Absolute oder aus der Ablage führende Pfade bleiben unangetastet und zählen nie als Duplikat."""
    return _datei(eintrag) is not None


def _vorhanden(eintrag: dict) -> bool:
    datei = _datei(eintrag)
    return bool(datei and datei.is_file())


def _bereiche() -> list[str]:
    cfg = kern.konfig("belege").get("ablage", {})
    namen = [str(cfg.get("bereich_betrieb", "Betrieb")), str(cfg.get("bereich_privat", "Privat"))]
    try:
        namen += [str(f["bereich"]) for f in kern.firmen()]
    except RuntimeError:
        pass
    return list(dict.fromkeys(n for n in namen if n))


def _kandidaten(pfad: str) -> list[str]:
    """Relative Pfade, unter denen dieselbe Datei nach Umbenennen liegen könnte."""
    alt = Path(pfad)
    if alt.is_absolute() or not alt.parts:
        return []
    ordner = [alt.parent]
    if len(alt.parts) > 1:
        ordner += [Path(b, *alt.parts[1:-1]) for b in _bereiche() if b != alt.parts[0]]
    stamm = ZUSATZ.match(alt.stem).group("stamm")
    ergebnis = []
    for o in ordner:
        voll = ablage_ordner() / o
        if not voll.is_dir():
            continue
        for datei in sorted(voll.iterdir()):
            treffer = ZUSATZ.match(datei.stem)
            if (datei.is_file() and datei.suffix.lower() == alt.suffix.lower()
                    and treffer and treffer.group("stamm") == stamm):
                ergebnis.append(str(o / datei.name))
    return [k for k in ergebnis if k != pfad]


def _betrag(wert) -> float | None:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _gleicher_vorgang(a: dict, b: dict) -> bool:
    """Gleiche Firma, Art, Datum, Währung, Betrag und gleicher Lieferant."""
    from .ablegen import sauber

    if not a.get("datum") or a.get("datum") != b.get("datum") or a.get("art") != b.get("art"):
        return False
    if str(a.get("waehrung") or "EUR").upper() != str(b.get("waehrung") or "EUR").upper():
        return False
    erster, zweiter = _betrag(a.get("betrag")), _betrag(b.get("betrag"))
    if erster is None or zweiter is None or abs(erster - zweiter) > 0.01:
        return False
    if not a.get("lieferant") or sauber(str(a["lieferant"])).casefold() != sauber(str(b.get("lieferant") or "")).casefold():
        return False
    return kern.firma_von(a) == kern.firma_von(b)


def _beschreiben(eintrag: dict) -> str:
    return "Ein vertraulicher Beleg" if eintrag.get("vertraulich") else str(eintrag.get("pfad"))


def pruefen(index: dict) -> dict:
    """Plan ohne Änderung: umbiegen {sha: neuer_pfad}, entfernen {sha: anderer_sha}, melden [sha]."""
    from .verarbeiten import _sha

    fingerabdruecke: dict[str, str] = {}

    def sha(relativ: str) -> str:
        if relativ not in fingerabdruecke:
            fingerabdruecke[relativ] = _sha(ablage_ordner() / relativ)
        return fingerabdruecke[relativ]

    fehlend = [k for k, e in index.items() if _pruefbar(e) and not _vorhanden(e)]
    umbiegen: dict[str, str] = {}
    for schluessel in fehlend:
        for kandidat in _kandidaten(str(index[schluessel]["pfad"])):
            try:
                if sha(kandidat) == schluessel:
                    umbiegen[schluessel] = kandidat
                    break
            except OSError:
                continue

    def pfad_von(k: str) -> str:
        return umbiegen.get(k) or str(index[k].get("pfad") or "")

    verwaist = [k for k in fehlend if k not in umbiegen]
    # Zwei Einträge auf derselben Datei: der, dessen Fingerabdruck nicht passt, ist verwaist.
    belegt: dict[str, list[str]] = {}
    for k, e in index.items():
        if k in verwaist or not _pruefbar(e):
            continue
        belegt.setdefault(pfad_von(k), []).append(k)
    for relativ, schluessel in belegt.items():
        if len(schluessel) < 2:
            continue
        try:
            inhalt = sha(relativ)
        except OSError:
            continue
        if inhalt in schluessel:
            verwaist += [k for k in schluessel if k != inhalt]

    echte = {k for k in index if k not in verwaist and _pruefbar(index[k])
             and (k in umbiegen or _vorhanden(index[k]))}
    entfernen: dict[str, str] = {}
    melden: list[str] = []
    for schluessel in verwaist:
        eintrag = index[schluessel]
        anderer = next((k for k in sorted(echte, key=pfad_von)
                        if _gleicher_vorgang(eintrag, index[k])), None)
        if anderer:
            entfernen[schluessel] = anderer
        elif eintrag.get("status") in {"abgelegt", "befund"}:
            # Unsortiert, Abofalle und Datei-prüfen-Ordner darf man von Hand leeren.
            melden.append(schluessel)
    return {"umbiegen": umbiegen, "entfernen": entfernen, "melden": melden, "fehlend": len(fehlend)}


def _gemeldet() -> set[str]:
    return set((kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}).get("verzeichnis_gemeldet", []))


def _merken(neu: set[str]) -> None:
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    gesehen["verzeichnis_gemeldet"] = sorted(set(gesehen.get("verzeichnis_gemeldet", [])) | neu)
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)


def _sichern(schluessel: str, eintrag: dict, anderer: str, grund: str) -> None:
    datei = kern.pfad("arbeit", ENTFERNT)
    datei.parent.mkdir(parents=True, exist_ok=True)
    zeile = {"zeit": kern.jetzt().isoformat(), "sha": schluessel, "grund": grund,
             "statt": anderer, "eintrag": eintrag}
    with open(datei, "a", encoding="utf-8") as f:
        f.write(json.dumps(zeile, ensure_ascii=False) + "\n")


def lauf(echt: bool) -> list[Ergebnis]:
    """Prüft das Belegverzeichnis und heilt nur, was sicher ein Duplikat oder umbenannt ist."""
    from .verarbeiten import _index, _speichere_index

    if not ablage_ordner().is_dir():
        return []
    index = _index()
    if not index:
        return []
    plan = pruefen(index)
    if plan["fehlend"] > 20 and plan["fehlend"] > HOECHSTENS_FEHLEND * len(index):
        meldung = (f"{plan['fehlend']} von {len(index)} Belegen fehlen in der Ablage. Ist der Ablageordner "
                   "gerade nicht erreichbar? Am Belegverzeichnis wurde nichts geändert.")
        if echt:
            gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
            heute = kern.jetzt().date().isoformat()
            if gesehen.get("verzeichnis_unerreichbar") != heute:
                kern.ereignis("zweifel", meldung, grund="verzeichnis")
                gesehen["verzeichnis_unerreichbar"] = heute
                kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
        return [Ergebnis("befund", meldung)]
    ergebnisse: list[Ergebnis] = []
    if not echt:
        for k, neu in plan["umbiegen"].items():
            print(f"würde umbiegen: {_beschreiben(index[k])} → {neu}")
        for k, anderer in plan["entfernen"].items():
            print(f"würde entfernen (Duplikat von {_beschreiben(index[anderer])}): {_beschreiben(index[k])}")
        for k in plan["melden"]:
            print(f"fehlt, kein Duplikat, bleibt stehen: {_beschreiben(index[k])}")
        if not (plan["umbiegen"] or plan["entfernen"] or plan["melden"]):
            print("nichts: Alle Einträge im Belegverzeichnis haben ihre Datei.")
        return [Ergebnis("nichts", "trocken", plan)]

    if plan["umbiegen"] or plan["entfernen"]:
        # Plan und Schreiben auf demselben Stand: `belege tag` und `belege verzeichnis`
        # laufen wie der Takt unter der Gesamtsperre (cli.py, SCHREIBEND), also schreibt
        # niemand dazwischen in den Index.
        for k, neu in plan["umbiegen"].items():
            alt = str(index[k]["pfad"])
            index[k]["pfad"] = neu
            for feld, endung in (("xml", ".xml"), ("befund", ".befund.txt")):
                wert = index[k].get(feld)
                if wert and not (ablage_ordner() / str(wert)).exists():
                    passend = Path(neu).with_suffix(".xml") if feld == "xml" else Path(neu + endung)
                    if (ablage_ordner() / passend).exists():
                        index[k][feld] = str(passend)
            if index[k].get("moegliche_dublette") == alt:
                index[k].pop("moegliche_dublette")
            ergebnisse.append(Ergebnis("ok", f"{_beschreiben(index[k])} liegt jetzt unter {neu}."))
        for k, anderer in plan["entfernen"].items():
            eintrag = index.pop(k)
            _sichern(k, eintrag, anderer, "Datei fehlt, Duplikat vorhanden")
            ergebnisse.append(Ergebnis("ok", f"{_beschreiben(eintrag)} fehlte und ist doppelt zu {_beschreiben(index[anderer])}."))
        verbliebene = {str(e.get("pfad")) for e in index.values()}
        for e in index.values():
            if e.get("moegliche_dublette") and str(e["moegliche_dublette"]) not in verbliebene:
                e.pop("moegliche_dublette")
        _speichere_index(index)
        texte = [e.meldung for e in ergebnisse]
        if texte:
            kern.ereignis("verzeichnis", f"Belegverzeichnis aufgeräumt: {len(texte)} Einträge "
                          f"({len(plan['umbiegen'])} umbenannt nachgezogen, {len(plan['entfernen'])} Duplikate ohne Datei entfernt).",
                          eintraege=texte)
    neu = {k for k in plan["melden"] if k not in _gemeldet()}
    for k in sorted(neu, key=lambda s: str(index.get(s, {}).get("pfad"))):
        eintrag = index.get(k)
        if not eintrag:
            continue
        text = (f"{_beschreiben(eintrag)} steht im Belegverzeichnis, die Datei fehlt aber in der Ablage. "
                "Leg sie zurück, falls du sie verschoben hast; das Verzeichnis bleibt unverändert.")
        kern.ereignis("zweifel", text, pfad=None if eintrag.get("vertraulich") else eintrag.get("pfad"),
                      grund="verzeichnis")
        ergebnisse.append(Ergebnis("befund", text))
    if neu:
        _merken(neu)
    return ergebnisse


def befehl(args) -> int:
    """`belege verzeichnis [--echt]`: fehlende Dateien im Belegverzeichnis nachziehen."""
    echt = kern.echt(args)
    ergebnisse = lauf(echt)
    if echt:
        for e in ergebnisse:
            print(e.meldung)
        if not ergebnisse:
            print("nichts: Alle Einträge im Belegverzeichnis haben ihre Datei.")
    return 0
