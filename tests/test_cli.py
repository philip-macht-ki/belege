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


def test_ausnahme_wird_als_fehler_ereignis_gespeichert(repo, monkeypatch):
    monkeypatch.setitem(cli.BEFEHLE, "kaputt", ("kaputt", "befehl", ""))
    import importlib
    monkeypatch.setattr(importlib, "import_module", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cli.main(["kaputt"]) == 1
    from belege import kern
    assert kern.ereignisse()[-1]["art"] == "fehler"
