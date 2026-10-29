"""Regelbasierter, opt-in Postfach-Agent ohne Zugriff auf Mailtexte."""
from __future__ import annotations

import json
import inspect
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from email.utils import parseaddr

from . import kern
from .quellen import ausgeschlossen
from .waechter import _eigene_mail, _mitteilung

AKTIONEN = {"archivieren", "liegen lassen", "melden", "melden, sofort"}
# Absender, auf die niemand antwortet, auch die deutschen Schreibweisen.
KEINE_ANTWORT = ("noreply", "no-reply", "no.reply", "no_reply", "donotreply", "do-not-reply", "nicht.antworten", "nicht-antworten", "nichtantworten", "keine-antwort")
ZUSTAENDE = {"beantwortet", "erledigt", "gelesen", "markiert"}
# So beginnen Klartext-Ergebnisse der Postfachwege, wenn nichts passiert ist.
NICHT_GESCHAFFT = ("nicht ", "Microsoft erlaubt noch kein")
# Gedächtnis je Konto und Obergrenze für einen Abruf (Mails, nicht Tage).
MAX_IDS = 5000
# So viele Fehlversuche je Konto und Lauf, bevor der Lauf aufhört (z. B. Server weg).
FEHLER_JE_LAUF = 10
MAX_KURZFASSUNGEN = 30


def _teilen(text: str, trennzeichen: str) -> list[str]:
    """Teilt nur außerhalb einfacher und doppelter Anführungszeichen."""
    teile, start, quote, index = [], 0, "", 0
    while index < len(text):
        zeichen = text[index]
        if zeichen in "\"'":
            quote = "" if quote == zeichen else (zeichen if not quote else quote)
        if not quote and text[index:index + len(trennzeichen)].lower() == trennzeichen.lower():
            teile.append(text[start:index])
            index += len(trennzeichen)
            start = index
            continue
        index += 1
    teile.append(text[start:])
    return teile


def _bedingungen(text: str) -> list[str]:
    """Trennt mit ``und`` verbundene Bedingungen außerhalb von Zitaten."""
    return _teilen(text, " und ")


def _aktion(text: str, nummer: int, fehler: list[str]) -> tuple[str, str] | None:
    """Prüft und normalisiert die Aktion einer einzelnen Regel."""
    niedrig = text.strip().lower()
    for art in ("ordner", "label", "entwurf"):
        if niedrig.startswith(f"{art}:"):
            wert = text.split(":", 1)[1].strip()
            if wert:
                return art, wert
            fehler.append(f"Zeile {nummer}: {art}: braucht einen Wert")
            return None
    normalisiert = re.sub(r",\s*", ", ", niedrig)
    if normalisiert in AKTIONEN:
        return normalisiert, ""
    fehler.append(f"Zeile {nummer}: unbekannte Aktion {text.strip()}")
    return None


def _bedingung_gueltig(text: str) -> bool:
    """Erkennt die kleine, absichtlich feste Sprache der Regelbedingungen."""
    niedrig = text.strip().lower()
    if niedrig.startswith("nicht "):
        return _bedingung_gueltig(text.strip()[6:])
    if niedrig in {"newsletter", "anhang", "sonst", *ZUSTAENDE}:
        return True
    if re.fullmatch(r"(?:ä|ae)lter\s+als\s+\d+\s+tage", niedrig):
        return True
    if ":" not in text:
        return False
    art, wert = text.split(":", 1)
    return art.strip().lower() in {"von", "betreff", "text"} and bool(wert.strip())


def _zustandsregel(regel: dict) -> bool:
    """Erkennt Regeln, die den Zustand einer Mail auswerten."""
    return any(teil.strip().lower().removeprefix("nicht ") in ZUSTAENDE or re.fullmatch(r"(?:ä|ae)lter\s+als\s+\d+\s+tage", teil.strip().lower().removeprefix("nicht ")) for teil in _bedingungen(regel["bedingung"]))


def regeln(datei=None):
    """Liest die SOP-Datei; jede ungültige Regel hält den ganzen Lauf an."""
    datei = datei or kern.pfad("konfig", "postfach-regeln.md")
    gefundene, fehler = [], []
    zeilen = datei.read_text(encoding="utf-8").splitlines() if datei.exists() else []
    lesen = str(kern.konfig("belege").get("aufraeumen", {}).get("lesen", "kopf")).lower()
    if lesen not in {"kopf", "text"}:
        fehler.append('[aufraeumen] lesen muss "kopf" oder "text" sein')
    for nummer, roh in enumerate(zeilen, 1):
        if not roh.startswith("- "):
            continue
        teile = re.split(r"\s*(?:->|→)\s*", roh[2:].strip(), maxsplit=1)
        if len(teile) != 2:
            fehler.append(f"Zeile {nummer}: erwartet Bedingung -> Aktion")
            continue
        bedingung, aktionstext = (teil.strip() for teil in teile)
        if not bedingung:
            fehler.append(f"Zeile {nummer}: Bedingung fehlt")
            continue
        aktion = _aktion(aktionstext, nummer, fehler)
        if not aktion:
            continue
        if not all(_bedingung_gueltig(teil) for teil in _bedingungen(bedingung)):
            fehler.append(f"Zeile {nummer}: unbekannte Bedingung {bedingung}")
            continue
        art, wert = aktion
        if art in {"ordner", "label"}:
            from .postfach import ziel_gesperrt
            if ziel_gesperrt(wert):
                fehler.append(f"Zeile {nummer}: {art}: Papierkorb/Spam ist als Ziel gesperrt")
                continue
        teile_bedingung = _bedingungen(bedingung)
        if any(teil.strip().lower().startswith("text:") for teil in teile_bedingung) and lesen != "text":
            fehler.append(f'Zeile {nummer}: text: braucht lesen = "text" in [aufraeumen]')
            continue
        regel = {"nr": nummer, "bedingung": bedingung, "aktion": art, "wert": wert, "text": roh[2:].strip()}
        if _zustandsregel(regel) and art not in {"archivieren", "ordner"}:
            fehler.append(f"Zeile {nummer}: Zustandsregeln dürfen nur archivieren oder ordner: verwenden")
            continue
        gefundene.append(regel)
    return gefundene, fehler


def _wert(text: str) -> str:
    """Entfernt optionale Anführungszeichen aus einem Regelwert."""
    return text.strip().strip("\"'")


def _passt(mail: dict, regel: dict) -> bool:
    """Prüft ausschließlich die erlaubten Kopfdaten gegen eine Regel."""
    adresse = str(mail.get("von", "")).lower()
    name = str(mail.get("von_name", "")).lower()
    betreff = str(mail.get("betreff", "")).lower()
    for teil in _bedingungen(regel["bedingung"]):
        roh, niedrig = teil.strip(), teil.strip().lower()
        negiert = niedrig.startswith("nicht ")
        pruefung = niedrig[6:] if negiert else niedrig
        if pruefung == "sonst":
            continue
        passt = True
        if pruefung == "newsletter":
            passt = bool(mail.get("newsletter"))
        elif pruefung == "anhang":
            passt = bool(mail.get("anhaenge"))
        elif pruefung == "erledigt":
            marker = str(kern.konfig("belege").get("aufraeumen", {}).get("erledigt_markierung", "Erledigt")).lower()
            zustand = mail.get("zustand", {})
            passt = bool(zustand.get("erledigt") or marker in {str(x).lower() for x in zustand.get("markierungen", [])})
        elif pruefung in ZUSTAENDE:
            passt = bool(mail.get("zustand", {}).get(pruefung))
        alter = re.fullmatch(r"(?:ä|ae)lter\s+als\s+(\d+)\s+tage", pruefung)
        if alter:
            try:
                passt = (kern.jetzt().date() - datetime.fromisoformat(str(mail.get("datum"))).date()).days >= int(alter.group(1))
            except ValueError:
                return False
        if pruefung.startswith("betreff:"):
            passt = _wert(roh.removeprefix("nicht ").split(":", 1)[1]).lower() in betreff
        if pruefung.startswith("text:"):
            passt = _wert(roh.removeprefix("nicht ").split(":", 1)[1]).lower() in str(mail.get("text", "")).lower()
        if pruefung.startswith("von:"):
            suchwert = _wert(roh.split(":", 1)[1]).lower()
            if suchwert.startswith("@"):
                domain = suchwert[1:]
                mail_domain = adresse.rsplit("@", 1)[-1]
                if mail_domain != domain and not mail_domain.endswith("." + domain):
                    passt = False
            elif suchwert not in f"{adresse} {name}":
                passt = False
        if passt == negiert:
            return False
    return True


def passende_regel(mail: dict, alle: list[dict]):
    """Gibt die erste passende Regel zurück, denn ihre Reihenfolge ist Priorität."""
    return next((regel for regel in alle if _passt(mail, regel)), None)


def _antwort_betreff(betreff: str) -> str:
    """Setzt genau ein Antwortpräfix vor den ursprünglichen Betreff."""
    return betreff if betreff.lower().startswith("re:") else f"Re: {betreff}"


def _protokoll(konto: str, mail: dict, regel: dict, aktion: str, ziel: str, ergebnis: str, durchlauf: str = "neu", neue_id: str = "") -> None:
    """Schreibt die vollständige, rückverfolgbare Zeile einer echten Aktion."""
    pfad = kern.pfad("arbeit", "aufraeumen.jsonl")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    privat = not bool(kern.konfig("belege").get("aufraeumen", {}).get("betreffe_im_bericht", True))
    von = str(mail.get("von", ""))
    daten = {"zeit": kern.jetzt().isoformat(timespec="seconds"), "konto": konto, "id": mail["id"], "von": von.rsplit("@", 1)[-1] if privat else von, "betreff": "" if privat else str(mail.get("betreff", ""))[:80], "regel": regel["text"], "aktion": aktion, "ziel": ziel, "ergebnis": ergebnis}
    if durchlauf == "erledigt":
        daten["durchlauf"] = durchlauf
    if neue_id:
        daten["neue_id"] = neue_id
    with pfad.open("a", encoding="utf-8") as datei:
        datei.write(json.dumps(daten, ensure_ascii=False) + "\n")


def faellig(stand: str | None, zeiten: list[str]) -> bool:
    """Prüft heutige und gestrige Berliner Termine, damit Schlaf nachgeholt wird."""
    jetzt = kern.jetzt()
    try:
        letzter_lauf = datetime.fromisoformat(stand) if stand else None
    except ValueError:
        letzter_lauf = None
    termine = []
    for tag in (jetzt.date() - timedelta(days=1), jetzt.date()):
        for wert in zeiten:
            try:
                stunde, minute = map(int, str(wert).split(":"))
                termine.append(jetzt.replace(year=tag.year, month=tag.month, day=tag.day, hour=stunde, minute=minute, second=0, microsecond=0))
            except ValueError:
                continue
    vergangen = [termin for termin in termine if termin <= jetzt]
    return bool(vergangen and (letzter_lauf is None or letzter_lauf < max(vergangen)))


def _mail_ignorieren(mail: dict, bekannte: set[str], eigene: set[str]) -> bool:
    """Hält erledigte, ausgeschlossene und eigene Mails vollständig heraus."""
    return mail.get("id") in bekannte or ausgeschlossen(mail) or _eigene_mail(mail, eigene)


def _aktion_ausfuehren(postfach, konto: str, mail: dict, regel: dict) -> str:
    """Führt eine erlaubte Aktion aus; Antworten bleiben stets Entwürfe."""
    aktion, ziel = regel["aktion"], regel["wert"]
    if aktion in {"archivieren", "ordner", "label"}:
        return postfach.aufraeumen(mail["id"], aktion, ziel)
    if aktion == "entwurf":
        adresse = parseaddr(str(mail.get("antwort_an") or mail.get("von", "")))[1]
        eigene = {str(k.get("adresse", "")).lower() for k in kern.konten()}
        if "@" not in adresse or adresse.lower() in eigene or any(wort in adresse.lower() for wort in KEINE_ANTWORT):
            return "kein Entwurf (keine Antwortadresse)"
        from .senden import entwurf
        antwort_auf = mail if (mail.get("message_id") or mail.get("thread_id")) else None
        if antwort_auf:
            return entwurf(adresse, _antwort_betreff(str(mail.get("betreff", ""))), ziel, [], True, konto, antwort_auf=antwort_auf).meldung
        return entwurf(adresse, _antwort_betreff(str(mail.get("betreff", ""))), ziel, [], True, konto).meldung
    if aktion == "melden, sofort":
        privat = not bool(kern.konfig("belege").get("aufraeumen", {}).get("betreffe_im_bericht", True))
        _mitteilung((str(mail.get("von", "")).rsplit("@", 1)[-1] + " – melden") if privat else f"{mail.get('von', '')} – {mail.get('betreff', '')}")
        from .bericht import empfaenger
        from .senden import senden
        if privat:
            domain = str(mail.get("von", "")).rsplit("@", 1)[-1]
            senden(empfaenger(), "Belege-Postfach: Meldung", f"{domain} – melden", [], True, konto)
        else:
            betreff = re.sub(r"\b\d+(?:[.,]\d{1,2})?\s*€", "", str(mail.get("betreff", "")))
            senden(empfaenger(), f"Belege-Postfach: {betreff[:100]}", f"{mail.get('von', '')} – {mail.get('betreff', '')}", [], True, konto)
    return "gemeldet" if aktion.startswith("melden") else "liegen gelassen"


def _kurzfassung(mail: dict) -> dict:
    """Fragt eine unverbindliche Kurzfassung für den Bericht ab."""
    from . import urteil
    try:
        lokal = str(kern.konfig("belege").get("aufraeumen", {}).get("modell", "eingestellt")).lower() == "lokal"
        daten = urteil.frage(urteil.vorlage("postfach_kurz", mailtext=str(mail.get("text", ""))[:4000]), zweck="postfach-kurz", rueckfall=lambda: {"kurz": ""}, nur_lokal=lokal) or {}
    except (urteil.Unerreichbar, urteil.KeinUrteil):
        return {"kurz": ""}
    if not isinstance(daten, dict):
        return {"kurz": ""}
    kurz = re.sub(r"[\r\n]+", " ", str(daten.get("kurz", ""))).strip()[:160]
    return {"kurz": kurz, "antwort_noetig": bool(daten.get("antwort_noetig"))}


def _konto_laufen(konto: dict, alle: list[dict], gesehen: dict, echt: bool, rest: int, eigene: set[str], durchlauf: str = "neu", kurzfassungen: list[int] | None = None):
    """Plant und bearbeitet höchstens ``rest`` Mails eines aktivierten Kontos."""
    from .postfach import oeffnen
    schluessel = f"aufraeumen:{konto['name']}"
    stand = gesehen.get(schluessel, {})
    bekannte = set(stand.get("ids", []))
    cfg = kern.konfig("belege").get("aufraeumen", {})
    seit = kern.jetzt().date() - timedelta(days=int(cfg.get("erste_tage", 7)))
    neue_id = ""
    if stand.get("stand"):
        try:
            seit = max(seit, datetime.fromisoformat(stand["stand"]).date())
        except ValueError:
            pass
    postfach = oeffnen(konto["name"])
    ausgabe, zaehler, behandelt, fehlversuche, versucht = [], Counter(), [], 0, 0
    # Schon behandelte Mails kommen mit, damit sie die Grenze nicht aufbrauchen;
    # eine mehr zeigt, ob über die Grenze hinaus noch etwas wartet. Mehr als MAX_IDS
    # Mails seit dem letzten Stand sieht ein Lauf nicht (bewusste Obergrenze).
    abholen = min(MAX_IDS, rest + len(bekannte) + FEHLER_JE_LAUF + 1)
    if durchlauf == "erledigt":
        seit = kern.jetzt().date() - timedelta(days=int(cfg.get("erledigt_tage", 90)))
        abholen = min(MAX_IDS, int(cfg.get("erledigt_max", 1000)))
    lesen_text = str(cfg.get("lesen", "kopf")).lower() == "text"
    parameter = inspect.signature(postfach.posteingang).parameters
    if "text" in parameter and "zustand" in parameter:
        zusatz = {"beantwortet": any(teil.strip().lower().removeprefix("nicht ") == "beantwortet" for r in alle for teil in _bedingungen(r["bedingung"]))} if "beantwortet" in parameter else {}
        geholt = postfach.posteingang(seit, abholen, text=lesen_text, zustand=durchlauf == "erledigt", **zusatz)
    else:  # ältere Drittanbieter-Postfächer ohne die erweiterten Parameter
        geholt = postfach.posteingang(seit, abholen)
    if len(geholt) >= MAX_IDS:
        kern.log(f"Postfach-Agent: Posteingang von {konto['name']} sehr voll, ältere Mails kommen erst später dran.")
    neue = [mail for mail in geholt if (not _mail_ignorieren(mail, bekannte if durchlauf == "neu" else set(), eigene))]
    for mail in neue:
        # Fehlversuche verbrauchen die Grenze nicht, sonst blockierte eine einzige
        # dauerhaft scheiternde Mail alle anderen. Sie haben eine eigene Grenze.
        erledigt = len(behandelt) if echt else versucht
        if erledigt >= rest or fehlversuche >= FEHLER_JE_LAUF:
            break
        regel = passende_regel(mail, alle) or ({"aktion": "liegen lassen", "wert": "", "text": "keine"} if durchlauf == "neu" else None)
        if regel is None:
            continue
        versucht += 1
        aktion = regel["aktion"]
        zusatz = " (erledigt)" if durchlauf == "erledigt" else ""
        ausgabe.append(f"würde {aktion}{zusatz}: {mail.get('von') or mail.get('von_name')} – {mail.get('betreff', '')} (Regel: {regel['text']})")
        if not echt:
            zaehler[aktion] += 1
            continue
        try:
            roh_ergebnis = _aktion_ausfuehren(postfach, konto["name"], mail, regel)
            neue_id, ergebnis = str(getattr(roh_ergebnis, "neue_id", "")), str(roh_ergebnis)
        except Exception as fehler:  # eine kaputte Mail hält den Rest nicht auf
            ergebnis = f"fehler: {fehler}"[:200]
        if ergebnis.startswith(NICHT_GESCHAFFT + ("fehler: ",)):
            # Nichts ist passiert (kein MOVE, fehlendes Schreibrecht, Serverfehler):
            # melden und beim nächsten Lauf erneut versuchen, nicht als erledigt merken.
            fehlversuche += 1
            _protokoll(konto["name"], mail, regel, aktion, regel["wert"], ergebnis, durchlauf, neue_id)
            privat = not bool(cfg.get("betreffe_im_bericht", True))
            domain = str(mail.get("von", "")).rsplit("@", 1)[-1]
            text = f"Postfach-Agent: {domain} – {aktion}: {ergebnis}" if privat else f"Postfach-Agent: {mail.get('von', '')} – {mail.get('betreff', '')}: {ergebnis}"
            kern.ereignis("fehler", text[:300], konto=konto["name"], id=mail["id"])
            continue
        # Reihenfolge: erst das Protokoll (zum Rückgängigmachen), dann sofort merken,
        # damit ein Abbruch keinen zweiten Entwurf erzeugt, zuletzt der Bericht.
        _protokoll(konto["name"], mail, regel, aktion, regel["wert"], ergebnis, durchlauf, neue_id)
        behandelt.append(mail["id"])
        if durchlauf == "neu":
            gesehen[schluessel] = {**stand, "ids": list(bekannte | set(behandelt))[-MAX_IDS:]}
            kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
        privat = not bool(cfg.get("betreffe_im_bericht", True))
        domain = str(mail.get("von", "")).rsplit("@", 1)[-1]
        daten = {"aktion": aktion, "konto": konto["name"], "id": mail["id"], "von": domain if privat else mail.get("von", ""), "betreff": "" if privat else str(mail.get("betreff", ""))[:80], "durchlauf": durchlauf, "privat": privat}
        if not privat and durchlauf == "neu" and lesen_text and aktion in {"liegen lassen", "melden", "melden, sofort"} and kurzfassungen is not None and kurzfassungen[0] < MAX_KURZFASSUNGEN:
            daten.update(_kurzfassung(mail))
            kurzfassungen[0] += 1
        kern.ereignis("aufraeumen", f"{aktion}: {domain}" if privat else f"{aktion}: {mail.get('von', '')} – {mail.get('betreff', '')}", **daten)
        zaehler[aktion] += 1
    if durchlauf == "neu" and echt and (behandelt or fehlversuche):
        # Blieb etwas liegen (Grenze oder Fehlversuch), rückt der Stand nicht vor,
        # sonst fielen diese Mails beim nächsten Lauf aus dem Zeitfenster.
        if len(neue) > len(behandelt):
            neuer_stand = datetime.combine(seit, datetime.min.time()).isoformat()
        else:
            neuer_stand = kern.jetzt().isoformat(timespec="seconds")
        gesehen[schluessel] = {"stand": neuer_stand, "ids": list(bekannte | set(behandelt))[-MAX_IDS:]}
    return ausgabe, zaehler, (len(behandelt) if echt else versucht), fehlversuche


def laufen(args, nur_faellig: bool = False) -> int:
    """Räumt opt-in-Konten trocken auf oder führt bestätigte Aktionen aus."""
    echt = kern.echt(args)
    alle, fehler = regeln()
    if fehler:
        for meldung in fehler:
            print(f"fehler: {meldung}")
        return 1
    cfg = kern.konfig("belege").get("aufraeumen", {})
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    takt_schluessel = "aufraeumen:takt"
    if nur_faellig and not faellig((gesehen.get(takt_schluessel) or {}).get("stand"), list(cfg.get("zeiten", ["07:30", "17:30"]))):
        print("nichts: Postfach-Agent noch nicht fällig")
        return 0
    eigene = {str(konto.get("adresse", "")).lower() for konto in kern.konten()}
    grenze, ausgabe, zaehler, verarbeitet, fehlversuche, kurzfassungen = int(cfg.get("max_je_lauf", 200)), [], Counter(), 0, 0, [0]
    neue_regeln = [regel for regel in alle if not _zustandsregel(regel)]
    zustandsregeln = [regel for regel in alle if _zustandsregel(regel)]
    for konto in kern.konten():
        if not konto.get("aufraeumen") or verarbeitet >= grenze:
            continue
        zeilen, zahlen, anzahl, fehlgeschlagen = _konto_laufen(konto, neue_regeln, gesehen, echt, grenze - verarbeitet, eigene, kurzfassungen=kurzfassungen)
        ausgabe.extend(zeilen)
        zaehler.update(zahlen)
        verarbeitet += anzahl
        fehlversuche += fehlgeschlagen
        if zustandsregeln and verarbeitet < grenze:
            zeilen, zahlen, anzahl, fehlgeschlagen = _konto_laufen(konto, zustandsregeln, gesehen, echt, grenze - verarbeitet, eigene, "erledigt", kurzfassungen)
            ausgabe.extend(zeilen)
            if "archivieren" in zahlen:
                zaehler["erledigte archiviert"] += zahlen.pop("archivieren")
            zaehler.update(zahlen)
            verarbeitet += anzahl
            fehlversuche += fehlgeschlagen
    if echt:
        if nur_faellig:
            gesehen[takt_schluessel] = {"stand": kern.jetzt().isoformat(timespec="seconds")}
        kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    for zeile in ausgabe:
        print(zeile)
    print(", ".join(f"{anzahl} {aktion}" for aktion, anzahl in zaehler.items()) or "nichts: keine passenden Mails")
    if fehlversuche:
        print(f"fehler: {fehlversuche} Mail(s) nicht aufgeräumt, siehe Tagesbericht; der nächste Lauf versucht es erneut.")
        return 1
    return 0


def _vorschlagsaktion(sender: str, mails: list[dict]) -> str:
    """Wählt die dokumentierte, rein deterministische Regelheuristik."""
    newsletter = any(mail.get("newsletter") for mail in mails)
    anhang = any(mail.get("anhaenge") for mail in mails)
    betreff = " ".join(str(mail.get("betreff", "")).lower() for mail in mails)
    automatisch = any(wort in sender.lower() for wort in (*KEINE_ANTWORT, "notification", "mailer-daemon"))
    if newsletter or (automatisch and not anhang):
        return "archivieren"
    if anhang and any(wort in betreff for wort in ("rechnung", "invoice", "beleg")):
        return "ordner: Belege"
    return "liegen lassen"


def _gruppe(sender: str, mails: list[dict], regel_sender: str | None = None) -> tuple[str, str]:
    """Formatiert eine Tabellenzeile samt übernehmbarer Regel für den Vorschlag."""
    newsletter = any(mail.get("newsletter") for mail in mails)
    anhang = any(mail.get("anhaenge") for mail in mails)
    beispiele = "; ".join(str(mail.get("betreff", ""))[:60].replace("|", "\\|") for mail in mails[:2])
    regel = f"- von: {regel_sender} -> {_vorschlagsaktion(sender, mails)}" if regel_sender else ""
    zeile = f"| {sender or '(ohne Absender)'} | {len(mails)} | {'ja' if newsletter else 'nein'} | {'ja' if anhang else 'nein'} | {beispiele} | `{regel}` |"
    return zeile, regel


def vorschlag(args) -> int:
    """Liest nur Metadaten und schreibt einen Vorschlag, nie Regeln oder Aktionen."""
    from .postfach import oeffnen
    tage = int(getattr(args, "tage", None) or 28)
    gruppen, ausgeschlossen_anzahl = defaultdict(list), 0
    eigene = {str(konto.get("adresse", "")).lower() for konto in kern.konten()}
    budget = 3000  # für alle Konten zusammen
    vorhandene_ziele = []
    for konto in kern.konten():
        if not konto.get("aufraeumen") or budget <= 0:
            continue
        postfach = oeffnen(konto["name"])
        try:
            ordnung = postfach.ordnung()
            vorhandene_ziele.extend(ordnung.get("ordner", []) + ordnung.get("labels", []))
        except Exception:
            pass
        geholt = postfach.posteingang(kern.jetzt().date() - timedelta(days=tage), budget)
        budget -= len(geholt)
        for mail in geholt:
            if ausgeschlossen(mail) or _eigene_mail(mail, eigene):
                ausgeschlossen_anzahl += 1
            else:
                gruppen[parseaddr(str(mail.get("von", "")))[1].lower()].append(mail)
    alle_mails = [mail for mails in gruppen.values() for mail in mails]
    anteil = 100 * sum(bool(mail.get("newsletter")) for mail in alle_mails) / len(alle_mails) if alle_mails else 0
    top = sorted(gruppen.items(), key=lambda eintrag: -len(eintrag[1]))[:5]
    zeilen = ["# Postfach-Vorschlag", "", "## Überblick", "", f"- Mails gesamt: {len(alle_mails)}", f"- Newsletter: {anteil:.0f} %", f"- Top-5-Absender: {', '.join(sender or '(ohne Absender)' for sender, _ in top) or 'keine'}", f"- {ausgeschlossen_anzahl} ausgeschlossen", "", "| Absender | Anzahl | Newsletter | Anhang | Beispiele | Vorgeschlagene Regel |", "|---|---:|---|---|---|---|"]
    block, domain_mails = [], defaultdict(list)
    for sender, mails in gruppen.items():
        if "@" in sender:
            domain_mails[sender.rsplit("@", 1)[1]].append((sender, mails))
    gruppierte = {sender for eintraege in domain_mails.values() if len(eintraege) >= 3 for sender, _ in eintraege}
    zeilengruppen = []
    for domain, eintraege in domain_mails.items():
        if len(eintraege) >= 3:
            zeilengruppen.append((f"@{domain}", [mail for _, mails in eintraege for mail in mails], f"@{domain}"))
    zeilengruppen.extend((sender, mails, sender if sender else None) for sender, mails in gruppen.items() if sender not in gruppierte)
    for sender, mails, regel_sender in sorted(zeilengruppen, key=lambda eintrag: -len(eintrag[1])):
        zeile, regel = _gruppe(sender, mails, regel_sender)
        zeilen.append(zeile)
        if regel:
            block.append(regel)
    vorhandenes_beleg = next((name for name in vorhandene_ziele if "beleg" in name.lower() or "rechnung" in name.lower()), "")
    if vorhandenes_beleg:
        block = [regel.replace("ordner: Belege", f"ordner: {vorhandenes_beleg}") for regel in block]
        zeilen = [zeile.replace("ordner: Belege", f"ordner: {vorhandenes_beleg}") for zeile in zeilen]
    if any("ordner: Belege" in regel for regel in block):
        zeilen.extend(["", "Hinweis: Mails im Ordner Belege findet der Beleg-Agent weiterhin."])
    zeilen.extend(["", "## Regelblock zum Einfügen", "", *block, "", "Tipp: `belege aufraeumen labels` zeigt deine vorhandenen Ordner und Labels."])
    ziel = kern.pfad("arbeit", "postfach-vorschlag.md")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print(f"ok: {ziel}")
    return 0


def labels(args) -> int:
    """Schreibt vorhandene Ordnung und daraus abgeleitete Regelideen."""
    from .postfach import oeffnen
    zeilen = ["# Postfach-Ordnung", ""]
    eigene = {str(konto.get("adresse", "")).lower() for konto in kern.konten()}
    ausschluesse = [str(wert).lower() for wert in kern.konfig("regeln").get("ausschluss", [])]
    for konto in kern.konten():
        if not konto.get("aufraeumen"):
            continue
        postfach = oeffnen(konto["name"])
        ordnung = postfach.ordnung()
        zeilen.extend([f"## {konto['name']}", "", "Ordner: " + (", ".join(ordnung.get("ordner", [])) or "keine"), "Labels: " + (", ".join(ordnung.get("labels", [])) or "keine"), f"Labels sichtbar: {'ja' if ordnung.get('labels_sichtbar') else 'nein'}"])
        if "keywords_erlaubt" in ordnung:
            zeilen.append(f"IMAP-Keywords erlaubt: {'ja' if ordnung['keywords_erlaubt'] else 'nein'}")
        if ordnung.get("hinweis"):
            zeilen.extend(["", ordnung["hinweis"]])
        zuordnung = postfach.zuordnung()
        # Alte Backends liefern flach; neue trennen sichtbar verschiebbare Ordner
        # und sichtbare Labels/Kategorien ausdrücklich.
        ziele = {"ordner": zuordnung.get("ordner", {}), "labels": zuordnung.get("labels", {})} if set(zuordnung) & {"ordner", "labels"} else {"ordner": zuordnung, "labels": {}}
        verteilung = defaultdict(Counter)
        for art, gruppen in ziele.items():
            for zielname, absender in gruppen.items():
                for adresse in absender:
                    adresse = parseaddr(str(adresse))[1].lower()
                    if adresse and adresse not in eigene and not any(muster in adresse for muster in ausschluesse):
                        verteilung[adresse][(art, zielname)] += 1
        vorschlaege = []
        for adresse, ziele_des_absenders in sorted(verteilung.items()):
            gesamt = sum(ziele_des_absenders.values())
            (art, zielname), anzahl = ziele_des_absenders.most_common(1)[0]
            if anzahl >= 2 and anzahl / gesamt >= .8:
                vorschlaege.append(f"- von: {adresse} -> {'label' if art == 'labels' else 'ordner'}: {zielname}")
        zeilen.extend(["", "### Regeln aus deiner bisherigen Ordnung", "", *(vorschlaege or ["Keine eindeutige Zuordnung gefunden."]), ""])
    ziel = kern.pfad("arbeit", "postfach-ordnung.md")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("\n".join(zeilen), encoding="utf-8")
    print(f"ok: {ziel}")
    return 0


def zurueck(args) -> int:
    """Zeigt oder widerruft heutige protokollierte Verschiebungen, nie Entwürfe."""
    try:
        seit = datetime.fromisoformat(str(getattr(args, "seit", "") or kern.jetzt().date().isoformat())).date()
    except ValueError:
        print("fehler: --seit braucht JJJJ-MM-TT")
        return 1
    pfad = kern.pfad("arbeit", "aufraeumen.jsonl")
    zeilen = [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()] if pfad.exists() else []
    schon = {str(x.get("id", "")) for x in zeilen if x.get("aktion") == "zurueck"}
    kandidaten = [x for x in zeilen if x.get("aktion") in {"archivieren", "ordner", "label"} and str(x.get("zeit", ""))[:10] >= seit.isoformat() and x.get("id") not in schon]
    if not kern.echt(args):
        for eintrag in kandidaten:
            print(f"würde zurückholen: {eintrag.get('konto')} – {eintrag.get('betreff', '') or eintrag.get('von', '')}")
        return 0
    for eintrag in kandidaten:
        if eintrag.get("aktion") == "label" and not eintrag.get("neue_id"):
            # Labels verbleiben bei derselben Mailkennung; das Backend kennt die Aktion.
            pass
        try:
            ergebnis = str(__import__("belege.postfach", fromlist=["oeffnen"]).oeffnen(eintrag["konto"]).zurueckholen(eintrag))
        except Exception as fehler:
            ergebnis = f"fehler: {fehler}"[:200]
        if ergebnis.startswith(("nicht ", "fehler:")):
            print(f"fehler: {eintrag.get('id')}: {ergebnis}")
            continue
        rueck = {"nr": 0, "text": "zurueck"}
        _protokoll(eintrag["konto"], {"id": eintrag["id"], "von": eintrag.get("von", ""), "betreff": eintrag.get("betreff", "")}, rueck, "zurueck", "Posteingang", ergebnis)
        print(f"zurückgeholt: {eintrag.get('konto')} – {eintrag.get('betreff', '') or eintrag.get('von', '')}")
    for eintrag in [x for x in zeilen if x.get("aktion") == "entwurf" and str(x.get("zeit", ""))[:10] >= seit.isoformat()]:
        print("Hinweis: Entwurf liegt noch in Entwürfe")
    return 0


def befehl(args) -> int:
    """Bedient ``aufraeumen``, ``aufraeumen regeln`` und den Vorschlag."""
    ziel = getattr(args, "ziel", []) or []
    if ziel and ziel[0] == "regeln":
        alle, fehler = regeln()
        if fehler:
            for meldung in fehler:
                print(f"fehler: {meldung}")
            return 1
        for regel in alle:
            print(f"{regel['nr']}: {regel['text']}")
        return 0
    if ziel and ziel[0] == "vorschlag":
        return vorschlag(args)
    if ziel and ziel[0] == "labels":
        return labels(args)
    if ziel and ziel[0] == "zurueck":
        return zurueck(args)
    return laufen(args)
