"""Linksuche über viele IMAP-Ordner in einem Durchlauf (iCloud mit mehreren hundert Ordnern)."""
from __future__ import annotations

import imaplib
from collections import Counter
from datetime import date
from email.message import EmailMessage

import pytest

from belege import postfach, quellen
from belege.postfach import ImapPostfach, PostfachAbbruch

WOERTER = ("Rechnung", "Invoice", "Receipt", "Beleg", "Quittung")


def _betreff(ordner: int, uid: int) -> str:
    # Mal ein Wort, mal zwei, mal keins: so prüfen wir die Auswahl je Wort.
    teile = [w for i, w in enumerate(WOERTER) if (uid + ordner) % (i + 2) == 0]
    return " ".join(teile) or "Hallo"


class Server:
    """Viele Ordner, jede Mail mit eigenem Datum; zählt die Befehle."""

    def __init__(self, ordner: int = 40, mails: int = 30, abbruch_bei: str | None = None):
        self.namen = ["INBOX"] + [f"Kunden/K{i:03d}" for i in range(1, ordner)]
        self.mails = mails
        self.befehle: Counter = Counter()
        self.abbruch_bei = abbruch_bei
        self.aktuell = ""
        self.tot = False
        self.leer: set[int] = set()  # Ordner ohne Post im Zeitfenster

    def _nr(self) -> int:
        return self.namen.index(self.aktuell)

    def list(self):
        self.befehle["list"] += 1
        return "OK", [f'(\\HasNoChildren) "/" "{n}"'.encode() for n in self.namen]

    def select(self, ordner, readonly=True):
        if self.tot:
            raise imaplib.IMAP4.abort("socket error: [SSL: BAD_LENGTH] bad length")
        self.befehle["select"] += 1
        self.aktuell = ordner.strip('"')
        if self.aktuell == self.abbruch_bei:
            self.abbruch_bei = None
            self.tot = True
            raise imaplib.IMAP4.abort("socket error: [SSL: BAD_LENGTH] bad length")
        return "OK", [b"1"]

    def uid(self, befehl, *teile):
        if befehl == "search":
            self.befehle["search"] += 1
            woerter = [teile[i + 1].lower() for i, t in enumerate(teile) if t == "TEXT"]
            if "OR" in teile:
                self.befehle["oder"] += 1
            if self._nr() in self.leer:
                return "OK", [b""]
            uids = [str(u) for u in range(1, self.mails + 1)
                    if any(w in _betreff(self._nr(), u).lower() for w in woerter)]
            return "OK", [" ".join(uids).encode()]
        self.befehle["fetch"] += 1
        uid = int(teile[0])
        m = EmailMessage()
        m["From"] = "Lieferant <info@lieferant.example>"
        m["Subject"] = _betreff(self._nr(), uid)
        # Datum quer über die Ordner verteilt, damit „die neuesten je Wort“ zählt.
        tag = 1 + (uid * 7 + self._nr() * 3) % 28
        m["Date"] = f"{tag:02d} Oct 2026 10:00:00 +0000"
        m["Message-ID"] = f"<{self._nr()}-{uid}@lieferant.example>"
        m.set_content("Ihre Rechnung finden Sie unter dem Link.")
        return "OK", [(b"1 (UID %d)" % uid, m.as_bytes()), b")"]

    def logout(self):
        if self.tot:
            raise imaplib.IMAP4.abort("tot")

    def shutdown(self):
        pass


@pytest.fixture
def box(monkeypatch):
    monkeypatch.setenv("PASSWORT_TEST", "x")
    monkeypatch.setattr(postfach.kern, "log", lambda *_a, **_k: None)
    return ImapPostfach({"name": "test", "adresse": "info@icloud.com"})


def _verbinden(monkeypatch, box, server):
    geoeffnet = []
    monkeypatch.setattr(box, "_imap", lambda: geoeffnet.append(1) or server)
    return geoeffnet


def test_ein_durchlauf_liefert_dasselbe_wie_wort_fuer_wort(monkeypatch, box):
    alt = Server()
    _verbinden(monkeypatch, box, alt)
    erwartet = set()
    for wort in WOERTER:
        erwartet |= {m["id"] for m in box.suchen(abfrage=wort, seit=date(2026, 10, 1))}

    neu = Server()
    geoeffnet = _verbinden(monkeypatch, box, neu)
    treffer = box.suchen_woerter(WOERTER, seit=date(2026, 10, 1))
    assert {m["id"] for m in treffer} == erwartet
    assert len(treffer) == len(erwartet)  # nichts doppelt

    # Eine Verbindung statt fünf, je Ordner ein SELECT statt fünf, jede Mail nur einmal geholt.
    assert len(geoeffnet) == 1
    assert neu.befehle["select"] == len(neu.namen) == alt.befehle["select"] / len(WOERTER)
    assert neu.befehle["fetch"] < alt.befehle["fetch"] * 0.6


def test_ordner_ohne_treffer_kostet_nur_eine_suche(monkeypatch, box):
    server = Server(ordner=300)
    server.leer = set(range(10, 300))  # wie bei iCloud: die meisten Ordner ohne neue Post
    _verbinden(monkeypatch, box, server)
    box.suchen_woerter(WOERTER, seit=date(2026, 10, 1))
    assert server.befehle["select"] == 300
    assert server.befehle["search"] == 300 + 10 * len(WOERTER)  # vorher 300 × 5 SELECT und SEARCH


def test_je_wort_hoechstens_max_neueste(monkeypatch, box):
    _verbinden(monkeypatch, box, Server(ordner=5, mails=60))
    treffer = box.suchen_woerter(["Rechnung"], seit=None, max=7)
    assert len(treffer) == 7
    alle = Server(ordner=5, mails=60)
    _verbinden(monkeypatch, box, alle)
    neueste = box.suchen(abfrage="Rechnung", max=7)
    assert {m["id"] for m in treffer} == {m["id"] for m in neueste}


def test_abbruch_im_durchlauf_verbindet_neu(monkeypatch, box):
    server = Server(ordner=10, abbruch_bei="Kunden/K004")
    geoeffnet = []

    def oeffnen():
        geoeffnet.append(1)
        server.tot = False
        return server

    monkeypatch.setattr(box, "_imap", oeffnen)
    treffer = box.suchen_woerter(WOERTER)
    assert len(geoeffnet) == 2
    assert any(m["id"].startswith("Kunden/K004:") for m in treffer)  # Ordner wiederholt


def test_wort_das_der_server_ablehnt_kippt_die_anderen_nicht(monkeypatch, box):
    server = Server(ordner=3)
    echte_uid = server.uid

    def uid(befehl, *teile):
        if befehl == "search" and "Beleg" in teile:
            raise imaplib.IMAP4.error("BAD")
        return echte_uid(befehl, *teile)

    server.uid = uid
    _verbinden(monkeypatch, box, server)
    treffer = box.suchen_woerter(WOERTER)
    andere = [w for w in WOERTER if w != "Beleg"]
    assert treffer
    assert all(any(w in m["betreff"] for w in andere) for m in treffer)


def test_linksuche_nutzt_einen_durchlauf(repo, monkeypatch):
    aufrufe = []

    class Box:
        def suchen_woerter(self, woerter, seit=None):
            aufrufe.append(tuple(woerter))
            return []

        def suchen(self, **_k):
            raise AssertionError("Wort-für-Wort-Suche darf nicht mehr laufen")

    assert list(quellen._link_funde(Box(), "geschaeft", {}, date(2026, 10, 1), set(), False)) == []
    assert len(aufrufe) == 1 and "Rechnung" in aufrufe[0]


def test_linksuche_nach_abbruch_ohne_fehler_weiter(repo, monkeypatch):
    class Box:
        def suchen_woerter(self, woerter, seit=None):
            raise PostfachAbbruch("bricht immer wieder ab")

    assert list(quellen._link_funde(Box(), "geschaeft", {}, date(2026, 10, 1), set(), False)) == []
