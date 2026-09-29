"""Tests für den konservativen Monatsabgleich."""
from __future__ import annotations

import argparse
import csv
from datetime import timedelta

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
    assert monat._auszug(_args(), monat_wert).name == "konto.csv"


def test_betraege_aendern_keine_namen():
    zeile = monat._zeile({"datum": "2026-09-05", "betrag": -34.0, "name": "Schnell & Co. KG", "zweck": ""})
    assert zeile == "- 05.09.2026 · 34,00 € · Schnell & Co. KG"


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
