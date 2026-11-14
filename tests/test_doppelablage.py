"""Fehlerbericht Malerbetrieb März, 11.11.2026: verschobene Mail und Mehrfachablage."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from belege import kern, nachsortieren, quellen, rechnungslink, takt, verarbeiten
from belege.postfach import MailFehlt, _anhaenge_speichern
from belege.typen import Einordnung, Fund, Text


class Box:
    """Postfach-Attrappe: Mails mit je einem PDF-Anhang."""

    weg = "a"

    def __init__(self, mails, fehlt=(), links=()):
        self.mails, self.fehlt, self.links = mails, set(fehlt), list(links)
        self.pflege = []

    def suchen(self, **_):
        return [dict(m) for m in self.mails]

    def suchen_woerter(self, *_a, **_k):
        return [dict(m) for m in self.links]

    def anhaenge(self, ident, ziel):
        if ident in self.fehlt:
            raise MailFehlt(f"Mail {ident} ist nicht mehr im Postfach (verschoben oder gelöscht).")
        ziel.mkdir(parents=True, exist_ok=True)
        datei = ziel / "rechnung.pdf"
        datei.write_bytes(f"%PDF {ident}".encode())
        return [datei]

    def lesen(self, ident):
        raise MailFehlt(f"Mail {ident} ist nicht mehr im Postfach (verschoben oder gelöscht).")

    def nach_ablage(self, *args):
        self.pflege.append(args)
        return "als gelesen und mit belege-erledigt markiert"


def _mail(ident, message_id=""):
    return {"id": ident, "von": "a@example.org", "betreff": "Rechnung", "datum": "2026-11-10",
            "anhaenge": ["rechnung.pdf"], "message_id": message_id}


def _box(monkeypatch, box):
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: box)
    return box


def _stand(repo):
    return json.loads((repo / "arbeit" / "gesehen.json").read_text(encoding="utf-8"))["geschaeft"]


def _lauf(monkeypatch, ergebnis_je_fund):
    monkeypatch.setattr(takt, "_postfach_konten", lambda args: ["geschaeft"])
    monkeypatch.setattr("belege.verarbeiten.verarbeite", lambda fund, echt: ergebnis_je_fund(fund))
    return takt.quelle_abarbeiten("postfach", SimpleNamespace(echt=True))


def test_verschobene_mail_wird_uebersprungen_die_anderen_kommen(repo, monkeypatch):
    _box(monkeypatch, Box([_mail("INBOX:1"), _mail("INBOX:2"), _mail("INBOX:3")], fehlt={"INBOX:2"}))
    funde = list(quellen.postfach_funde("geschaeft", 3, echt=True))
    assert sorted(f.mail["id"] for f in funde) == ["INBOX:1", "INBOX:3"]
    protokoll = "".join(p.read_text(encoding="utf-8") for p in (repo / "arbeit" / "logs").glob("*.log"))
    assert "INBOX:2 übersprungen" in protokoll
    assert not (repo / "arbeit" / "gesehen.json").exists()


def test_mailfehlt_bleibt_ein_runtimeerror():
    assert issubclass(MailFehlt, RuntimeError)


def test_verschobene_linkmail_wird_gemerkt_statt_offen_gehalten(repo, monkeypatch):
    link = {**_mail("INBOX:9", "<l@x>"), "anhaenge": []}
    _box(monkeypatch, Box([], links=[link]))
    assert list(quellen.postfach_funde("geschaeft", 3, echt=True)) == []
    stand = _stand(repo)
    assert stand["links_geprueft"] == ["INBOX:9"]
    assert not stand.get("offen")


def test_abbruch_des_stroms_behaelt_abgeschlossene_mails(repo, monkeypatch):
    def strom(*_):
        for ident in ("INBOX:1", "INBOX:2"):
            yield Fund(repo / f"{ident[-1]}.pdf", "postfach", "r.pdf", date(2026, 11, 10),
                       {"konto": "geschaeft", "id": ident})
        raise RuntimeError("Verbindung weg")

    _box(monkeypatch, Box([]))
    monkeypatch.setattr(takt, "_funde", strom)
    with pytest.raises(RuntimeError):
        _lauf(monkeypatch, lambda fund: kern.Ergebnis("ok"))
    # Mail 1 war abgeschlossen, als Mail 2 begann; die angefangene Mail 2 bleibt offen.
    assert _stand(repo)["mails"] == ["INBOX:1"]


def test_befund_gilt_als_gesehen_aber_ohne_postfachpflege(repo, monkeypatch):
    box = _box(monkeypatch, Box([_mail("INBOX:5")]))
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        "waechter = true", 'waechter = true\nnach_ablage = "markieren"'), encoding="utf-8")
    _lauf(monkeypatch, lambda fund: kern.Ergebnis("befund", "Unsortiert"))
    assert _stand(repo)["mails"] == ["INBOX:5"]
    assert box.pflege == []
    assert list(quellen.postfach_funde("geschaeft", 3, echt=True)) == []


def test_fehler_haelt_die_mail_offen(repo, monkeypatch):
    def strom(*_):
        for name in ("a.pdf", "b.pdf"):
            yield Fund(repo / name, "postfach", name, date(2026, 11, 10), {"konto": "geschaeft", "id": "INBOX:6"})

    _box(monkeypatch, Box([]))
    monkeypatch.setattr(takt, "_funde", strom)
    _lauf(monkeypatch, lambda fund: kern.Ergebnis("ok" if fund.name == "a.pdf" else "fehler"))
    stand = _stand(repo)
    assert stand["mails"] == [] and "INBOX:6" in stand["offen"]


def test_abgelegte_mail_wird_einmal_im_postfach_markiert(repo, monkeypatch):
    box = _box(monkeypatch, Box([_mail("INBOX:7")]))
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        "waechter = true", 'waechter = true\nnach_ablage = "markieren"'), encoding="utf-8")
    _lauf(monkeypatch, lambda fund: kern.Ergebnis("ok"))
    assert len(box.pflege) == 1 and box.pflege[0][0] == "INBOX:7"


def test_in_anderen_ordner_verschobene_mail_kommt_nicht_wieder(repo, monkeypatch):
    _box(monkeypatch, Box([_mail("INBOX:5", "<a@b>"), _mail("INBOX:8")]))
    _lauf(monkeypatch, lambda fund: kern.Ergebnis("ok"))
    assert _stand(repo)["kennungen"] == ["<a@b>"]
    # Dieselbe Mail liegt jetzt im Archiv; eine neue Mail ohne Message-ID kommt weiter durch.
    _box(monkeypatch, Box([_mail("Archiv:7", "<a@b>"), _mail("INBOX:9")]))
    assert [f.mail["id"] for f in quellen.postfach_funde("geschaeft", 3, echt=True)] == ["INBOX:9"]


def test_mailtext_pdf_ist_bei_jedem_lauf_bytegleich(tmp_path):
    mail = {"von": "apple@example.org", "betreff": "Deine Rechnung", "datum": "2026-11-09", "text": "Gesamt 9,99 €"}
    erste = rechnungslink.mailtext_pdf(mail, tmp_path / "a").read_bytes()
    time.sleep(1.1)  # der Erstellzeitpunkt im PDF hat Sekundenauflösung
    zweite = rechnungslink.mailtext_pdf(mail, tmp_path / "b").read_bytes()
    assert hashlib.sha256(erste).hexdigest() == hashlib.sha256(zweite).hexdigest()


def _einordnen(sicherheit):
    def einordnen(fund, text, **_):
        return Einordnung(True, "eingang", "betrieb", date(2026, 11, 9), "Pixelwerk", "Software-Abo", 59.5,
                          "EUR", sicherheit, "Test.", "urteil", "")
    return einordnen


def test_fehler_nach_der_ablage_fuehrt_nicht_zur_zweiten_kopie(repo, monkeypatch):
    datei = repo / "arbeit" / "tmp" / "r.pdf"
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_bytes(b"%PDF einmalig")
    monkeypatch.setattr("belege.text.auslesen", lambda *_a, **_k: Text("Rechnung 4711 Gesamt 59,50 €", "pdftotext", 1))
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnen("niedrig"))
    echtes_ereignis = kern.ereignis

    def kaputt(art, *a, **k):
        if art == "unsortiert":
            raise OSError("Platte voll")
        return echtes_ereignis(art, *a, **k)

    monkeypatch.setattr(kern, "ereignis", kaputt)
    fund = Fund(datei, "postfach", "r.pdf", date(2026, 11, 9), {"konto": "geschaeft", "id": "INBOX:1"})
    assert verarbeiten.verarbeite(fund, True).status == "fehler"
    assert verarbeiten._sha(datei) in json.loads((repo / "arbeit" / "index.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(kern, "ereignis", echtes_ereignis)
    assert verarbeiten.verarbeite(fund, True).status == "nichts"
    assert len(list((repo / "ablage" / "Unsortiert").glob("*.pdf"))) == 1


def test_anhang_wird_im_arbeitsordner_nicht_hochgezaehlt(tmp_path):
    def nachricht(inhalt):
        n = EmailMessage()
        n.set_content("siehe Anhang")
        n.add_attachment(inhalt, maintype="application", subtype="pdf", filename="BWA.pdf")
        return n

    erste = _anhaenge_speichern(nachricht(b"%PDF eins"), tmp_path)
    zweite = _anhaenge_speichern(nachricht(b"%PDF eins"), tmp_path)
    assert erste == zweite and len(list(tmp_path.iterdir())) == 1
    andere = _anhaenge_speichern(nachricht(b"%PDF zwei"), tmp_path)
    assert andere != erste and len(list(tmp_path.iterdir())) == 2


def _unsortiert(repo, name, inhalt):
    ordner = repo / "ablage" / "Unsortiert"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / name).write_bytes(inhalt)
    return ordner / name


def _zaehler(monkeypatch, texte=None):
    gelesen = []

    def auslesen(datei, *_a, **_k):
        gelesen.append(datei.name)
        return Text((texte or {}).get(datei.name, "Rechnung 4711 Gesamt 59,50 €"), "pdftotext", 1)

    monkeypatch.setattr("belege.text.auslesen", auslesen)
    monkeypatch.setattr("belege.einordnen.einordnen", _einordnen("niedrig"))
    return gelesen


def test_nachsortieren_raeumt_bytegleiche_kopien_ohne_pruefung_weg(repo, monkeypatch):
    namen = ["2026-11-09_BWA.pdf", "2026-11-09_BWA_2.pdf", "2026-11-09_BWA_3.pdf"]
    for name in namen:
        _unsortiert(repo, name, b"%PDF bwa januar")
    gelesen = _zaehler(monkeypatch)
    weg = repo / "ablage" / "Unsortiert" / "Zu löschen"
    nachsortieren.lauf(False)
    assert not weg.exists()
    gelesen.clear()
    nachsortieren.lauf(True)
    assert sorted(p.name for p in weg.iterdir()) == namen[1:]
    assert (repo / "ablage" / "Unsortiert" / namen[0]).exists()
    assert set(gelesen) == {namen[0]}


def test_nachsortieren_erkennt_mailtext_kopien_am_text(repo, monkeypatch):
    a = _unsortiert(repo, "2026-11-09_rechnung-aus-mailtext.pdf", b"%PDF lauf 1")
    b = _unsortiert(repo, "2026-11-09_rechnung-aus-mailtext_2.pdf", b"%PDF lauf 2")
    c = _unsortiert(repo, "2026-11-09_rechnung-aus-mailtext_3.pdf", b"%PDF andere Rechnung")
    _zaehler(monkeypatch, {c.name: "Rechnung 9000 Gesamt 12,00 €"})
    nachsortieren.lauf(True)
    assert a.exists() and c.exists() and not b.exists()
    assert (repo / "ablage" / "Unsortiert" / "Zu löschen" / b.name).exists()


def test_nachsortieren_kopie_eines_schon_abgelegten_belegs(repo, monkeypatch):
    abgelegt = repo / "ablage" / "Betrieb" / "2026" / "11" / "Eingang" / "x.pdf"
    abgelegt.parent.mkdir(parents=True)
    abgelegt.write_bytes(b"%PDF amazon")
    kopie = _unsortiert(repo, "2026-11-09_amazon.pdf", b"%PDF amazon")
    eigen = _unsortiert(repo, "2026-11-09_eigen.pdf", b"%PDF eigen")
    index = {verarbeiten._sha(kopie): {"pfad": "Betrieb/2026/11/Eingang/x.pdf", "status": "abgelegt"},
             verarbeiten._sha(eigen): {"pfad": "Unsortiert/2026-11-09_eigen.pdf", "status": "unsortiert"}}
    (repo / "arbeit" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _zaehler(monkeypatch)
    nachsortieren.lauf(True)
    assert not kopie.exists() and abgelegt.exists() and eigen.exists()
