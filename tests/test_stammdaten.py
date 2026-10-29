"""Stammdatenblatt: Zusammenführung, sichere Erkennung und Ampelhinweise."""
from argparse import Namespace
from datetime import date

from belege import kern, pruefen
from belege.einordnen import _firma_aus_text
from belege.pruefung import pruefe as rechnungspruefe
from belege.typen import Einordnung, Text


def _einrichtung(tmp_path, monkeypatch, stamm: str, belege: str = ""):
    (tmp_path / "konfig").mkdir()
    (tmp_path / "konfig" / "belege.toml").write_text(
        '[ablage]\nordner = "ablage"\nbereich_betrieb = "Betrieb"\n' + belege,
        encoding="utf-8")
    (tmp_path / "konfig" / "regeln.toml").write_text("", encoding="utf-8")
    (tmp_path / "konfig" / "stammdaten.toml").write_text(stamm, encoding="utf-8")
    monkeypatch.setattr(kern, "ROOT", tmp_path)


def _firmen() -> str:
    return '''[[firma]]
name = "Alpha GmbH"
namen = ["Alpha Handelsgesellschaft"]
ust_id = "DE 344 935 206"
steuernummer = "32/670/10144"
anschrift = { strasse = "Musterstraße 12", plz = "12345", ort = "Berlin" }
weitere_anschriften = [{ strasse = "Hotelweg 4", plz = "54321", ort = "Bonn" }]
ibans = ["DE01"]

[[firma]]
name = "Beta GmbH"
namen = ["Beta"]
ust_id = "DE222222222"
anschrift = { strasse = "Gemeinsamer Weg 1", plz = "99999", ort = "Köln" }

[[firma]]
name = "Gamma GmbH"
namen = ["Gamma"]
steuernummer = "11/222/33333"
anschrift = { strasse = "Gemeinsamer Weg 1", plz = "99999", ort = "Köln" }
'''


def test_stammdaten_ueberschreiben_nur_betriebsschluessel(tmp_path, monkeypatch):
    _einrichtung(tmp_path, monkeypatch, _firmen(),
                 '[[firma]]\nname = "Alpha GmbH"\nnamen = ["Alpha Alt"]\nbereich = "Alpha"\nkonten = ["DE99"]\n')
    alpha = kern.firma("Alpha GmbH")
    assert alpha["bereich"] == "Alpha"
    assert alpha["konten"] == ["DE99"]
    assert set(alpha["namen"]) == {"Alpha Handelsgesellschaft", "Alpha Alt"}
    assert alpha["ust_id"] == "DE 344 935 206"


def test_ust_id_steuernummer_anschrift_und_widerspruch(tmp_path, monkeypatch):
    _einrichtung(tmp_path, monkeypatch, _firmen())
    assert _firma_aus_text("Rechnung an:\nAnderer Name\nDE344.935/206") == "Alpha GmbH"
    assert _firma_aus_text("Rechnungsempfänger:\nUnbekannt\n32 / 670 . 10144") == "Alpha GmbH"
    assert _firma_aus_text("Rechnung an:\nUnbekannt\nMusterstraße 12\n12345 Berlin") == "Alpha GmbH"
    assert _firma_aus_text("Rechnung an:\nUnbekannt\nGemeinsamer Weg 1\n99999 Köln") is None
    assert _firma_aus_text("Rechnung an:\nBeta GmbH\nDE344935206") is None


def test_lieferanten_ust_im_fuss_zaehlt_nicht(tmp_path, monkeypatch):
    _einrichtung(tmp_path, monkeypatch, _firmen())
    text = "Lieferant GmbH\nRechnung\nPositionen\n\nImpressum\nUSt-IdNr. DE344935206"
    assert _firma_aus_text(text, "eingang") is None


def test_weitere_anschrift_ist_fuer_rechnungspruefung_gueltig(tmp_path, monkeypatch):
    _einrichtung(tmp_path, monkeypatch, _firmen(), '[pruefung]\nan = true\nregeln = ["anschrift"]\nkleinbetrag = 0\n')
    e = Einordnung(True, "eingang", "betrieb", date(2026, 1, 1), "L", "R", 300, "EUR", "hoch", "", "regel", "Alpha GmbH")
    assert rechnungspruefe(e, Text("Rechnung an: Alpha GmbH\nHotelweg 4\n54321 Bonn", "klartext", 1)) == []


def test_pruefen_meldet_fehlendes_und_doppelte_stammdaten(repo, capsys):
    pruefen.befehl(Namespace())
    assert "GELB: Stammdatenblatt fehlt (optional)" in capsys.readouterr().out
    (repo / "konfig" / "stammdaten.toml").write_text(
        '[[firma]]\nname = "A"\nsteuernummer = "32/670/10144"\nanschrift = { strasse = "A 1", plz = "12345", ort = "B" }\n'
        '[[firma]]\nname = "B"\nsteuernummer = "3267010144"\nanschrift = { strasse = "B 1", plz = "12345", ort = "B" }\n', encoding="utf-8")
    assert pruefen.befehl(Namespace()) == 1
    assert "ROT: Stammdatenblatt fehlerhaft: steuernummer doppelt" in capsys.readouterr().out


def test_firmenname_mit_sonderzeichen_ergibt_sicheren_bereich(repo):
    from belege import kern
    (repo / "konfig" / "stammdaten.toml").write_text(
        '[[firma]]\nname = "Muster & Co. GmbH"\nust_id = "DE111111111"\n'
        'anschrift = { strasse = "Musterweg 1", plz = "12345", ort = "Berlin" }\n'
        '[[firma]]\nname = "Beispiel UG (haftungsbeschränkt)"\nsteuernummer = "12/345/67890"\n'
        'anschrift = { strasse = "Musterweg 1", plz = "12345", ort = "Berlin" }\n', encoding="utf-8")
    bereiche = {f["name"]: f["bereich"] for f in kern.firmen()}
    assert bereiche["Muster & Co. GmbH"] == "Muster-Co.-GmbH"
    assert bereiche["Beispiel UG (haftungsbeschränkt)"] == "Beispiel-UG-haftungsbeschränkt"
