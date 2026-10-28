from datetime import date

from belege import kern
from belege.fehlerbericht import schwaerzen
from belege.quellen import mail_erledigt
from belege.text import pdf_defekt


def test_fehlerbericht_schwaerzt_private_werte():
    text = schwaerzen("max@example.test DE12 3456 7890 1234 5678 90 1.234,56 EUR Rechnung.pdf token: geheim")
    assert "<mail>" in text and "<iban>" in text and "<betrag>" in text and "<datei>" in text and "token: geheim" not in text


def test_fehlerbericht_schwaerzt_token_betraege_und_dateipfade_mit_leerzeichen():
    text = schwaerzen('de12 3456 7890 1234 5678 90 -1.234,56 12.30 access_token=abc "refresh_token": "def" Bearer xyz /tmp/Meine Rechnung ä.pdf')
    assert "de12" not in text and "-1.234,56" not in text and "12.30" not in text
    assert "abc" not in text and "def" not in text and "xyz" not in text and "Meine Rechnung" not in text


def test_fehlerbericht_startet_keine_pruefung(repo, monkeypatch, capsys):
    from belege import fehlerbericht

    monkeypatch.setattr("belege.pruefen.befehl", lambda *_: (_ for _ in ()).throw(AssertionError("kein pruefen")))
    monkeypatch.setattr(fehlerbericht, "_system", lambda: "Testsystem")
    assert fehlerbericht.befehl(None) == 0
    assert "Fehlerbericht" in capsys.readouterr().out


def test_imap_ablage_ordner_lehnt_steuerzeichen_und_anfuehrungszeichen_ab():
    from belege.postfach import imap_ablage_ordner_gueltig

    assert imap_ablage_ordner_gueltig("Belege erledigt")
    assert not any(imap_ablage_ordner_gueltig(name) for name in ("", " ", "x\ny", 'x"y', "x" * 101))


def test_imap_nach_ablage_prueft_status_und_sendet_nie_loeschbefehle(monkeypatch):
    from belege.postfach import ImapPostfach

    befehle = []

    class Verbindung:
        def select(self, *args, **kwargs):
            befehle.append(("select", args)); return "OK", []
        def uid(self, befehl, *args):
            befehle.append((befehl, args)); return ("NO", []) if befehl == "store" else ("OK", [])
        def logout(self):
            pass

    box = ImapPostfach.__new__(ImapPostfach)
    monkeypatch.setattr(box, "_imap", lambda: Verbindung())
    assert "UID STORE fehlgeschlagen" in box.nach_ablage("INBOX:7", "verschieben", "Erledigt")
    assert [b[0] for b in befehle] == ["select", "store"]
    assert not any("delete" in str(b).lower() or "expunge" in str(b).lower() for b in befehle)


def test_nach_ablage_standard_aendert_nichts(repo, monkeypatch):
    class Postfach:
        weg = "b"
        def nach_ablage(self, *args):
            raise AssertionError("darf ohne Einstellung nicht aufgerufen werden")
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: Postfach())
    mail_erledigt("geschaeft", "id", True)


def test_nach_ablage_markiert_nur_echt(repo, monkeypatch):
    (repo / "konfig" / "belege.toml").write_text((repo / "konfig" / "belege.toml").read_text() + '\n[[konto]]\nname = "zweites"\nweg = "ordner"\nnach_ablage = "markieren"\n', encoding="utf-8")
    aufrufe = []
    class Postfach:
        weg = "b"
        def nach_ablage(self, *args):
            aufrufe.append(args); return "markiert"
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: Postfach())
    mail_erledigt("zweites", "id", True)
    assert aufrufe and aufrufe[0][1] == "markieren"


def test_pdf_defekt_erkennt_leere_fehlende_header_und_abschnitt(tmp_path):
    kaputt = tmp_path / "kaputt.pdf"; kaputt.write_bytes(b"%PDF-1.7 kaputt")
    attrappe = tmp_path / "attrappe.pdf"; attrappe.write_bytes(b"Rechnung")
    assert pdf_defekt(kaputt)
    assert not pdf_defekt(attrappe)
    leer = tmp_path / "leer.pdf"; leer.write_bytes(b"")
    html = tmp_path / "fehler.pdf"; html.write_text("<html>Download error</html>")
    assert pdf_defekt(leer) and pdf_defekt(html)


def test_schwaerzen_geheimnis_mit_leerzeichen_in_anfuehrungszeichen():
    from belege.fehlerbericht import schwaerzen

    text = schwaerzen('passwort = "mein geheimes wort" und {"client_secret": "a b c"}')
    assert "geheimes" not in text and "a b c" not in text
    assert text.count("<geheimnis>") == 2



def test_schwaerzen_header_cookie_und_oauth_code():
    from belege.fehlerbericht import schwaerzen

    text = schwaerzen("Authorization: Basic dXNlcjpwYXNz\nCookie: sid=abc; x=1\nGET /cb?code=4/0AbcDef&state=xyz")
    assert "dXNlcjpwYXNz" not in text and "abc;" not in text and "0AbcDef" not in text and "xyz" not in text


def test_schwaerzen_header_als_json():
    from belege.fehlerbericht import schwaerzen

    text = schwaerzen('{"Authorization": "Basic geheim", \'Cookie\': \'a=b; c=d\'}')
    assert "geheim" not in text and "a=b" not in text
