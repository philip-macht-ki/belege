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


def test_rechner_sperre_und_doppelordner(repo, capsys, monkeypatch):
    from belege import kern

    monkeypatch.setattr(kern.socket, "gethostname", lambda: "Mac-mini.local")
    p = repo / "konfig/belege.toml"
    p.write_text(p.read_text().replace('erlaubt = ""', 'erlaubt = "Mac-mini"', 1))
    (repo / "ablage/Betrieb/2026/10").mkdir(parents=True)
    (repo / "ablage/Betrieb/2026/10 (1)").mkdir()
    pruefen.befehl(Namespace())
    out = capsys.readouterr().out
    assert "GRUEN: Rechner-Sperre: nur Mac-mini legt ab" in out
    assert "GELB: Doppelte Ordner in der Ablage: Betrieb/2026/10 (1)" in out


def test_ohne_sperre_gelb(repo, capsys):
    pruefen.befehl(Namespace())
    assert "GELB: Rechner-Sperre nicht gesetzt" in capsys.readouterr().out


def test_papierpost_leer_ist_ok_und_fehlender_ordner_rot(repo, capsys):
    pruefen.befehl(Namespace())
    assert "GRUEN: Papierpost: keine Papierpost eingetragen" in capsys.readouterr().out
    konfig = repo / "konfig/belege.toml"
    konfig.write_text(konfig.read_text().replace('scan_ordner = ""', 'scan_ordner = "/nicht/vorhanden"'))
    assert pruefen.befehl(Namespace()) == 1
    assert "ROT: Papierpost-Ordner fehlt" in capsys.readouterr().out
