"""Backend-Vertrag des Postfach-Agenten, vollständig mit lokalen Fakes."""

from __future__ import annotations

import inspect
from datetime import date
from email.message import EmailMessage

from belege.microsoft import MicrosoftPostfach
from belege.postfach import GmailPostfach, ImapPostfach, OrdnerPostfach, Postfach


def _gmail_mail(ident, extra=None):
    headers = [
        {"name": "From", "value": "Liste <liste@example.test>"},
        {"name": "To", "value": "ich@example.test"},
        {"name": "Subject", "value": ident},
        {"name": "Date", "value": "Mon, 26 Oct 2026 10:00:00 +0000"},
    ]
    headers.extend(extra or [])
    return {"id": ident, "payload": {"headers": headers}, "snippet": "Vorschau"}


class _GmailDienst:
    def __init__(self):
        self.aufrufe = []
        self.seiten = [
            {"messages": [{"id": "eins"}], "nextPageToken": "zwei"},
            {"messages": [{"id": "zwei"}]},
        ]

    def users(self):
        return self

    def messages(self):
        return self

    def labels(self):
        return self

    def list(self, **kwargs):
        self.aufrufe.append(("list", kwargs))
        return self

    def get(self, **kwargs):
        self.aufrufe.append(("get", kwargs))
        self.aktuell = kwargs["id"]
        return self

    def create(self, **kwargs):
        self.aufrufe.append(("create", kwargs))
        return self

    def modify(self, **kwargs):
        self.aufrufe.append(("modify", kwargs))
        return self

    def execute(self):
        art, kwargs = self.aufrufe[-1]
        if art == "list" and "q" in kwargs:
            return self.seiten.pop(0)
        if art == "list":
            return {"labels": []}
        if art == "get":
            extra = [{"name": "List-Unsubscribe", "value": "<https://example.test>"}]
            return _gmail_mail(self.aktuell, extra if self.aktuell == "eins" else [])
        if art == "create":
            return {"id": "neu"}
        return {}


def test_gmail_posteingang_blaettert_und_erkennt_newsletter(monkeypatch):
    dienst = _GmailDienst()
    box = GmailPostfach.__new__(GmailPostfach)
    monkeypatch.setattr(box, "_dienst", lambda: dienst)
    eingang = box.posteingang(max=2)
    assert [mail["id"] for mail in eingang] == ["eins", "zwei"]
    assert eingang[0]["newsletter"] is True
    assert all("auszug" not in mail for mail in eingang)  # kein Textanfang aus dem snippet
    listen = [daten for art, daten in dienst.aufrufe if art == "list"]
    assert listen[0]["q"] == "in:inbox"
    assert listen[1]["pageToken"] == "zwei"


def test_gmail_aufraeumen_nutzt_nur_labels(monkeypatch):
    dienst = _GmailDienst()
    box = GmailPostfach.__new__(GmailPostfach)
    monkeypatch.setattr(box, "_dienst", lambda: dienst)
    assert box.aufraeumen("a", "archivieren") == "archiviert"
    assert box.aufraeumen("b", "ordner", "Ablage") == "nach Ablage verschoben"
    assert box.aufraeumen("c", "label", "Stern") == "mit Label Stern markiert"
    aenderungen = [daten["body"] for art, daten in dienst.aufrufe if art == "modify"]
    assert aenderungen[0] == {"removeLabelIds": ["INBOX"]}
    assert aenderungen[1]["removeLabelIds"] == ["INBOX"]
    assert aenderungen[2] == {"addLabelIds": ["neu"]}


class _Imap:
    def __init__(self, move=True):
        self.move = move
        self.aufrufe = []

    def select(self, name, readonly=True):
        self.aufrufe.append(("select", name, readonly))
        return "OK", [b"1"]

    def uid(self, befehl, *args):
        self.aufrufe.append((befehl, *args))
        if befehl == "search":
            return "OK", [b"1 2"]
        if befehl == "fetch":
            roh = (
                b"From: Liste <liste@example.test>\r\nSubject: Neu\r\n"
                b"Date: Mon, 26 Oct 2026 10:00:00 +0000\r\nList-Id: <liste>\r\n\r\n"
            )
            return "OK", [(b"2 (BODYSTRUCTURE (\"TEXT\" \"PLAIN\"))", roh)]
        return "OK", []

    def capability(self):
        return "OK", [b"IMAP4rev1 MOVE" if self.move else b"IMAP4rev1"]

    def create(self, ziel):
        self.aufrufe.append(("create", ziel))
        return "OK", []

    def logout(self):
        self.aufrufe.append(("logout",))


def _imap_box(monkeypatch, verbindung):
    box = ImapPostfach.__new__(ImapPostfach)
    box.konto = {"name": "test"}
    monkeypatch.setattr(box, "_imap", lambda: verbindung)
    return box


def test_imap_posteingang_peekt_und_markiert_nichts(monkeypatch):
    verbindung = _Imap()
    box = _imap_box(monkeypatch, verbindung)
    eingang = box.posteingang(max=1)
    assert eingang[0]["newsletter"] is True
    assert ("select", "INBOX", True) in verbindung.aufrufe
    assert "BODY.PEEK" in next(a for a in verbindung.aufrufe if a[0] == "fetch")[2]


def test_imap_aufraeumen_bewegt_nur_mit_move_und_label_ohne_seen(monkeypatch):
    mit_move = _Imap(move=True)
    assert _imap_box(monkeypatch, mit_move).aufraeumen("INBOX:2", "ordner", "Ablage") == "nach Ablage verschoben"
    assert ("move", "2", "Ablage") in mit_move.aufrufe
    ohne_move = _Imap(move=False)
    assert "nicht verschoben" in _imap_box(monkeypatch, ohne_move).aufraeumen("INBOX:2", "ordner", "Ablage")
    assert not any(aufruf[0] in {"copy", "store", "expunge"} for aufruf in ohne_move.aufrufe)
    labels = _Imap()
    assert "markiert" in _imap_box(monkeypatch, labels).aufraeumen("INBOX:2", "label", "Wichtig! heute")
    store = next(aufruf for aufruf in labels.aufrufe if aufruf[0] == "store")
    assert "Seen" not in store[-1]
    assert store[-1] == "(Wichtig--heute)"


class _Antwort:
    def __init__(self, daten):
        self.daten = daten

    def json(self):
        return self.daten


def _microsoft_mail(ident, anhang=True, headers=None):
    return {
        "id": ident,
        "subject": "Betreff",
        "from": {"emailAddress": {"address": "a@example.test"}},
        "toRecipients": [],
        "receivedDateTime": "2026-10-26T10:00:00Z",
        "hasAttachments": anhang,
        "internetMessageHeaders": headers or [],
    }


def test_microsoft_posteingang_blaettert_und_setzt_anhaenge(monkeypatch):
    box = MicrosoftPostfach.__new__(MicrosoftPostfach)
    aufrufe = []
    antworten = iter([
        {"value": [_microsoft_mail("eins", headers=[{"name": "List-Id", "value": "<liste>"}])], "@odata.nextLink": "https://graph.test/next"},
        {"value": [_microsoft_mail("zwei")]},
    ])
    monkeypatch.setattr(box, "_anfrage", lambda art, pfad, **kw: aufrufe.append((art, pfad, kw)) or _Antwort(next(antworten)))
    eingang = box.posteingang(max=2)
    assert [mail["id"] for mail in eingang] == ["eins", "zwei"]
    assert eingang[0]["newsletter"] is True and eingang[0]["anhaenge"]
    assert aufrufe[0][1] == "/me/mailFolders/inbox/messages"
    assert "bodyPreview" not in aufrufe[0][2]["params"]["$select"]
    assert aufrufe[0][2]["params"]["$top"] == 2
    assert aufrufe[1][1] == "https://graph.test/next"


def test_microsoft_aufraeumen_move_403_und_kategorien(monkeypatch):
    box = MicrosoftPostfach.__new__(MicrosoftPostfach)
    aufrufe = []
    def anfrage(art, pfad, **kwargs):
        aufrufe.append((art, pfad, kwargs))
        if art == "GET":
            return _Antwort({"categories": ["Schon"]})
        return _Antwort({})
    monkeypatch.setattr(box, "_anfrage", anfrage)
    assert box.aufraeumen("a", "archivieren") == "archiviert"
    assert aufrufe[-1] == ("POST", "/me/messages/a/move", {"json": {"destinationId": "archive"}})
    assert box.aufraeumen("a", "label", "Schon") == "mit Kategorie Schon markiert"
    assert aufrufe[-1][2]["json"] == {"categories": ["Schon"]}
    monkeypatch.setattr(box, "_anfrage", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("Microsoft Graph 403: nein")))
    box.name = "buero"
    assert "uv run belege anmelden --microsoft buero" in box.aufraeumen("a", "archivieren")


def test_ordner_postfach_laesst_dateien_unveraendert(repo):
    ordner = repo / "beispiel" / "erzeugt" / "postfach"
    nachricht = EmailMessage()
    nachricht["From"] = "a@example.test"
    nachricht["Subject"] = "ohne Datum"
    nachricht.add_attachment(b"beleg", maintype="application", subtype="pdf", filename="beleg.pdf")
    datei = ordner / "test.eml"
    datei.write_bytes(nachricht.as_bytes())
    vorher = {pfad.name: pfad.read_bytes() for pfad in ordner.glob("*.eml")}
    box = OrdnerPostfach({"name": "test", "ordner": str(ordner)})
    assert box.posteingang(seit=date(2026, 1, 1))[0]["anhaenge"] == ["beleg.pdf"]
    box.aufraeumen("test.eml", "label", "Beleg")
    assert {pfad.name: pfad.read_bytes() for pfad in ordner.glob("*.eml")} == vorher
    assert (repo / "arbeit" / "postfach-ordner-aktionen.jsonl").exists()


def test_posteingang_basis_ist_nicht_suche():
    box = Postfach({"name": "test"})
    assert box.posteingang(None, 2) == []


def test_neue_backend_methoden_enthalten_keine_loeschoperationen():
    for klasse in (GmailPostfach, ImapPostfach, MicrosoftPostfach, OrdnerPostfach):
        text = inspect.getsource(klasse.posteingang) + inspect.getsource(klasse.aufraeumen)
        assert "delete" not in text.lower()
        assert "trash" not in text.lower()
        assert "expunge" not in text.lower()
        assert "\\\\Deleted" not in text


def test_microsoft_ordner_suchen_anlegen_und_datumsfilter(monkeypatch):
    box = MicrosoftPostfach.__new__(MicrosoftPostfach)
    aufrufe = []

    def anfrage(art, pfad, **kwargs):
        aufrufe.append((art, pfad, kwargs))
        if art == "GET" and pfad == "/me/mailFolders":
            return _Antwort({"value": []})
        if art == "POST" and pfad == "/me/mailFolders":
            return _Antwort({"id": "neu-1", "displayName": kwargs["json"]["displayName"]})
        return _Antwort({"value": []})

    monkeypatch.setattr(box, "_anfrage", anfrage)
    assert box.aufraeumen("m1", "ordner", "Kunden O'Neil") == "nach Kunden O'Neil verschoben"
    suche = aufrufe[0][2]["params"]["$filter"]
    assert suche == "displayName eq 'Kunden O''Neil'"
    assert aufrufe[1] == ("POST", "/me/mailFolders", {"json": {"displayName": "Kunden O'Neil"}})
    assert aufrufe[2] == ("POST", "/me/messages/m1/move", {"json": {"destinationId": "neu-1"}})

    aufrufe.clear()
    box.posteingang(seit=date(2026, 10, 22), max=5)
    params = aufrufe[0][2]["params"]
    # Graph verlangt: Sortierfeld zuerst im Filter.
    assert params["$filter"].startswith("receivedDateTime ge 2026-10-22")
    assert params["$orderby"] == "receivedDateTime desc"
