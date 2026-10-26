from email.message import EmailMessage
from belege.postfach import OrdnerPostfach, ImapPostfach, _server, passwort, schluesselbund_passwort
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
    monkeypatch.setattr("belege.postfach.schluesselbund_passwort", lambda _: None)
    monkeypatch.delenv("PASSWORT_TEST", raising=False)
    with pytest.raises(RuntimeError, match="App-Passwort"):
        ImapPostfach({"name": "test", "adresse": "a@gmail.com"})
    monkeypatch.setenv("PASSWORT_TEST", "x")
    b = ImapPostfach({"name": "test", "adresse": "a@gmx.de"})
    assert (b.imap_host, b.smtp_port) == ("imap.gmx.net", 587)
    with pytest.raises(RuntimeError, match="Microsoft-Postfächer"):
        ImapPostfach({"name": "test", "adresse": "a@outlook.com"})


@pytest.mark.parametrize(("domain", "imap", "smtp"), [
    ("gmx.net", "imap.gmx.net:993", "mail.gmx.net:587"),
    ("t-online.de", "secureimap.t-online.de:993", "securesmtp.t-online.de:465"),
    ("icloud.com", "imap.mail.me.com:993", "smtp.mail.me.com:587"),
    ("me.com", "imap.mail.me.com:993", "smtp.mail.me.com:587"),
    ("mac.com", "imap.mail.me.com:993", "smtp.mail.me.com:587"),
    ("mailbox.org", "imap.mailbox.org:993", "smtp.mailbox.org:465"),
    ("freenet.de", "mx.freenet.de:993", "mx.freenet.de:587"),
    ("posteo.de", "posteo.de:993", "posteo.de:465"),
    ("posteo.net", "posteo.de:993", "posteo.de:465"),
])
def test_bekannte_server(domain, imap, smtp):
    assert _server(domain, {}) == ((imap.rsplit(":", 1)[0], int(imap.rsplit(":", 1)[1])), (smtp.rsplit(":", 1)[0], int(smtp.rsplit(":", 1)[1])))


def test_schluesselbund_vor_umgebung(monkeypatch):
    class Antwort:
        returncode = 0
        stdout = "geheim\n"
    monkeypatch.setattr("belege.postfach.subprocess.run", lambda *a, **k: Antwort())
    monkeypatch.setenv("PASSWORT_TEST", "alt")
    assert schluesselbund_passwort("test") == "geheim"
    assert passwort("test") == "geheim"


def test_passwort_faellt_auf_umgebung_zurueck(monkeypatch):
    monkeypatch.setattr("belege.postfach.schluesselbund_passwort", lambda _: None)
    monkeypatch.setenv("PASSWORT_TEST", "alt")
    assert passwort("test") == "alt"


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


@pytest.mark.parametrize(("mx", "imap", "smtp"), [
    (["aspmx.l.google.com"], ("imap.gmail.com", 993), ("smtp.gmail.com", 465)),
    (["mx00.ionos.de"], ("imap.ionos.de", 993), ("smtp.ionos.de", 465)),
    (["smtpin.rzone.de"], ("imap.strato.de", 993), ("smtp.strato.de", 465)),
    (["w0123456.kasserver.com"], ("w0123456.kasserver.com", 993), ("w0123456.kasserver.com", 465)),
    (["www42.your-server.de"], ("mail.your-server.de", 993), ("mail.your-server.de", 465)),
])
def test_eigene_domain_am_mx_erkannt(monkeypatch, mx, imap, smtp):
    monkeypatch.setattr("belege.postfach._mx", lambda domain: mx)
    monkeypatch.setattr("belege.postfach._ispdb", lambda domain: pytest.fail("ISPDB nicht nötig"))
    assert _server("studio-beispiel.de", {}) == (imap, smtp)


def test_eigene_domain_konfig_hat_vorrang(monkeypatch):
    monkeypatch.setattr("belege.postfach._mx", lambda domain: pytest.fail("kein DNS nötig"))
    konto = {"imap_server": "mail.example.de", "smtp_server": "mail.example.de:587"}
    assert _server("example.de", konto) == (("mail.example.de", 993), ("mail.example.de", 587))


def test_eigene_domain_ueber_thunderbird_oder_klare_meldung(monkeypatch):
    monkeypatch.setattr("belege.postfach._mx", lambda domain: ["mx.unbekannt.example"])
    monkeypatch.setattr("belege.postfach._ispdb", lambda domain: ("imap.anbieter.example:993", "smtp.anbieter.example:587"))
    assert _server("firma.example", {}) == (("imap.anbieter.example", 993), ("smtp.anbieter.example", 587))
    monkeypatch.setattr("belege.postfach._ispdb", lambda domain: ("", ""))
    with pytest.raises(RuntimeError, match="imap_server und smtp_server"):
        _server("firma.example", {})


def test_eigene_domain_bei_microsoft_365(monkeypatch):
    monkeypatch.setattr("belege.postfach._mx", lambda domain: ["firma-de.mail.protection.outlook.com"])
    with pytest.raises(RuntimeError, match="Microsoft 365"):
        _server("firma.de", {})


def test_ispdb_liest_ssl_server(monkeypatch):
    from belege.postfach import _ispdb

    xml = b"""<clientConfig><emailProvider>
      <incomingServer type="pop3"><hostname>pop.x.example</hostname><port>995</port><socketType>SSL</socketType></incomingServer>
      <incomingServer type="imap"><hostname>imap.x.example</hostname><port>143</port><socketType>STARTTLS</socketType></incomingServer>
      <incomingServer type="imap"><hostname>imap.x.example</hostname><port>993</port><socketType>SSL</socketType></incomingServer>
      <outgoingServer type="smtp"><hostname>smtp.x.example</hostname><port>465</port><socketType>SSL</socketType></outgoingServer>
    </emailProvider></clientConfig>"""

    class Antwort:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return xml

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Antwort())
    assert _ispdb("x.example") == ("imap.x.example:993", "smtp.x.example:465")
