import os
import sys
import types
from argparse import Namespace
from datetime import date
from pathlib import Path

from belege import takt
from belege.kern import Ergebnis
from belege.typen import Fund


def _falsche_module(monkeypatch, handy_kaputt=False, ergebnisse=None):
    erledigt = []
    quellen = types.ModuleType("belege.quellen")
    fund_a = Fund(
        Path("a.pdf"),
        "postfach",
        "a.pdf",
        date(2026, 9, 1),
        mail={"konto": "geschaeft", "id": "m1"},
    )
    fund_b = Fund(
        Path("b.pdf"),
        "postfach",
        "b.pdf",
        date(2026, 9, 1),
        mail={"konto": "geschaeft", "id": "m1"},
    )
    quellen.postfach_funde = lambda konto, tage: [fund_a, fund_b]

    def handy():
        if handy_kaputt:
            raise RuntimeError("kaputt")
        return []

    quellen.handy_funde = handy
    quellen.mail_erledigt = lambda konto, mail_id, echt: erledigt.append(mail_id)
    verarbeiten = types.ModuleType("belege.verarbeiten")
    folge = iter(ergebnisse or [Ergebnis("ok"), Ergebnis("ok")])
    verarbeiten.verarbeite = lambda fund, echt: next(folge)
    waechter = types.ModuleType("belege.waechter")
    waechter.aufgerufen = []
    waechter.befehl = lambda args: waechter.aufgerufen.append(True) or 0
    monkeypatch.setitem(sys.modules, "belege.quellen", quellen)
    monkeypatch.setitem(sys.modules, "belege.verarbeiten", verarbeiten)
    monkeypatch.setitem(sys.modules, "belege.waechter", waechter)
    return erledigt, waechter


def test_fehler_in_einem_schritt_stoppt_die_anderen_nicht(repo, monkeypatch, capsys):
    _, waechter = _falsche_module(monkeypatch, handy_kaputt=True)
    assert takt.befehl(Namespace(echt=False, tage=None, konto=None)) == 0
    ausgabe = capsys.readouterr().out
    assert "handy: fehler: kaputt" in ausgabe
    assert waechter.aufgerufen


def test_mail_erst_erledigt_wenn_alle_anhaenge_gut(repo, monkeypatch):
    erledigt, _ = _falsche_module(
        monkeypatch, ergebnisse=[Ergebnis("ok"), Ergebnis("fehler", "x")]
    )
    takt.quelle_abarbeiten("postfach", Namespace(echt=True, tage=None, konto=None))
    assert erledigt == []
    erledigt, _ = _falsche_module(monkeypatch)
    takt.quelle_abarbeiten("postfach", Namespace(echt=True, tage=None, konto=None))
    assert erledigt == ["m1"]


def test_sperre(repo, capsys):
    (repo / "arbeit" / ".takt.pid").write_text(str(os.getpid()))
    assert takt.befehl(Namespace(echt=False, tage=None, konto=None)) == 0
    assert "schon aktiv" in capsys.readouterr().out
