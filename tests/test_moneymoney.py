"""MoneyMoney-Export ohne MoneyMoney: osascript wird ersetzt, `belege monat` liest das Ergebnis."""
import plistlib
import shutil
from argparse import Namespace
from datetime import date, datetime, timedelta
from pathlib import Path

from belege import kern, moneymoney, monat, zeitplan

ECHT = Path(__file__).resolve().parents[1]


def _args(**werte):
    return Namespace(**{"echt": False, "testordner": None, **werte})


def _konfig(repo, konten: str, an: bool = True):
    (repo / "konfig" / "moneymoney.toml").write_text(
        f"an = {'true' if an else 'false'}\nmonate = 2\nwarnen_nach_tagen = 3\n" + konten,
        encoding="utf-8",
    )


GIRO = '[[konto]]\nkennung = "DE00 1234 5678 9000 0000 01"\nname = "Girokonto"\nformat = "bank"\n'
AMEX = '[[konto]]\nkennung = "XXX-12345"\nname = "Amex"\nformat = "amex"\n'


def _mm(monkeypatch, tag: date, abgerufen: datetime | None = None):
    """Ersetzt MoneyMoney: zwei Konten, je zwei gebuchte Umsätze und ein vorgemerkter."""
    abgerufen = abgerufen or kern.jetzt()
    konten = [
        {"accountNumber": "DE00123456789000000001", "uuid": "giro-uuid", "refreshTimestamp": abgerufen},
        {"accountNumber": "XXX-12345", "uuid": "amex-uuid", "refreshTimestamp": abgerufen},
    ]
    umsaetze = {
        "giro-uuid": [
            {"bookingDate": datetime.combine(tag, datetime.min.time()), "amount": -59.5, "name": "Pixelwerk Software GmbH",
             "purpose": "Abo", "booked": True, "currency": "EUR", "accountNumber": "DE11"},
            {"bookingDate": datetime.combine(tag, datetime.min.time()), "amount": 1200.0, "name": "Kunde AG",
             "purpose": "RE-2026-7", "booked": True, "currency": "EUR"},
            {"bookingDate": datetime.combine(tag, datetime.min.time()), "amount": -5.0, "name": "Vorgemerkt",
             "purpose": "", "booked": False},
        ],
        "amex-uuid": [
            {"bookingDate": datetime.combine(tag, datetime.min.time()), "amount": -23.8, "name": "Cafe Morgenrot",
             "purpose": "", "booked": True},
            {"bookingDate": datetime.combine(tag, datetime.min.time()), "amount": 10.0, "name": "Gutschrift Shop",
             "purpose": "", "booked": True},
        ],
    }
    aufrufe = []
    monkeypatch.setattr(moneymoney, "konten_mm", lambda: konten)

    def umsaetze_mm(konto, von, bis):
        aufrufe.append((konto, von, bis))
        return umsaetze[konto]

    monkeypatch.setattr(moneymoney, "umsaetze_mm", umsaetze_mm)
    return aufrufe


def test_aus_tut_nichts(repo, capsys):
    assert moneymoney.befehl(_args(echt=True)) == 0
    assert "MoneyMoney ist aus" in capsys.readouterr().out
    assert not list((repo / "auszuege").iterdir())


def test_trocken_schreibt_nichts(repo, monkeypatch, capsys):
    _konfig(repo, GIRO)
    _mm(monkeypatch, kern.jetzt().date())
    assert moneymoney.befehl(_args()) == 0
    assert "trocken: würde schreiben" in capsys.readouterr().out
    assert not list((repo / "auszuege").iterdir())


def test_echt_schreibt_je_konto_und_monat_und_monat_liest_beides(repo, monkeypatch):
    _konfig(repo, GIRO + AMEX)
    heute = kern.jetzt().date()
    aufrufe = _mm(monkeypatch, heute)
    assert moneymoney.befehl(_args(echt=True)) == 0
    # Gelesen über die UUID, nie über einen zusammengebauten Skripttext.
    assert {a[0] for a in aufrufe} == {"giro-uuid", "amex-uuid"}
    namen = sorted(p.name for p in (repo / "auszuege").iterdir())
    vormonat = (heute.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    assert namen == sorted([
        f"{heute:%Y-%m}_Girokonto_MoneyMoney.csv", f"{heute:%Y-%m}_Amex_MoneyMoney.csv",
        f"{vormonat}_Girokonto_MoneyMoney.csv", f"{vormonat}_Amex_MoneyMoney.csv",
    ])
    gelesen = monat.buchungen_aus(monat._auszuege(_args(), f"{heute:%Y-%m}"), f"{heute:%Y-%m}")
    betraege = sorted((b["name"], b["betrag"]) for b in gelesen)
    # Ausgaben negativ, Einnahmen positiv, auch bei der Kreditkarte; Vorgemerktes fehlt.
    assert betraege == [
        ("Cafe Morgenrot", -23.8), ("Gutschrift Shop", 10.0),
        ("Kunde AG", 1200.0), ("Pixelwerk Software GmbH", -59.5),
    ]


def test_zweiter_lauf_aendert_nichts(repo, monkeypatch, capsys):
    _konfig(repo, GIRO)
    _mm(monkeypatch, kern.jetzt().date())
    moneymoney.befehl(_args(echt=True))
    capsys.readouterr()
    moneymoney.befehl(_args(echt=True))
    assert "ok:" not in capsys.readouterr().out


def test_testordner_auch_wenn_noch_aus(repo, monkeypatch):
    _konfig(repo, GIRO, an=False)
    _mm(monkeypatch, kern.jetzt().date())
    test = repo / "mm-test"
    assert moneymoney.befehl(_args(echt=True, testordner=str(test))) == 0
    assert len(list(test.glob("*.csv"))) == 2
    assert not list((repo / "auszuege").iterdir())


def test_veraltetes_konto_kommt_in_den_bericht(repo, monkeypatch, capsys):
    _konfig(repo, GIRO)
    _mm(monkeypatch, kern.jetzt().date(), abgerufen=kern.jetzt() - timedelta(days=5))
    moneymoney.befehl(_args(echt=True))
    assert "zuletzt abgerufen" in capsys.readouterr().out
    assert any("zuletzt abgerufen" in e["text"] for e in kern.ereignisse())


def test_unbekannte_kennung_ist_fehler_ohne_datei(repo, monkeypatch):
    _konfig(repo, '[[konto]]\nkennung = "DE99"\nname = "Fremd"\nformat = "bank"\n')
    _mm(monkeypatch, kern.jetzt().date())
    assert moneymoney.befehl(_args(echt=True)) == 1
    assert not list((repo / "auszuege").iterdir())


def test_mehrdeutige_kennung_wird_nicht_geraten():
    konten = [{"accountNumber": "DE001111"}, {"accountNumber": "DE002111"}]
    assert moneymoney.finde(konten, "111") is None
    assert moneymoney.finde(konten, "DE00 1111")["accountNumber"] == "DE001111"


def test_moneymoney_gesperrt(repo, monkeypatch, capsys):
    _konfig(repo, GIRO)

    def gesperrt():
        raise RuntimeError("MoneyMoney ist gesperrt")

    monkeypatch.setattr(moneymoney, "konten_mm", gesperrt)
    assert moneymoney.befehl(_args(echt=True)) == 1
    assert "nicht erreichbar" in capsys.readouterr().out


def test_unbekanntes_format(repo, capsys):
    _konfig(repo, '[[konto]]\nkennung = "1"\nname = "X"\nformat = "pdf"\n')
    assert moneymoney.befehl(_args(echt=True)) == 2
    assert "Format" in capsys.readouterr().out


def test_amex_de_export_von_hand_wird_gelesen(repo):
    """Auch ohne MoneyMoney: der CSV-Export von amex.de, Belastungen positiv."""
    datei = repo / "auszuege" / "amex.csv"
    datei.write_text(
        "Datum,Beschreibung,Betrag,Erweiterte Details,Erscheint auf Ihrer Abrechnung als\n"
        '05.09.2026,PIXELWERK SOFTWARE,"59,50",,PIXELWERK\n'
        '06.09.2026,ZAHLUNG ERHALTEN,"-100,00",,\n',
        encoding="utf-8",
    )
    assert [(b["name"], b["betrag"]) for b in monat.buchungen(datei, "2026-09")] == [
        ("PIXELWERK SOFTWARE", -59.5), ("ZAHLUNG ERHALTEN", 100.0),
    ]


def test_bank_csv_mit_beschreibung_bleibt_unveraendert(repo):
    datei = repo / "auszuege" / "bank.csv"
    datei.write_text(
        "Buchungstag;Beguenstigter/Zahlungspflichtiger;Beschreibung;Betrag\n"
        "05.09.2026;Pixelwerk;Abo;-59,50\n",
        encoding="utf-8",
    )
    assert monat.buchungen(datei, "2026-09")[0]["betrag"] == -59.5


def test_zeitplan_nimmt_moneymoney_nur_wenn_an(repo):
    shutil.copytree(ECHT / "zeitplan", repo / "zeitplan")
    assert "moneymoney" not in zeitplan.laeufe()
    _konfig(repo, GIRO)
    assert zeitplan.laeufe()[-1] == "moneymoney"
    plist = plistlib.loads(zeitplan.plist_text("moneymoney").encode())
    assert [z["Hour"] for z in plist["StartCalendarInterval"]] == [7, 19]
    assert "belege moneymoney --echt" in plist["ProgramArguments"][2]


def test_vorlage_im_repo_ist_aus_und_ohne_konto():
    import tomllib

    cfg = tomllib.loads((ECHT / "konfig" / "moneymoney.toml").read_text(encoding="utf-8"))
    assert cfg["an"] is False and "konto" not in cfg


def test_konten_zeigt_kennungen_ohne_kontostand(repo, monkeypatch, capsys):
    monkeypatch.setattr(moneymoney, "konten_mm", lambda: [
        {"name": "Alle Konten", "group": True, "accountNumber": ""},
        {"name": "Girokonto", "accountNumber": "DE00123", "type": "Girokonto", "balance": [[1234.5, "EUR"]]},
    ])
    assert moneymoney.befehl(Namespace(ziel=["konten"], echt=False)) == 0
    aus = capsys.readouterr().out
    assert aus.strip() == "Girokonto | DE00123 | Girokonto"
    assert "1234" not in aus


def test_gleiche_buchungen_in_einer_datei_bleiben_dubletten_ueber_dateien_nicht(repo):
    kopf = "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag\n"
    zwei_kaffee = "05.09.2026;Cafe Morgenrot;;-3,50\n05.09.2026;Cafe Morgenrot;;-3,50\n"
    monatsdatei = repo / "auszuege" / "a_monat.csv"
    jahresdatei = repo / "auszuege" / "b_jahr.csv"
    monatsdatei.write_text(kopf + zwei_kaffee, encoding="utf-8")
    jahresdatei.write_text(kopf + zwei_kaffee + "06.09.2026;Pixelwerk;Abo;-59,50\n", encoding="utf-8")
    assert len(monat.buchungen_aus([monatsdatei], "2026-09")) == 2
    gelesen = monat.buchungen_aus([monatsdatei, jahresdatei], "2026-09")
    assert sorted(b["betrag"] for b in gelesen) == [-59.5, -3.5, -3.5]


def test_amex_csv_und_moneymoney_zaehlen_dieselbe_kartenbuchung_einmal(repo):
    # Philip, 28.10.2026: amex.de und MoneyMoney schreiben denselben Händler verschieden.
    kopf = "Datum,Beschreibung,Betrag\n"
    amex = repo / "auszuege" / "a_amex.csv"
    mm = repo / "auszuege" / "b_moneymoney.csv"
    amex.write_text(kopf + '14.09.2026,FACEBK *XD8YZ42FB4  DUBLIN,"321,68"\n', encoding="utf-8")
    mm.write_text(kopf + '14.09.2026,"Facebk *XD8YZ42FB4 Dublin Facebook Advertisi, UK","321,68"\n'
                  + '15.09.2026,GITHUB INC,"14,96"\n', encoding="utf-8")
    gelesen = monat.buchungen_aus([amex, mm], "2026-09")
    assert len(gelesen) == 2
    assert sorted(abs(b["betrag"]) for b in gelesen) == [14.96, 321.68]


def test_girokonto_und_karte_mit_gleichem_haendler_bleiben_zwei(repo):
    giro = repo / "auszuege" / "a_giro.csv"
    karte = repo / "auszuege" / "b_karte.csv"
    giro.write_text("Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag\n"
                    "14.09.2026;AMAZON EU;Bestellung 1;-19,99\n", encoding="utf-8")
    karte.write_text('Datum,Beschreibung,Betrag\n14.09.2026,AMAZON EU SARL,"19,99"\n', encoding="utf-8")
    assert len(monat.buchungen_aus([giro, karte], "2026-09")) == 2


def test_karte_mit_verschiedener_referenz_bleibt_zwei(repo):
    a = repo / "auszuege" / "a_amex.csv"
    b = repo / "auszuege" / "b_mm.csv"
    a.write_text('Datum,Beschreibung,Betrag\n14.09.2026,FACEBK *AAA111 DUBLIN,"10,00"\n', encoding="utf-8")
    b.write_text('Datum,Beschreibung,Betrag\n14.09.2026,Facebk *BBB222 Dublin,"10,00"\n', encoding="utf-8")
    assert len(monat.buchungen_aus([a, b], "2026-09")) == 2
