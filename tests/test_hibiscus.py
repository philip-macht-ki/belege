"""Hibiscus-XML-RPC bleibt lokal, lesend und erzeugt MoneyMoney-kompatible CSVs."""
from argparse import Namespace
import shutil
from pathlib import Path
import pytest

from belege import hibiscus, kern, monat, zeitplan


def _args(**werte):
    return Namespace(**{"echt": False, "testordner": None, "ziel": [], **werte})


def _konfig(repo, konten, an=True):
    (repo / "konfig" / "hibiscus.toml").write_text(
        f"an = {'true' if an else 'false'}\nmonate = 2\n" + konten, encoding="utf-8"
    )


GIRO = '[[konto]]\nkennung = "DE00 1234"\nname = "Girokonto"\nformat = "bank"\n'
KARTE = '[[konto]]\nkennung = "12345"\nname = "Karte"\nformat = "amex"\n'


class Server:
    def __init__(self, heute):
        self.heute = heute
        self.aufrufe = []
        self.hibiscus = self
        self.xmlrpc = self
        self.konto = self
        self.umsatz = self

    def find(self):
        self.aufrufe.append("find")
        return [{"id": 1, "iban": "DE001234", "bezeichnung": "Giro", "waehrung": "EUR"}, {"id": 2, "kontonummer": "12345", "bezeichnung": "Karte", "waehrung": "EUR"}]

    def list(self, optionen):
        self.aufrufe.append(optionen)
        return [
            {"datum": self.heute.strftime("%d.%m.%Y"), "valuta": self.heute.strftime("%d.%m.%Y"), "betrag": "-59,50", "empfaenger_name": "Pixelwerk", "zweck": "Abo", "art": "Lastschrift"},
            {"datum": self.heute.strftime("%d.%m.%Y"), "betrag": "10,00", "empfaenger_name": "Gutschrift", "zweck": ""},
        ]


def _xmlrpc(monkeypatch, heute):
    server = Server(heute)
    monkeypatch.setattr(hibiscus, "passwort", lambda: "nie-ausgeben")
    monkeypatch.setattr(hibiscus.xmlrpc.client, "ServerProxy", lambda url, **werte: server)
    return server


def test_echt_schreibt_bank_und_kartenformat(repo, monkeypatch):
    _konfig(repo, GIRO + KARTE)
    heute = kern.jetzt().date()
    server = _xmlrpc(monkeypatch, heute)
    assert hibiscus.befehl(_args(echt=True)) == 0
    assert server.aufrufe[0] == "find"
    assert all(isinstance(a, dict) and set(a) == {"konto_id", "datum:min", "datum:max"} for a in server.aufrufe[1:])
    giro = (repo / "auszuege" / f"{heute:%Y-%m}_Girokonto_Hibiscus.csv").read_text(encoding="utf-8-sig")
    karte = (repo / "auszuege" / f"{heute:%Y-%m}_Karte_Hibiscus.csv").read_text(encoding="utf-8-sig")
    assert '"-59,50"' in giro
    assert "59,50" in karte  # Kreditkartenexport: Belastungen positiv
    buchungen = monat.buchungen_aus([repo / "auszuege" / f"{heute:%Y-%m}_Karte_Hibiscus.csv"], f"{heute:%Y-%m}")
    assert [b["betrag"] for b in buchungen] == [-59.5, 10.0]


def test_trocken_und_aus_schreiben_nichts(repo, monkeypatch, capsys):
    _konfig(repo, GIRO, an=False)
    _xmlrpc(monkeypatch, kern.jetzt().date())
    assert hibiscus.befehl(_args()) == 0
    assert "Hibiscus ist aus" in capsys.readouterr().out
    assert not list((repo / "auszuege").iterdir())
    _konfig(repo, GIRO)
    assert hibiscus.befehl(_args()) == 0
    assert not list((repo / "auszuege").iterdir())


def test_fehler_und_passwort_bleiben_verdeckt(repo, monkeypatch, capsys):
    _konfig(repo, GIRO)
    monkeypatch.setattr(hibiscus, "passwort", lambda: "sehr-geheim")
    monkeypatch.setattr(hibiscus, "konten_hibiscus", lambda geheim: (_ for _ in ()).throw(hibiscus.HibiscusFehler("Jameica ist nicht erreichbar.")))
    assert hibiscus.befehl(_args(echt=True)) == 1
    ausgabe = capsys.readouterr().out
    assert "Jameica ist nicht erreichbar" in ausgabe
    assert "sehr-geheim" not in ausgabe


def test_falsches_passwort_hat_klartext_ohne_geheimnis(monkeypatch):
    geheim = "nicht-ausgeben"
    monkeypatch.setattr(hibiscus, "verbindung", lambda wert: (_ for _ in ()).throw(hibiscus.xmlrpc.client.ProtocolError(hibiscus.URL, 401, "Unauthorized", {})))
    with pytest.raises(hibiscus.HibiscusFehler, match="Master-Passwort"):
        hibiscus.konten_hibiscus(geheim)


def test_zertifikat_nur_fuer_festen_loopback_endpunkt(monkeypatch):
    aufruf = {}

    def proxy(url, **werte):
        aufruf["url"] = url
        aufruf.update(werte)
        return object()

    monkeypatch.setattr(hibiscus.xmlrpc.client, "ServerProxy", proxy)
    hibiscus.verbindung("x")
    assert aufruf["url"] == "https://127.0.0.1:8080/xmlrpc/"
    assert aufruf["transport"].context.verify_mode.name == "CERT_NONE"


def test_zeitplan_nimmt_hibiscus_nur_wenn_an(repo):
    echt = Path(__file__).resolve().parents[1]
    shutil.copytree(echt / "zeitplan", repo / "zeitplan")
    _konfig(repo, GIRO, an=False)
    assert "hibiscus" not in zeitplan.laeufe()
    _konfig(repo, GIRO)
    assert zeitplan.laeufe()[-1] == "hibiscus"
    assert "belege hibiscus --echt" in zeitplan.plist_text("hibiscus")
