import pytest
from belege import cli


def test_unbekannt():
    with pytest.raises(SystemExit) as e:
        cli.main(["unbekannt"])
    assert e.value.code == 2


def test_fehlendes_modul(monkeypatch):
    monkeypatch.setitem(cli.BEFEHLE, "x", ("fehlt", "befehl", ""))
    assert cli.main(["x"]) == 2


def test_rechner_sperre_bricht_echten_lauf_ab(repo, monkeypatch, capsys):
    from belege import cli, kern

    monkeypatch.setattr(kern.socket, "gethostname", lambda: "MacBook-Air")
    p = repo / "konfig/belege.toml"
    p.write_text(p.read_text().replace('erlaubt = ""', 'erlaubt = "Mac-mini"', 1))
    assert cli.main(["takt", "--echt"]) == 0
    assert "Rechner-Sperre" in capsys.readouterr().out
