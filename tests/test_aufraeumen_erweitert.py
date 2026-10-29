"""Zusagen des erweiterten Postfach-Agenten."""
from __future__ import annotations

import argparse
from datetime import timedelta
from email.message import EmailMessage

from belege import postfach_agent as aufraeumen, kern
from belege.postfach import OrdnerPostfach


def _regeln(repo, *zeilen):
    (repo / "konfig" / "postfach-regeln.md").write_text("\n".join(zeilen), encoding="utf-8")


def _mail(repo, name="x.eml", text="Kündigung bitte", datum=None):
    mail = EmailMessage()
    mail["From"] = "x@example.test"
    mail["Subject"] = "Bitte ansehen"
    mail["Date"] = (datum or kern.jetzt()).strftime("%a, %d %b %Y %H:%M:%S +0000")
    mail.set_content(text)
    datei = repo / "beispiel" / "erzeugt" / "postfach" / name
    datei.write_bytes(mail.as_bytes())
    return name


def _args(echt=False, ziel=None):
    return argparse.Namespace(echt=echt, ziel=ziel or [], tage=None)


def test_kopfmodus_liefert_keinen_text_und_textregel_ist_fehler(repo):
    box = OrdnerPostfach({"name": "test", "ordner": str(repo / "beispiel" / "erzeugt" / "postfach")})
    _mail(repo)
    assert "text" not in box.posteingang(None, 1)[0]
    _regeln(repo, '- text: "Kündigung" -> melden')
    _, fehler = aufraeumen.regeln()
    assert 'text: braucht lesen = "text"' in " ".join(fehler)


def test_textregel_greift_nur_im_textmodus(repo):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("[aufraeumen]", '[aufraeumen]\nlesen = "text"'), encoding="utf-8")
    _mail(repo)
    _regeln(repo, '- text: "kündigung" -> archivieren')
    regeln, fehler = aufraeumen.regeln()
    assert not fehler
    box = OrdnerPostfach({"name": "test", "ordner": str(repo / "beispiel" / "erzeugt" / "postfach")})
    assert aufraeumen.passende_regel(box.posteingang(None, 1, text=True)[0], regeln)["aktion"] == "archivieren"


def test_zustandsregeln_lassen_nur_sichere_aktionen_zu(repo):
    _regeln(repo, "- beantwortet -> entwurf: Nein")
    _, fehler = aufraeumen.regeln()
    assert "Zustandsregeln dürfen nur archivieren" in " ".join(fehler)


def test_alter_zaehlt_volle_tage(monkeypatch):
    mail = {"datum": (kern.jetzt() - timedelta(days=14)).isoformat()}
    regel = {"bedingung": "älter als 14 tage"}
    assert aufraeumen._passt(mail, regel)
    mail["datum"] = (kern.jetzt() - timedelta(days=13)).isoformat()
    assert not aufraeumen._passt(mail, regel)


def test_labels_schreibt_nur_ordnung(repo, monkeypatch):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("aufraeumen = false", "aufraeumen = true", 1), encoding="utf-8")
    class Box:
        def ordnung(self):
            return {"ordner": ["Belege"], "labels": [], "labels_sichtbar": False, "hinweis": "IMAP-Hinweis"}
        def zuordnung(self):
            return {"Belege": ["x@example.test", "x@example.test"]}
    monkeypatch.setattr("belege.postfach.oeffnen", lambda *_: Box())
    assert aufraeumen.labels(_args()) == 0
    text = (repo / "arbeit" / "postfach-ordnung.md").read_text(encoding="utf-8")
    assert "von: x@example.test -> ordner: Belege" in text and "IMAP-Hinweis" in text


def test_kurzfassung_schneidet_ab_und_ist_nie_aktion(monkeypatch):
    monkeypatch.setattr("belege.urteil.frage", lambda *a, **k: {"kurz": "x\n" + "a" * 200, "antwort_noetig": True})
    kurz = aufraeumen._kurzfassung({"text": "Material"})
    assert len(kurz["kurz"]) == 160 and "\n" not in kurz["kurz"] and kurz["antwort_noetig"]
