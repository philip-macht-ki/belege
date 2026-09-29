from argparse import Namespace
from belege import pruefen


def test_musterwerte_gelb(repo, capsys):
    pruefen.befehl(Namespace())
    assert "GELB: Betrieb: noch Musterwerte" in capsys.readouterr().out


def test_ablage_fehlt_rot(repo, capsys):
    (repo / "ablage").rmdir()
    assert pruefen.befehl(Namespace()) == 1
    assert "ROT: Ablageordner" in capsys.readouterr().out


def test_uebergabe_nicht_erlaubt(repo, capsys):
    p = repo / "konfig/belege.toml"
    p.write_text(
        p.read_text() + "\n[senden]\nerlaubt = []\n", encoding="utf8"
    ) if False else None
    t = p.read_text()
    t = t.replace('adresse = ""', 'adresse = "steuer@example"').replace(
        "erlaubt = []", 'erlaubt = ["andere@example"]'
    )
    p.write_text(t)
    assert pruefen.befehl(Namespace()) == 1
    assert "Übergabe-Adresse ist nicht erlaubt" in capsys.readouterr().out


def test_datev_ohne_pdf_rot(repo, capsys):
    p = repo / "konfig/belege.toml"
    t = (
        p.read_text()
        .replace('adresse = ""', 'adresse = "upload@datev.example"')
        .replace("erlaubt = []", 'erlaubt = ["upload@datev.example"]')
    )
    p.write_text(t)
    assert pruefen.befehl(Namespace()) == 1
    assert "DATEV-Format fehlt" in capsys.readouterr().out
