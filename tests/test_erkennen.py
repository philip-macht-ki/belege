import pytest

from belege import erkennen, postfach


@pytest.fixture
def netz(monkeypatch):
    monkeypatch.setattr(postfach, "_namensaufloesung_da", lambda: True)
    monkeypatch.setattr(postfach, "_ispdb", lambda domain: ("", ""))
    monkeypatch.setattr(erkennen, "_imap_antwortet", lambda host, port=993: False)
    monkeypatch.setattr(erkennen, "_smtp_antwortet", lambda host: "")

    def setze(mx):
        monkeypatch.setattr(postfach, "_mx", lambda domain: list(mx))

    return setze


def test_microsoft_privat_ohne_netz():
    e = erkennen.erkennen("Anna@Hotmail.de")
    assert e["weg"] == "microsoft" and "privat" in e["art"]


def test_microsoft_365_am_mx(netz):
    netz(["firma-de.mail.protection.outlook.com"])
    e = erkennen.erkennen("info@firma.de")
    assert e["weg"] == "microsoft" and "365" in e["art"] and "--admin-link" in e["hinweis"]


def test_outlook_als_programm_bei_kabelplus(netz):
    netz(["mx21.kabsi.at"])
    e = erkennen.erkennen("rechnungen@ktp.at")
    assert e["weg"] == "a" and "Kabelplus" in e["art"]
    assert e["imap_server"] == "imap.kabelplus.at:993"
    assert "benutzer" in e["hinweis"]


def test_bekannter_anbieter_ohne_mx():
    e = erkennen.erkennen("x@gmx.de")
    assert e["art"] == "GMX" and e["imap_server"] == "imap.gmx.net:993"


def test_ausprobiert_ist_unsicher_und_wird_eingetragen(netz, monkeypatch):
    netz(["mx.kleinhoster.example"])
    monkeypatch.setattr(erkennen, "_imap_antwortet", lambda host, port=993: host == "imap.kleinhoster.example")
    monkeypatch.setattr(erkennen, "_smtp_antwortet", lambda host: "smtp.kleinhoster.example:465" if host == "smtp.kleinhoster.example" else "")
    e = erkennen.erkennen("info@kunde.example")
    assert e["sicher"] is False and e["imap_server"] == "imap.kleinhoster.example:993"
    assert 'imap_server = "imap.kleinhoster.example:993"' in erkennen.naechster_schritt(e, "geschaeft")


def test_unbekannt_sagt_was_zu_tun_ist(netz):
    netz([])
    e = erkennen.erkennen("info@nirgends.example")
    assert e["art"].startswith("unbekannt") and "imap_server" in e["hinweis"]


def test_keine_adresse():
    with pytest.raises(ValueError):
        erkennen.erkennen("outlook")


def test_befehl_gibt_naechsten_schritt_aus(capsys):
    class A:
        ziel = ["anna@outlook.com"]
        konto = "privat"

    assert erkennen.befehl(A()) == 0
    assert "uv run belege anmelden --microsoft privat" in capsys.readouterr().out


def test_imap_meldet_mit_benutzer_an(monkeypatch):
    monkeypatch.setattr(postfach, "passwort", lambda name: "geheim")
    gesehen = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        def login(self, benutzer, pw):
            gesehen.append(benutzer)

    monkeypatch.setattr("belege.postfach.imaplib.IMAP4_SSL", Fake)
    konto = {"name": "haus", "adresse": "rechnungen@ktp.at", "imap_server": "imap.kabelplus.at:993", "smtp_server": "mail.kabelplus.at:465"}
    postfach.ImapPostfach({**konto, "benutzer": "x1234a00"})._imap()
    postfach.ImapPostfach(konto)._imap()
    assert gesehen == ["x1234a00", "rechnungen@ktp.at"]


def test_hoster_nur_an_punktgrenze():
    assert postfach.hoster_passt("smx01.a1.net", "a1.net")
    assert not postfach.hoster_passt("mail.xa1.net", "a1.net")
    assert not postfach.hoster_passt("mx2.evil1blu.de", "1blu.de")
    assert postfach.hoster_passt("mx00.ionos.de", "ionos.")
    assert postfach.hoster_passt("mx.kundenserver.de", "kundenserver.de")


def test_firmendomain_mit_live_ist_nicht_privat(netz):
    netz([])
    assert erkennen.erkennen("info@live.firma.de")["weg"] == "a"
    assert erkennen.erkennen("anna@hotmail.co.uk")["weg"] == "microsoft"


def test_kaputte_domain_ist_keine_adresse():
    with pytest.raises(ValueError):
        erkennen.erkennen("a@foo..de")
