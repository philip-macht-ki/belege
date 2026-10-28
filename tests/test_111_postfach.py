"""Abnahmefälle für die Mailpflege und getrennte Monatsübergaben aus 1.11."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from belege import kern, monat, takt
from belege.microsoft import MicrosoftPostfach
from belege.postfach import GmailPostfach, ImapPostfach
from belege.quellen import mail_erledigt
from belege.typen import Fund


class _Imap:
    def __init__(self, select="OK", store="OK", move="OK", move_faehig=True):
        self.status = {"select": select, "store": store, "move": move}
        self.move_faehig = move_faehig
        self.befehle = []

    def select(self, *args, **kwargs):
        self.befehle.append(("select", args))
        return self.status["select"], []

    def uid(self, befehl, *args):
        self.befehle.append(("uid " + befehl, args))
        return self.status.get(befehl, "OK"), []

    def capability(self):
        self.befehle.append(("capability", ()))
        return "OK", [b"IMAP4rev1 MOVE"] if self.move_faehig else [b"IMAP4rev1"]

    def create(self, *args):
        self.befehle.append(("create", args))
        return "OK", []

    def logout(self):
        self.befehle.append(("logout", ()))


def _imap_box(monkeypatch, verbindung):
    box = ImapPostfach.__new__(ImapPostfach)
    monkeypatch.setattr(box, "_imap", lambda: verbindung)
    return box


def test_imap_nach_ablage_markiert_oder_bewegt_ohne_loeschen(monkeypatch):
    verbindung = _Imap()
    meldung = _imap_box(monkeypatch, verbindung).nach_ablage("INBOX:42", "verschieben", "Belege erledigt")
    assert meldung == "nach Belege erledigt verschoben"
    assert ("uid store", ("42", "+FLAGS", "(\\Seen belege-erledigt)")) in verbindung.befehle
    assert ("uid move", ("42", '"Belege erledigt"')) in verbindung.befehle
    assert not any("deleted" in str(b).lower() or "expunge" in str(b).lower() for b in verbindung.befehle)


def test_imap_ohne_move_markiert_nur_und_statusfehler_sind_keine_erfolge(monkeypatch):
    ohne_move = _Imap(move_faehig=False)
    assert "nur markiert" in _imap_box(monkeypatch, ohne_move).nach_ablage("INBOX:7", "verschieben", "Erledigt")
    assert not any(name == "uid move" for name, _ in ohne_move.befehle)
    for schritt in ("select", "store", "move"):
        verbindung = _Imap(**{schritt: "NO"})
        meldung = _imap_box(monkeypatch, verbindung).nach_ablage("INBOX:8", "verschieben", "Erledigt")
        assert "fehlgeschlagen" in meldung


def test_mailpflege_nur_echt_und_nur_bei_vollstaendiger_mail(repo, monkeypatch):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("waechter = true", 'waechter = true\nnach_ablage = "markieren"'), encoding="utf-8")
    aufrufe = []

    class Box:
        weg = "b"

        def nach_ablage(self, *args):
            aufrufe.append(args)
            return "markiert"

    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: Box())
    mail_erledigt("geschaeft", "m1", False)
    assert aufrufe == []
    funde = [
        Fund(repo / "a.pdf", "postfach", "a.pdf", date(2026, 10, 1), {"konto": "geschaeft", "id": "m1"}),
        Fund(repo / "b.pdf", "postfach", "b.pdf", date(2026, 10, 1), {"konto": "geschaeft", "id": "m1"}),
    ]
    erledigt = []
    monkeypatch.setattr(takt, "_funde", lambda *_: funde)
    monkeypatch.setattr("belege.verarbeiten.verarbeite", lambda fund, echt: kern.Ergebnis("ok") if fund.name == "a.pdf" else kern.Ergebnis("befund", "Unsortiert"))
    monkeypatch.setattr("belege.quellen.mail_erledigt", lambda *args: erledigt.append(args))
    monkeypatch.setattr("belege.quellen.lauf_abschliessen", lambda *args: None)
    monkeypatch.setattr(takt, "_postfach_konten", lambda args: ["geschaeft"])
    takt.quelle_abarbeiten("postfach", SimpleNamespace(echt=True))
    assert erledigt == []
    mail_erledigt("geschaeft", "m1", True)
    assert aufrufe == [("m1", "markieren", "Belege erledigt")]


def test_gmail_label_archiviert_ohne_zu_loeschen_und_fehler_bleibt_lokal(monkeypatch):
    aufrufe = []

    class Dienst:
        def users(self): return self
        def labels(self): return self
        def messages(self): return self
        def list(self, **kwargs): return self
        def create(self, **kwargs): aufrufe.append(("create", kwargs)); return self
        def modify(self, **kwargs): aufrufe.append(("modify", kwargs)); return self
        def execute(self):
            if aufrufe and aufrufe[-1][0] == "create":
                return {"id": "erledigt"}
            return {"labels": []}

    box = GmailPostfach.__new__(GmailPostfach)
    monkeypatch.setattr(box, "_dienst", lambda *args: Dienst())
    assert box.nach_ablage("mail1", "verschieben", "Belege erledigt") == "archiviert und mit Label Belege erledigt markiert"
    assert aufrufe[-1] == ("modify", {"userId": "me", "id": "mail1", "body": {"addLabelIds": ["erledigt"], "removeLabelIds": ["INBOX"]}})
    assert not any("delete" in str(aufruf).lower() for aufruf in aufrufe)
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: box)
    monkeypatch.setattr(box, "nach_ablage", lambda *args: (_ for _ in ()).throw(RuntimeError("API kaputt")))
    mail_erledigt("geschaeft", "mail2", True)


def test_microsoft_schreibrecht_fehlt_bricht_nicht_ab_und_move_nutzt_graph(monkeypatch, repo):
    box = MicrosoftPostfach.__new__(MicrosoftPostfach)
    ohne_recht = []
    monkeypatch.setattr(box, "_anfrage", lambda *args, **kwargs: ohne_recht.append(args) or (_ for _ in ()).throw(RuntimeError("Mail.ReadWrite fehlt")))
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: box)
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("waechter = true", 'waechter = true\nnach_ablage = "verschieben"'), encoding="utf-8")
    mail_erledigt("geschaeft", "microsoft1", True)
    assert ohne_recht and ohne_recht[0][0] == "GET"

    class Antwort:
        def __init__(self, daten): self.daten = daten
        def json(self): return self.daten

    aufrufe = []
    def anfrage(art, pfad, **kwargs):
        aufrufe.append((art, pfad, kwargs))
        return Antwort({"value": [{"id": "ziel"}]} if art == "GET" else {})
    monkeypatch.setattr(box, "_anfrage", anfrage)
    assert box.nach_ablage("microsoft2", "verschieben", "Belege erledigt") == "nach Belege erledigt verschoben"
    assert aufrufe[-1] == ("POST", "/me/messages/microsoft2/move", {"json": {"destinationId": "ziel"}})


def test_pruefen_warnt_bei_microsoft_nur_mit_aktiver_mailpflege(repo, monkeypatch, capsys):
    from belege import pruefen

    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('weg = "ordner"', 'weg = "microsoft"'), encoding="utf-8")
    monkeypatch.setattr("belege.microsoft.token", lambda konto: "zugang")
    pruefen.befehl(None)
    assert "Markieren bei Microsoft braucht neue Anmeldung" not in capsys.readouterr().out
    toml.write_text(toml.read_text(encoding="utf-8").replace("waechter = true", 'waechter = true\nnach_ablage = "markieren"'), encoding="utf-8")
    pruefen.befehl(None)
    assert "GELB: Markieren bei Microsoft braucht neue Anmeldung" in capsys.readouterr().out


def test_uebergabe_trennt_arten_merkt_teilerfolge_und_firmen(repo, monkeypatch):
    monat_wert = "2026-10"
    toml = repo / "konfig" / "belege.toml"
    text = toml.read_text(encoding="utf-8").replace('adresse = ""\nordner = ""', 'adresse = ""\nadressen = { eingang = "ein@example.test", ausgang = "aus@example.test", sonstige = "sonst@example.test" }\nordner = ""')
    toml.write_text(text, encoding="utf-8")
    datei = repo / "beleg.pdf"; datei.write_bytes(b"%PDF")
    monkeypatch.setattr(monat, "paket_packen", lambda *args: [datei])
    gesendet = []
    fehlend = {"ausgang"}
    def senden(an, betreff, text, anhaenge, echt, **kwargs):
        art = betreff.rsplit("(", 1)[1].split(")", 1)[0]
        gesendet.append((art, an, kwargs["fortschritt"]))
        return kern.Ergebnis("fehler" if art in fehlend else "ok")
    monkeypatch.setattr("belege.senden.senden", senden)
    args = SimpleNamespace(echt=True, ziel=[])
    monat._uebergabe(monat_wert, repo / "paket", {}, [], args)
    assert gesendet == [("eingang", "ein@example.test", "uebergabe:2026-10:eingang"), ("ausgang", "aus@example.test", "uebergabe:2026-10:ausgang"), ("sonstige", "sonst@example.test", "uebergabe:2026-10:sonstige")]
    fehlend.clear()
    monat._uebergabe(monat_wert, repo / "paket", {}, [], args)
    assert gesendet[-1] == ("ausgang", "aus@example.test", "uebergabe:2026-10:ausgang")
    monkeypatch.setattr(kern, "firmen", lambda: [{"name": "Alpha"}, {"name": "Beta"}])
    kern.schreiben(repo / "arbeit" / "gesehen.json", {"uebergabe": {monat_wert: "2026-11-01T00:00:00"}})
    vor = len(gesendet)
    monat._uebergabe(monat_wert, repo / "alpha", {}, [], args, {"name": "Alpha"})
    monat._uebergabe(monat_wert, repo / "beta", {}, [], args, {"name": "Beta"})
    assert len(gesendet) == vor + 3
    assert all(":Beta:" in fortschritt for _, _, fortschritt in gesendet[-3:])
