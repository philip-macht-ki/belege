"""Jahresende: alle Kontoauszüge eines Jahres abgleichen und für den
Steuerberater bündeln (Modul bh7). Baut bewusst auf `monat.py` auf, statt den
Abgleich, die Ausgabedateien oder den Paketbau ein zweites Mal zu schreiben."""

from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path

from . import kern, monat


def _jahr(wert: str | None) -> str:
    """Ohne Angabe zählt im Januar und Februar noch das Vorjahr als "das Jahr"."""
    if wert and re.fullmatch(r"\d{4}", wert):
        return wert
    heute = kern.jetzt().date()
    return str(heute.year - 1) if heute.month <= 2 else str(heute.year)


def _auszugsdateien() -> list[Path]:
    """Alle CSV-Dateien im Auszugsordner, auch eine einzige Jahres-CSV."""
    cfg = kern.konfig("belege").get("monat", {})
    ordner = kern.erweitert(cfg.get("auszuege", ""))
    if not ordner.exists():
        return []
    return sorted(ordner.glob("*.csv"))


def _buchungen_dedupliziert(dateien: list[Path], monat_str: str) -> list[dict]:
    """Liest einen Monat aus allen Kontoauszug-Dateien und zählt Dubletten nur einmal.

    Mehrere CSVs können sich überschneiden (eine Jahres-CSV neben einer
    einzelnen Monats-CSV); dieselbe Buchung (Datum, Betrag, Name, Zweck) soll
    dann nicht doppelt in den Abgleich einfließen.
    """
    gesehen: set[tuple] = set()
    ergebnis: list[dict] = []
    for datei in dateien:
        try:
            gefunden = monat.buchungen(datei, monat_str)
        except Exception as fehler:  # noqa: BLE001 - eine kaputte CSV stoppt das Jahr nicht
            kern.log(f"Kontoauszug {datei.name} für {monat_str} nicht lesbar: {fehler}")
            continue
        for buchung in gefunden:
            schluessel = (
                buchung["datum"], buchung["betrag"], buchung["name"], buchung["zweck"]
            )
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            ergebnis.append(buchung)
    return ergebnis


def _schreibe_jahresausgaben(
    jahr_ordner: Path, jahr: str, ergebnisse: list[dict]
) -> None:
    """Schreibt die Jahresausgaben: alle Monate zusammen, in denselben Formaten
    wie `monat._schreibe_ausgaben`, nur über das ganze Jahr statt einen Monat."""
    jahr_ordner.mkdir(parents=True, exist_ok=True)
    offen = [x for x in ergebnisse if x["status"] == "fehlt"]
    pruefen = [x for x in ergebnisse if x["status"] == "pruefen"]
    privat = [x for x in ergebnisse if x["status"] == "privat"]

    spalten = ["Datum", "Betrag", "Name", "Verwendungszweck"]
    ziel_csv = jahr_ordner / "fehlt_noch.csv"
    with open(ziel_csv, "w", encoding="utf-8", newline="") as ziel:
        schreiber = csv.DictWriter(ziel, fieldnames=spalten, delimiter=";")
        schreiber.writeheader()
        for x in offen:
            schreiber.writerow(
                {
                    "Datum": monat._tag(x["datum"]),
                    "Betrag": f"{abs(x['betrag']):.2f}".replace(".", ","),
                    "Name": x["name"],
                    "Verwendungszweck": x["zweck"],
                }
            )

    summe = monat.euro(sum(abs(x["betrag"]) for x in offen))
    (jahr_ordner / "fehlt_noch.md").write_text(
        f"# Fehlende Belege {jahr}\n\n"
        + "\n".join(monat._zeile(x) for x in offen)
        + f"\n\nSumme: {summe}\n",
        encoding="utf-8",
    )

    zeilen = [f"# Zu prüfen und privat bezahlt {jahr}"]
    if pruefen:
        zeilen += ["", "## Bitte prüfen", ""] + [monat._zeile(x) for x in pruefen]
    if privat:
        zeilen += ["", "## Vom Geschäftskonto bezahlt, Beleg privat", ""]
        zeilen += [monat._zeile(x) for x in privat]
    if not pruefen and not privat:
        zeilen += ["", "Nichts zu klären."]
    (jahr_ordner / "klaerung.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def _paket_jahr(jahr: str, jahr_ordner: Path, index: dict) -> None:
    """Baut arbeit/jahr/<JJJJ>/paket/<MM>/ über `monat.paket_packen`, je Monat.

    `paket_packen` legt sein Ergebnis unter `<ziel>/paket` ab; für den
    Jahresordner braucht es zwölf getrennte Ziele (<MM>), deshalb läuft jeder
    Monat über einen kurzlebigen Zwischenordner, der danach verschwindet.
    """
    ziel_paket = jahr_ordner / "paket"
    if ziel_paket.exists():
        shutil.rmtree(ziel_paket)  # unser Zwischenpaket, nie Belege des Mitglieds
    ziel_paket.mkdir(parents=True)
    tmp = jahr_ordner / "_zwischenpaket"
    for nr in range(1, 13):
        monat_str = f"{jahr}-{nr:02d}"
        if tmp.exists():
            shutil.rmtree(tmp)
        dateien = monat.paket_packen(monat_str, tmp, index)
        if dateien:
            shutil.move(str(tmp / "paket"), str(ziel_paket / f"{nr:02d}"))
    if tmp.exists():
        shutil.rmtree(tmp)
    for name in ("uebersicht.md", "fehlt_noch.csv", "fehlt_noch.md", "klaerung.md"):
        quelle = jahr_ordner / name
        if quelle.exists():
            shutil.copy2(quelle, ziel_paket / name)


def _uebergabe(jahr: str, jahr_ordner: Path, index: dict, args) -> None:
    """Übergibt das Jahrespaket, einmal je Jahr.

    Bei `weg = "mail"` entsteht immer nur ein Entwurf: ein Jahr an Belegen
    passt in keine Mail, deshalb steht im Text nur, wo das Paket liegt.
    """
    echt = kern.echt(args)
    gesehen = kern.lesen(kern.pfad("arbeit", "gesehen.json"), {}) or {}
    schon = gesehen.get("uebergabe_jahr", {}).get(jahr)
    if schon and "nochmal" not in (getattr(args, "ziel", None) or []):
        print(
            f"nichts: {jahr} wurde schon am {schon[:10]} übergeben. Nochmal: "
            f"belege jahr nochmal --jahr {jahr} --uebergabe --echt"
        )
        return

    cfg = kern.konfig("belege").get("uebergabe", {})
    betrieb = kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")

    if cfg.get("weg") == "ordner":
        if not cfg.get("ordner"):
            print("fehler: [uebergabe] ordner ist leer.")
            return
        zielordner = kern.erweitert(cfg["ordner"]) / jahr
        if not echt:
            print(f"trocken: würde das Jahrespaket {jahr} nach {zielordner} kopieren.")
            return
        _paket_jahr(jahr, jahr_ordner, index)
        zielordner.mkdir(parents=True, exist_ok=True)
        quelle_paket = jahr_ordner / "paket"
        for element in sorted(quelle_paket.iterdir()) if quelle_paket.exists() else []:
            ziel_el = kern.freier_name(zielordner / element.name)
            if element.is_dir():
                shutil.copytree(element, ziel_el)
            else:
                shutil.copy2(element, ziel_el)
        ergebnis_text = f"Jahrespaket {jahr} nach {zielordner} kopiert"
    else:
        if not cfg.get("adresse"):
            print(
                "fehler: [uebergabe] adresse ist leer. "
                "Sag deinem Claude: Richte Teil 5 aus einrichten.md ein."
            )
            return
        from .senden import entwurf

        uebersicht = (jahr_ordner / "uebersicht.md").read_text(encoding="utf-8")
        text = (
            f"Hallo,\n\nanbei die Jahresübersicht {jahr}. Das vollständige Paket "
            f"liegt unter {jahr_ordner / 'paket'} auf diesem Rechner "
            f"(mit --paket --echt gebaut, falls es noch fehlt).\n\n"
            f"{uebersicht}\nViele Grüße\n{betrieb}"
        )
        r = entwurf(cfg["adresse"], f"Jahresübergabe {jahr}, {betrieb}", text, [], echt)
        print(f"{r.status}: {r.meldung}")
        if not echt or r.status != "ok":
            return
        ergebnis_text = f"Entwurf für {jahr} an {cfg['adresse']} angelegt"

    stempel = kern.jetzt().isoformat(timespec="seconds")
    gesehen.setdefault("uebergabe_jahr", {})[jahr] = stempel
    kern.schreiben(kern.pfad("arbeit", "gesehen.json"), gesehen)
    kern.ereignis("jahr", f"Übergabe {jahr}: {ergebnis_text}")


def befehl(args) -> int:
    """Gleicht ein ganzes Jahr ab: je Monat wie `belege monat`, dazu die
    Jahresausgaben unter arbeit/jahr/<JJJJ>/. Trocken ist Standard, wie überall."""
    jahr = _jahr(getattr(args, "jahr", None))
    index = kern.lesen(kern.pfad("arbeit", "index.json"), {}) or {}
    dateien = _auszugsdateien()
    jahr_ordner = kern.pfad("arbeit", "jahr", jahr)

    rohdaten: dict[str, dict] = {}
    alle_ergebnisse: list[dict] = []
    zeilen_uebersicht = []
    mit_auszug = 0
    gesamt_zugeordnet = 0
    gesamt_pruefen = 0
    gesamt_fehlt: list[dict] = []

    for nr in range(1, 13):
        monat_str = f"{jahr}-{nr:02d}"
        buchungen_liste = _buchungen_dedupliziert(dateien, monat_str)
        if not buchungen_liste:
            rohdaten[monat_str] = {"status": "kontoauszug_fehlt", "buchungen": []}
            zeilen_uebersicht.append(f"- {monat_str}: Kontoauszug fehlt")
            continue
        mit_auszug += 1
        ergebnis = monat.abgleichen(buchungen_liste, index)
        ziel_monat = kern.pfad("arbeit", "monat", monat_str)
        monat._schreibe_ausgaben(ziel_monat, monat_str, ergebnis)
        rohdaten[monat_str] = {"status": "ausgewertet", "buchungen": ergebnis}
        alle_ergebnisse.extend(ergebnis)

        zugeordnet = sum(x["status"] == "zugeordnet" for x in ergebnis)
        pruefen = sum(x["status"] == "pruefen" for x in ergebnis)
        fehlt = [x for x in ergebnis if x["status"] == "fehlt"]
        gesamt_zugeordnet += zugeordnet
        gesamt_pruefen += pruefen
        gesamt_fehlt.extend(fehlt)
        betrag_fehlt = monat.euro(sum(abs(x["betrag"]) for x in fehlt))
        zeilen_uebersicht.append(
            f"- {monat_str}: {len(ergebnis)} Buchungen, {zugeordnet} zugeordnet, "
            f"{pruefen} prüfen, {len(fehlt)} fehlen noch ({betrag_fehlt})"
        )

    betrieb = kern.konfig("belege").get("betrieb", {}).get("name", "Betrieb")
    jahr_ordner.mkdir(parents=True, exist_ok=True)
    uebersicht_text = "\n".join(zeilen_uebersicht)
    (jahr_ordner / "uebersicht.md").write_text(
        f"# Jahresübersicht {jahr}, {betrieb}\n\n{uebersicht_text}\n",
        encoding="utf-8",
    )
    _schreibe_jahresausgaben(jahr_ordner, jahr, alle_ergebnisse)
    kern.schreiben(jahr_ordner / "jahr.json", rohdaten)

    fehlbetrag = monat.euro(sum(abs(x["betrag"]) for x in gesamt_fehlt))
    ohne_kontoauszug = 12 - mit_auszug
    zeile = (
        f"ok: {jahr}: 12 Monate, {mit_auszug} mit Kontoauszug, "
        f"{len(alle_ergebnisse)} Buchungen, {gesamt_zugeordnet} zugeordnet, "
        f"{gesamt_pruefen} prüfen, {len(gesamt_fehlt)} fehlen noch ({fehlbetrag}), "
        f"{ohne_kontoauszug} ohne Kontoauszug"
    )
    print(zeile)
    kern.ereignis("jahr", zeile)

    echt = kern.echt(args)
    if getattr(args, "anfragen", False):
        monat._anfragen(gesamt_fehlt, echt)
    if getattr(args, "paket", False):
        if not echt:
            ziel_text = jahr_ordner / "paket"
            print(f"trocken: würde das Jahrespaket unter {ziel_text} anlegen.")
        else:
            _paket_jahr(jahr, jahr_ordner, index)
    if getattr(args, "uebergabe", False):
        _uebergabe(jahr, jahr_ordner, index, args)
    return 0
