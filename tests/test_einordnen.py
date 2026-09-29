"""Tests für die regelbasierte und modellfreie Belegeinordnung."""

from __future__ import annotations

from datetime import date

from belege.einordnen import einordnen
from belege.typen import Fund, Text


def _fund(repo, name="rechnung.pdf", mail=None):
    datei = repo / name
    datei.write_bytes(b"Beleg")
    return Fund(datei, "postfach", name, date(2026, 9, 10), mail=mail)


def _text(wert):
    return Text(wert, "klartext", 1)


def test_regel_uebernimmt_feste_felder(repo):
    regeln = repo / "konfig" / "regeln.toml"
    regeln.write_text(
        "[zahlungsabwickler]\ndomains = []\n\n[[absender]]\n"
        'muster = "@abo.example"\nlieferant = "Abo Beispiel"\n'
        'bereich = "betrieb"\nart = "eingang"\n'
        'beschreibung = "Software-Abo"\n',
        encoding="utf-8",
    )
    fund = _fund(repo, mail={"von": "rechnung@abo.example", "von_name": "Abo Beispiel"})
    ergebnis = einordnen(fund, _text("Rechnung\nDatum: 10.09.2026\nGesamt 19,90 EUR"))
    assert ergebnis.quelle == "regel"
    assert ergebnis.lieferant == "Abo Beispiel"
    assert ergebnis.beschreibung == "Software-Abo"
    assert ergebnis.betrag == 19.90


def test_zahlungsabwickler_nimmt_anzeigenamen(repo):
    fund = _fund(
        repo,
        mail={
            "von": "rechnung@paypal.com",
            "von_name": "Schriftwerk Fonts via Zahlfix",
        },
    )
    ergebnis = einordnen(fund, _text("Receipt\nDate: 2026-09-10\nTotal €19.00"))
    assert ergebnis.lieferant == "Schriftwerk Fonts"


def test_generische_kopfzeile_ist_nie_lieferant(repo):
    fund = _fund(repo)
    ergebnis = einordnen(
        fund, _text("Invoice\nNordlicht Bürobedarf\nDate: 2026-09-10\nTotal 21.00 EUR")
    )
    assert ergebnis.lieferant == "Nordlicht Bürobedarf"


def test_fristdatum_wird_ignoriert(repo):
    fund = _fund(repo)
    text = "Papier Beispiel\nRechnungsdatum: 10.09.2026\nZahlbar bis 15.10.2026\nGesamt 12,00 EUR"
    ergebnis = einordnen(fund, _text(text))
    assert ergebnis.datum == date(2026, 9, 10)


def test_eigene_ausgangsrechnung(repo):
    fund = _fund(repo)
    text = "Studio Beispiel\nRechnung\nKunde Beispiel\nDatum: 10.09.2026\nGesamt 238,00 EUR"
    ergebnis = einordnen(fund, _text(text))
    assert ergebnis.art == "ausgang"


def test_newsletter_ist_kein_beleg(repo):
    fund = _fund(repo)
    ergebnis = einordnen(fund, _text("Newsletter\nAngebot der Woche\nJetzt abmelden"))
    assert not ergebnis.ist_beleg


def test_pruefe_lehnt_kaputtes_json_ab(monkeypatch, repo):
    from belege import einordnen as modul

    def falsche_frage(auftrag, *, zweck, pruefe, rueckfall):
        assert zweck == "einordnen"
        assert pruefe({"ist_beleg": True}) is not None
        return rueckfall()

    monkeypatch.setattr(modul, "frage", falsche_frage)
    ergebnis = modul.einordnen(
        _fund(repo), _text("Rechnung\nDatum: 10.09.2026\nSumme 4,00 EUR")
    )
    assert ergebnis.quelle == "rueckfall"
