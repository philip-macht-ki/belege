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
