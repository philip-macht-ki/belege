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
        def suchen(self, *args, **kwargs): return [{"id": "1", "betreff": "[Belege-Posten]"}]
        def lesen(self, ident): return {"text": f"[{ident[:8]}] privat"}
    monkeypatch.setattr("belege.postfach.oeffnen", lambda: Postfach())
    # Die Kurz-ID ist in der Antwort, nicht die Mail-ID.
    monkeypatch.setattr(Postfach, "lesen", lambda self, _: {"text": f"[{ident[:8]}] privat"})
    posten.antworten()
    assert posten.laden()[ident]["status"] == "geklaert"
