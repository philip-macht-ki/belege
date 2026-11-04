from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace


def test_anfrage_parser_formate_und_gruesse(monkeypatch):
    from belege.anfrage import lesen
    monkeypatch.setattr("belege.anfrage.kern.jetzt", lambda: __import__("datetime").datetime(2026, 11, 4))
    zeilen = lesen("Hallo Frau Müller,\nAmazon 12.10.2026 12,34 €\n13.10. 12.34 Telekom\n2026-10-14, 1.234,56 Lieferant\n15.10. 8,00 Bon\n16.10.2026; 9.99 Shop\n17.10. 10,01 Markt\nViele Grüße")
    assert len(zeilen) == 6
    assert zeilen[1].datum == date(2026, 10, 13)
    assert zeilen[2].betrag == 1234.56


def test_anfrage_zuordnung_toleranz():
    from belege.anfrage import Anfrage, zuordnen
    a = Anfrage("x", date(2026, 10, 10), 12.34, "Telekom")
    index = {"a": {"datum": "2026-10-17", "betrag": 12.35, "lieferant": "Telekom", "pfad": "a.pdf"}, "b": {"datum": "2026-10-18", "betrag": 12.34}}
    fund, weitere = zuordnen(a, index)
    assert fund and fund["lieferant"] == "Telekom" and weitere == []


def test_anfrage_kopiert_nur_echt(repo, capsys):
    from belege import kern
    from belege.anfrage import befehl
    quelle = repo / "ablage" / "Betrieb" / "beleg.pdf"
    quelle.parent.mkdir(parents=True, exist_ok=True)
    quelle.write_bytes(b"beleg")
    kern.schreiben(repo / "arbeit/index.json", {"x": {"datum": "2026-10-10", "betrag": 12.34, "lieferant": "Telekom", "pfad": "Betrieb/beleg.pdf"}})
    liste = repo / "liste.txt"
    liste.write_text("Telekom 10.10.2026 12,34", encoding="utf-8")
    args = SimpleNamespace(ziel=[str(liste)], echt=False, postfach=False)
    assert befehl(args) == 0
    assert not (repo / "ablage/Anfragen").exists()
    args.echt = True
    assert befehl(args) == 0
    assert list((repo / "ablage/Anfragen").rglob("beleg.pdf"))


def test_regel_schreibt_nur_echt(repo):
    from belege.regel import befehl
    args = SimpleNamespace(ziel=["Katzenfutter"], privat=True, betrieb=False, echt=False)
    vorher = (repo / "konfig/regeln.toml").read_text()
    assert befehl(args) == 0
    assert (repo / "konfig/regeln.toml").read_text() == vorher
    args.echt = True
    befehl(args)
    assert "Katzenfutter" in (repo / "konfig/regeln.toml").read_text()


def test_stichwort_vor_absender_und_vertraulich(repo):
    from belege.einordnen import _regel
    from belege.typen import Fund
    (repo / "konfig/regeln.toml").write_text('[[absender]]\nmuster="amazon"\nbereich="betrieb"\n[[stichwort]]\nwort="katzenfutter"\nbereich="privat"\n', encoding="utf-8")
    fund = Fund(Path("Amazon_Katzenfutter.pdf"), "test", "Amazon_Katzenfutter.pdf", date.today())
    assert _regel(fund, "Katzenfutter")["bereich"] == "privat"
    from belege.vertraulich import wortregel
    assert wortregel("Patient Katzenfutter").vertraulich


def test_verfahrensdoku_ohne_geheimnisse(repo):
    from belege.verfahrensdoku import entwurf
    (repo / "konfig/belege.toml").write_text((repo / "konfig/belege.toml").read_text() + '\n[geheim]\ntoken = "nie-ausgeben"\n')
    text = entwurf()
    assert "Entwurf, keine Rechts- oder Steuerberatung" in text
    assert "nie-ausgeben" not in text


def test_anfrage_ganze_betraege_vorjahr_und_kein_blinder_datumstreffer():
    from datetime import date
    from belege import anfrage
    zeilen = anfrage.lesen("Adobe 120 € vom 03.12.\nRechnung 4711\nEUR 80 Hosting")
    assert [z.betrag for z in zeilen] == [120.0, 80.0]
    assert anfrage._datum("03.12.", heute=date(2027, 1, 10)) == date(2026, 12, 3)
    assert anfrage._datum("03.01.", heute=date(2027, 1, 10)) == date(2027, 1, 3)
    index = {"a": {"pfad": "x.pdf", "datum": "2026-12-04", "betrag": 55.0, "lieferant": "Netzfunk", "beschreibung": ""}}
    nur_datum = anfrage.Anfrage("03.12.2026 Adobe", date(2026, 12, 3), None, "Adobe")
    assert anfrage.zuordnen(nur_datum, index)[0] is None
