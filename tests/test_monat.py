"""Tests für den konservativen Monatsabgleich."""
from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timedelta

from belege import kern, monat


def _args(**werte):
    """Baut die kleinen Argumente für einen Monatslauf."""
    grund = {"monat": None, "auszug": None, "uebergabe": False, "anfragen": False, "echt": False}
    grund.update(werte)
    return argparse.Namespace(**grund)


def test_monat_ordnet_zu_und_markiert_unklar(repo):
    """Gleiche Beträge ohne eindeutigen Namen bleiben bewusst zur Prüfung offen."""
    monat_wert = (kern.jetzt().date() - timedelta(days=1)).strftime("%Y-%m")
    tag = f"01.{monat_wert[5:]}.{monat_wert[:4]}"
    auszug = repo / "auszug.csv"
    with open(auszug, "w", encoding="cp1252", newline="") as datei:
        csv.writer(datei, delimiter=";").writerows(
            [["Hinweis"], ["Buchungstag", "Name", "Verwendungszweck", "Betrag"],
             [tag, "Pixelwerk GmbH", "Abo", "-9,90"], [tag, "Kopierzentrum Schnell", "Kopien", "-34,00"],
             [tag, "Finanzamt", "Steuer", "-12,00"]]
        )
    kern.schreiben(repo / "arbeit/index.json", {
        "a": {
            "datum": f"{monat_wert}-01", "betrag": 9.90, "lieferant": "Pixelwerk",
            "art": "eingang", "bereich": "betrieb", "status": "abgelegt",
        },
        "b": {
            "datum": f"{monat_wert}-01", "betrag": 9.90, "lieferant": "Anderer",
            "art": "eingang", "bereich": "betrieb", "status": "abgelegt",
        },
    })
    assert monat.befehl(_args(monat=monat_wert, auszug=str(auszug))) == 0
    daten = kern.lesen(repo / "arbeit" / "monat" / monat_wert / "abgleich.json")
    assert [x["status"] for x in daten] == ["pruefen", "fehlt", "ohne_beleg"]
    assert "Was ist das?" in (repo / "arbeit" / "monat" / monat_wert / "klaerung.md").read_text()


def test_uebergabe_trocken_sendet_nichts(repo):
    """Die Übergabe erzeugt trocken keinen Postausgang und auch keinen Versand."""
    monat_wert = (kern.jetzt().date() - timedelta(days=1)).strftime("%Y-%m")
    auszug = repo / "auszug.csv"
    auszug.write_text("Datum;Name;Betrag\n01.%s.%s;Finanzamt;-1,00\n" % (monat_wert[5:], monat_wert[:4]))
    monat.befehl(_args(monat=monat_wert, auszug=str(auszug), uebergabe=True))
    assert not (repo / "arbeit" / "postausgang").exists()


def _monat_mit_belegen(repo):
    """Ein Monat mit einem PDF-Beleg, einem Kassenbon-Foto und einer fehlenden Zahlung."""
    from PIL import Image

    monat_wert = (kern.jetzt().date() - timedelta(days=40)).strftime("%Y-%m")
    ablage = kern.ablage_ordner()
    ordner = ablage / "Betrieb" / monat_wert[:4] / monat_wert[5:] / "Eingang"
    ordner.mkdir(parents=True)
    (ordner / "rechnung.pdf").write_bytes(b"%PDF-1.4 fake")
    Image.new("RGB", (60, 120), "white").save(ordner / "bon.jpg")
    kern.schreiben(repo / "arbeit/index.json", {
        "a": {"datum": f"{monat_wert}-03", "betrag": 59.5, "lieferant": "Pixelwerk", "art": "eingang",
              "bereich": "betrieb", "status": "abgelegt",
              "pfad": f"Betrieb/{monat_wert[:4]}/{monat_wert[5:]}/Eingang/rechnung.pdf"},
        "b": {"datum": f"{monat_wert}-04", "betrag": 23.8, "lieferant": "Café Morgenrot", "art": "eingang",
              "bereich": "betrieb", "status": "abgelegt",
              "pfad": f"Betrieb/{monat_wert[:4]}/{monat_wert[5:]}/Eingang/bon.jpg"},
    })
    auszug = repo / "auszuege" / "konto.csv"
    tag = f"05.{monat_wert[5:]}.{monat_wert[:4]}"
    auszug.write_text(
        "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag\n"
        f"{tag};Pixelwerk Software GmbH;Abo;-59,50\n"
        f"{tag};Kopierzentrum Schnell & Co. KG;Kopien;-34,00\n",
        encoding="utf-8",
    )
    return monat_wert


def test_auszug_wird_ueber_deutsches_datum_gefunden(repo):
    monat_wert = _monat_mit_belegen(repo)
    assert [d.name for d in monat._auszuege(_args(), monat_wert)] == ["konto.csv"]


def test_betraege_aendern_keine_namen():
    zeile = monat._zeile({"datum": "2026-09-05", "betrag": -34.0, "name": "Schnell & Co. KG", "zweck": ""})
    assert zeile == "- 05.09.2026 · 34,00 € · Schnell & Co. KG"


def test_monatsereignis_ist_ohne_pfade_und_alltagssprachlich(repo):
    monat_wert = _monat_mit_belegen(repo)
    monat.befehl(_args(monat=monat_wert))
    ereignisse = (repo / "arbeit/ereignisse" / f"{kern.jetzt():%Y-%m-%d}.jsonl").read_text()
    assert "Abbuchungen zugeordnet" in ereignisse
    assert "Die Liste kommt am 1. und 15. per Mail." in ereignisse
    assert "fehlt_noch.md" not in ereignisse


def test_uebergabe_echt_an_erlaubte_adresse_einmal(repo, monkeypatch, capsys):
    monat_wert = _monat_mit_belegen(repo)
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8")
        .replace('erlaubt = []', 'erlaubt = ["upload@datev.example"]')
        .replace('adresse = ""\nordner = ""', 'adresse = "upload@datev.example"\nordner = ""')
        .replace("nur_pdf_tif = false", "nur_pdf_tif = true"),
        encoding="utf-8",
    )
    gesendet = []

    def falsch_senden(an, betreff, text, anhaenge, echt, konto=None, fortschritt=None):
        gesendet.append((an, betreff, text, [p.name for p in anhaenge], echt))
        return kern.Ergebnis("ok" if echt else "nichts", "x")

    monkeypatch.setattr("belege.senden.senden", falsch_senden)

    monat.befehl(_args(monat=monat_wert, uebergabe=True))
    assert gesendet[-1][4] is False
    assert "uebergabe" not in (kern.lesen(repo / "arbeit" / "gesehen.json", {}) or {})

    monat.befehl(_args(monat=monat_wert, uebergabe=True, echt=True))
    an, betreff, text, anhaenge, echt = gesendet[-1]
    assert an == "upload@datev.example" and echt
    assert anhaenge == ["bon.pdf", "rechnung.pdf"]
    assert "Kopierzentrum Schnell & Co. KG" in text and "34,00 €" in text

    anzahl = len(gesendet)
    monat.befehl(_args(monat=monat_wert, uebergabe=True, echt=True))
    assert len(gesendet) == anzahl
    assert "schon am" in capsys.readouterr().out


def test_anfragen_sind_immer_entwuerfe(repo, monkeypatch):
    monat_wert = _monat_mit_belegen(repo)
    entwuerfe, gesendet = [], []
    monkeypatch.setattr("belege.senden.entwurf", lambda *a, **k: entwuerfe.append(a) or kern.Ergebnis("ok"))
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a) or kern.Ergebnis("ok"))
    monat.befehl(_args(monat=monat_wert, anfragen=True, echt=True))
    assert len(entwuerfe) == 1 and "34,00" in entwuerfe[0][1]
    assert gesendet == []


def test_monat_praezision_alias_referenz_und_fremdwaehrung(repo):
    """A-C: Name bleibt Pflicht, Alias und Rechnungsnummer machen eindeutig."""
    tag = kern.jetzt().date().isoformat()
    index = {
        "falsch": {"datum": tag, "betrag": 10, "lieferant": "Anderer", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "richtig": {"datum": tag, "betrag": 10, "lieferant": "Pixelwerk", "rechnungsnummer": "RE-4711", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "usd": {"datum": tag, "betrag": 9.2, "originalbetrag": 10, "lieferant": "Dollar Dienst", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
    }
    daten = monat.abgleichen([
        {"datum": tag, "betrag": -10, "name": "Fremde Firma", "zweck": "RE-4711"},
        {"datum": tag, "betrag": -10, "name": "PXW", "zweck": "RE-4711"},
        {"datum": tag, "betrag": -9.2, "originalbetrag": -10, "name": "Dollar Dienst", "zweck": ""},
    ], index)
    assert [x["status"] for x in daten] == ["pruefen", "zugeordnet", "zugeordnet"]


def test_monat_gleicher_betrag_ohne_lieferantenbezug_wird_nicht_zugeordnet(repo):
    tag = kern.jetzt().date().isoformat()
    index = {"fremd": {"datum": tag, "betrag": 10, "lieferant": "Anderer Dienst", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"}}
    daten = monat.abgleichen([{"datum": tag, "betrag": -10, "name": "Pixelwerk", "zweck": "Abo"}], index)
    assert daten[0]["status"] in {"fehlt", "pruefen"}


def test_monat_datums_und_null_referenzen_werden_nicht_eindeutig_zugeordnet(repo):
    tag = kern.jetzt().date().isoformat()
    index = {
        "datum-a": {"datum": tag, "betrag": 10, "lieferant": "Pixelwerk", "rechnungsnummer": "2026-09-01", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "datum-b": {"datum": tag, "betrag": 10, "lieferant": "Pixelwerk", "rechnungsnummer": "2026-09-01", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "null-a": {"datum": tag, "betrag": 20, "lieferant": "Pixelwerk", "rechnungsnummer": "000001", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "null-b": {"datum": tag, "betrag": 20, "lieferant": "Pixelwerk", "rechnungsnummer": "000001", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
    }
    daten = monat.abgleichen([
        {"datum": tag, "betrag": -10, "name": "Pixelwerk", "zweck": "Rechnung 2026-09-01"},
        {"datum": tag, "betrag": -20, "name": "Pixelwerk", "zweck": "Rechnung 000001"},
    ], index)
    assert [x["status"] for x in daten] == ["pruefen", "pruefen"]


def test_monat_fremdwaehrung_ohne_originalbetrag_wird_nicht_zugeordnet(repo):
    tag = kern.jetzt().date().isoformat()
    index = {"usd": {"datum": tag, "betrag": 98, "waehrung": "USD", "lieferant": "Dollar Dienst", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"}}
    daten = monat.abgleichen([{"datum": tag, "betrag": -100, "name": "Dollar Dienst", "zweck": "Abo"}], index)
    assert daten[0]["status"] == "pruefen"


def test_monat_belegpaar_sammelrechnung_dauerbeleg_und_sonderarten(repo):
    """D-G: Paare, Teilzahlungen, Verträge und besondere Nachweise."""
    tag = kern.jetzt().date().isoformat()
    kern.schreiben(repo / "arbeit/dokumente.json", {
        "vertrag": {"art": "vertrag", "gegenueber": "Mietwerk", "titel": "Mietvertrag", "pfad": "Dokumente/Vertrag/Mietwerk.pdf"},
    })
    index = {
        "rechnung": {"datum": tag, "betrag": 20, "lieferant": "Druckwerk", "beschreibung": "Rechnung", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "quittung": {"datum": tag, "betrag": 20, "lieferant": "Druckwerk", "beschreibung": "Receipt", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
        "sammel": {"datum": tag, "betrag": 30, "lieferant": "Abohaus", "art": "eingang", "bereich": "betrieb", "status": "abgelegt"},
    }
    daten = monat.abgleichen([
        {"datum": tag, "betrag": -20, "name": "Druckwerk", "zweck": ""},
        {"datum": tag, "betrag": -10, "name": "Abohaus", "zweck": "Teil 1"},
        {"datum": tag, "betrag": -20, "name": "Abohaus", "zweck": "Teil 2"},
        {"datum": tag, "betrag": -50, "name": "Mietwerk", "zweck": "Miete"},
        {"datum": tag, "betrag": -3, "name": "Bank", "zweck": "Kontoführung"},
    ], index)
    assert [x["status"] for x in daten] == ["zugeordnet", "zugeordnet (Sammelrechnung)", "zugeordnet (Sammelrechnung)", "zugeordnet (Dauerbeleg)", "bank"]


def test_monat_kuendigung_ist_kein_dauerbeleg(repo):
    tag = kern.jetzt().date().isoformat()
    kern.schreiben(repo / "arbeit/dokumente.json", {
        "kuendigung": {"art": "vertrag", "gegenueber": "Mietwerk", "titel": "Kündigung", "pfad": "Dokumente/Kündigung.pdf"},
    })
    daten = monat.abgleichen([{"datum": tag, "betrag": -50, "name": "Mietwerk", "zweck": "Miete"}], {})
    assert daten[0]["status"] != "zugeordnet (Dauerbeleg)"


def test_monat_nachsuche_und_mahnung(repo):
    """H und J: Fund bleibt trocken, eine Mahnung wird gegen alle CSV geprüft."""
    fund = repo / "downloads" / "pixelwerk.pdf"
    fund.write_text("Pixelwerk Rechnung 12,00", encoding="utf-8")
    alt = kern.jetzt().timestamp() - 700
    os.utime(fund, (alt, alt))
    daten = [{"datum": kern.jetzt().date().isoformat(), "betrag": -12, "name": "Pixelwerk", "zweck": "", "status": "fehlt"}]
    monat._nachsuche(daten, _args())
    assert daten[0]["status"] == "gefunden" and fund.exists()
    monat_wert = kern.jetzt().strftime("%Y-%m")
    (repo / "auszuege" / "mahnung.csv").write_text(
        f"Datum;Name;Betrag\n{kern.jetzt():%d.%m.%Y};Pixelwerk;-12,00\n", encoding="utf-8")
    kern.schreiben(repo / "arbeit/dokumente.json", {"m": {"datum": kern.jetzt().date().isoformat(), "gegenueber": "Pixelwerk", "titel": "Mahnung", "text": "Zahlungserinnerung 12,00", "pfad": "Dokumente/Mahnung.pdf"}})
    assert monat._mahnungen()[0]["status"].startswith("bezahlt am")


def test_monat_nachsuche_braucht_einen_eindeutigen_lieferantenfund(repo, monkeypatch):
    alt = kern.jetzt().timestamp() - 700
    falsch = repo / "downloads" / "anderer.pdf"
    falsch.write_text("Anderer Dienst Rechnung 12,00", encoding="utf-8")
    os.utime(falsch, (alt, alt))
    daten = [{"datum": kern.jetzt().date().isoformat(), "betrag": -12, "name": "Pixelwerk", "zweck": "", "status": "fehlt"}]
    monat._nachsuche(daten, _args(echt=True))
    assert daten[0]["status"] == "fehlt"

    for name in ("pixel-1.pdf", "pixel-2.pdf"):
        datei = repo / "downloads" / name
        datei.write_text("Pixelwerk Rechnung 12,00", encoding="utf-8")
        os.utime(datei, (alt, alt))
    verarbeitet = []
    monkeypatch.setattr("belege.verarbeiten.verarbeite", lambda *args: verarbeitet.append(args))
    monat._nachsuche(daten, _args(echt=True))
    assert daten[0]["status"] == "pruefen" and "mehrdeutig" in daten[0]["hinweis"] and not verarbeitet


def test_nachsuche_findet_flate_komprimiertes_pdf(repo):
    """Der Suchtext kommt aus pypdf, nicht aus den komprimierten Rohbytes."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    fund = repo / "downloads" / "rechnung.pdf"
    writer = PdfWriter()
    seite = writer.add_blank_page(width=300, height=300)
    seite[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })})
    })
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 20 20 Td (Pixelwerk Rechnung 12,00) Tj ET " * 8).encode())
    seite[NameObject("/Contents")] = stream.flate_encode()
    with open(fund, "wb") as datei:
        writer.write(datei)
    assert monat._fund_passt(fund, {"betrag": -12, "name": "Pixelwerk"})


def test_kontenregister_warnt_woechentlich_und_entwarnt(repo, monkeypatch):
    (repo / "konfig/konten.toml").write_text(
        '[[konto]]\nkuerzel = "giro"\nname = "Giro"\nquelle = "csv"\nmuster = "giro*.csv"\naktiv_ab = "2026-01"\n', encoding="utf-8")
    zeit = [datetime(2026, 1, 4, tzinfo=kern.zone())]
    monkeypatch.setattr(kern, "jetzt", lambda: zeit[0])
    monat._konten_pruefen("2026-01", _args())
    monat._konten_pruefen("2026-01", _args())
    zeit[0] = datetime(2026, 1, 11, tzinfo=kern.zone())
    monat._konten_pruefen("2026-01", _args())
    ereignisse = (repo / "arbeit/ereignisse/2026-01-11.jsonl").read_text()
    assert ereignisse.count("Für Januar fehlt der Kontoauszug von Giro") == 1
    (repo / "auszuege/giro-2026-01.csv").write_text("Datum;Name;Betrag\n04.01.2026;Test;-1,00\n", encoding="utf-8")
    monat._konten_pruefen("2026-01", _args())
    assert "Kontoauszug Giro für Januar ist da – danke." in (repo / "arbeit/ereignisse/2026-01-11.jsonl").read_text()


def test_ohne_kontenregister_bleibt_auszugswahl_unveraendert(repo):
    (repo / "konfig/konten.toml").unlink()
    assert monat._konten_pruefen("2026-01", _args()) == []


def test_monat_mahnung_ohne_zahlung_ist_offen(repo):
    tag = kern.jetzt().date() - timedelta(days=2)
    (repo / "auszuege" / "konto.csv").write_text(
        f"Datum;Name;Betrag\n{kern.jetzt():%d.%m.%Y};Anderer Dienst;-12,00\n", encoding="utf-8")
    kern.schreiben(repo / "arbeit/dokumente.json", {"m": {"datum": tag.isoformat(), "gegenueber": "Pixelwerk", "titel": "Mahnung", "text": "Zahlungserinnerung 12,00", "pfad": "Dokumente/Mahnung.pdf"}})
    assert monat._mahnungen()[0]["status"] == "offen"


def test_monat_mahnung_ohne_auszug_bis_mahntermin_ist_nicht_pruefbar(repo):
    tag = kern.jetzt().date()
    vor_mahnung = tag - timedelta(days=1)
    (repo / "auszuege" / "konto.csv").write_text(
        f"Datum;Name;Betrag\n{vor_mahnung:%d.%m.%Y};Anderer Dienst;-12,00\n", encoding="utf-8")
    kern.schreiben(repo / "arbeit/dokumente.json", {"m": {"datum": tag.isoformat(), "gegenueber": "Pixelwerk", "titel": "Mahnung", "text": "Zahlungserinnerung 12,00", "pfad": "Dokumente/Mahnung.pdf"}})
    status = monat._mahnungen()[0]["status"]
    assert status.startswith("nicht prüfbar") and status != "offen"


def test_monat_rundfunk_bescheid_ist_dauerbeleg(repo):
    """Rundfunkbeitrag: Bescheid mit derselben Beitragsnummer gilt jeden Monat (Philip, 28.10.2026)."""
    tag = kern.jetzt().date().isoformat()
    kern.schreiben(repo / "arbeit/dokumente.json", {
        "bescheid": {"art": "behoerde", "gegenueber": "ARD ZDF Deutschlandradio Beitragsservice",
                     "titel": "Festsetzungsbescheid", "text": "Beitragsnummer 471 440 743 Betriebsstätte",
                     "pfad": "Dokumente/Behörde/Rundfunk.pdf"},
        "anderer": {"art": "behoerde", "gegenueber": "Beitragsservice", "titel": "Bescheid",
                    "text": "Beitragsnummer 534 548 136", "pfad": "Dokumente/Behörde/Privat.pdf"},
    })
    daten = monat.abgleichen([
        {"datum": tag, "betrag": -18.36, "name": "Rundfunk ARD, ZDF, DRadio",
         "zweck": "Rundfunk 08.2026 - 10.2026 Beitragsnr. 471440743"},
        {"datum": tag, "betrag": -18.36, "name": "Rundfunk ARD, ZDF, DRadio",
         "zweck": "Rundfunk 08.2026 - 10.2026 Beitragsnr. 999999999"},
    ], {})
    assert daten[0]["status"] == "zugeordnet (Dauerbeleg)"
    assert daten[0]["beleg_pfad"] == "Dokumente/Behörde/Rundfunk.pdf"
    assert daten[1]["status"] == "fehlt"


def test_monat_rundfunk_nummernvarianten_und_grenzen(repo):
    tag = kern.jetzt().date().isoformat()
    kern.schreiben(repo / "arbeit/dokumente.json", {
        "bescheid": {"art": "behoerde", "gegenueber": "Beitragsservice", "titel": "Anmeldebestätigung",
                     "text": "Beitragsnummer 471 440 743", "pfad": "Dokumente/Rundfunk.pdf"},
        "lang": {"art": "behoerde", "gegenueber": "Beitragsservice", "titel": "Anderes",
                 "text": "Aktenzeichen 1234567890", "pfad": "Dokumente/Lang.pdf"},
    })
    buchungen = [
        {"datum": tag, "betrag": -18.36, "name": "Beitragsservice", "zweck": "Rundfunk Beitragsnummer 471 440 743"},
        {"datum": tag, "betrag": -18.36, "name": "ARD ZDF Beitragsservice", "zweck": "Rundfunk Beitrags-Nr. 471440743"},
        {"datum": tag, "betrag": -18.36, "name": "Rundfunk", "zweck": "Beitragsnr. 234567890"},
    ]
    daten = monat.abgleichen(buchungen, {})
    assert [x["status"] for x in daten[:2]] == ["zugeordnet (Dauerbeleg)"] * 2
    assert daten[2]["status"] == "fehlt", "Teil einer längeren Zahl zählt nicht"


def test_nachsuche_liest_jede_datei_nur_einmal_je_lauf(repo, monkeypatch):
    """Viele fehlende Buchungen dürfen einen Scan nicht viele Male neu lesen (Meldung Nina, 29.10.2026)."""
    from belege import text

    alt = kern.jetzt().timestamp() - 700
    for name in ("scan-1.pdf", "scan-2.pdf"):
        datei = repo / "downloads" / name
        datei.write_text("Anderer Dienst Rechnung 99,00", encoding="utf-8")
        os.utime(datei, (alt, alt))
    gelesen: list[str] = []
    echt = text.auslesen

    def zaehlen(datei, *a, **k):
        gelesen.append(datei.name)
        return echt(datei, *a, **k)

    monkeypatch.setattr(text, "auslesen", zaehlen)
    heute = kern.jetzt().date().isoformat()
    daten = [{"datum": heute, "betrag": -i, "name": f"Lieferant {i}", "zweck": "", "status": "fehlt"} for i in range(1, 9)]
    monat._nachsuche(daten, _args())
    assert sorted(gelesen) == ["scan-1.pdf", "scan-2.pdf"]
    monat._nachsuche(daten, _args())
    assert len(gelesen) == 4  # ein neuer Lauf liest frisch
