"""Zusätze zur Rechnungsprüfung: Anschrift, VIES und Buchhaltungshinweise."""
from datetime import date

from belege import kern
from belege.monat import _hinweise_text
from belege.pruefung import _vies_pruefen, hinweise, pruefe
from belege.typen import Einordnung, Text


def _einordnung(betrag=300):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Lieferant", "Leistung", betrag,
                       "EUR", "hoch", "", "regel", "Eigene GmbH")


def _konfig(repo, extra=""):
    (repo / "konfig" / "belege.toml").write_text(
        '[ablage]\nordner = "ablage"\nbereich_betrieb = "Betrieb"\n'
        '[[firma]]\nname = "Eigene GmbH"\nnamen = ["Eigene GmbH"]\nust_id = "DE111111111"\nbereich = "Eigene"\n'
        'anschrift = { strasse = "Musterstraße 12", plz = "12345", ort = "Berlin" }\n'
        '[pruefung]\nan = true\nregeln = ["anschrift"]\nkleinbetrag = 250\n' + extra,
        encoding="utf-8")


def test_anschrift_normalisiert_und_ignoriert_lieferantenfusszeile(repo):
    _konfig(repo)
    passend = Text("Lieferant\nRechnung an: Eigene GmbH\nMuster Str. Nr. 12\n12345 BERLIN", "klartext", 1)
    assert pruefe(_einordnung(), passend) == []
    # Eine Lieferantenadresse außerhalb des Empfängerblocks darf nicht als eigene zählen.
    fusszeile = Text("Rechnung an: Eigene GmbH\nRechnungsnummer RE-1\n\nLieferant GmbH\nMusterstraße 12\n12345 Berlin", "klartext", 1)
    assert pruefe(_einordnung(), fusszeile) == ["Anschrift fehlt"]


def test_anschrift_abweichend_und_kleinbetrag(repo):
    _konfig(repo)
    alt = Text("Rechnung an: Eigene GmbH\nAlte Straße 3\n54321 Bonn", "klartext", 1)
    assert any("Anschrift abweichend" in x for x in pruefe(_einordnung(), alt))
    assert pruefe(_einordnung(20), alt) == []


def test_anschrift_abweichend_bei_alter_eigener_adresse(repo):
    _konfig(repo)
    alt = Text("Eigene GmbH\nAlte Straße 3\n54321 Bonn", "klartext", 1)
    assert any("Anschrift abweichend" in x for x in pruefe(_einordnung(), alt))


def test_anschrift_fensterkuvert_und_obere_zeilen(repo):
    _konfig(repo)
    oben = Text("Muster Str. 12 a\n12345 Berlin\nEigene GmbH\nc/o Buchhaltung", "klartext", 1)
    assert pruefe(_einordnung(), oben) == []
    ausserhalb = Text("Musterstraße 12\n12345 Berlin\n\nEigene GmbH\nRechnung", "klartext", 1)
    assert pruefe(_einordnung(), ausserhalb) == ["Anschrift fehlt"]
    nur_plz = Text("12345 Berlin\n\nEigene GmbH\nRechnung", "klartext", 1)
    assert pruefe(_einordnung(), nur_plz) == ["Anschrift fehlt"]
    fehlt = Text("Eigene GmbH\nRechnung\nLeistung", "klartext", 1)
    assert pruefe(_einordnung(), fehlt) == ["Anschrift fehlt"]


def test_empfaengerblock_nur_im_sicheren_rechnungskopf(repo):
    _konfig(repo)
    nach_positionen = Text("Pos. Beschreibung\nEigene GmbH\nAlte Straße 3\n54321 Bonn", "klartext", 1)
    assert pruefe(_einordnung(), nach_positionen) == []
    fusszeile = Text("Lieferant GmbH\nHRB 12345\nEigene GmbH\nAlte Straße 3\n54321 Bonn", "klartext", 1)
    assert pruefe(_einordnung(), fusszeile) == []
    nach_30_zeilen = Text("\n".join(["Kopf"] * 30 + ["Eigene GmbH", "Alte Straße 3", "54321 Bonn"]), "klartext", 1)
    assert pruefe(_einordnung(), nach_30_zeilen) == []


def test_vies_ungueltig_cache_und_netzfehler(repo, monkeypatch):
    _konfig(repo, "ust_id_amtlich = true\n")
    text = Text("Lieferant\nUSt-IdNr. FR12345678901", "klartext", 1)

    class Antwort:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self): return b'{"isValid": false, "userError": "INVALID"}'

    monkeypatch.setattr("belege.pruefung.urlopen", lambda url, timeout: Antwort())
    assert "ungültig (FR12345678901)" in pruefe(_einordnung(), text)[0]
    monkeypatch.setattr("belege.pruefung.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert "ungültig" in pruefe(_einordnung(), text)[0]  # Cache, kein zweiter Netzaufruf.
    kern.schreiben(repo / "arbeit" / "ust_id_cache.json", {})
    assert pruefe(_einordnung(), text) == []


def test_vies_nur_bei_aktivierter_pruefung_und_amtlicher_abfrage(repo, monkeypatch):
    text = Text("Lieferant\nUSt-IdNr. FR12345678901", "klartext", 1)
    aufrufe = []
    monkeypatch.setattr("belege.pruefung._vies_pruefen", lambda nummer: aufrufe.append(nummer))
    _konfig(repo, "ust_id_amtlich = true\n")
    pruefe(_einordnung(), text)
    assert aufrufe == ["FR12345678901"]
    konfig = repo / "konfig" / "belege.toml"
    konfig.write_text(konfig.read_text(encoding="utf-8").replace("an = true", "an = false"), encoding="utf-8")
    pruefe(_einordnung(), text)
    _konfig(repo)
    pruefe(_einordnung(), text)
    assert aufrufe == ["FR12345678901"]


def test_vies_log_maskiert_ust_id_und_antwortdetails(repo, monkeypatch):
    _konfig(repo)
    logs = []
    monkeypatch.setattr("belege.pruefung.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError("internes Detail")))
    monkeypatch.setattr("belege.pruefung.kern.log", logs.append)
    assert _vies_pruefen("FR12345678901") is None
    assert logs == ["EU-USt-IdNr.-Abfrage für FR***901 nicht verfügbar"]


def test_ust_id_aus_konfig_wird_wie_aus_text_normalisiert(repo):
    _konfig(repo)
    konfig = repo / "konfig" / "belege.toml"
    konfig.write_text(konfig.read_text(encoding="utf-8").replace("DE111111111", "de 111.111-111"), encoding="utf-8")
    assert hinweise(_einordnung(), Text("VAT number: DE111.111-111", "klartext", 1)) == []


def test_hinweise_reverse_charge_und_pdf_erechnung_und_kleinbetrag(repo):
    _konfig(repo)
    reverse = Text("USt-IdNr. ATU12345678\nReverse Charge", "klartext", 1)
    assert hinweise(_einordnung(), reverse) == ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]
    deutsch = Text("USt-IdNr. DE123456789", "klartext", 1)
    assert "keine E-Rechnung" in hinweise(_einordnung(), deutsch)[0]
    assert hinweise(_einordnung(), deutsch, xml={"verkaeufer_ust": "DE123456789"}) == []
    assert hinweise(_einordnung(20), deutsch) == []


def test_hinweise_ust_id_nur_eu_gekennzeichnet_und_nicht_beim_empfaenger(repo):
    _konfig(repo)
    assert hinweise(_einordnung(), Text("Rechnungsnummer RE20261029", "klartext", 1)) == []
    assert hinweise(_einordnung(), Text("VAT number: IE6388047V", "klartext", 1)) == []
    assert hinweise(_einordnung(), Text("BTW: NL123456789B01\nVAT 0%", "klartext", 1)) == [
        "Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]
    assert hinweise(_einordnung(), Text("VAT number: CHE123456789", "klartext", 1)) == []
    assert hinweise(_einordnung(), Text("Rechnung an: Eigene GmbH, VAT number: NL123456789B01", "klartext", 1)) == []
    konfig = repo / "konfig" / "belege.toml"
    konfig.write_text(konfig.read_text(encoding="utf-8").replace("DE111111111", "IE6388047V"), encoding="utf-8")
    assert hinweise(_einordnung(), Text("VAT number: IE6388047V", "klartext", 1)) == []


def test_hinweise_erechnung_ignoriert_eigene_ust_und_steuernummer_im_empfaengerblock(repo):
    _konfig(repo)
    empfaenger = Text("Rechnung an: Eigene GmbH\nUSt-IdNr. DE111111111\nSteuernummer: 123/456/789\n", "klartext", 1)
    assert hinweise(_einordnung(), empfaenger) == []


def test_empfaenger_ust_ohne_konfigurierte_nummer_ist_nie_lieferanten_ust(repo, monkeypatch):
    _konfig(repo, "ust_id_amtlich = true\n")
    konfig = repo / "konfig" / "belege.toml"
    konfig.write_text(konfig.read_text(encoding="utf-8").replace('ust_id = "DE111111111"', ""), encoding="utf-8")
    vies = []
    monkeypatch.setattr("belege.pruefung._vies_pruefen", lambda nummer: vies.append(nummer) or False)
    im_block = Text("Rechnung an: Eigene GmbH\nUSt-IdNr. NL123456789B01\nVAT 0%", "klartext", 1)
    assert hinweise(_einordnung(), im_block) == []
    assert not any("ungültig" in punkt for punkt in pruefe(_einordnung(), im_block))
    assert vies == []
    for kennwort in ["Ihre USt-IdNr.", "Kunden-USt-Id", "USt-Id des Leistungsempfängers", "Your VAT", "Customer VAT"]:
        text = Text(f"{kennwort}: NL123456789B01\nVAT 0%", "klartext", 1)
        assert hinweise(_einordnung(), text) == []
        assert not any("ungültig" in punkt for punkt in pruefe(_einordnung(), text))
    assert vies == []


def test_hinweise_stehen_in_der_monatlichen_uebergabe(repo):
    text = _hinweise_text("2026-10", {
        "abc": {"datum": "2026-10-29", "pfad": "Betrieb/2026/10/Eingang/rechnung.pdf",
                "hinweise": ["Reverse Charge: Umsatzsteuer selbst anmelden (§ 13b UStG)"]}
    })
    assert "Hinweise für die Buchhaltung" in text
    assert "rechnung.pdf: Reverse Charge" in text


def test_lieferanten_ustid_im_kopf_beendet_empfaengersuche_nicht():
    from belege import pruefung
    text = "Lieferant AG\nTel. 0221 12345\nUSt-IdNr. DE123456789\n\nMuster GmbH\nHauptstraße 1\n12345 Musterstadt\n\nPos. Beschreibung Netto"
    assert "Muster GmbH" in "\n".join(pruefung._kopfzeilen(text))
    assert pruefung._empfaenger(text, {"name": "Muster GmbH"}, None) is None
