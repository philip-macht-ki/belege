"""Gezielte Gegenprüfungen für die Nachbesserungen des Postfach-Agenten."""

from __future__ import annotations

from email.message import EmailMessage
from types import SimpleNamespace

from belege import postfach_agent as aufraeumen, kern
from belege.postfach import GmailPostfach, _datum, _mutf7, _mutf7_encode


def test_kurzfassung_ignoriert_keine_dict_antwort(monkeypatch):
    from belege import urteil

    monkeypatch.setattr(urteil, "frage", lambda *a, **k: "kein JSON")
    assert aufraeumen._kurzfassung({"text": "Material"}) == {"kurz": ""}


def test_regeln_sperren_papierkorb_und_spam_ziele(tmp_path):
    datei = tmp_path / "regeln.md"
    datei.write_text("- sonst -> ordner: Gelöschte Elemente\n- von: x -> label: SPAM\n", encoding="utf-8")
    regeln, fehler = aufraeumen.regeln(datei)
    assert regeln == []
    assert len(fehler) == 2 and all("Papierkorb/Spam" in fehlertext for fehlertext in fehler)


def test_gmail_sperrt_systemlabel_vor_api_aufruf(monkeypatch):
    box = GmailPostfach.__new__(GmailPostfach)
    monkeypatch.setattr(box, "_dienst", lambda *args: (_ for _ in ()).throw(AssertionError("API darf nicht laufen")))
    assert box.aufraeumen("mail", "label", "TRASH") == "nicht verschoben (Papierkorb/Spam ist gesperrt)"


def test_labels_zaehlen_absender_ueber_ordner_und_labels(repo, monkeypatch):
    class Postfach:
        def ordnung(self):
            return {"ordner": ["Rechnungen"], "labels": ["Sonst"], "labels_sichtbar": True}

        def zuordnung(self):
            return {"ordner": {"Rechnungen": ["a@example.test", "a@example.test"]}, "labels": {"Sonst": ["a@example.test"]}}

    monkeypatch.setattr(kern, "konten", lambda: [{"name": "test", "aufraeumen": True, "adresse": "ich@example.test"}])
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: Postfach())
    assert aufraeumen.labels(SimpleNamespace()) == 0
    text = (repo / "arbeit" / "postfach-ordnung.md").read_text(encoding="utf-8")
    assert "von: a@example.test" not in text


def test_maildatum_wird_nach_berlin_umgerechnet():
    nachricht = EmailMessage()
    nachricht["Date"] = "Mon, 26 Oct 2026 23:30:00 -0200"
    assert _datum(nachricht) == "2026-10-27"


def test_modified_utf7_kodiert_und_dekodiert_ordnernamen():
    assert _mutf7(_mutf7_encode("Kunden/Entwürfe & März")) == "Kunden/Entwürfe & März"


def test_nicht_markiert_ist_zustandsregel_und_kehrt_um():
    regel = {"bedingung": "gelesen und nicht markiert", "text": ""}
    assert aufraeumen._zustandsregel(regel)
    assert aufraeumen._passt({"zustand": {"gelesen": True, "markiert": False}}, regel)
    assert not aufraeumen._passt({"zustand": {"gelesen": True, "markiert": True}}, regel)
