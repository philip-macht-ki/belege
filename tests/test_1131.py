from datetime import date

from belege.aufraeumen import aktualisieren, liste
from belege.pruefung import hinweise, pruefe
from belege.typen import Einordnung, Text


def _e(betrag=300):
    return Einordnung(True, "eingang", "betrieb", date(2026, 10, 29), "Muster GmbH", "Abo", betrag, "EUR", "hoch", "", "regel", "Studio Beispiel")


def _rechnung(extra="", steuer="MwSt 19 %"):
    return Text("Muster GmbH\nRechnung an: Studio Beispiel\nUSt-IdNr. DE123456789\nRechnung RE-100\n29.10.2026\nLeistung: Beratung\n" + steuer + "\n" + extra, "klartext", 1)


def test_mahnung_und_kuerzel_liste_bleiben_still_und_fliestext_nicht(repo):
    assert pruefe(_e(), Text("Muster GmbH\nMAHNUNG\nRechnung RE-1", "klartext", 1)) == []
    assert "Steuersatz" in " ".join(pruefe(_e(), _rechnung("Erinnerung: zahlbar bis morgen", "")))
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("[pruefung]\n", "[pruefung]\nnie_beleg = [\"report@example.test\", \"Wochenreport\"]\n"), encoding="utf-8")
    assert pruefe(_e(), Text("Wochenreport\nRechnung RE-1", "klartext", 1), absender="x@example.test") == []
    assert pruefe(_e(), _rechnung(), absender="report@example.test") == []


def test_eu_ohne_hinweis_nur_mit_eigener_ustid(repo):
    cfg = repo / "konfig" / "belege.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('ust_id = ""', 'ust_id = "DE111111111"').replace("an = false", "an = true"), encoding="utf-8")
    text = _rechnung("VAT number: FR12345678901", "")
    assert not any("Steuersatz" in p for p in pruefe(_e(), text))
    assert any("EU-Rechnung ohne" in p for p in hinweise(_e(), text))
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('ust_id = "DE111111111"', ''), encoding="utf-8")
    assert "Steuersatz" in " ".join(pruefe(_e(), text))


def test_ocr_steuer_und_kleinbetrag_position_und_drittland(repo):
    assert not any("Steuersatz" in p for p in pruefe(_e(), _rechnung("MwSt\n\n\n19 %")))
    klein = Text("Receipt\nRechnung RE-1\n29.10.2026\niCloud+ mit 50 GB 2,99\nGesamt 2,99", "klartext", 1)
    assert not any("Leistungsbeschreibung" in p for p in pruefe(_e(2.99), klein))
    ausland = _rechnung("Canva Pty Ltd\nAustralia\nABN 123 456 789", "")
    assert not any("Steuersatz" in p for p in pruefe(_e(), ausland))


def test_liste_sortiert_blendet_aus_und_status_wird_bei_neuem_problem_geoeffnet():
    stand = {"erste_liste": None, "anbieter": {"alt": {"name": "Alt", "status": "ignorieren", "weg": "lieferant", "probleme": [], "rechnungen": 1}}}
    eintraege = [{"lieferant": "Meta GmbH", "punkte": ["Empfänger fehlt"], "hinweise": [], "datum": "2026-10-01", "betrag": 1},
                 {"lieferant": "Anders", "punkte": ["Steuer fehlt"], "hinweise": [], "datum": "2026-10-01", "betrag": 1},
                 {"lieferant": "Alt", "punkte": ["Steuer fehlt"], "hinweise": [], "datum": "2026-10-01", "betrag": 1}]
    _, text = liste(eintraege, stand)
    assert text.index("Meta") < text.index("Anders") and "- Alt" not in text
    daten = {"erste_liste": None, "anbieter": {"muster": {"name": "Muster", "status": "erledigt", "probleme": ["Empfänger fehlt"], "rechnungen": 1}}}
    neu, melden = aktualisieren({"lieferant": "Muster GmbH", "punkte": ["Steuer fehlt"], "hinweise": [], "datum": "2026-10-02"}, daten)
    assert neu["status"] == "offen" and melden
