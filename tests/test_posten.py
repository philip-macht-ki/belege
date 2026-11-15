"""Zustand und Rückfragen der offenen Posten."""
from __future__ import annotations

from belege import kern, posten
from belege.cli import main


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


def test_weiche_posten_werden_neu_bewertet(repo):
    b = _buchung("pruefen")
    zustand = posten.fortschreiben([b])
    ident = next(iter(zustand))
    zustand[ident]["grund"] = "Beleg liegt bei"
    kern.schreiben(repo / "arbeit/posten.json", zustand)
    assert posten.fortschreiben([{**b, "status": "ohne_beleg"}])[ident]["status"] == "ohne_beleg"
    zustand = posten.fortschreiben([{**b, "status": "pruefen"}])
    assert posten.fortschreiben([{**b, "status": "zugeordnet"}])[ident]["status"] == "zugeordnet"
    zustand[ident].update(status="wartet_mensch", grund="Beleg liegt bei")
    kern.schreiben(repo / "arbeit/posten.json", zustand)
    neu = posten.fortschreiben([{**b, "status": "fehlt"}])
    assert (neu[ident]["status"], neu[ident]["grund"]) == ("wartet_mensch", "Beleg liegt bei")


def test_entfallene_posten_und_feste_klaerung(repo):
    b1 = {**_buchung(), "datum": "2026-10-04"}
    b2 = {**_buchung(), "datum": "2026-10-05", "zweck": "Zwei"}
    alt = {**_buchung(), "datum": "2026-09-04", "zweck": "Alt"}
    zustand = posten.fortschreiben([b1, alt], "2026-10")
    ident1 = posten.posten_id(b1)
    geklaert = posten.posten_id(alt)
    zustand[geklaert].update(status="geklaert", grund="privat")
    kern.schreiben(repo / "arbeit/posten.json", zustand)
    assert posten.fortschreiben([], "2026-10")[ident1]["status"] == "offen"
    neu = posten.fortschreiben([b2], "2026-10")
    assert neu[ident1]["status"] == "entfallen"
    assert neu[geklaert]["status"] == "geklaert"
    assert posten.fortschreiben([b1, b2], "2026-10")[ident1]["status"] == "offen"


def test_klaeren_ueber_cli(repo):
    zustand = posten.fortschreiben([_buchung(), {**_buchung(), "name": "PayPal", "zweck": "Zwei", "betrag": -2}])
    ident = next(iter(zustand))
    assert main(["posten", "--klaeren", ident[:8], "--grund", "privat", "--echt"]) == 0
    assert posten.laden()[ident]["weg"] == "gespraech"
    assert main(["posten", "--klaeren", "paypal", "--grund", "liegt-ab"]) == 0
    assert posten.laden()[posten.posten_id({**_buchung(), "name": "PayPal", "zweck": "Zwei", "betrag": -2})]["status"] == "offen"
    assert main(["posten", "--klaeren", "unbekannt", "--grund", "privat"]) == 1


def test_mailtext_trennt_einnahmen_und_antworten(repo, monkeypatch):
    zustand = posten.fortschreiben([_buchung(), {**_buchung(), "name": "Kunde", "betrag": 628.2, "zweck": "Rechnung"}])
    text = posten.mailtext(zustand)
    assert "Bei dieser Abbuchung fehlt noch der Beleg" in text
    assert "Bei diesem Zahlungseingang fehlt deine Rechnung" in text
    # Der Eingang steht unter den Zahlungseingängen, nicht unter den Abbuchungen.
    assert text.index("Zahlungseingang") < text.index("628,20 €")
    assert "liegt ab = " in text and "liegt bei = " in text
    assert "Zahlungseing" not in posten.mailtext({k: v for k, v in zustand.items() if v["betrag"] < 0})
    ids = list(zustand)
    class Postfach:
        def suchen(self, *args, **kwargs): return [{"id": "mail-neu", "betreff": "[Belege]"}]
        def lesen(self, _): return {"text": f"[{ids[0][:8]}] liegt ab\n[{ids[1][:8]}] Einnahme"}
    monkeypatch.setattr("belege.postfach.oeffnen", lambda: Postfach())
    posten.antworten()
    assert {posten.laden()[i]["grund"] for i in ids} == {"liegt_ab", "einnahme"}


def test_auflistung_ignoriert_technische_markierung(repo, capsys):
    zustand = posten.fortschreiben([_buchung()])
    zustand["__bearbeitete_mails__"] = []
    kern.schreiben(repo / "arbeit/posten.json", zustand)
    assert main(["posten"]) == 0
    assert "__bearbeitete" not in capsys.readouterr().out


def test_nachpruefen_findet_abgelegten_beleg_ohne_nebenwirkungen(repo):
    from belege import monat
    auszug = repo / "auszuege" / "august.csv"
    auszug.write_text("Datum;Betrag;Name;Zweck\n07.08.2026;-59,50;Pixelwerk;Abo\n", encoding="utf-8")
    buchung = {**monat.buchungen_aus([auszug], "2026-08")[0], "status": "fehlt"}
    ident = posten.posten_id(buchung)
    posten.fortschreiben([buchung])
    kern.schreiben(repo / "arbeit/index.json", {"beleg": {"status": "abgelegt", "bereich": "betrieb", "art": "eingang", "betrag": 59.5, "datum": "2026-08-07", "lieferant": "Pixelwerk"}})
    assert posten.nachpruefen(False) == 1
    assert posten.laden()[ident]["status"] == "offen"
    assert posten.nachpruefen(True) == 1
    assert posten.laden()[ident]["status"] == "zugeordnet"
    assert not list((repo / "arbeit" / "ereignisse").glob("*.jsonl")) if (repo / "arbeit" / "ereignisse").exists() else True


def test_mail_trocken_zeigt_nachpruefung_ohne_zu_schreiben(repo, monkeypatch, capsys):
    zustand = posten.fortschreiben([_buchung()])
    ident = next(iter(zustand))
    monkeypatch.setattr(posten, "_nachpruefen", lambda echt: (1, {ident: {**zustand[ident], "status": "zugeordnet"}}))
    assert posten.mail(False) == 0
    assert "Pixelwerk" not in capsys.readouterr().out
    assert posten.laden()[ident]["status"] == "offen"


def test_betreff_zaehlt_alle_posten_aber_nur_abbuchungen_als_summe(repo, monkeypatch, capsys):
    posten.fortschreiben([_buchung(), {**_buchung(), "name": "Kunde", "betrag": 628.2, "zweck": "Rechnung"}])
    assert posten.mail(False) == 0
    betreff = capsys.readouterr().out.splitlines()[0]
    assert betreff.startswith("[Belege] 2 Posten") and "628" not in betreff


def test_antwort_liegt_bei_und_zitierte_vorlage(repo, monkeypatch):
    zustand = posten.fortschreiben([_buchung(), {**_buchung(), "zweck": "Zwei"}])
    a, b = list(zustand)

    class Postfach:
        def suchen(self, *args, **kwargs): return [{"id": "m", "betreff": "[Belege]"}]
        def lesen(self, _): return {"text": f"[{a[:8]}] liegt bei\n"
                                    f"[{b[:8]}] privat, kein Beleg, liegt ab, liegt bei, andere Firma"}

    monkeypatch.setattr("belege.postfach.oeffnen", lambda: Postfach())
    posten.antworten()
    neu = posten.laden()
    assert (neu[a]["status"], neu[a]["grund"]) == ("wartet_mensch", "Beleg liegt bei")
    assert neu[b]["status"] == "offen"


def test_klaeren_fasst_nur_offene_posten_an(repo, capsys):
    offen = {**_buchung(), "name": "PayPal Bank Account", "zweck": "Umbuchung"}
    zweiter = {**_buchung(), "name": "PayPal Bank Account", "zweck": "Umbuchung zwei", "betrag": -20}
    fertig = {**_buchung("zugeordnet"), "name": "PayPal Europe", "zweck": "Rechnung 9", "beleg": "sha"}
    posten.fortschreiben([offen, zweiter, fertig])
    assert main(["posten", "--klaeren", "PayPal", "--grund", "kein-beleg", "--echt"]) == 0
    neu = posten.laden()
    assert neu[posten.posten_id(offen)]["grund"] == "ohne_beleg"
    assert neu[posten.posten_id(zweiter)]["status"] == "geklaert"
    assert neu[posten.posten_id(fertig)]["status"] == "zugeordnet"
    # Noch einmal dasselbe: nichts mehr offen, aber kein Fehler.
    assert main(["posten", "--klaeren", "PayPal", "--grund", "privat", "--echt"]) == 0
    assert posten.laden()[posten.posten_id(offen)]["grund"] == "ohne_beleg"
    assert main(["posten", "--klaeren", "PayPal"]) == 2
    assert "--grund" in capsys.readouterr().out


def test_nachpruefen_raeumt_nichts_als_entfallen_ab(repo):
    """Liegt für den Monat nur ein Teil der Auszüge vor, bleiben die anderen Posten stehen."""
    from belege import monat

    auszug = repo / "auszuege" / "august.csv"
    auszug.write_text("Datum;Betrag;Name;Zweck\n07.08.2026;-59,50;Pixelwerk;Abo\n", encoding="utf-8")
    da = {**monat.buchungen_aus([auszug], "2026-08")[0], "status": "fehlt"}
    anderes_konto = {"datum": "2026-08-09", "betrag": -12.0, "name": "Bäcker", "zweck": "Karte", "status": "fehlt"}
    posten.fortschreiben([da, anderes_konto])
    posten.nachpruefen(True)
    assert posten.laden()[posten.posten_id(anderes_konto)]["status"] == "offen"


def test_nachpruefen_ohne_auszug_laesst_alles_stehen(repo):
    b = {**_buchung(), "datum": "2026-08-07"}
    posten.fortschreiben([b])
    assert posten.nachpruefen(True) == 0
    assert posten.laden()[posten.posten_id(b)]["status"] == "offen"


def test_ohne_beleg_regel_greift_auch_bei_wartenden_posten(repo):
    """PayPal-Umbuchung stand als „prüfen“ in der Liste, danach kam die Regel ohne_beleg (Nina, 15.11.2026)."""
    from belege import monat

    b = {"datum": "2026-10-06", "betrag": -200.0, "name": "PayPal", "zweck": "Bank Account"}
    posten.fortschreiben([{**b, "status": "pruefen"}])
    regeln = repo / "konfig" / "regeln.toml"
    text = regeln.read_text(encoding="utf-8")
    assert "[monat]" in text
    regeln.write_text(text.replace("[monat]", '[monat]\nohne_beleg = ["Bank Account"]', 1) if "ohne_beleg" not in text
                      else text.replace("ohne_beleg = [", 'ohne_beleg = ["Bank Account", ', 1), encoding="utf-8")
    daten = monat.abgleichen([b], {})
    assert daten[0]["status"] == "ohne_beleg"
    neu = posten.fortschreiben(daten, "2026-10")
    assert neu[posten.posten_id(b)]["status"] == "ohne_beleg"
    assert posten.mailtext(neu) == ""
