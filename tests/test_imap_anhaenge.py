from belege.postfach import _imap_anhaenge, _imap_ordnerliste, _imap_quote


def test_ordnerliste_inbox_zuerst_ohne_doppelte():
    assert _imap_ordnerliste({}) == ["INBOX"]
    konto = {"imap_ordner": ["INBOX/Sumup", "INBOX", " INBOX/Sumup ", "INBOX/Telekom"]}
    assert _imap_ordnerliste(konto) == ["INBOX", "INBOX/Sumup", "INBOX/Telekom"]


def test_ordnernamen_mit_leerzeichen_werden_gequotet():
    assert _imap_quote("INBOX") == "INBOX"
    assert _imap_quote("INBOX/Lieferanten") == "INBOX/Lieferanten"
    assert _imap_quote("INBOX/Software, Hosting etc") == '"INBOX/Software, Hosting etc"'
    assert _imap_quote('"INBOX/Meine Scans"') == '"INBOX/Meine Scans"'


def test_anhang_aus_bodystructure():
    antwort = [
        (
            b'1 (UID 20655 BODYSTRUCTURE ((("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL '
            b'"7BIT" 10 1 NIL NIL NIL NIL)) ("APPLICATION" "OCTET-STREAM" ("NAME" '
            b'"Faktur.pdf") NIL NIL "BASE64" 100 NIL ("ATTACHMENT" ("FILENAME" '
            b'"Faktur.pdf")) NIL NIL) "MIXED") BODY[HEADER] {20}',
            b"Subject: Rechnung\r\n\r\n",
        ),
        b")",
    ]
    assert _imap_anhaenge(antwort) == ["Faktur.pdf"]


def test_ohne_anhang_leer():
    antwort = [
        (
            b'1 (UID 1 BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL '
            b'"7BIT" 10 1 NIL NIL NIL NIL) "ALTERNATIVE") BODY[HEADER] {20}',
            b"Subject: Hallo\r\n\r\n",
        ),
        b")",
    ]
    assert _imap_anhaenge(antwort) == []


def test_rfc2231_und_rfc2047_namen():
    antwort = [
        (
            b'1 (UID 2 BODYSTRUCTURE ("APPLICATION" "PDF" ("NAME*" '
            b"\"utf-8''Rechnung%20M%C3%A4rz.pdf\") NIL NIL \"BASE64\" 1 NIL "
            b'("ATTACHMENT" ("FILENAME" "=?utf-8?q?Beleg_=C3=BC.pdf?=")) NIL NIL) '
            b"BODY[HEADER] {2}",
            b"\r\n",
        ),
    ]
    assert _imap_anhaenge(antwort) == ["Rechnung März.pdf", "Beleg ü.pdf"]


class _Liste:
    def __init__(self, zeilen):
        self.zeilen = zeilen

    def list(self):
        return "OK", self.zeilen


def test_alle_ordner_ohne_gesendet_papierkorb_und_spam():
    from belege.postfach import _imap_alle_ordner

    zeilen = [
        b'(\\HasChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "INBOX/Rechnungen"',
        b'(\\HasNoChildren) "/" "INBOX/Software, Hosting"',
        b'(\\HasNoChildren \\Sent) "/" "Gesendet"',
        b'(\\HasNoChildren) "/" "Entw&APw-rfe"',
        b'(\\HasNoChildren) "." "Gel&APY-schte Elemente"',
        b'(\\HasNoChildren) "/" "Spam"',
        b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
        b'(\\HasNoChildren \\All) "/" "[Gmail]/Alle Nachrichten"',
        b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Papierkorb"',
        b'(\\HasNoChildren) "/" "Archiv"',
        (b'(\\HasNoChildren) "/" {11}', b"Lieferanten"),
    ]
    assert _imap_alle_ordner(_Liste(zeilen)) == [
        "INBOX", "INBOX/Rechnungen", "INBOX/Software, Hosting", "Archiv", "Lieferanten",
    ]


def test_ordnerliste_kaputt_nur_inbox():
    from belege.postfach import _imap_alle_ordner

    class Kaputt:
        def list(self):
            raise OSError("weg")

    assert _imap_alle_ordner(Kaputt()) == ["INBOX"]


def test_suchen_ueber_ordner_mit_anhang_und_ohne_doppelte(monkeypatch):
    """Rechnung im Filterordner wird gefunden; dieselbe Mail unter einem Gmail-Label nur einmal."""
    from belege import postfach
    from belege.postfach import ImapPostfach

    def antwort(betreff, mid, anhang):
        struktur = (b'("APPLICATION" "PDF" ("NAME" "r.pdf") NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("FILENAME" "r.pdf")) NIL NIL)'
                    if anhang else b'("TEXT" "PLAIN" ("CHARSET" "utf-8") NIL NIL "7BIT" 1 1 NIL NIL NIL NIL)')
        kopf = f"Subject: {betreff}\r\nMessage-ID: <{mid}>\r\nFrom: a@b.example\r\nDate: Mon, 26 Oct 2026 10:00:00 +0000\r\n\r\n".encode()
        return [(b"1 (UID 1 BODYSTRUCTURE " + struktur + b" BODY[HEADER] {%d}" % len(kopf), kopf), b")"]

    postfaecher = {
        "INBOX": {b"1": antwort("Hallo", "x1", False)},
        "Rechnungen": {b"1": antwort("Rechnung", "r1", True)},
        "Label": {b"1": antwort("Rechnung", "r1", True)},
    }

    class Verbindung:
        aktuell = None

        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Rechnungen"',
                          b'(\\HasNoChildren) "/" "Label"', b'(\\HasNoChildren \\Sent) "/" "Sent"']

        def select(self, name, readonly=True):
            self.aktuell = name
            return ("OK", [b"1"]) if name in postfaecher else ("NO", [])

        def uid(self, befehl, *args):
            if befehl == "search":
                return "OK", [b" ".join(postfaecher[self.aktuell])]
            return "OK", postfaecher[self.aktuell][args[0]]

        def logout(self):
            pass

    box = ImapPostfach.__new__(ImapPostfach)
    box.konto, box.name, box.adresse, box.weg = {"name": "t"}, "t", "a@b.example", "a"
    monkeypatch.setattr(ImapPostfach, "_imap", lambda self: Verbindung())
    monkeypatch.setattr(ImapPostfach, "_suche", lambda self, v, k: v.uid("search"))
    treffer = box.suchen(nur_anhang=True)
    assert [t["id"] for t in treffer] == ["Rechnungen:1"]
    assert treffer[0]["anhaenge"] == ["r.pdf"]
    assert postfach._imap_ordnerliste({"imap_ordner": ["Rechnungen"]}) == ["INBOX", "Rechnungen"]


def test_sperriger_ordner_haelt_suche_nicht_auf(monkeypatch):
    import imaplib

    from belege.postfach import ImapPostfach

    class Verbindung:
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Kaputt"']

        def select(self, name, readonly=True):
            if name == "Kaputt":
                raise imaplib.IMAP4.error("SELECT failed")
            return "OK", [b"0"]

        def uid(self, befehl, *args):
            return "OK", [b""]

        def logout(self):
            pass

    box = ImapPostfach.__new__(ImapPostfach)
    box.konto, box.name, box.adresse, box.weg = {"name": "t"}, "t", "a@b.example", "a"
    monkeypatch.setattr(ImapPostfach, "_imap", lambda self: Verbindung())
    monkeypatch.setattr(ImapPostfach, "_suche", lambda self, v, k: v.uid("search"))
    assert box.suchen(nur_anhang=True) == []
