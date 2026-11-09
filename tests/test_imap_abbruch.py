"""Verbindungsabbrüche und hängende Sockets im Takt (Fehlerbericht iCloud, 09.11.2026).

Ein ``[SSL: BAD_LENGTH]`` ließ früher alle folgenden Ordner auf der toten
Verbindung scheitern, und ein Aufruf ohne Zeitlimit hielt den Takt stundenlang an.
"""
from __future__ import annotations

import argparse
import imaplib
import socket
import threading
import time
from datetime import date
from email.message import EmailMessage

import pytest

from belege import kern, postfach, takt
from belege.postfach import ImapPostfach, PostfachAbbruch

SSL_ABBRUCH = "socket error: [SSL: BAD_LENGTH] bad length (_ssl.c:2428)"


def _roh(ordner: str, nr: int) -> bytes:
    m = EmailMessage()
    m["From"] = "Lieferant <rechnung@lieferant.example>"
    m["To"] = "info@maler.example"
    m["Subject"] = f"Rechnung {ordner} {nr}"
    m["Date"] = "Mon, 02 Nov 2026 10:00:00 +0000"
    m["Message-ID"] = f"<{ordner}-{nr}@lieferant.example>"
    m.set_content("Anbei die Rechnung.")
    m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="r.pdf")
    return m.as_bytes()


class Verbindung:
    """Eine IMAP-Verbindung, die nach `bricht_nach` Befehlen wie iCloud abbricht."""

    ordner = ["INBOX", "Kunden/A", "Kunden/B", "Kunden/C"]

    def __init__(self, bricht_nach: int | None = None, bei: str | None = None):
        self.bricht_nach = bricht_nach
        self.bei = bei
        self.befehle = 0
        self.tot = False
        self.aktuell = None
        self.abgemeldet = False

    def _befehl(self):
        if self.tot:
            raise imaplib.IMAP4.abort(SSL_ABBRUCH)
        self.befehle += 1
        if self.bricht_nach is not None and self.befehle > self.bricht_nach:
            self.tot = True
            raise imaplib.IMAP4.abort(SSL_ABBRUCH)

    def list(self):
        self._befehl()
        return "OK", [f'(\\HasNoChildren) "/" "{o}"'.encode() for o in self.ordner]

    def select(self, ordner, readonly=True):
        self._befehl()
        self.aktuell = ordner.strip('"')
        if self.bei and self.aktuell == self.bei:
            self.tot = True
            raise imaplib.IMAP4.abort(SSL_ABBRUCH)
        return "OK", [b"1"]

    def uid(self, befehl, *teile):
        self._befehl()
        if befehl == "search":
            return "OK", [b"1 2"]
        uid = teile[0].decode() if isinstance(teile[0], bytes) else str(teile[0])
        return "OK", [(b"1 (UID " + uid.encode() + b")", _roh(self.aktuell, int(uid))), b")"]

    def logout(self):
        if self.tot:
            raise imaplib.IMAP4.abort(SSL_ABBRUCH)  # wie auf der echten toten Verbindung
        self.abgemeldet = True

    def shutdown(self):
        self.abgemeldet = True


def _box(monkeypatch, verbindungen: list[Verbindung]):
    monkeypatch.setenv("PASSWORT_TEST", "x")
    box = ImapPostfach({"name": "test", "adresse": "info@icloud.com"})
    geoeffnet = []

    def oeffnen():
        v = verbindungen[len(geoeffnet)] if len(geoeffnet) < len(verbindungen) else Verbindung(bricht_nach=0)
        geoeffnet.append(v)
        return v

    monkeypatch.setattr(box, "_imap", oeffnen)
    monkeypatch.setattr(postfach.kern, "log", lambda *_a, **_k: None)
    return box, geoeffnet


def test_imap_verbindung_hat_zeitlimit(monkeypatch):
    monkeypatch.setenv("PASSWORT_TEST", "x")
    gesehen = {}

    class Fake:
        def __init__(self, host, port, **k):
            gesehen.update(k, host=host)

        def login(self, *a):
            return "OK", []

    monkeypatch.setattr("belege.postfach.imaplib.IMAP4_SSL", Fake)
    ImapPostfach({"name": "test", "adresse": "info@icloud.com"})._imap()
    assert gesehen["host"] == "imap.mail.me.com"
    assert gesehen["timeout"] == postfach.ZEITLIMIT


def test_ssl_abbruch_verbindet_neu_und_sucht_weiter(monkeypatch):
    """Nach dem Abbruch in Kunden/A geht es auf frischer Verbindung mit A, B, C weiter."""
    erste = Verbindung(bei="Kunden/A")
    zweite = Verbindung()
    box, geoeffnet = _box(monkeypatch, [erste, zweite])
    treffer = box.suchen(seit=date(2026, 10, 1), nur_anhang=True, max=500)
    betreffe = {t["betreff"] for t in treffer}
    assert len(geoeffnet) == 2
    assert {"Rechnung INBOX 1", "Rechnung Kunden/A 1", "Rechnung Kunden/B 2", "Rechnung Kunden/C 1"} <= betreffe
    assert len(treffer) == 8  # 4 Ordner × 2 Mails, nichts doppelt, nichts verloren
    assert zweite.abgemeldet


def test_abbruch_mitten_im_ordner_liefert_nichts_doppelt(monkeypatch):
    # list, select INBOX, search, fetch 2, fetch 1, select A, search, fetch 2 → Abbruch beim nächsten
    erste = Verbindung(bricht_nach=8)
    box, geoeffnet = _box(monkeypatch, [erste, Verbindung()])
    treffer = box.suchen(seit=date(2026, 10, 1), nur_anhang=True, max=500)
    ids = [t["betreff"] for t in treffer]
    assert len(geoeffnet) == 2
    assert len(ids) == len(set(ids)) == 8


def test_ordner_der_immer_abbricht_wird_uebersprungen(monkeypatch):
    box, geoeffnet = _box(monkeypatch, [Verbindung(bei="Kunden/B"), Verbindung(bei="Kunden/B"), Verbindung()])
    treffer = box.suchen(seit=date(2026, 10, 1), nur_anhang=True, max=500)
    assert len(geoeffnet) == 3
    assert not any("Kunden/B" in t["betreff"] for t in treffer)
    assert any("Kunden/C" in t["betreff"] for t in treffer)


def test_dauerhafter_abbruch_endet_mit_fehler_statt_zu_haengen(monkeypatch):
    box, geoeffnet = _box(monkeypatch, [Verbindung(bricht_nach=2) for _ in range(10)])
    with pytest.raises(PostfachAbbruch, match="bricht immer wieder ab"):
        box.suchen(seit=date(2026, 10, 1), nur_anhang=True, max=500)
    assert len(geoeffnet) == postfach.NEUVERBINDUNGEN + 1
    # Ein Abbruch ist kein „offline“: er soll als Fehler im Tagesbericht stehen.
    assert not kern.netzfehler(PostfachAbbruch("x"))


def test_logout_auf_toter_verbindung_ueberdeckt_nichts():
    v = Verbindung()
    v.tot = True
    postfach._abmelden(v)
    assert v.abgemeldet


def test_haengender_server_loest_zeitlimit_aus(monkeypatch):
    """Ein Server, der annimmt und dann schweigt: Ohne Zeitlimit wartete das ewig."""
    lauscher = socket.socket()
    lauscher.bind(("127.0.0.1", 0))
    lauscher.listen(1)
    offen = []
    threading.Thread(target=lambda: offen.append(lauscher.accept()), daemon=True).start()
    monkeypatch.setenv("PASSWORT_TEST", "x")
    monkeypatch.setattr(postfach, "ZEITLIMIT", 0.5)
    box = ImapPostfach({"name": "test", "adresse": "info@icloud.com", "imap": f"127.0.0.1:{lauscher.getsockname()[1]}"})
    box.imap_host, box.imap_port = "127.0.0.1", lauscher.getsockname()[1]
    beginn = time.monotonic()
    with pytest.raises(RuntimeError):
        box._imap()
    assert time.monotonic() - beginn < 5
    lauscher.close()


def test_rechnungslinks_hoeren_nach_abbruch_auf(repo, monkeypatch):
    from belege import quellen

    aufrufe = []

    class Kaputt:
        def suchen(self, **_k):
            aufrufe.append(_k)
            raise PostfachAbbruch("Verbindung zu imap.mail.me.com bricht immer wieder ab")

    assert list(quellen._link_funde(Kaputt(), "geschaeft", {}, date(2026, 10, 1), set(), False)) == []
    assert len(aufrufe) == 1


def _args():
    return argparse.Namespace(echt=True, tage=None, konto=None)


def _ereignisse(art):
    return [e for e in kern.ereignisse() if e["art"] == art]


def test_takt_mit_haengendem_socket_endet_mit_fehler(repo, monkeypatch):
    """Ein Schritt blockiert in recv(); die Laufzeitgrenze holt den Takt da heraus."""
    lauscher = socket.socket()
    lauscher.bind(("127.0.0.1", 0))
    lauscher.listen(1)

    def haengt(name, args):
        s = socket.create_connection(lauscher.getsockname())
        s.recv(1)  # der Server antwortet nie
        return "ok", []

    monkeypatch.setattr(takt, "_starter_auffrischen", lambda: False)
    monkeypatch.setattr(takt, "_schritt", haengt)
    monkeypatch.setattr(takt, "_max_minuten", lambda: 0.01)  # 0,6 Sekunden
    beginn = time.monotonic()
    assert takt._lauf(_args(), ("postfach", "handy"), "takt") is False
    assert time.monotonic() - beginn < 10
    fehler = _ereignisse("fehler")
    assert fehler and "abgebrochen" in fehler[-1]["text"] and fehler[-1]["daten"]["schritt"] == "postfach"
    assert not (repo / "arbeit" / ".takt.pid").exists()  # Sperre freigegeben
    lauscher.close()


def test_langer_takt_steht_im_tagesbericht(repo, monkeypatch):
    from belege import bericht

    uhr = iter([0.0, 75 * 60.0])
    monkeypatch.setattr(takt.time, "monotonic", lambda: next(uhr))
    monkeypatch.setattr(takt, "_starter_auffrischen", lambda: False)
    monkeypatch.setattr(takt, "_schritt", lambda name, args: ("ok", []))
    assert takt._lauf(_args(), ("postfach",), "takt") is True
    langsam = _ereignisse("langsam")
    assert langsam and langsam[0]["daten"]["minuten"] == 75
    text, _ = bericht.text_und_betreff(langsam)
    assert "Langsamer Takt" in text and "75 Minuten" in text


def test_normaler_takt_ohne_hinweis(repo, monkeypatch):
    monkeypatch.setattr(takt, "_starter_auffrischen", lambda: False)
    monkeypatch.setattr(takt, "_schritt", lambda name, args: ("ok", []))
    assert takt._lauf(_args(), ("postfach",), "takt") is True
    assert not _ereignisse("langsam")
