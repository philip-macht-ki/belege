"""Postfach-Agent: jede Zusage aus dem Plan als eigener Test, ohne Modell und Netz."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from belege import postfach_agent as aufraeumen, bericht, kern, takt

BERLIN = kern.zone()


def _args(echt=False, ziel=None, tage=None):
    return argparse.Namespace(echt=echt, ziel=ziel or [], tage=tage)


def _toml(repo: Path, ersetzen: dict[str, str]) -> None:
    datei = repo / "konfig" / "belege.toml"
    text = datei.read_text(encoding="utf-8")
    for alt, neu in ersetzen.items():
        assert alt in text, alt
        text = text.replace(alt, neu, 1)
    datei.write_text(text, encoding="utf-8")


def _einschalten(repo: Path, an: bool = False, max_je_lauf: int = 200) -> None:
    ersetzen = {"aufraeumen = false": "aufraeumen = true",
                "max_je_lauf = 200": f"max_je_lauf = {max_je_lauf}"}
    if an:
        ersetzen["\nan = false\nzeiten"] = "\nan = true\nzeiten"
    _toml(repo, ersetzen)


def _regeln(repo: Path, *zeilen: str) -> None:
    (repo / "konfig" / "postfach-regeln.md").write_text(
        "# Regeln\n\nErklärung ohne Strich.\n\n" + "\n".join(zeilen) + "\n", encoding="utf-8"
    )


_ZAEHLER = iter(range(10_000))


def _mail(repo: Path, von: str, betreff: str, *, newsletter=False, anhang=False, name=None,
          datum="Thu, 29 Oct 2026 08:00:00 +0100") -> str:
    """Legt eine .eml im Muster-Postfach ab; jüngere Dateien kommen zuerst."""
    nummer = next(_ZAEHLER)
    mail = EmailMessage()
    mail["From"] = von
    mail["To"] = "mara@studio-beispiel.example"
    mail["Subject"] = betreff
    mail["Date"] = datum
    if newsletter:
        mail["List-Unsubscribe"] = "<mailto:ab@liste.example>"
    mail.set_content("Text, den der Agent nie liest.")
    if anhang:
        mail.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="rechnung.pdf")
    datei = repo / "beispiel/erzeugt/postfach" / (name or f"m{nummer:04d}.eml")
    datei.write_bytes(mail.as_bytes())
    zeit = 1_800_000_000 + nummer
    os.utime(datei, (zeit, zeit))
    return datei.name


def _jsonl(datei: Path) -> list[dict]:
    if not datei.exists():
        return []
    return [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines() if z.strip()]


def _aktionen(repo):
    return _jsonl(repo / "arbeit" / "postfach-ordner-aktionen.jsonl")


def _protokoll(repo):
    return _jsonl(repo / "arbeit" / "aufraeumen.jsonl")


@pytest.fixture
def still(monkeypatch):
    """Keine macOS-Mitteilung, kein Versand; beides wird mitgeschrieben."""
    gesendet, mitteilungen, entwuerfe = [], [], []
    monkeypatch.setattr(aufraeumen, "_mitteilung", lambda satz: mitteilungen.append(satz))
    monkeypatch.setattr("belege.senden.senden", lambda *a, **k: gesendet.append(a) or kern.Ergebnis("ok"))

    def _entwurf(an, betreff, text, anhaenge, echt, konto=None):
        entwuerfe.append((an, betreff, text, echt))
        return kern.Ergebnis("ok", f"Entwurf an {an} angelegt.")

    monkeypatch.setattr("belege.senden.entwurf", _entwurf)
    return gesendet, mitteilungen, entwuerfe


# 1. Parser


def test_parser_kennt_alle_bedingungen_und_aktionen(tmp_path):
    datei = tmp_path / "r.md"
    datei.write_text(
        "Text\n"
        "    - eingerückt ist keine Regel -> archivieren\n"
        "- von: a@firma.example -> archivieren\n"
        "- von: @firma.example → ordner: Kunden\n"
        "- betreff: \"Müller und Partner\" -> label: Kanzlei\n"
        "- newsletter und anhang -> entwurf: Danke, ich melde mich.\n"
        "- von: Bank -> melden\n"
        "- betreff: dringend -> melden,sofort\n"
        "- sonst -> Liegen lassen\n",
        encoding="utf-8",
    )
    regeln, fehler = aufraeumen.regeln(datei)
    assert fehler == []
    assert [(r["aktion"], r["wert"]) for r in regeln] == [
        ("archivieren", ""), ("ordner", "Kunden"), ("label", "Kanzlei"),
        ("entwurf", "Danke, ich melde mich."), ("melden", ""), ("melden, sofort", ""), ("liegen lassen", ""),
    ]
    assert regeln[0]["nr"] == 3


def test_erste_passende_regel_gewinnt_und_bedingungen_greifen(tmp_path):
    datei = tmp_path / "r.md"
    datei.write_text(
        "- von: @firma.example und anhang -> label: A\n"
        "- betreff: \"Müller und Partner\" -> label: B\n"
        "- newsletter -> label: C\n"
        "- von: chef -> label: D\n"
        "- sonst -> archivieren\n",
        encoding="utf-8",
    )
    regeln, _ = aufraeumen.regeln(datei)

    def treffer(**mail):
        basis = {"von": "x@andere.example", "von_name": "", "betreff": "", "anhaenge": [], "newsletter": False}
        return aufraeumen.passende_regel({**basis, **mail}, regeln)["wert"] or "archivieren"

    assert treffer(von="a@sub.firma.example", anhaenge=["r.pdf"]) == "A"
    assert treffer(von="a@firma.example") == "archivieren"  # ohne Anhang greift A nicht
    assert treffer(von="a@nichtfirma.example", anhaenge=["r.pdf"]) == "archivieren"
    assert treffer(betreff="Post von Müller und Partner") == "B"
    assert treffer(newsletter=True) == "C"
    assert treffer(von_name="Der Chef") == "D"


# 2. Parser-Fehler


@pytest.mark.parametrize("zeile, teil", [
    ("- von: x -> wegwerfen", "unbekannte Aktion"),
    ("- absender: x -> archivieren", "unbekannte Bedingung"),
    ("- von: x archivieren", "Bedingung -> Aktion"),
    ("- von: x -> entwurf:   ", "entwurf"),
])
def test_parser_fehler_mit_zeilennummer(tmp_path, zeile, teil):
    datei = tmp_path / "r.md"
    datei.write_text(f"# Kopf\n\n{zeile}\n", encoding="utf-8")
    regeln, fehler = aufraeumen.regeln(datei)
    assert regeln == [] or len(fehler) == 1
    assert len(fehler) == 1 and fehler[0].startswith("Zeile 3") and teil in fehler[0]


# 3. Fehlerhafte Datei: kein Handeln


def test_fehlerhafte_regeldatei_handelt_gar_nicht(repo, still, capsys):
    _einschalten(repo)
    _regeln(repo, "- newsletter -> archivieren", "- von: x -> wegwerfen")
    _mail(repo, "news@liste.example", "Neu", newsletter=True)
    assert aufraeumen.befehl(_args(echt=True)) == 1
    assert "Zeile" in capsys.readouterr().out
    assert _aktionen(repo) == [] and _protokoll(repo) == []
    assert not (repo / "arbeit" / "gesehen.json").exists()
    assert aufraeumen.befehl(_args(ziel=["regeln"])) == 1


# 4. Trocken


def test_trocken_zeigt_nur_und_speichert_nichts(repo, still, capsys):
    _einschalten(repo)
    _regeln(repo, "- newsletter -> archivieren", "- sonst -> liegen lassen")
    _mail(repo, "news@liste.example", "Angebote", newsletter=True)
    assert aufraeumen.befehl(_args()) == 0
    aus = capsys.readouterr().out
    assert "würde archivieren: news@liste.example – Angebote" in aus
    for name in ("aufraeumen.jsonl", "gesehen.json", "postfach-ordner-aktionen.jsonl"):
        assert not (repo / "arbeit" / name).exists(), name
    assert not (repo / "arbeit" / "ereignisse").exists()


# 5. Echt + 6. nur einmal


def test_echt_handelt_protokolliert_und_merkt_sich_jede_mail(repo, still):
    _einschalten(repo)
    _regeln(repo, "- newsletter -> archivieren", "- von: @kunde.example -> ordner: Kunden",
            "- betreff: Termin -> label: Termine", "- sonst -> liegen lassen")
    a = _mail(repo, "news@liste.example", "Angebote", newsletter=True)
    b = _mail(repo, "max@kunde.example", "Auftrag")
    c = _mail(repo, "x@praxis.example", "Termin morgen")
    d = _mail(repo, "freund@privat.example", "Hallo")
    assert aufraeumen.befehl(_args(echt=True)) == 0
    assert sorted((z["id"], z["aktion"], z["name"]) for z in _aktionen(repo)) == sorted(
        [(a, "archivieren", ""), (b, "ordner", "Kunden"), (c, "label", "Termine")]
    )
    protokoll = _protokoll(repo)
    assert {z["id"] for z in protokoll} == {a, b, c, d}
    felder = {"zeit", "konto", "id", "von", "betreff", "regel", "aktion", "ziel", "ergebnis"}
    assert all(set(z) == felder for z in protokoll)
    gesehen = json.loads((repo / "arbeit" / "gesehen.json").read_text())
    assert set(gesehen["aufraeumen:geschaeft"]["ids"]) == {a, b, c, d}

    assert aufraeumen.befehl(_args(echt=True)) == 0
    assert len(_aktionen(repo)) == 3 and len(_protokoll(repo)) == 4


# 7. Grenze je Lauf


def test_max_je_lauf_arbeitet_in_portionen_ohne_mails_zu_verlieren(repo, still, monkeypatch):
    _um(monkeypatch, 29, 10)
    _einschalten(repo, max_je_lauf=2)
    _regeln(repo, "- sonst -> archivieren")
    # Ältere Mails dürfen nicht aus dem Zeitfenster fallen, wenn der erste Lauf nur zwei schafft.
    ids = [_mail(repo, f"p{i}@liste.example", f"Nr {i}", datum="Mon, 26 Oct 2026 08:00:00 +0100") for i in range(3)]
    ids += [_mail(repo, f"q{i}@liste.example", f"Neu {i}") for i in range(2)]
    for erwartet in (2, 4, 5, 5):
        aufraeumen.befehl(_args(echt=True))
        assert len(_aktionen(repo)) == erwartet
    assert sorted(z["id"] for z in _aktionen(repo)) == sorted(ids)


# 8. Ausgeschlossen und eigene Mails


def test_ausgeschlossene_und_eigene_mails_bleiben_unberuehrt(repo, still):
    _einschalten(repo)
    regeln_toml = repo / "konfig" / "regeln.toml"
    regeln_toml.write_text(
        regeln_toml.read_text(encoding="utf-8").replace("ausschluss = []", 'ausschluss = ["arztpraxis"]'),
        encoding="utf-8",
    )
    _regeln(repo, "- sonst -> archivieren")
    _mail(repo, "befund@arztpraxis.example", "Ihr Befund")
    _mail(repo, "mara@studio-beispiel.example", "Belege: Tagesbericht")
    normal = _mail(repo, "shop@laden.example", "Bestellung")
    aufraeumen.befehl(_args(echt=True))
    assert [z["id"] for z in _aktionen(repo)] == [normal]
    assert [z["id"] for z in _protokoll(repo)] == [normal]


# 9. Entwurf, nie senden


def test_entwurf_mit_re_betreff_und_regeltext_ohne_senden(repo, still, monkeypatch):
    gesendet, _, entwuerfe = still
    from belege import postfach

    def nie(*a, **k):
        raise AssertionError("_senden darf nie aufgerufen werden")

    for klasse in (postfach.OrdnerPostfach, postfach.ImapPostfach, postfach.GmailPostfach):
        monkeypatch.setattr(klasse, "_senden", nie)
    _einschalten(repo)
    _regeln(repo, "- von: @praxis.example -> entwurf: Danke, ich melde mich bis Freitag.", "- sonst -> liegen lassen")
    _mail(repo, "Termine <termine@praxis.example>", "Terminanfrage")
    _mail(repo, "info@praxis.example", "Re: Rückfrage")
    aufraeumen.befehl(_args(echt=True))
    assert sorted(entwuerfe) == sorted([
        ("termine@praxis.example", "Re: Terminanfrage", "Danke, ich melde mich bis Freitag.", True),
        ("info@praxis.example", "Re: Rückfrage", "Danke, ich melde mich bis Freitag.", True),
    ])
    assert gesendet == [] and _aktionen(repo) == []


# 10. melden, sofort


def test_melden_sofort_nur_an_eigene_adresse_ohne_betrag(repo, still):
    gesendet, mitteilungen, _ = still
    _einschalten(repo)
    _regeln(repo, "- betreff: Mahnung -> melden, sofort", "- betreff: Info -> melden")
    _mail(repo, "inkasso@firma.example", "Mahnung über 120,50 €")
    _mail(repo, "info@firma.example", "Info zum Vertrag")
    aufraeumen.befehl(_args(echt=True))
    assert len(gesendet) == 1 and len(mitteilungen) == 1
    an, betreff = gesendet[0][0], gesendet[0][1]
    assert an == bericht.empfaenger() == "mara@studio-beispiel.example"
    assert betreff.startswith("Belege-Postfach:") and "€" not in betreff and "120" not in betreff
    assert _aktionen(repo) == []


# 11. Vorschlag


def test_vorschlag_schreibt_uebersicht_und_aendert_nichts(repo, still, capsys):
    _einschalten(repo)
    _regeln(repo, "- sonst -> liegen lassen")
    for _ in range(3):
        _mail(repo, "news@liste.example", "Wochenbrief | Neu", newsletter=True)
    _mail(repo, "noreply@dienst.example", "Dein Login")
    _mail(repo, "buchhaltung@lieferant.example", "Rechnung 4711", anhang=True)
    for name in ("anna", "ben", "cora"):
        _mail(repo, f"{name}@kunde.example", "Projekt")
    _mail(repo, "freund@privat.example", "Hallo")
    assert aufraeumen.befehl(_args(ziel=["vorschlag"], tage=28)) == 0
    text = (repo / "arbeit" / "postfach-vorschlag.md").read_text(encoding="utf-8")
    assert "Mails gesamt: 9" in text and "Newsletter: 33 %" in text
    assert "- von: news@liste.example -> archivieren" in text
    assert "- von: noreply@dienst.example -> archivieren" in text
    assert "- von: buchhaltung@lieferant.example -> ordner: Belege" in text
    assert "Beleg-Agent" in text
    assert "- von: @kunde.example -> liegen lassen" in text
    assert "- von: anna@kunde.example" not in text
    assert "- von: freund@privat.example -> liegen lassen" in text
    assert "Wochenbrief \\| Neu" in text
    assert _aktionen(repo) == [] and _protokoll(repo) == []
    assert not (repo / "arbeit" / "gesehen.json").exists()


# 12. Konto ohne Schalter


def test_konto_ohne_aufraeumen_wird_nicht_angefasst(repo, still, capsys):
    _regeln(repo, "- sonst -> archivieren")
    _mail(repo, "shop@laden.example", "Bestellung")
    assert aufraeumen.befehl(_args(echt=True)) == 0
    aufraeumen.befehl(_args(ziel=["vorschlag"]))
    assert _aktionen(repo) == [] and _protokoll(repo) == []
    assert "Mails gesamt: 0" in (repo / "arbeit" / "postfach-vorschlag.md").read_text(encoding="utf-8")


# 13. Fällig


def _um(monkeypatch, tag, stunde, minute=0):
    monkeypatch.setattr(kern, "jetzt", lambda: datetime(2026, 10, tag, stunde, minute, tzinfo=BERLIN))


def test_faellig_je_termin_genau_einmal_und_nachholen(monkeypatch):
    zeiten = ["07:30", "17:30"]
    _um(monkeypatch, 29, 7, 0)
    assert not aufraeumen.faellig("2026-10-28T17:31:00+01:00", zeiten)
    _um(monkeypatch, 29, 7, 45)
    assert aufraeumen.faellig("2026-10-28T17:31:00+01:00", zeiten)
    assert not aufraeumen.faellig("2026-10-29T07:46:00+01:00", zeiten)
    # Mac war über den Abendtermin zu: am Morgen danach genau ein Lauf.
    _um(monkeypatch, 30, 6, 0)
    assert aufraeumen.faellig("2026-10-29T08:00:00+01:00", zeiten)
    assert not aufraeumen.faellig("2026-10-30T06:00:00+01:00", zeiten)


# 14. Takt


def test_takt_ohne_an_hat_keinen_aufraeumschritt(repo, monkeypatch):
    schritte = []
    monkeypatch.setattr(takt, "_lauf", lambda args, s, sperre: schritte.append(s) or True)
    takt.befehl(_args())
    assert "aufraeumen" not in schritte[0]
    assert takt._schritt("aufraeumen", _args())[0] == "aus"


def test_takt_mit_an_laeuft_je_termin_einmal_und_trocken_ohne_stand(repo, still, monkeypatch):
    _einschalten(repo, an=True)
    _regeln(repo, "- sonst -> archivieren")
    _mail(repo, "shop@laden.example", "Bestellung")
    schritte = []
    monkeypatch.setattr(takt, "_lauf", lambda args, s, sperre: schritte.append(s) or True)
    takt.befehl(_args())
    assert schritte[0][-1] == "aufraeumen"

    _um(monkeypatch, 29, 8)
    assert takt._schritt("aufraeumen", _args())[0] == "ok"
    assert not (repo / "arbeit" / "gesehen.json").exists()
    assert takt._schritt("aufraeumen", _args(echt=True))[0] == "ok"
    assert len(_aktionen(repo)) == 1
    _mail(repo, "shop@laden.example", "Noch eine Bestellung")
    takt._schritt("aufraeumen", _args(echt=True))
    assert len(_aktionen(repo)) == 1  # 17:30 ist noch nicht erreicht
    _um(monkeypatch, 29, 17, 31)
    takt._schritt("aufraeumen", _args(echt=True))
    assert len(_aktionen(repo)) == 2


# 15. Bericht


def test_bericht_zeigt_klartext_und_braucht_dich(repo):
    liste = [{"art": "aufraeumen", "text": f"archivieren: n{i}@liste.example – Brief", "daten": {"aktion": "archivieren"}}
             for i in range(3)]
    liste += [{"art": "aufraeumen", "text": f"liegen lassen: k{i}@kunde.example – Frage {i}", "daten": {"aktion": "liegen lassen"}}
              for i in range(32)]
    liste.append({"art": "aufraeumen", "text": "melden: bank@bank.example – Info", "daten": {"aktion": "melden"}})
    text, betreff = bericht.text_und_betreff(liste)
    assert "Postfach aufgeräumt" in text
    assert "3 archiviert" in text and "32 liegen gelassen" in text and "1 gemeldet" in text
    assert "Braucht dich" in text and "- und 3 weitere" in text
    assert "€" not in betreff
    ohne, _ = bericht.text_und_betreff([])
    assert "Postfach aufgeräumt" not in ohne


# 16. Alte Konfiguration


def test_alte_konfiguration_ohne_eintraege_raeumt_nicht_auf(repo, still, monkeypatch):
    datei = repo / "konfig" / "belege.toml"
    text = datei.read_text(encoding="utf-8")
    text = re.sub(r"\n\[aufraeumen\]\n(?:[^\[\n].*\n|\n)*?(?=\[)", "\n", text)
    text = text.replace("aufraeumen = false\n", "")
    assert "aufraeumen" not in text
    datei.write_text(text, encoding="utf-8")
    _regeln(repo, "- sonst -> archivieren")
    _mail(repo, "shop@laden.example", "Bestellung")
    schritte = []
    monkeypatch.setattr(takt, "_lauf", lambda args, s, sperre: schritte.append(s) or True)
    takt.befehl(_args(echt=True))
    assert "aufraeumen" not in schritte[0]
    assert aufraeumen.befehl(_args(echt=True)) == 0
    assert _aktionen(repo) == []


# 17. Nie löschen


def test_postfach_agent_kennt_keine_loeschbefehle():
    quelle = (Path(aufraeumen.__file__)).read_text(encoding="utf-8").lower()
    for wort in ("delete", "trash", "expunge", "\\deleted"):
        assert wort not in quelle, wort


# Robustheit


def test_fehler_bei_einer_mail_haelt_den_rest_nicht_auf(repo, still, monkeypatch):
    from belege import postfach

    _einschalten(repo)
    _regeln(repo, "- sonst -> archivieren")
    kaputt = _mail(repo, "a@laden.example", "Eins")
    gut = _mail(repo, "b@laden.example", "Zwei")
    original = postfach.OrdnerPostfach.aufraeumen

    def wackelig(self, ident, aktion, name=""):
        if ident == kaputt:
            raise RuntimeError("Server weg")
        return original(self, ident, aktion, name)

    monkeypatch.setattr(postfach.OrdnerPostfach, "aufraeumen", wackelig)
    assert aufraeumen.befehl(_args(echt=True)) == 1
    assert [z["id"] for z in _aktionen(repo)] == [gut]
    gesehen = json.loads((repo / "arbeit" / "gesehen.json").read_text())
    assert gesehen["aufraeumen:geschaeft"]["ids"] == [gut]  # die kaputte kommt beim nächsten Lauf wieder
    monkeypatch.setattr(postfach.OrdnerPostfach, "aufraeumen", original)
    aufraeumen.befehl(_args(echt=True))
    assert sorted(z["id"] for z in _aktionen(repo)) == sorted([kaputt, gut])


def test_nichts_passiert_heisst_nicht_erledigt(repo, still, monkeypatch):
    from belege import postfach

    _einschalten(repo)
    _regeln(repo, "- sonst -> archivieren")
    mail = _mail(repo, "a@laden.example", "Eins")
    monkeypatch.setattr(postfach.OrdnerPostfach, "aufraeumen",
                        lambda self, ident, aktion, name="": "nicht verschoben (Server kann kein MOVE)")
    assert aufraeumen.befehl(_args(echt=True)) == 1
    gesehen = json.loads((repo / "arbeit" / "gesehen.json").read_text()) if (repo / "arbeit" / "gesehen.json").exists() else {}
    assert mail not in gesehen.get("aufraeumen:geschaeft", {}).get("ids", [])
    ereignisse = "".join(p.read_text() for p in (repo / "arbeit" / "ereignisse").glob("*.jsonl"))
    assert '"art": "fehler"' in ereignisse and "kein MOVE" in ereignisse
    assert '"art": "aufraeumen"' not in ereignisse


def test_abbruch_nach_entwurf_legt_keinen_zweiten_an(repo, still, monkeypatch):
    _, _, entwuerfe = still
    _einschalten(repo)
    _regeln(repo, "- sonst -> entwurf: Danke!")
    _mail(repo, "a@kunde.example", "Eins")
    _mail(repo, "b@kunde.example", "Zwei")
    original = kern.ereignis

    def bricht_ab(art, *a, **k):
        original(art, *a, **k)
        raise KeyboardInterrupt  # Mac geht mitten im Lauf schlafen

    monkeypatch.setattr(kern, "ereignis", bricht_ab)
    with pytest.raises(KeyboardInterrupt):
        aufraeumen.befehl(_args(echt=True))
    assert len(entwuerfe) == 1
    assert len(_protokoll(repo)) == 1  # die ausgeführte Aktion steht im Protokoll
    monkeypatch.setattr(kern, "ereignis", original)
    aufraeumen.befehl(_args(echt=True))
    assert sorted(e[0] for e in entwuerfe) == ["a@kunde.example", "b@kunde.example"]


def test_vorschlag_liest_hoechstens_3000_mails_ueber_alle_konten(repo, monkeypatch):
    abgefragt = []

    class Fake:
        def posteingang(self, seit, max):
            abgefragt.append(max)
            return [{"id": f"x{i}", "von": f"a{i}@x.example", "betreff": ""} for i in range(2500)][:max]

    monkeypatch.setattr(kern, "konten", lambda: [
        {"name": "eins", "aufraeumen": True, "adresse": "eins@x.example"},
        {"name": "zwei", "aufraeumen": True, "adresse": "zwei@x.example"},
        {"name": "drei", "aufraeumen": True, "adresse": "drei@x.example"},
    ])
    monkeypatch.setattr("belege.postfach.oeffnen", lambda name=None: Fake())
    aufraeumen.befehl(_args(ziel=["vorschlag"]))
    assert abgefragt == [3000, 500]


def test_dauerhaft_scheiternde_mail_blockiert_die_anderen_nicht(repo, still, monkeypatch, capsys):
    from belege import postfach

    _einschalten(repo, max_je_lauf=1)
    _regeln(repo, "- betreff: Stur -> ordner: X", "- sonst -> archivieren")
    andere = [_mail(repo, f"a{i}@laden.example", f"Normal {i}") for i in range(2)]
    stur = _mail(repo, "s@laden.example", "Stur")  # die neueste
    original = postfach.OrdnerPostfach.aufraeumen

    def kein_move(self, ident, aktion, name=""):
        if ident == stur:
            return "nicht verschoben (Server kann kein MOVE)"
        return original(self, ident, aktion, name)

    monkeypatch.setattr(postfach.OrdnerPostfach, "aufraeumen", kein_move)
    for _ in range(3):
        aufraeumen.befehl(_args(echt=True))
    assert sorted(z["id"] for z in _aktionen(repo)) == sorted(andere)
    assert "1 archivieren" in capsys.readouterr().out
    gesehen = json.loads((repo / "arbeit" / "gesehen.json").read_text())
    assert stur not in gesehen["aufraeumen:geschaeft"]["ids"]
