from argparse import Namespace

from belege import bericht, kern


def test_text_nennt_abgelegte_und_offene():
    liste = [
        {
            "art": "abgelegt",
            "text": "ok",
            "daten": {"datum": "2026-09-29", "lieferant": "Pixelwerk", "betrag": 59.5},
        },
        {"art": "unsortiert", "text": "Unsortiert/foto.jpg", "daten": {}},
        {"art": "fehler", "text": "postfach: Anmeldung abgelehnt", "daten": {}},
    ]
    text, betreff = bericht.text_und_betreff(liste)
    assert "Abgelegt (1)" in text
    assert "29.09. Pixelwerk 59,50 €" in text
    assert "Bitte ansehen" in text
    assert "Sag deinem Claude" in text
    assert betreff == "Belege: 1 abgelegt, 1 zum Ansehen, 1 Fehler"


def test_leerer_tag():
    assert bericht.text_und_betreff([]) == (
        "Heute nichts Neues.",
        "Belege: heute nichts Neues",
    )


def test_trocken_sendet_nicht(repo, monkeypatch, capsys):
    kern.ereignis("abgelegt", "ok", datum="2026-09-29", lieferant="Test", betrag=5)
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a))
    assert bericht.befehl(Namespace(echt=False)) == 0
    assert gesendet == []
    assert "Abgelegt (1)" in capsys.readouterr().out
    assert "bericht" not in (kern.lesen(repo / "arbeit" / "gesehen.json", {}) or {})


def test_echt_sendet_und_merkt_sich_den_stand(repo, monkeypatch):
    kern.ereignis("abgelegt", "ok", datum="2026-09-29", lieferant="Test", betrag=5)
    gesendet = []

    def falsches_senden(an, betreff, text, anhaenge, echt, konto=None):
        gesendet.append((an, betreff))
        return kern.Ergebnis("ok", "gesendet")

    monkeypatch.setattr("belege.senden.senden", falsches_senden)
    assert bericht.befehl(Namespace(echt=True)) == 0
    assert gesendet[0][0] == "mara@studio-beispiel.example"
    assert kern.lesen(repo / "arbeit" / "gesehen.json", {})["bericht"]
    assert bericht.neue_ereignisse() == []


def test_nicht_gesendeter_bericht_kommt_wieder(repo, monkeypatch):
    kern.ereignis("abgelegt", "ok", datum="2026-09-29", lieferant="Test", betrag=5)
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: kern.Ergebnis("befund", "nur Entwurf"))
    bericht.befehl(Namespace(echt=True))
    assert "bericht" not in (kern.lesen(repo / "arbeit" / "gesehen.json", {}) or {})
    assert bericht.neue_ereignisse()
