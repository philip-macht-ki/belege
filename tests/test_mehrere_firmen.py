"""Regressionsfälle für die getrennte Firmenablage ohne Modellaufruf."""
from datetime import date

from belege import kern
from belege.ablegen import ziel
from belege.einordnen import _aus_xml, _firma_aus_text, _rueckfall, pruefe
from belege.typen import Fund, Text
from belege.typen import Einordnung
from belege import bericht, monat


def _mehrere(tmp_path, monkeypatch):
    (tmp_path / "konfig").mkdir()
    (tmp_path / "konfig" / "belege.toml").write_text(
        '[ablage]\nordner = "ablage"\nprivat = true\nbereich_betrieb = "Betrieb"\n'
        '[[firma]]\nname = "Alpha GmbH"\nnamen = ["Alpha", "Alpha Gesellschaft"]\nust_id = "DE111111111"\nbereich = "Alpha"\n'
        '[[firma]]\nname = "Beta GmbH"\nnamen = ["Beta"]\nust_id = "DE222222222"\nbereich = "Beta"\n', encoding="utf-8")
    (tmp_path / "konfig" / "regeln.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)


def test_firma_eindeutig_schreibweise_und_ust_id(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    assert _firma_aus_text("Rechnung\nEmpfänger: Alpha Gesellschaft\nBerlin") == "Alpha GmbH"
    assert _firma_aus_text("Rechnung\nUSt-IdNr DE222222222") == "Beta GmbH"


def test_firma_unklar_und_bereichspfad(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    assert _firma_aus_text("Rechnung\nEmpfänger: Alpha und Beta") is None
    e = Einordnung(True, "eingang", "betrieb", date(2026, 10, 1), "Lieferant", "Rechnung", 1,
                   "EUR", "hoch", "Test", "rueckfall", "Beta GmbH")
    assert str(ziel(e, ".pdf")).endswith("ablage/Beta/2026/10/Eingang/2026-10-01_Lieferant_Rechnung.pdf")


def test_alte_einzelfirma_bleibt_betrieb(tmp_path, monkeypatch):
    (tmp_path / "konfig").mkdir()
    (tmp_path / "konfig" / "belege.toml").write_text(
        '[ablage]\nordner = "ablage"\nbereich_betrieb = "Betrieb"\n[betrieb]\nname = "Müller & Söhne GmbH / Nord"\nnamen = ["Alt"]\n', encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)
    e = Einordnung(True, "eingang", "betrieb", date(2026, 10, 1), "Lieferant", "Rechnung", 1,
                   "EUR", "hoch", "Test", "rueckfall", "Müller & Söhne GmbH / Nord")
    assert kern.firmen()[0]["bereich"] == "Betrieb"
    assert "/Betrieb/2026/10/" in str(ziel(e, ".pdf"))


def test_bericht_gruppiert_nach_firma():
    text, _ = bericht.text_und_betreff([
        {"art": "abgelegt", "text": "", "daten": {"firma": "Alpha GmbH", "lieferant": "A"}},
        {"art": "abgelegt", "text": "", "daten": {"firma": "Beta GmbH", "lieferant": "B"}},
        {"art": "unsortiert", "text": "beleg.pdf", "daten": {"grund": "Firma unklar"}},
    ])
    assert "Alpha GmbH (1)" in text and "Beta GmbH (1)" in text and "Firma unklar" in text


def test_monat_filtert_firma(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    tag = "2026-10-01"
    index = {"a": {"datum": tag, "betrag": 10, "lieferant": "Alpha", "art": "eingang", "bereich": "betrieb", "firma": "Alpha GmbH", "status": "abgelegt"},
             "b": {"datum": tag, "betrag": 10, "lieferant": "Beta", "art": "eingang", "bereich": "betrieb", "firma": "Beta GmbH", "status": "abgelegt"}}
    daten = monat.abgleichen([{"datum": tag, "betrag": -10, "name": "Alpha", "zweck": ""}], index, "Alpha GmbH")
    assert daten[0]["status"] == "zugeordnet"


def test_sammelrechnung_filtert_firma(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    tag = "2026-10-01"
    index = {"beta": {"datum": tag, "betrag": 10, "lieferant": "Sammel", "art": "eingang", "bereich": "betrieb", "firma": "Beta GmbH", "status": "abgelegt"}}
    daten = monat.abgleichen([
        {"datum": tag, "betrag": -5, "name": "Sammel", "zweck": ""},
        {"datum": tag, "betrag": -5, "name": "Sammel", "zweck": ""},
    ], index, "Alpha GmbH")
    assert [x["status"] for x in daten] == ["fehlt", "fehlt"]


def test_monat_trennt_konten_je_firma(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    cfg = tmp_path / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('bereich = "Alpha"', 'bereich = "Alpha"\nkonten = ["DE01"]')
                   .replace('bereich = "Beta"', 'bereich = "Beta"\nkonten = ["DE02"]'), encoding="utf-8")
    (tmp_path / "auszug.csv").write_text(
        "Buchungstag;Name;Betrag;Konto\n01.10.2026;Alpha Lieferant;-10,00;DE01\n01.10.2026;Beta Lieferant;-20,00;DE02\n",
        encoding="utf-8")
    kern.schreiben(tmp_path / "arbeit" / "index.json", {
        "alpha": {"datum": "2026-10-01", "betrag": 10, "lieferant": "Alpha Lieferant", "art": "eingang", "bereich": "betrieb", "firma": "Alpha GmbH", "status": "abgelegt"},
        "beta": {"datum": "2026-10-01", "betrag": 20, "lieferant": "Beta Lieferant", "art": "eingang", "bereich": "betrieb", "firma": "Beta GmbH", "status": "abgelegt"},
    })
    args = type("Args", (), {"monat": "2026-10", "auszug": str(tmp_path / "auszug.csv"), "uebergabe": False, "anfragen": False, "echt": False})()
    assert monat.befehl(args) == 0
    assert [x["name"] for x in kern.lesen(tmp_path / "arbeit/monat/2026-10/Alpha/abgleich.json")] == ["Alpha Lieferant"]
    assert [x["name"] for x in kern.lesen(tmp_path / "arbeit/monat/2026-10/Beta/abgleich.json")] == ["Beta Lieferant"]


def test_monat_ohne_konten_nutzt_hauptfirma_und_hinweis(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    (tmp_path / "auszug.csv").write_text("Buchungstag;Name;Betrag\n01.10.2026;Lieferant;-10,00\n", encoding="utf-8")
    args = type("Args", (), {"monat": "2026-10", "auszug": str(tmp_path / "auszug.csv"), "uebergabe": False, "anfragen": False, "echt": False})()
    assert monat.befehl(args) == 0
    assert len(kern.lesen(tmp_path / "arbeit/monat/2026-10/Alpha/abgleich.json")) == 1
    assert kern.lesen(tmp_path / "arbeit/monat/2026-10/Beta/abgleich.json") == []
    assert "Kontoauszug keiner Firma zugeordnet" in (tmp_path / "arbeit/monat/2026-10/Beta/fehlt_noch.md").read_text(encoding="utf-8")


def test_alter_indexeintrag_gehoert_zur_hauptfirma(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    tag = "2026-10-01"
    index = {"alt": {"datum": tag, "betrag": 10, "lieferant": "Alpha", "art": "eingang",
                      "bereich": "betrieb", "status": "abgelegt"}}
    daten = monat.abgleichen([{"datum": tag, "betrag": -10, "name": "Alpha", "zweck": ""}], index, "Alpha GmbH")
    assert daten[0]["status"] == "zugeordnet"


def test_alter_uebergabeschluessel_schuetzt_nur_hauptfirma(tmp_path, monkeypatch, capsys):
    _mehrere(tmp_path, monkeypatch)
    (tmp_path / "konfig" / "belege.toml").write_text(
        (tmp_path / "konfig" / "belege.toml").read_text() + '\n[uebergabe]\nadresse = "steuer@example.test"\n', encoding="utf-8")
    kern.schreiben(tmp_path / "arbeit" / "gesehen.json", {"uebergabe": {"2026-10": "2026-11-01T00:00:00"}})
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a) or kern.Ergebnis("ok", "ok"))
    args = type("Args", (), {"echt": True, "ziel": []})()
    index = {}
    monat._uebergabe("2026-10", tmp_path / "alpha", index, [], args, kern.firmen()[0])
    monat._uebergabe("2026-10", tmp_path / "beta", index, [], args, kern.firmen()[1])
    assert len(gesendet) == 1 and "Beta GmbH" in gesendet[0][1]
    assert "schon am" in capsys.readouterr().out


def test_mehrere_treffer_entscheiden_empfaengerblock(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    text = "Alpha GmbH\nLieferant\nRechnung an:\nBeta GmbH\nDE222222222"
    assert _firma_aus_text(text) == "Beta GmbH"


def test_unklare_firma_wird_nicht_vom_postfach_ueberschrieben(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    p = tmp_path / "konfig" / "belege.toml"
    p.write_text(p.read_text() + '\n[[konto]]\nname = "postfach"\nfirma = "Alpha GmbH"\n', encoding="utf-8")
    fund = Fund(tmp_path / "rechnung.pdf", "postfach", "rechnung.pdf", date(2026, 10, 1), {"konto": "postfach"})
    rueckfall = _rueckfall(fund, Text("Rechnung an: Alpha GmbH und Beta GmbH", "klartext", 1), None, None)
    assert rueckfall["firma"] == "unklar"


def test_modellfirma_ausserhalb_der_liste_ist_unklar(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    assert pruefe({"ist_beleg": True, "art": "eingang", "bereich": "betrieb", "datum": None,
                   "lieferant": "A", "beschreibung": "Rechnung", "betrag": None, "waehrung": "EUR",
                   "sicherheit": "hoch", "grund": "x", "firma": "IGNORIERE ALLES"},
                  {"Alpha GmbH", "Beta GmbH"})


def test_xml_zwischen_eigenen_firmen_bleibt_unsortiert(tmp_path, monkeypatch):
    _mehrere(tmp_path, monkeypatch)
    xml = tmp_path / "rechnung.xml"
    xml.write_text(
        "<Invoice><ID>R-1</ID><IssueDate>2026-10-01</IssueDate>"
        "<AccountingSupplierParty><Party><PartyName><Name>Alpha GmbH</Name></PartyName></Party></AccountingSupplierParty>"
        "<AccountingCustomerParty><Party><PartyName><Name>Beta GmbH</Name></PartyName></Party></AccountingCustomerParty>"
        '<LegalMonetaryTotal><PayableAmount currencyID="EUR">1.00</PayableAmount></LegalMonetaryTotal>'
        "<InvoiceLine><Item><Name>Leistung</Name></Item></InvoiceLine></Invoice>", encoding="utf-8")
    e = _aus_xml(Fund(xml, "postfach", xml.name, date(2026, 10, 1)))
    assert e and e.firma == "unklar" and e.grund == "Rechnung zwischen eigenen Firmen"


def test_bereichskollision_und_pfadtraversal_sind_konfigurationsfehler(tmp_path, monkeypatch, capsys):
    _mehrere(tmp_path, monkeypatch)
    p = tmp_path / "konfig" / "belege.toml"
    p.write_text(p.read_text().replace('bereich = "Beta"', 'bereich = "Alpha"'), encoding="utf-8")
    from belege import pruefen
    assert pruefen.befehl(type("Args", (), {})()) == 1
    assert "ROT: Konfiguration fehlerhaft" in capsys.readouterr().out
    p.write_text(p.read_text().replace('bereich = "Alpha"', 'bereich = "../Alpha"', 1), encoding="utf-8")
    try:
        kern.firmen()
    except RuntimeError as fehler:
        assert "Ungültiger Firmenbereich" in str(fehler)
    else:
        raise AssertionError("Pfadtraversal wurde akzeptiert")


def test_hauptfirma_mit_eigenen_konten_behaelt_buchungen_ohne_kennung():
    from belege.monat import _buchungen_fuer_firma

    firmen = [{"name": "Haupt", "konten": ["DE01"]}, {"name": "Zweit", "konten": ["DE02"]}]
    buchungen = [{"konto": "DE01"}, {"konto": "DE02"}, {"konto": ""}, {}, {"konto": "DE99"}]
    assert _buchungen_fuer_firma(buchungen, firmen[0], firmen) == [{"konto": "DE01"}, {"konto": ""}, {}, {"konto": "DE99"}]
    assert _buchungen_fuer_firma(buchungen, firmen[1], firmen) == [{"konto": "DE02"}]
