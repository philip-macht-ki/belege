import pytest
from belege import cli


def test_unbekannt():
    with pytest.raises(SystemExit) as e:
        cli.main(["unbekannt"])
    assert e.value.code == 2


def test_fehlendes_modul(monkeypatch):
    monkeypatch.setitem(cli.BEFEHLE, "x", ("fehlt", "befehl", ""))
    assert cli.main(["x"]) == 2
