import base64
from datetime import date
from email.message import EmailMessage

import pytest

from belege import microsoft
from belege.microsoft import MicrosoftPostfach, _graph_suche, ist_microsoft
from belege.postfach import oeffnen


def _roh():
    m = EmailMessage()
    m["From"] = "Stadtwerke <rechnung@stadtwerke.example>"
    m["To"] = "info@firma.example"
    m["Subject"] = "Ihre Rechnung Oktober"
    m["Date"] = "Mon, 26 Oct 2026 10:00:00 +0000"
    m.set_content("Anbei die Rechnung.")
    m.add_attachment(b"%PDF-1.4 beleg", maintype="application", subtype="pdf", filename="rechnung.pdf")
    return m.as_bytes()


class Antwort:
    def __init__(self, status=200, json=None, content=b"", headers=None):
        self.status_code = status
        self._json = json or {}
        self.content = content
        self.text = str(json or content)
        self.headers = headers or {}

    def json(self):
        return self._json


class Sitzung:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []

    def request(self, art, url, **kwargs):
        self.aufrufe.append((art, url, kwargs))
        return self.antworten.pop(0)


@pytest.fixture
def box(monkeypatch):
    monkeypatch.setattr(microsoft, "token", lambda konto: "t")
    return MicrosoftPostfach({"name": "firma", "weg": "microsoft", "adresse": "info@firma.example"})


def _mail(ident, anhang=True, eingang="2026-10-26T10:00:00Z"):
    return {
        "id": ident,
        "subject": "Ihre Rechnung Oktober",
        "from": {"emailAddress": {"name": "Stadtwerke", "address": "rechnung@stadtwerke.example"}},
        "toRecipients": [{"emailAddress": {"address": "info@firma.example"}}],
        "receivedDateTime": eingang,
        "hasAttachments": anhang,
        "bodyPreview": "Anbei die Rechnung.",
    }


def test_oeffnen_waehlt_microsoft(monkeypatch, repo):
    monkeypatch.setattr("belege.kern.konto", lambda name=None: {"name": "firma", "weg": "microsoft", "adresse": "a@b.example"})
    assert isinstance(oeffnen("firma"), MicrosoftPostfach)


def test_suchen_filtert_datum_und_anhang_und_folgt_naechster_seite(box):
    box.sitzung = Sitzung([
        Antwort(json={"value": [_mail("1"), _mail("2", anhang=False)], "@odata.nextLink": "https://graph/next"}),
        Antwort(json={"value": [_mail("3")]}),
    ])
    treffer = box.suchen(seit=date(2026, 10, 1), nur_anhang=True)
    assert [t["id"] for t in treffer] == ["1", "3"]
    assert treffer[0]["von"] == "rechnung@stadtwerke.example"
    assert treffer[0]["datum"] == "2026-10-26"
    art, url, kwargs = box.sitzung.aufrufe[0]
    assert url.endswith("/me/mailFolders/inbox/messages")
    assert kwargs["params"]["$filter"] == "receivedDateTime ge 2026-10-01T00:00:00Z and hasAttachments eq true"
    assert kwargs["params"]["$orderby"] == "receivedDateTime desc"
    assert box.sitzung.aufrufe[1][1] == "https://graph/next"
    assert box.sitzung.aufrufe[1][2]["params"] is None


def test_suchen_mit_woertern_nutzt_search_und_filtert_selbst(box):
    box.sitzung = Sitzung([Antwort(json={"value": [_mail("alt", eingang="2026-09-01T10:00:00Z"), _mail("neu")]})])
    treffer = box.suchen("von:stadtwerke betreff:Rechnung seit:2026-10-01")
    assert [t["id"] for t in treffer] == ["neu"]
    params = box.sitzung.aufrufe[0][2]["params"]
    assert params["$search"] == '"from:stadtwerke subject:Rechnung"'
    assert "$filter" not in params


def test_lesen_und_anhaenge_aus_rohmail(box, tmp_path):
    box.sitzung = Sitzung([Antwort(content=_roh()), Antwort(content=_roh())])
    mail = box.lesen("abc")
    assert mail["betreff"] == "Ihre Rechnung Oktober"
    assert mail["anhaenge"][0]["name"] == "rechnung.pdf"
    pfade = box.anhaenge("abc", tmp_path)
    assert pfade[0].read_bytes() == b"%PDF-1.4 beleg"
    assert box.sitzung.aufrufe[0][1].endswith("/me/messages/abc/$value")


def test_entwurf_und_senden_als_mime(box):
    box.sitzung = Sitzung([Antwort(status=201, json={"id": "entwurf1"}), Antwort(status=202)])
    assert box.entwurf("stb@kanzlei.example", "Belege", "Hallo", []) == "entwurf1"
    box._senden("stb@kanzlei.example", "Belege", "Hallo", [])
    for (art, url, kwargs), ziel in zip(box.sitzung.aufrufe, ["/me/messages", "/me/sendMail"]):
        assert art == "POST" and url.endswith(ziel)
        assert kwargs["headers"]["Content-Type"] == "text/plain"
        assert b"Subject: Belege" in base64.b64decode(kwargs["data"])


def test_drosselung_wird_abgewartet_und_401_erklaert(box, monkeypatch):
    monkeypatch.setattr(microsoft.time, "sleep", lambda s: None)
    box.sitzung = Sitzung([Antwort(status=429, headers={"Retry-After": "1"}), Antwort(content=_roh())])
    assert box.lesen("x")["betreff"] == "Ihre Rechnung Oktober"
    box.sitzung = Sitzung([Antwort(status=503), Antwort(status=202)])
    box._senden("a@b.example", "T", "Text", [])
    assert box.sitzung.aufrufe[1][2]["headers"]["Content-Type"] == "text/plain"
    box.sitzung = Sitzung([Antwort(status=401)])
    with pytest.raises(RuntimeError, match="belege anmelden --microsoft firma"):
        box.lesen("x")


def test_ohne_client_id_klarer_rueckfall(monkeypatch, repo):
    monkeypatch.setattr(microsoft, "CLIENT_ID", "")
    monkeypatch.delenv("BELEGE_MICROSOFT_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="Eigene App"):
        microsoft.token({"name": "firma", "adresse": "a@b.example"})
    assert microsoft.anmelden({"name": "firma"}) == 2


def test_client_id_reihenfolge(monkeypatch):
    monkeypatch.setattr(microsoft, "CLIENT_ID", "eingebaut")
    monkeypatch.setenv("BELEGE_MICROSOFT_CLIENT_ID", "umgebung")
    assert microsoft.client_id({"client_id": "konto"}) == "konto"
    assert microsoft.client_id({}) == "umgebung"
    monkeypatch.delenv("BELEGE_MICROSOFT_CLIENT_ID")
    assert microsoft.client_id({}) == "eingebaut"


def test_mandant_eigene_app_oder_gemeinsam():
    assert microsoft.mandant({"tenant_id": "abc-123"}) == "abc-123"
    assert microsoft.mandant({}) == "common"


def test_fehlertexte_fuer_admin_und_richtlinie():
    assert "tenant_id" in microsoft._fehlertext({"error_description": "AADSTS50194: not multi-tenant"})
    assert "Admin" in microsoft._fehlertext({"error_description": "AADSTS90094: admin approval required"})
    assert "Firmenrichtlinie" in microsoft._fehlertext({"error_description": "AADSTS530036: blocked"})


def test_graph_suche_und_erkennung(monkeypatch):
    assert _graph_suche('von:x betreff:Rechnung seit:2026-01-01 "Strom"') == "from:x subject:Rechnung Strom"
    monkeypatch.setattr("belege.postfach._mx", lambda d: ["firma-de.mail.protection.outlook.com"] if d == "firma.de" else ["mx.gmx.net"])
    assert ist_microsoft("a@hotmail.de")
    assert ist_microsoft("info@firma.de")
    assert not ist_microsoft("a@gmx.de")
