"""Fremdwährung bei Belegen und Kontoauszügen (Meldung Nina, 15.11.2026)."""
from datetime import date

from belege import einordnen, monat, kurse


def test_modellantwort_usd_ist_gueltig():
    antwort = {"ist_beleg": True, "art": "eingang", "bereich": "betrieb", "datum": "2026-10-02", "lieferant": "A", "beschreibung": "Rechnung", "betrag": 23.80, "waehrung": "USD", "sicherheit": "hoch", "grund": "x"}
    assert einordnen.pruefe(antwort) is None
    for wert in ("usd", "Dollar", ""):
        antwort["waehrung"] = wert
        assert einordnen.pruefe(antwort)


def test_rueckfall_erkennt_usd():
    assert einordnen._waehrung_aus_text("Total $23.80 USD") == "USD"
    assert einordnen._waehrung_aus_text("Gesamt 23,80 €") == "EUR"


def test_bankformat_rechnet_fremdwaehrung(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.1215)
    datei = repo / "auszuege" / "a.csv"
    datei.write_text("Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag;Waehrung\n02.10.2026;Skool;;-10,71;USD\n02.10.2026;Euro;;-2,00;EUR\n")
    usd, eur = monat.buchungen(datei, "2026-10")
    assert usd["originalbetrag"] == -10.71 and usd["waehrung"] == "USD"
    assert usd["betrag"] == round(-10.71 / 1.1215, 2) and usd["umgerechnet"] is True
    assert "waehrung" not in eur


def test_bankformat_ohne_kurs(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: None)
    datei = repo / "auszuege" / "a.csv"
    datei.write_text("Datum;Name;Betrag;Waehrung\n02.10.2026;Skool;-10,71;USD\n")
    buchung = monat.buchungen(datei, "2026-10")[0]
    assert buchung["betrag"] == -10.71 and buchung["kurs_fehlt"] is True


def test_paypal_umrechnung(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.1)
    datei = repo / "auszuege" / "paypal.csv"
    datei.write_text("Datum;Name;Betrag;Waehrung\n02.10.2026;Acme Inc;-1145,00;USD\n02.10.2026;Currency Conversion;1145,00;USD\n02.10.2026;Currency Conversion;-1054,55;EUR\n02.10.2026;Andere;-2,00;EUR\n")
    daten = monat.buchungen(datei, "2026-10")
    assert len(daten) == 2
    acme = next(x for x in daten if x["name"] == "Acme Inc")
    assert acme["betrag"] == -1054.55 and acme["originalbetrag"] == -1145.0 and "umgerechnet" not in acme


def test_paypal_umrechnung_steht_im_buchungstext(repo, monkeypatch):
    """MoneyMoney-Bankformat: „Currency Conversion“ steht dort im Buchungstext, nicht im Namen."""
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.1)
    kopf = "Buchungstag;Valutadatum;Buchungstext;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag;Waehrung"
    datei = repo / "auszuege" / "paypal.csv"
    datei.write_text(kopf + "\n02.10.2026;02.10.2026;Payment;Rechnung 7;Acme Inc;-1145,00;USD\n"
                     "02.10.2026;02.10.2026;Currency Conversion;;PayPal;1145,00;USD\n"
                     "02.10.2026;02.10.2026;Currency Conversion;;PayPal;-1054,55;EUR\n", encoding="utf-8")
    daten = monat.buchungen(datei, "2026-10")
    assert [(x["name"], x["betrag"]) for x in daten] == [("Acme Inc", -1054.55)]
    assert "_zeile" not in daten[0]


def test_einzelne_umrechnungszeile_bleibt_stehen(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.1)
    datei = repo / "auszuege" / "paypal.csv"
    datei.write_text("Datum;Name;Betrag;Waehrung\n02.10.2026;Acme Inc;-1145,00;USD\n"
                     "02.10.2026;Currency Conversion;-1054,55;EUR\n", encoding="utf-8")
    daten = monat.buchungen(datei, "2026-10")
    assert len(daten) == 2 and daten[0]["umgerechnet"] is True


def test_umgerechnete_buchung_ist_dublette_der_echten_eurobuchung(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.1215)
    sumup = repo / "auszuege" / "sumup.csv"
    sumup.write_text("Datum;Name;Betrag\n02.10.2026;Skool;-9,55\n", encoding="utf-8")
    mm = repo / "auszuege" / "mm.csv"
    mm.write_text("Datum;Name;Betrag;Waehrung\n02.10.2026;Skool;-10,71;USD\n", encoding="utf-8")
    for reihenfolge in ([sumup, mm], [mm, sumup]):
        daten = monat.buchungen_aus(reihenfolge, "2026-10")
        assert [x["betrag"] for x in daten] == [-9.55]


def _beleg(betrag, waehrung, lieferant="Anthropic", datum="2026-10-01"):
    return {"status": "abgelegt", "bereich": "betrieb", "art": "eingang", "betrag": betrag, "waehrung": waehrung,
            "lieferant": lieferant, "datum": datum, "beschreibung": "Rechnung", "pfad": "x.pdf"}


def _buchung(betrag, name="Anthropic", **mehr):
    return {"datum": "2026-10-02", "betrag": betrag, "name": name, "zweck": "", "originalbetrag": None, **mehr}


def test_usd_beleg_findet_die_eurobuchung_ueber_den_ezb_kurs(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.0868)
    index = {"a": _beleg(23.80, "USD")}
    ergebnis = monat.abgleichen([_buchung(-21.90)], index)[0]
    assert ergebnis["status"] == "zugeordnet" and ergebnis["beleg"] == "a" and "EZB" in ergebnis["hinweis"]
    # Betrag zu weit weg: kein Treffer, auch kein „prüfen“.
    assert monat.abgleichen([_buchung(-30.00)], index)[0]["status"] == "fehlt"
    # Zwei gleiche Belege: nur ein Hinweis.
    index["b"] = _beleg(23.80, "USD", datum="2026-10-02")
    assert monat.abgleichen([_buchung(-21.90)], index)[0]["status"] == "pruefen"


def test_ohne_kurs_wird_nie_zugeordnet(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: None)
    assert monat.abgleichen([_buchung(-21.90)], {"a": _beleg(23.80, "USD")})[0]["status"] == "pruefen"


def test_fremdwaehrungsabgleich_nimmt_nur_abgelegte_betriebsbelege(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.0868)
    privat = {**_beleg(23.80, "USD"), "bereich": "privat"}
    unsortiert = {**_beleg(23.80, "USD"), "status": "unsortiert"}
    assert monat.abgleichen([_buchung(-21.90)], {"a": privat, "b": unsortiert})[0]["status"] == "fehlt"


def test_usd_beleg_passt_ueber_den_originalbetrag(repo, monkeypatch):
    monkeypatch.setattr(kurse, "kurs", lambda *_: 1.1)
    buchung = _buchung(-1054.55, "Acme Inc", originalbetrag=-1145.0, waehrung="USD")
    index = {"a": _beleg(1145.00, "USD", "Acme Inc"), "chf": _beleg(1145.00, "CHF", "Acme Inc")}
    ergebnis = monat.abgleichen([buchung], index)[0]
    assert ergebnis["status"] == "zugeordnet" and ergebnis["beleg"] == "a"


def test_bericht_zeigt_die_belegwaehrung():
    from belege import bericht

    assert "23,80 USD" in bericht._zeile_beleg({"daten": {"lieferant": "Anthropic", "betrag": 23.8, "waehrung": "USD"}})
    assert "23,80 €" in bericht._zeile_beleg({"daten": {"lieferant": "Wolkenwerk", "betrag": 23.8, "waehrung": None}})


def test_zeile_nennt_die_umrechnung():
    zeile = monat._zeile({"datum": "2026-10-02", "betrag": -9.55, "name": "Skool", "zweck": "",
                          "umgerechnet": True, "originalbetrag": -10.71, "waehrung": "USD"})
    assert "umgerechnet aus 10,71 USD" in zeile
    ohne = monat._zeile({"datum": "2026-10-02", "betrag": -10.71, "name": "Skool", "zweck": "",
                         "kurs_fehlt": True, "originalbetrag": -10.71, "waehrung": "USD"})
    assert "10,71 USD (nicht umgerechnet)" in ohne


EZB = (b'<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
       b'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube>'
       b'<Cube time="2026-10-02"><Cube currency="USD" rate="1.12"/><Cube currency="CHF" rate="0.93"/></Cube>'
       b'<Cube time="2026-10-01"><Cube currency="USD" rate="1.11"/></Cube></Cube></gesmes:Envelope>')


def test_ezb_liste_cache_wochenende_und_ein_abruf_am_tag(repo, monkeypatch):
    abrufe = []

    def laden(url):
        abrufe.append(url)
        return kurse._lesen(EZB)

    monkeypatch.setattr(kurse, "_laden", laden)
    assert kurse.kurs("USD", date(2026, 10, 2)) == 1.12
    assert kurse.kurs("usd", date(2026, 10, 4)) == 1.12  # Sonntag: Kurs vom Freitag
    assert kurse.in_euro(-10.71, "USD", date(2026, 10, 1)) == round(-10.71 / 1.11, 2)
    assert len(abrufe) == 1
    # Unbekannte Währung: ein einziger weiterer Versuch je Liste und Tag, nicht je Buchung.
    for _ in range(5):
        assert kurse.kurs("XXX", date(2026, 10, 2)) is None
    assert len(abrufe) == 1


def test_ezb_nicht_erreichbar_gibt_keinen_kurs_und_keinen_fehler(repo, monkeypatch):
    abrufe = []

    def laden(url):
        abrufe.append(url)
        raise OSError("kein Netz")

    monkeypatch.setattr(kurse, "_laden", laden)
    for _ in range(4):
        assert kurse.kurs("USD", date(2026, 10, 2)) is None
    assert len(abrufe) == 1
