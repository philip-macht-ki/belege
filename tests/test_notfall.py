"""Tests für den Notfallordner (Modul bh8)."""
from __future__ import annotations

import argparse

from belege import notfall


def _args(**werte):
    grund = {"echt": False}
    grund.update(werte)
    return argparse.Namespace(**grund)


def test_notfall_schreibt_md_und_pdf(repo):
    code = notfall.befehl(_args(echt=True))
    assert code == 0
    ziel_md = repo / "ablage" / "Notfallordner" / "Notfallordner.md"
    ziel_pdf = repo / "ablage" / "Notfallordner" / "Notfallordner.pdf"
    assert ziel_md.exists()
    assert ziel_pdf.exists() and ziel_pdf.stat().st_size > 0
    inhalt = ziel_md.read_text(encoding="utf-8")
    assert "Ansprechpartner" in inhalt
    assert "Jonas Beispiel" in inhalt


def test_notfall_trocken_schreibt_nichts(repo):
    code = notfall.befehl(_args(echt=False))
    assert code == 0
    assert not (repo / "ablage" / "Notfallordner").exists()


def test_notfall_bricht_bei_passwortaehnlichem_feldnamen_ab(repo, capsys):
    toml = repo / "konfig" / "notfall.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[wlan]\npasswort = "geheim123"\n',
        encoding="utf-8",
    )
    code = notfall.befehl(_args(echt=True))
    assert code == 1
    assert not (repo / "ablage" / "Notfallordner").exists()
    assert "fehler" in capsys.readouterr().out.lower()


def test_notfall_bricht_bei_passwortaehnlichem_wert_ab(repo):
    toml = repo / "konfig" / "notfall.toml"
    zusatz = '\n[zugang_hinweis]\ntext = "Das Passwort steht im Tresor."\n'
    toml.write_text(toml.read_text(encoding="utf-8") + zusatz, encoding="utf-8")
    code = notfall.befehl(_args(echt=True))
    assert code == 1
    assert not (repo / "ablage" / "Notfallordner").exists()


def test_pruefe_keine_passwoerter_findet_nichts_im_musterordner(repo):
    from belege.kern import konfig

    assert notfall.pruefe_keine_passwoerter(konfig("notfall")) is None
