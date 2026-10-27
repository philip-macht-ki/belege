"""Zustand und Rückfragen der offenen Posten."""
from __future__ import annotations

from belege import kern, posten


def _buchung(status="fehlt"):
    return {"datum": "2026-01-04", "betrag": -12.5, "name": "Pixelwerk", "zweck": "Abo Januar", "status": status}


def test_posten_id_und_klaerung_bleiben_ueber_zwei_lauefe(repo):
    erster = posten.fortschreiben([_buchung()])
    ident = next(iter(erster))
    erster[ident].update(status="geklaert", grund="privat")
    kern.schreiben(repo / "arbeit/posten.json", erster)
    zweiter = posten.fortschreiben([_buchung("zugeordnet")])
    assert list(zweiter) == [ident]
    assert zweiter[ident]["status"] == "geklaert"


def test_mail_hat_nur_offen_und_wartet_mensch(repo):
    zustand = posten.fortschreiben([_buchung(), {**_buchung(), "name": "Unklar", "zweck": "X", "status": "pruefen"}])
    zustand[next(iter(zustand))]["status"] = "zugeordnet"
    text = posten.mailtext(zustand)
    assert "Unklar" in text and "Pixelwerk" not in text


def test_antwort_privat_setzt_status(repo, monkeypatch):
    zustand = posten.fortschreiben([_buchung()])
    ident = next(iter(zustand))

    class Postfach:
        def suchen(self, *args, **kwargs): return [{"id": "1", "betreff": "[Belege]"}]
        def lesen(self, ident): return {"text": f"[{ident[:8]}] privat"}
    monkeypatch.setattr("belege.postfach.oeffnen", lambda: Postfach())
    # Die Kurz-ID ist in der Antwort, nicht die Mail-ID.
    monkeypatch.setattr(Postfach, "lesen", lambda self, _: {"text": f"[{ident[:8]}] privat"})
    posten.antworten()
    assert posten.laden()[ident]["status"] == "geklaert"


def test_antwort_ignoriert_zitat_und_verarbeitet_mail_nur_einmal(repo, monkeypatch):
    zustand = posten.fortschreiben([
        _buchung(), {**_buchung(), "name": "Zwei", "zweck": "B", "betrag": -20},
        {**_buchung(), "name": "Drei", "zweck": "C", "betrag": -30},
    ])
    ids = list(zustand)
    text = f"[{ids[1][:8]}] Kein Beleg\n\nAm gestern schrieb Mara:\n> [{ids[0][:8]}] privat | kein Beleg | liegt bei | andere Firma\n> [{ids[1][:8]}] privat | kein Beleg | liegt bei | andere Firma\n> [{ids[2][:8]}] privat | kein Beleg | liegt bei | andere Firma"

    class Postfach:
        def suchen(self, *args, **kwargs): return [{"id": "mail-1", "betreff": "[Belege] 3 Posten"}]
        def lesen(self, _): return {"text": text}

    monkeypatch.setattr("belege.postfach.oeffnen", lambda: Postfach())
    posten.antworten()
    assert posten.laden()[ids[0]]["status"] == "offen"
    assert posten.laden()[ids[1]]["grund"] == "ohne_beleg"
    assert posten.laden()[ids[2]]["status"] == "offen"
    posten.antworten()
    assert posten.laden()["__bearbeitete_mails__"] == ["mail-1"]


def test_zwei_antworten_in_einer_mail_gelten_nur_fuer_ihre_id(repo, monkeypatch):
    zustand = posten.fortschreiben([_buchung(), {**_buchung(), "name": "Zwei", "zweck": "B", "betrag": -20}])
    ids = list(zustand)

    class Postfach:
        def suchen(self, *args, **kwargs): return [{"id": "mail-2", "betreff": "[Belege]"}]
        def lesen(self, _): return {"text": f"[{ids[0][:8]}] privat\n[{ids[1][:8]}]\nliegt bei"}

    monkeypatch.setattr("belege.postfach.oeffnen", lambda: Postfach())
    posten.antworten()
    assert posten.laden()[ids[0]]["grund"] == "privat"
    assert posten.laden()[ids[1]]["grund"] == "Beleg liegt bei"


def test_mail_ohne_offene_posten_sendet_nichts(repo, monkeypatch, capsys):
    posten.fortschreiben([{**_buchung(), "status": "zugeordnet"}])
    gesendet = []
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a))
    assert posten.mail(True) == 0
    assert gesendet == []
    assert "nichts offen, keine Mail" in capsys.readouterr().out


def test_posten_mail_ist_fuer_kunden_verstaendlich(repo, capsys):
    posten.fortschreiben([_buchung(), {**_buchung(), "name": "Zwei", "zweck": "B", "betrag": -20}, {**_buchung(), "name": "Drei", "zweck": "C", "betrag": -30}])
    posten.mail(False)
    text = capsys.readouterr().out
    assert "[Belege] 3 Posten brauchen dich (62,50 €)" in text
    assert "04.01.2026 · 12,50 € · Pixelwerk" in text
    assert "[" in text and "] → " in text
    assert "Was du offen lässt, frage ich in zwei Wochen wieder." in text
