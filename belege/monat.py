"""Monatlicher, bewusst konservativer Abgleich von Kontoauszug und Belegen."""

from __future__ import annotations

import csv
import re
import shutil
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from . import kern

BEKANNTE = {
    "datum": ("buchungstag", "datum", "valuta"),
    "betrag": ("betrag", "umsatz"),
    "name": ("beguenstigter", "zahlungspflichtiger", "name", "empfänger", "empfaenger"),
    "zweck": ("verwendungszweck", "buchungstext"),
    "soll_haben": ("soll/haben", "soll haben", "soll", "haben"),
}


def _monat(wert: str | None) -> str:
    """Gibt den gewünschten Monat zurück, standardmäßig den Vormonat."""
    if wert and re.fullmatch(r"\d{4}-\d{2}", wert):
        return wert
    erster = kern.jetzt().date().replace(day=1)
    return (erster - timedelta(days=1)).strftime("%Y-%m")


def _normal(wert: str) -> str:
    """Vereinfacht Namen für einen vorsichtigen Lieferantenvergleich."""
    wert = (
        wert.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    wert = unicodedata.normalize("NFKD", wert).encode("ascii", "ignore").decode()
    wert = re.sub(r"\b(gmbh|ug|ag|e\.?k\.?|inc|ltd)\b", " ", wert)
    return re.sub(r"[^a-z0-9]+", " ", wert).strip()


def _betrag(wert: str, soll_haben: str = "") -> float:
    """Liest deutsche und englische Betragsformate einschließlich Soll/Haben."""
    text = str(wert).replace("€", "").replace(" ", "").strip()
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    zahl = float(re.sub(r"[^0-9.+-]", "", text) or "0")
    if "soll" in soll_haben.lower() and zahl > 0:
        return -zahl
    return zahl


def _spalten(kopf: list[str]) -> dict[str, str | None]:
    """Erkennt eindeutige Spalten oder fragt bei Mehrdeutigkeit konservativ nach."""
    klein = {wert: _normal(wert) for wert in kopf}
    gefunden: dict[str, list[str]] = {}
    for art, namen in BEKANNTE.items():
        # Die Namen stehen nach Vorrang: "Buchungstag" schlägt "Valuta". Die erste
        # Stufe, die genau eine Spalte trifft, gewinnt.
        gefunden[art] = []
        for name in namen:
            treffer = [original for original, normal in klein.items() if name in normal]
            if treffer:
                gefunden[art] = treffer
                break
    if all(len(gefunden[art]) == 1 for art in ("datum", "betrag", "name")):
        return {
            art: (werte[0] if len(werte) == 1 else None)
            for art, werte in gefunden.items()
        }
    from .urteil import frage, vorlage

    def rueckfall():
        return {
            art: (werte[0] if len(werte) == 1 else None)
            for art, werte in gefunden.items()
        }

    antwort = frage(
        vorlage("spalten", kopfzeile=" | ".join(kopf)),
        zweck="spalten",
        rueckfall=rueckfall,
    )
    if not isinstance(antwort, dict):
        return rueckfall()
    return {
        art: antwort.get(art) if antwort.get(art) in kopf else None for art in BEKANNTE
    }


def buchungen(datei: Path, monat: str) -> list[dict]:
    """Liest einen Auszug robust und gibt nur Buchungen des gewünschten Monats zurück."""
    roh = next(
        (
            datei.read_text(encoding=kodierung)
            for kodierung in ("utf-8-sig", "cp1252", "latin-1")
            if _lesbar(datei, kodierung)
        ),
        "",
    )
    zeilen = roh.splitlines()
    kopf_nr = next(
        (
            i
            for i, zeile in enumerate(zeilen)
            if len(_teile(zeile)) >= 3
            and sum(
                bool(re.search("datum|betrag|umsatz|name|zweck|buchung", z, re.I))
                for z in _teile(zeile)
            )
            >= 2
        ),
        -1,
    )
    if kopf_nr < 0:
        raise RuntimeError(
            "Die CSV hat keine erkennbare Kopfzeile. Prüfe den Kontoauszug."
        )
    muster = csv.Sniffer().sniff(
        "\n".join(zeilen[kopf_nr : kopf_nr + 3]), delimiters=";,\t|"
    )
    leser = csv.DictReader(zeilen[kopf_nr:], dialect=muster)
    spalten = _spalten(leser.fieldnames or [])
    if not all(spalten.get(art) for art in ("datum", "betrag", "name")):
        raise RuntimeError(
            "Datum, Betrag oder Name sind nicht eindeutig. Prüfe die CSV-Spalten."
        )
    ergebnis = []
    for zeile in leser:
        try:
            tag = _datum(zeile[spalten["datum"]])
            menge = _betrag(
                zeile[spalten["betrag"]], zeile.get(spalten.get("soll_haben") or "", "")
            )
        except (KeyError, ValueError):
            continue
        if tag.strftime("%Y-%m") == monat:
            ergebnis.append(
                {
                    "datum": tag.isoformat(),
                    "betrag": menge,
                    "name": zeile[spalten["name"]].strip(),
                    "zweck": zeile.get(spalten.get("zweck") or "", "").strip(),
                }
            )
    return ergebnis


def _lesbar(datei: Path, kodierung: str) -> bool:
    """Prüft eine Kodierung ohne unlesbare CSV-Ausnahme nach außen zu geben."""
    try:
        datei.read_text(encoding=kodierung)
        return True
    except UnicodeDecodeError:
        return False


def _teile(zeile: str) -> list[str]:
    """Teilt eine mögliche Kopfzeile grob für ihre Erkennung."""
    return re.split(r"[;,\t|]", zeile)


def _datum(wert: str) -> date:
    """Liest die gebräuchlichen Datumsformate eines Kontoauszugs."""
    for format in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return (
                date.fromisoformat(wert)
                if format == "%Y-%m-%d"
                else datetime.strptime(wert.strip(), format).date()
            )
        except ValueError:
            continue
    raise ValueError(wert)


def _auszug(args, monat: str) -> Path | None:
    """Der angegebene Kontoauszug, sonst der jüngste im Auszugsordner mit Buchungen im Monat.

    Gesucht wird über die gelesenen Buchungen, nicht über den Dateitext: deutsche
    Banken schreiben das Datum als 12.09.2026, nicht als 2026-09-12.
    """
    if getattr(args, "auszug", None):
        return Path(args.auszug).expanduser()
    ordner = kern.erweitert(kern.konfig("belege").get("monat", {}).get("auszuege", ""))
    treffer = []
    for datei in ordner.glob("*.csv"):
        try:
            if buchungen(datei, monat):
                treffer.append(datei)
        except Exception as fehler:  # noqa: BLE001 - eine kaputte CSV soll die Suche nicht stoppen
            kern.log(f"Kontoauszug {datei.name} nicht lesbar: {fehler}")
    return max(treffer, key=lambda p: p.stat().st_mtime) if treffer else None


def _gleicher_name(beleg: dict, buchung: dict) -> bool:
    """Prüft ein aussagekräftiges gemeinsames Wort in Lieferant und Buchung."""
    suchraum = _normal(f"{buchung['name']} {buchung['zweck']}").split()
    return any(
        wort in suchraum
        for wort in _normal(str(beleg.get("lieferant", ""))).split()
        if len(wort) >= 4
    )


def abgleichen(buchungen_liste: list[dict], index: dict) -> list[dict]:
    """Ordnet Belege nur bei einem eindeutigen Kandidaten mit Namensbezug zu."""
    benutzt: set[str] = set()
    ohne = kern.konfig("regeln").get("monat", {}).get("ohne_beleg", [])
    ergebnis = []
    for buchung in buchungen_liste:
        eintrag = dict(buchung)
        if any(
            _normal(muster) in _normal(f"{buchung['name']} {buchung['zweck']}")
            for muster in ohne
        ):
            eintrag["status"] = "ohne_beleg"
            ergebnis.append(eintrag)
            continue
        art = "eingang" if buchung["betrag"] < 0 else "ausgang"
        tag = date.fromisoformat(buchung["datum"])
        kandidaten = [
            (sha, beleg)
            for sha, beleg in index.items()
            if sha not in benutzt
            and beleg.get("status") == "abgelegt"
            and beleg.get("bereich") == "betrieb"
            and beleg.get("art") == art
            and beleg.get("betrag") is not None
            and abs(abs(buchung["betrag"]) - float(beleg["betrag"])) <= 0.01
            and _im_fenster(beleg.get("datum"), tag)
        ]
        passende = [
            (sha, beleg) for sha, beleg in kandidaten if _gleicher_name(beleg, buchung)
        ]
        privat = [
            beleg for beleg in index.values()
            if beleg.get("bereich") == "privat" and beleg.get("status") == "abgelegt"
            and beleg.get("betrag") is not None
            and abs(abs(buchung["betrag"]) - float(beleg["betrag"])) <= 0.01
            and _im_fenster(beleg.get("datum"), tag) and _gleicher_name(beleg, buchung)
        ]
        if not kandidaten and privat:
            # Vom Geschäftskonto bezahlt, Beleg liegt unter Privat: für den Steuerberater eine
            # Privatentnahme, kein fehlender Beleg.
            eintrag["status"] = "privat"
            eintrag["beleg_pfad"] = privat[0].get("pfad")
        elif len(passende) == 1 and len(kandidaten) == 1:
            eintrag["status"] = "zugeordnet"
            eintrag["beleg"] = passende[0][0]
            benutzt.add(passende[0][0])
        elif kandidaten:
            eintrag["status"] = "pruefen"
        else:
            eintrag["status"] = "fehlt"
        ergebnis.append(eintrag)
    return ergebnis


def _im_fenster(wert: str | None, tag: date) -> bool:
    """Prüft das vertragliche Zeitfenster rund um eine Buchung."""
    try:
        belegtag = date.fromisoformat(str(wert))
    except ValueError:
        return False
    return tag - timedelta(days=45) <= belegtag <= tag + timedelta(days=5)


def euro(betrag: float) -> str:
    """12.5 → "12,50 €" (nur der Betrag wird umformatiert, nie der übrige Text)."""
    return f"{abs(betrag):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _tag(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d.%m.%Y")


def _zeile(buchung: dict) -> str:
    zweck = f" · {buchung['zweck']}" if buchung.get("zweck") else ""
    return f"- {_tag(buchung['datum'])} · {euro(buchung['betrag'])} · {buchung['name']}{zweck}"


def offene_posten_text(monat: str, ergebnis: list[dict]) -> str:
    """Der Text für den Steuerberater: was fehlt, was zu prüfen ist, mit Summen."""
    offen = [x for x in ergebnis if x["status"] == "fehlt"]
    pruefen = [x for x in ergebnis if x["status"] == "pruefen"]
    teile = []
    if offen:
        summe = euro(sum(abs(x["betrag"]) for x in offen))
        teile.append(f"Zu diesen Zahlungen fehlt noch ein Beleg ({len(offen)}, zusammen {summe}):\n"
                     + "\n".join(_zeile(x) for x in offen))
    if pruefen:
        teile.append("Hier passen mehrere Belege oder der Name ist unklar, bitte prüfen:\n"
                     + "\n".join(_zeile(x) for x in pruefen))
    privat = [x for x in ergebnis if x["status"] == "privat"]
    if privat:
        teile.append("Vom Geschäftskonto bezahlt, der Beleg ist privat (vermutlich Privatentnahme):\n"
                     + "\n".join(_zeile(x) for x in privat))
    if not teile:
        teile.append(f"Zu allen Zahlungen im {monat[5:]}/{monat[:4]} liegt ein Beleg vor.")
    return "\n\n".join(teile)


def _schreibe_ausgaben(ordner: Path, monat: str, ergebnis: list[dict]) -> None:
    """Schreibt die lesbaren Abgleichdateien nach arbeit/monat/<JJJJ-MM>/."""
    ordner.mkdir(parents=True, exist_ok=True)
    offen = [x for x in ergebnis if x["status"] == "fehlt"]
    pruefen = [x for x in ergebnis if x["status"] == "pruefen"]

    spalten = ["Datum", "Betrag", "Name", "Verwendungszweck"]
    with open(ordner / "fehlt_noch.csv", "w", encoding="utf-8", newline="") as ziel:
        schreiber = csv.DictWriter(ziel, fieldnames=spalten, delimiter=";")
        schreiber.writeheader()
        for x in offen:
            schreiber.writerow({
                "Datum": _tag(x["datum"]),
                "Betrag": f"{abs(x['betrag']):.2f}".replace(".", ","),
                "Name": x["name"],
                "Verwendungszweck": x["zweck"],
            })

    summe = euro(sum(abs(x["betrag"]) for x in offen))
    (ordner / "fehlt_noch.md").write_text(
        "# Fehlende Belege\n\n" + "\n".join(_zeile(x) for x in offen) + f"\n\nSumme: {summe}\n",
        encoding="utf-8",
    )
    (ordner / "pruefen.md").write_text(
        "# Bitte prüfen\n\n" + "\n".join(_zeile(x) for x in pruefen) + "\n", encoding="utf-8"
    )

    betrieb = kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")
    zeilen = [f"# Offene Posten {monat[5:]}/{monat[:4]}, {betrieb}", ""]
    for x in offen + pruefen:
        zeilen.append(_zeile(x) + " → Was ist das? ______")
    privat = [x for x in ergebnis if x["status"] == "privat"]
    if privat:
        zeilen += ["", "Vom Geschäftskonto bezahlt, Beleg privat:"] + [_zeile(x) for x in privat]
    (ordner / "klaerung.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    kern.schreiben(ordner / "abgleich.json", ergebnis)


def _als_pdf(bild: Path, ziel: Path) -> Path:
    """Fotos (Kassenbons) werden für die Übergabe zu PDF: DATEV nimmt nur PDF/TIF."""
    from PIL import Image

    pdf = kern.freier_name(ziel / (bild.stem + ".pdf"))
    with Image.open(bild) as offen:
        offen.convert("RGB").save(pdf, "PDF", resolution=200)
    return pdf


def paket_packen(monat: str, ziel: Path, index: dict) -> list[Path]:
    """Kopiert alle abgelegten Betriebsbelege des Monats nach <ziel>/paket/.

    PDFs werden byte-gleich kopiert (ZUGFeRD bleibt erhalten), Fotos zu PDF
    umgewandelt, das XML einer E-Rechnung kommt dazu, außer nur_pdf_tif ist an.
    """
    paket = ziel / "paket"
    if paket.exists():
        shutil.rmtree(paket)  # unser eigenes Zwischenpaket, nie Belege des Mitglieds
    paket.mkdir(parents=True)
    nur_pdf = kern.konfig("belege").get("uebergabe", {}).get("nur_pdf_tif", False)
    ablage = kern.ablage_ordner()
    dateien: list[Path] = []
    for beleg in index.values():
        if str(beleg.get("datum", ""))[:7] != monat:
            continue
        if beleg.get("bereich") != "betrieb" or beleg.get("status") != "abgelegt":
            continue
        quelle = ablage / str(beleg.get("pfad", ""))
        if not quelle.exists():
            continue
        if quelle.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic"):
            dateien.append(_als_pdf(quelle, paket))
        else:
            kopie = kern.freier_name(paket / quelle.name)
            shutil.copy2(quelle, kopie)
            dateien.append(kopie)
        if beleg.get("xml") and not nur_pdf:
            xml = ablage / beleg["xml"]
            if xml.exists():
                xml_kopie = kern.freier_name(paket / xml.name)
                shutil.copy2(xml, xml_kopie)
                dateien.append(xml_kopie)
    return sorted(dateien)


def _uebergabe(monat: str, ziel: Path, index: dict, ergebnis: list[dict], args) -> None:
    """Übergibt das Paket an den Steuerberater, einmal je Monat.

    Die offenen Posten stehen im Mailtext, nicht als Anhang, weil Beleg-Adressen
    wie DATEV Upload Mail nur PDF und TIF annehmen.
    """
    echt = kern.echt(args)
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    schon = gesehen.get("uebergabe", {}).get(monat)
    if schon and "nochmal" not in (getattr(args, "ziel", None) or []):
        print(f"nichts: {monat} wurde schon am {schon[:10]} übergeben. Nochmal: belege monat nochmal "
              f"--monat {monat} --uebergabe --echt")
        return

    dateien = paket_packen(monat, ziel, index)
    cfg = kern.konfig("belege").get("uebergabe", {})
    betrieb = kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")
    betreff = f"Belege {monat[5:]}/{monat[:4]}, {betrieb}"
    text = (
        f"Hallo,\n\nanbei {len(dateien)} Belege für {monat[5:]}/{monat[:4]}.\n\n"
        + offene_posten_text(monat, ergebnis)
        + f"\n\nViele Grüße\n{betrieb}"
    )

    if cfg.get("weg") == "ordner":
        if not cfg.get("ordner"):
            print("fehler: [uebergabe] ordner ist leer.")
            return
        zielordner = kern.erweitert(cfg["ordner"]) / monat
        if not echt:
            print(f"trocken: würde {len(dateien)} Dateien nach {zielordner} kopieren.")
            return
        zielordner.mkdir(parents=True, exist_ok=True)
        for datei in dateien + [ziel / "fehlt_noch.md", ziel / "klaerung.md"]:
            shutil.copy2(datei, kern.freier_name(zielordner / datei.name))
        ergebnis_text = f"{len(dateien)} Belege nach {zielordner} kopiert"
    else:
        if not cfg.get("adresse"):
            print("fehler: [uebergabe] adresse ist leer. "
                  "Sag deinem Claude: Richte Teil 5 aus einrichten.md ein.")
            return
        from .senden import senden

        r = senden(cfg["adresse"], betreff, text, dateien, echt, fortschritt=f"uebergabe:{monat}")
        print(f"{r.status}: {r.meldung}")
        if not echt or r.status != "ok":
            return
        ergebnis_text = f"{len(dateien)} Belege an {cfg['adresse']} gesendet"

    gesehen.setdefault("uebergabe", {})[monat] = kern.jetzt().isoformat(timespec="seconds")
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    kern.ereignis("monat", f"Übergabe {monat}: {ergebnis_text}")


def _anfragen(daten: list[dict], echt: bool) -> None:
    """Legt für jede fehlende Ausgabe einen Rechnungsentwurf an, nie eine Sendung."""
    from .postfach import oeffnen
    from .senden import entwurf

    postfach = oeffnen()
    for buchung in (x for x in daten if x["status"] == "fehlt"):
        wort = next(iter(_normal(buchung["name"]).split()), "")
        treffer = postfach.suchen(f"von:{wort}", max=1) if wort else []
        an = treffer[0].get("von", "") if treffer else ""
        tag = date.fromisoformat(buchung["datum"])
        text = (
            f"Guten Tag,\n\nbitte schicken Sie mir die Rechnung zur Zahlung vom {tag:%d.%m.%Y} "
            f"über {euro(buchung['betrag'])} als PDF. Verwendungszweck: {buchung['zweck']}\n\nDanke."
        )
        entwurf(
            an,
            f"Rechnung zur Zahlung vom {tag:%d.%m.%Y} über {euro(buchung['betrag'])}",
            text,
            [],
            echt,
        )


def befehl(args) -> int:
    """Führt Monatsabgleich, optionale Übergabe und Rechnungsanfragen aus."""
    monat = _monat(getattr(args, "monat", None))
    auszug = _auszug(args, monat)
    if not auszug or not auszug.exists():
        ordner = kern.erweitert(
            kern.konfig("belege").get("monat", {}).get("auszuege", "")
        )
        text = f"Kontoauszug für {monat} fehlt, leg die CSV in {ordner}"
        kern.ereignis("monat", text)
        print(f"nichts: {text}")
        return 0
    index = kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}
    daten = abgleichen(buchungen(auszug, monat), index)
    ziel = kern.pfad("arbeit", "monat", monat)
    _schreibe_ausgaben(ziel, monat, daten)
    zugeordnet = sum(x["status"] == "zugeordnet" for x in daten)
    pruefen = sum(x["status"] == "pruefen" for x in daten)
    fehlt = [x for x in daten if x["status"] == "fehlt"]
    fehlbetrag = f"{sum(abs(x['betrag']) for x in fehlt):.2f}".replace(".", ",")
    ohne_beleg = sum(x["status"] == "ohne_beleg" for x in daten)
    privat = sum(x["status"] == "privat" for x in daten)
    print(
        f"ok: {len(daten)} Buchungen, {zugeordnet} zugeordnet, {pruefen} prüfen, "
        f"{len(fehlt)} fehlen noch ({fehlbetrag} €), {privat} privat bezahlt, {ohne_beleg} ohne Beleg nötig"
    )
    if getattr(args, "uebergabe", False):
        _uebergabe(monat, ziel, index, daten, args)
    if getattr(args, "anfragen", False):
        _anfragen(daten, kern.echt(args))
    return 0
