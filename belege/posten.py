"""Offene Konto-Posten: beständiger Zustand, Rückfragen und Antworten."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from argparse import Namespace

from . import kern


def _eintraege(zustand: dict) -> list[dict]:
    """Nur Posten, nicht die technische Markierung bearbeiteter Mails."""
    return [wert for schluessel, wert in zustand.items()
            if not schluessel.startswith("__") and isinstance(wert, dict)]


def _euro(wert: float) -> str:
    return f"{wert:.2f}".replace(".", ",") + " €"


def posten_id(buchung: dict) -> str:
    """Eine Buchung unabhängig von Dateiname und Reihenfolge wiedererkennen."""
    zweck = re.sub(r"\s+", " ", str(buchung.get("zweck", "")).strip().lower())
    roh = "|".join((str(buchung.get("konto", "")), str(buchung.get("datum", "")),
                    f"{float(buchung.get('betrag', 0)):.2f}", zweck))
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()


def laden() -> dict:
    return kern.lesen(kern.pfad("arbeit", "posten.json"), {}) or {}


def fortschreiben(buchungen: list[dict], monat: str | None = None, *, schreiben: bool = True,
                  zustand: dict | None = None) -> dict:
    """Übernimmt neue Ergebnisse, ohne menschliche Klärungen zurückzusetzen."""
    zustand = dict(laden() if zustand is None else zustand)
    fest = {"zugeordnet", "nachgeholt", "geklaert", "regel"}
    gesehen: set[str] = set()
    for buchung in buchungen:
        ident = posten_id(buchung)
        gesehen.add(ident)
        alt = zustand.get(ident, {})
        eintrag = {**alt, **{k: v for k, v in buchung.items() if k != "status"}}
        eintrag["id"] = ident
        neuer_status = buchung.get("status", "offen")
        if alt.get("status") in fest:
            pass
        elif alt.get("status") in {"angefragt", "wartet_mensch"} and neuer_status in {"fehlt", "pruefen"}:
            eintrag["status"] = alt["status"]
            for feld in ("grund", "seit"):
                if feld in alt:
                    eintrag[feld] = alt[feld]
        elif str(neuer_status).startswith("zugeordnet"):
            eintrag["status"] = "zugeordnet"
            eintrag["beleg"] = buchung.get("beleg") or buchung.get("beleg_pfad", "")
        elif neuer_status == "gefunden":
            eintrag["status"] = "nachgeholt"
            eintrag["quelle"] = buchung.get("quelle", "")
        elif neuer_status in {"fehlt", "pruefen"}:
            eintrag["status"] = "offen" if neuer_status == "fehlt" else "wartet_mensch"
            if neuer_status == "pruefen":
                eintrag.setdefault("grund", buchung.get("hinweis", "Zuordnung unklar"))
                eintrag.setdefault("seit", kern.jetzt().date().isoformat())
        else:
            eintrag["status"] = neuer_status
        zustand[ident] = eintrag
    if monat and buchungen:
        for ident, eintrag in zustand.items():
            if ident.startswith("__") or ident in gesehen:
                continue
            if str(eintrag.get("datum", ""))[:7] == monat and eintrag.get("status") not in {"geklaert", "regel"}:
                eintrag["status"] = "entfallen"
    if schreiben:
        kern.schreiben(kern.pfad("arbeit", "posten.json"), zustand)
    return zustand


OFFEN = {"offen", "wartet_mensch"}


def mailtext(zustand: dict) -> str:
    offen = [x for x in _eintraege(zustand) if x.get("status") in OFFEN]
    if not offen:
        return ""
    ausgaben = [x for x in offen if float(x.get("betrag", 0)) < 0]
    eingaenge = [x for x in offen if float(x.get("betrag", 0)) >= 0]
    zeilen = [
        "Hallo,", "",
        f"alles andere aus dem Konto ist zugeordnet und liegt im Ordner. Bei {len(offen)} Posten brauche ich dich. "
        "Antworte einfach auf diese Mail und schreib hinter die Nummer eines dieser Wörter:",
        "",
        "privat = privat bezahlt",
        "kein Beleg = dafür gibt es keinen Beleg",
        "liegt ab = der Beleg ist schon im Ordner, frag nicht mehr",
        "liegt bei = ich hänge ihn an diese Antwort oder lege ihn noch in den Ordner",
        "andere Firma = gehört zu einer anderen Firma",
        "",
    ]

    def liste(gruppe: list[dict], hinweis) -> list[str]:
        teile = []
        for x in sorted(gruppe, key=lambda e: (e.get("datum", ""), e["id"])):
            datum = date.fromisoformat(str(x.get("datum", ""))).strftime("%d.%m.%Y")
            name = x.get("name") or "dem Anbieter"
            betrag = _euro(abs(float(x.get("betrag", 0))))
            if x.get("kurs_fehlt"):  # Fremdwährung ohne Kurs: nicht als Euro ausgeben
                betrag = betrag.replace("€", str(x.get("waehrung", "")))
            teile += [f"{datum} · {betrag} · {name}", hinweis(name),
                      f"[{x['id'][:8]}] → ", ""]
        return teile

    if ausgaben:
        kopf = "Bei dieser Abbuchung fehlt noch der Beleg:" if len(ausgaben) == 1 else \
            f"Bei diesen {len(ausgaben)} Abbuchungen fehlt noch der Beleg:"
        zeilen += [kopf, ""] + liste(ausgaben, lambda name: f"Der Beleg kommt meist als Mail von {name}.")
    if eingaenge:
        kopf = "Bei diesem Zahlungseingang fehlt deine Rechnung:" if len(eingaenge) == 1 else \
            f"Bei diesen {len(eingaenge)} Zahlungseingängen fehlt deine Rechnung:"
        zeilen += [kopf, ""] + liste(
            eingaenge, lambda _name: "Leg deine Rechnung dazu in den Ordner oder antworte mit: kein Beleg.")
    zeilen += ["Was du offen lässt, frage ich in zwei Wochen wieder."]
    return "\n".join(zeilen)


def _zieladresse() -> str:
    cfg = kern.konfig("belege")
    return str(cfg.get("bericht", {}).get("an") or (kern.konten() or [{}])[0].get("adresse", ""))


def mail(echt: bool) -> int:
    from .senden import senden
    # Vor jeder Rückfrage noch einmal nachsehen: Vieles liegt inzwischen im Ordner.
    _, zustand = _nachpruefen(echt)
    text = mailtext(zustand)
    if not text:
        kern.log("nichts offen, keine Mail")
        if echt:
            _lauf_merken()
        return 0
    offen = [x for x in _eintraege(zustand) if x.get("status") in OFFEN]
    ausgaben = [x for x in offen if float(x.get("betrag", 0)) < 0]
    betrag = sum(abs(float(x.get("betrag", 0))) for x in ausgaben)
    betreff = f"[Belege] {len(offen)} Posten brauchen dich ({_euro(betrag)})"
    if not echt:
        print(f"{betreff}\n\n{text}")
        return 0
    r = senden(_zieladresse(), betreff, text, [], True, fortschritt=f"posten:{kern.jetzt():%Y-%m-%d}")
    print(f"{r.status}: {r.meldung}")
    if r.gut:
        _lauf_merken()
    return 0 if r.gut else 1


def _nachpruefen(echt: bool) -> tuple[int, dict]:
    """Gleicht offene Monate leise erneut ab und liefert den neuen Zustand."""
    from . import monat
    zustand = laden()
    monate = sorted({str(x.get("datum", ""))[:7] for x in _eintraege(zustand)
                     if x.get("status") in {"offen", "wartet_mensch", "angefragt"} and re.fullmatch(r"\d{4}-\d{2}", str(x.get("datum", ""))[:7])})[-12:]
    geaendert = 0
    for monat_wert in monate:
        try:
            args = Namespace(auszug=None)
            auszuege = [pfad for pfad in monat._auszuege(args, monat_wert) if pfad.exists()]
            auszuege = list(dict.fromkeys(auszuege + _register_dateien(monat_wert)))
            if not auszuege:
                continue
            buchungen = monat.buchungen_aus(auszuege, monat_wert)
            index = kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}
            firmen = kern.firmen()
            if len(firmen) > 1:
                daten = []
                for firma in firmen:
                    daten += monat.abgleichen(monat._buchungen_fuer_firma(buchungen, firma, firmen), index, firma["name"])
            else:
                daten = monat.abgleichen(buchungen, index)
            vorher = {k: dict(v) for k, v in zustand.items() if isinstance(v, dict)}
            # Ohne Monat: Hier wird nichts als entfallen abgeräumt, das darf nur der Monatslauf,
            # der alle Auszüge sicher beisammen hat.
            zustand = fortschreiben(daten, schreiben=False, zustand=zustand)
            geaendert += sum(v != zustand.get(k) for k, v in vorher.items())
        except Exception as fehler:  # Ein defekter Monat darf keinen anderen stoppen.
            kern.log(f"Posten nachprüfen {monat_wert} fehlgeschlagen: {fehler}")
    if echt and geaendert:
        kern.schreiben(kern.pfad("arbeit", "posten.json"), zustand)
    return geaendert, zustand


def _register_dateien(monat_wert: str) -> list:
    """Auszüge aus eigenen Kontoordnern (konten.toml), nur gelesen, ohne Lückenmeldung."""
    from . import monat
    try:
        register = kern.konfig("konten").get("konto", [])
    except FileNotFoundError:
        return []
    dateien = []
    for konto in register:
        if not konto.get("ordner") or konto.get("quelle", "csv") not in {"csv", "moneymoney", "hibiscus"}:
            continue
        ordner = kern.erweitert(konto["ordner"])
        for datei in sorted(ordner.glob(konto.get("muster") or "*.csv")) if ordner.exists() else []:
            try:
                if monat.buchungen(datei, monat_wert):
                    dateien.append(datei)
            except Exception:  # noqa: BLE001 - eine kaputte CSV stoppt das Nachsehen nicht
                continue
    return dateien


def nachpruefen(echt: bool) -> int:
    """Prüft offene Posten der letzten zwölf Monate ohne Mail oder Nachsuche."""
    geaendert, _ = _nachpruefen(echt)
    print(f"ok: {geaendert} Posten neu bewertet." if echt else f"trocken: {geaendert} Posten würden sich ändern.")
    return geaendert


def _lauf_merken() -> None:
    """Ein erfolgreicher Zwischenstand verhindert ein zweites Nachholen."""
    nun = kern.jetzt()
    tage = [tag for tag in (1, 15) if nun.day > tag or (nun.day == tag and (nun.hour, nun.minute) >= (7, 0))]
    # Ein Handlauf vor dem nächsten Solltermin sperrt diesen nicht.
    if not tage:
        return
    termin = nun.replace(day=tage[-1], hour=7, minute=0, second=0, microsecond=0)
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    gesehen.setdefault("lauf", {})["posten"] = termin.isoformat(timespec="seconds")
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)


def antworten() -> int:
    """Liest ausschließlich Mails mit unserem Betreff-Token und übernimmt klare Antworten."""
    from .postfach import oeffnen
    zustand = laden()
    postfach = oeffnen()
    bearbeitet = set(zustand.get("__bearbeitete_mails__", []))
    for kopf in postfach.suchen("betreff:[Belege]", max=100):
        if kopf["id"] in bearbeitet:
            continue
        nachricht = postfach.lesen(kopf["id"])
        zeilen = []
        for zeile in str(nachricht.get("text", "")).splitlines():
            if re.match(r"\s*(Am .+ schrieb.*:|On .+ wrote:)\s*$", zeile, re.I):
                break
            if not zeile.lstrip().startswith(">"):
                zeilen.append(zeile)
        for nr, zeile in enumerate(zeilen):
            ids = re.findall(r"\[([0-9a-f]{8})\]", zeile, re.I)
            if len(ids) != 1:
                continue
            antwort = zeile
            if nr + 1 < len(zeilen) and not re.search(r"\[[0-9a-f]{8}\]", zeilen[nr + 1], re.I):
                antwort += " " + zeilen[nr + 1]
            klein = antwort.lower()
            # Die Vorlage selbst ist keine Antwort.
            if all(wort in klein for wort in ("privat", "kein beleg", "liegt ab", "liegt bei", "andere firma")):
                continue
            kurz = ids[0]
            treffer = [x for ident, x in zustand.items() if not ident.startswith("__") and ident.startswith(kurz)]
            if len(treffer) != 1:
                continue
            eintrag = treffer[0]
            if "liegt ab" in klein or "ist abgelegt" in klein or "schon abgelegt" in klein:
                eintrag.update(status="geklaert", grund="liegt_ab", seit=date.today().isoformat())
            elif "einnahme" in klein:
                eintrag.update(status="geklaert", grund="einnahme", seit=date.today().isoformat())
            elif "privat" in klein:
                eintrag.update(status="geklaert", grund="privat", seit=date.today().isoformat())
            elif "kein beleg" in klein or "keinen beleg" in klein:
                eintrag.update(status="geklaert", grund="ohne_beleg", seit=date.today().isoformat())
            elif "andere firma" in klein:
                eintrag.update(status="geklaert", grund="andere_firma", seit=date.today().isoformat())
            elif "liegt bei" in klein:
                eintrag.update(status="wartet_mensch", grund="Beleg liegt bei", seit=date.today().isoformat())
        bearbeitet.add(kopf["id"])
    zustand["__bearbeitete_mails__"] = sorted(bearbeitet)
    # Nur Vorschlag, nie Regel automatisch aktivieren.
    geklaert = [x for x in _eintraege(zustand) if x.get("status") == "geklaert"]
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


GRUENDE = {"privat": "privat", "kein-beleg": "ohne_beleg", "andere-firma": "andere_firma",
           "einnahme": "einnahme", "liegt-ab": "liegt_ab"}


def klaeren(suchen: list[str], grund: str | None, echt: bool) -> int:
    """Übernimmt eine Klärung aus dem Gespräch statt aus einer Antwortmail.

    Kennung ist die Nummer aus der Mail (acht Zeichen) oder ein Suchtext aus Name oder
    Zweck. Geklärt werden nur Posten, die noch offen sind; Zugeordnetes bleibt, wie es ist.
    """
    if grund not in GRUENDE:
        print("fehler: Nutze: belege posten --klaeren NUMMER-ODER-SUCHTEXT --grund "
              + "|".join(GRUENDE) + " [--echt]")
        return 2
    zustand = laden()
    offen = [x for x in _eintraege(zustand) if x.get("status") in OFFEN | {"angefragt"}]
    erledigt = [x for x in _eintraege(zustand) if x.get("status") == "geklaert"]

    def passt(x: dict, text: str) -> bool:
        if re.fullmatch(r"[0-9a-f]{8}", text):
            return x.get("id", "").startswith(text)
        return text in str(x.get("name", "")).casefold() or text in str(x.get("zweck", "")).casefold()

    fehlend, treffer = [], {}
    for roh in suchen:
        text = roh.strip().strip("[]").casefold()
        gefunden = [x for x in offen if text and passt(x, text)]
        for x in gefunden:
            treffer[x["id"]] = x
        if not gefunden:
            schon = [x for x in erledigt if text and passt(x, text)]
            for x in schon:
                print(f"{x['id'][:8]} {x.get('name', '')}: war schon geklärt ({x.get('grund', '')})")
            if not schon:
                fehlend.append(roh)
    if fehlend:
        print("fehler: Kein offener Posten gefunden zu: " + ", ".join(fehlend)
              + ". `uv run belege posten` zeigt alle mit Nummer.")
        return 1
    for eintrag in treffer.values():
        datum = str(eintrag.get("datum", ""))
        zeile = (f"{eintrag['id'][:8]} {datum} {eintrag.get('name', '')} "
                 f"{_euro(abs(float(eintrag.get('betrag', 0))))}: geklärt ({GRUENDE[grund]})")
        print(zeile if echt else "trocken: würde eintragen: " + zeile)
        if echt:
            eintrag.update(status="geklaert", grund=GRUENDE[grund], seit=date.today().isoformat(), weg="gespraech")
    if echt and treffer:
        kern.schreiben(kern.pfad("arbeit", "posten.json"), zustand)
    return 0


def befehl(args) -> int:
    if getattr(args, "klaeren", None):
        return klaeren(args.klaeren, getattr(args, "grund", None), kern.echt(args))
    if getattr(args, "antworten", False):
        return antworten()
    if getattr(args, "mail", False):
        return mail(kern.echt(args))
    for x in _eintraege(laden()):
        print(f"{x['id'][:8]} {x.get('status', '')} {x.get('datum', '')} {x.get('name', '')} {_euro(abs(float(x.get('betrag', 0))))} {x.get('grund', '')}")
    return 0
