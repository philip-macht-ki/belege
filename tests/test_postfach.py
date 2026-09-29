from email.message import EmailMessage
from belege.postfach import OrdnerPostfach, ImapPostfach
import pytest


def _mail(p, anhang=True):
    m = EmailMessage()
    m["From"] = "Mara Beispiel <mara@studio-beispiel.example>"
    m["To"] = "x@example"
    m["Subject"] = "Rechnung September"
    m["Date"] = "Mon, 28 Sep 2026 10:00:00 +0000"
    m.set_content("Hallo, hier ist die Rechnung.")
    if anhang:
        m.add_attachment(
            b"beleg", maintype="application", subtype="pdf", filename="beleg.pdf"
        )
    p.write_bytes(m.as_bytes())


def test_ordner_suchen_lesen_anhaenge_und_entwurf(repo):
    p = repo / "beispiel/erzeugt/postfach" / "rechnung.eml"
    _mail(p)
    box = OrdnerPostfach(
        {
            "name": "x",
            "weg": "ordner",
            "adresse": "mara@studio-beispiel.example",
            "ordner": str(p.parent),
        }
    )
    treffer = box.suchen("von:studio betreff:Rechnung", nur_anhang=True)
    assert treffer[0]["id"] == "rechnung.eml"
    assert "Rechnung" in box.lesen("rechnung.eml")["text"]
    assert box.anhaenge("rechnung.eml", repo / "tmp")[0].read_bytes() == b"beleg"
    ident = box.entwurf("x@example", "T", "Text", [])
    assert (repo / "arbeit/postausgang" / ident).exists()


def test_imap_server_und_passwortmeldungen(repo, monkeypatch):
    monkeypatch.delenv("PASSWORT_TEST", raising=False)
    with pytest.raises(RuntimeError, match="Trag das App-Passwort"):
        ImapPostfach({"name": "test", "adresse": "a@gmail.com"})
    monkeypatch.setenv("PASSWORT_TEST", "x")
    b = ImapPostfach({"name": "test", "adresse": "a@gmx.de"})
    assert (b.imap_host, b.smtp_port) == ("imap.gmx.net", 587)
    with pytest.raises(RuntimeError, match="Microsoft-Postfächer"):
        ImapPostfach({"name": "test", "adresse": "a@outlook.com"})


def test_imap_entwurf_findet_special_use_drafts(repo, monkeypatch):
    monkeypatch.setenv("PASSWORT_TEST", "x")
    aufrufe = []

    class Fake:
        def __init__(self, *a):
            pass

        def login(self, *a):
            return "OK", []

        def list(self):
            return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Meine Entwuerfe"']

        def append(self, *a):
            aufrufe.append(a)
            return "OK", []

        def logout(self):
            pass

    monkeypatch.setattr("belege.postfach.imaplib.IMAP4_SSL", Fake)
    ImapPostfach({"name": "test", "adresse": "a@gmail.com"}).entwurf(
        "x@example", "T", "Text", []
    )
    assert aufrufe and aufrufe[0][0] == "Meine Entwuerfe" and aufrufe[0][1] == "\\Draft"


def test_imap_suche_ohne_kriterien_nutzt_all():
    from belege.postfach import _imap_kriterien

    assert _imap_kriterien("", None) == []


def test_gmail_metadata_liest_anhaenge_und_label_quoted(monkeypatch):
    from belege.postfach import GmailPostfach, _gmail_metadata

    daten = _gmail_metadata(
        {
            "id": "1",
            "snippet": "Kurzer Auszug",
            "payload": {
                "headers": [{"name": "Subject", "value": "Rechnung"}],
                "parts": [{"filename": "a.pdf"}],
            },
        }
    )
    assert daten["anhaenge"] == ["a.pdf"]
    box = GmailPostfach({"name": "g", "weg": "b"})
    aufrufe = []
    monkeypatch.setattr(box, "suchen", lambda abfrage: aufrufe.append(abfrage) or [])
    box.mit_label("Beleg/Neu")
    assert aufrufe == ['label:"Beleg-Neu"']
