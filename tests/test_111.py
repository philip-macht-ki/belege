from datetime import date

from belege import kern
from belege.fehlerbericht import schwaerzen
from belege.quellen import mail_erledigt
from belege.text import pdf_defekt


def test_fehlerbericht_schwaerzt_private_werte():
    text = schwaerzen("max@example.test DE12 3456 7890 1234 5678 90 1.234,56 EUR Rechnung.pdf token: geheim")
    assert "<mail>" in text and "<iban>" in text and "<betrag>" in text and "<datei>" in text and "token: geheim" not in text


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


def test_pdf_defekt_und_textattrappe_unterschieden(tmp_path):
    kaputt = tmp_path / "kaputt.pdf"; kaputt.write_bytes(b"%PDF-1.7 kaputt")
    attrappe = tmp_path / "attrappe.pdf"; attrappe.write_bytes(b"Rechnung")
    assert pdf_defekt(kaputt)
    assert not pdf_defekt(attrappe)
