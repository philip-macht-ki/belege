"""Weiche „vertraulich“: Was anschlägt, geht an kein Cloud-Modell."""
from datetime import date
from types import SimpleNamespace

import pytest

from belege import urteil, verarbeiten, vertraulich
from belege.typen import Fund, Text

# Die neun vertraulichen und neun normalen Testtexte der Messung vom 27.10.2026.
VERTRAULICH = [
    "Praxis Dr. med. Weber, Innere Medizin. Arztbrief. Patientin: Anna Muster. Diagnose: Diabetes mellitus Typ 2.",
    "Privatliquidation nach GOÄ. Behandlungszeitraum 02.09.–30.09.2026. Patient: Herr Jonas Beispiel.",
    "Psychotherapeutische Praxis Lena Kurz. Rechnung für 5 Sitzungen Verhaltenstherapie für Frau M. Beispiel.",
    "Amtsgericht Coburg – Zentrales Mahngericht. Mahnbescheid. Antragsgegner: Studio Beispiel.",
    "Entgeltabrechnung Oktober 2026. Mitarbeiterin: Sabine Probe, Steuer-ID 12 345 678 901, Steuerklasse 1.",
    "Arbeitsunfähigkeitsbescheinigung. Versicherter: Tom Muster, Krankenkasse AOK.",
    "Kanzlei Recht & Partner. In der Sache Müller ./. Schmidt, Az. 4 O 123/26, übersenden wir den Schriftsatz.",
    "Heilpraktikerin Eva Sonne. Rechnung Akupunktur und Anamnese für Herrn K. Beispiel.",
    "Beratungsprotokoll Mandant Fa. Beispiel GmbH: Liquiditätsplanung. Streng vertraulich.",
]
NORMAL = [
    "Telekom Deutschland GmbH. Ihre Rechnung Oktober 2026. MagentaZuhause L 44,95 EUR.",
    "Amazon EU S.à r.l. Rechnung. Logitech MX Master 3S Maus 99,99 EUR inkl. 19 % USt.",
    "Adobe Systems Software Ireland Ltd. Invoice. Creative Cloud All Apps. Total 66,45 EUR.",
    "Aral Station 1234. Super E10 42,10 l = 75,74 EUR.",
    "Hotel am Markt, Leipzig. Rechnung Nr. 8812. 2 Übernachtungen 238,00 EUR.",
    "Deutsche Bahn Fernverkehr. Online-Ticket Köln – Berlin, 129,90 EUR.",
    "Restaurant Morgenrot. Bewirtungsbeleg. 86,40 EUR. Anlass: Kundengespräch.",
    "Hetzner Online GmbH. Rechnung R0012345. Cloud Server 4,51 EUR. Amtsgericht Ansbach HRB 6089.",
    "Finanzamt Musterstadt. Umsatzsteuer-Vorauszahlung Q3, Zahlbetrag 1.120,00 EUR.",
]


@pytest.mark.parametrize("text", VERTRAULICH)
def test_wortregel_erkennt_vertrauliches(text):
    assert vertraulich.wortregel(text).vertraulich


@pytest.mark.parametrize("text", NORMAL)
def test_wortregel_laesst_normale_rechnungen_in_ruhe(text):
    assert not vertraulich.wortregel(text).vertraulich


def test_ein_schwaches_wort_reicht_nicht_auch_nicht_doppelt_gezaehlt():
    # „Steuer-ID“ steht auf vielen Auslandsrechnungen; es steckt auch in „Steuer-Identifikationsnummer“.
    assert not vertraulich.wortregel("Google Ireland. Steuer-Identifikationsnummer DE123").vertraulich


def test_absender_und_eigene_woerter_und_abschalten(repo):
    regeln = repo / "konfig" / "regeln.toml"
    regeln.write_text(regeln.read_text(encoding="utf-8") + '\n[vertraulich]\nabsender = ["@labor-beispiel.de"]\n'
                      'woerter_stark = ["praxissoft"]\n', encoding="utf-8")
    assert vertraulich.pruefen("Befund folgt", mail={"von": "post@labor-beispiel.de"}).grund.startswith("Absender")
    assert vertraulich.pruefen("Export aus PraxisSoft").vertraulich
    regeln.write_text(regeln.read_text(encoding="utf-8").replace("[vertraulich]", "[vertraulich]\naus = true"),
                      encoding="utf-8")
    assert not vertraulich.pruefen(VERTRAULICH[0]).vertraulich


def test_nur_lokal_fragt_keine_cloud(repo, monkeypatch):
    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    monkeypatch.setattr(vertraulich, "lokales_modell", lambda: None)
    monkeypatch.setattr(urteil, "BACKENDS", {"claude": lambda *a: pytest.fail("Cloud gefragt")})
    assert urteil.frage("x", zweck="t", rueckfall=lambda: {"regel": True}, nur_lokal=True) == {"regel": True}


def test_nur_lokal_nimmt_vorhandenes_ollama(repo, monkeypatch):
    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    monkeypatch.setattr(vertraulich, "lokales_modell", lambda: "qwen3:8b")
    gefragt = []
    monkeypatch.setattr(urteil, "BACKENDS", {"claude": lambda *a: pytest.fail("Cloud gefragt"),
                                             "lokal": lambda a, m: gefragt.append(m) or '{"ok": 1}'})
    assert urteil.frage("y", zweck="t", nur_lokal=True) == {"ok": 1}
    assert gefragt == ["qwen3:8b"]


def test_vertraulicher_beleg_geht_nicht_in_die_cloud_und_wird_gemeldet(repo, monkeypatch):
    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    monkeypatch.setattr(vertraulich, "lokales_modell", lambda: None)
    monkeypatch.setattr(urteil, "BACKENDS", {"claude": lambda *a: pytest.fail("Cloud gefragt")})
    monkeypatch.setattr("belege.text.auslesen",
                        lambda _, **__: Text("Praxis Dr. med. Weber\nRechnung 12.10.2026\nDiagnose …\nSumme 143,21 EUR", "pdftotext", 1))
    datei = repo / "handy" / "arzt.pdf"
    datei.write_bytes(b"pdf")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 12)), True)
    assert ergebnis.status in {"ok", "befund"}
    zeilen = "".join(p.read_text(encoding="utf-8") for p in (repo / "arbeit" / "ereignisse").glob("*.jsonl"))
    assert '"art": "vertraulich"' in zeilen and "nur auf deinem Mac gelesen" in zeilen


def test_ocr_notstufe_schickt_vertrauliches_nicht_an_claude(repo, monkeypatch):
    from belege import text

    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    datei = repo / "scan.pdf"
    datei.write_bytes(b"%PDF")
    monkeypatch.setattr(text, "_pdftotext", lambda d: "Mahnbescheid")
    for stufe in ("_pypdf", "_vision", "_tesseract"):
        monkeypatch.setattr(text, stufe, lambda d: "")
    monkeypatch.setattr(text, "_claude", lambda d: pytest.fail("Claude-Texterkennung trotz vertraulich"))
    assert text.auslesen(datei).text == "Mahnbescheid"
    # Ganz leer: lässt sich nicht prüfen, also nie in die Cloud, egal aus welcher Quelle.
    monkeypatch.setattr(text, "_pdftotext", lambda d: "")
    assert text.auslesen(datei).stufe == "ohne_text"
    # Teilweise gelesen und nicht vertraulich: Claude darf vervollständigen.
    monkeypatch.setattr(text, "_pdftotext", lambda d: "Hetzner Online GmbH Rechnung")
    monkeypatch.setattr(text, "_claude", lambda d: "Rechnung der Hetzner Online GmbH für den Cloud Server im Oktober, bitte bis Monatsende zahlen. " * 3)
    assert text.auslesen(datei).stufe == "claude"


def test_scan_ohne_text_landet_unsortiert_ohne_cloud(repo, monkeypatch):
    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    monkeypatch.setattr(urteil, "BACKENDS", {"claude": lambda *a: pytest.fail("Cloud gefragt")})
    monkeypatch.setattr("belege.text.auslesen", lambda _, **__: Text("", "ohne_text", 1))
    datei = repo / "handy" / "scan.pdf"
    datei.write_bytes(b"pdf")
    ergebnis = verarbeiten.verarbeite(Fund(datei, "handy", datei.name, date(2026, 10, 12)), True)
    assert "Unsortiert" in ergebnis.daten.get("pfad", "")
    zeilen = "".join(p.read_text(encoding="utf-8") for p in (repo / "arbeit" / "ereignisse").glob("*.jsonl"))
    assert '"art": "unsortiert"' in zeilen


def test_monats_nachsuche_schickt_nichts_vertrauliches_an_claude(repo, monkeypatch):
    from belege import monat, text

    monkeypatch.setenv("URTEIL_BACKEND", "claude")
    datei = repo / "brief.pdf"
    datei.write_bytes(b"%PDF")
    for stufe in ("_pypdf", "_vision", "_tesseract"):
        monkeypatch.setattr(text, stufe, lambda d: "")
    monkeypatch.setattr(text, "_claude", lambda d: pytest.fail("Claude-Texterkennung in der Nachsuche"))
    for teil in ("Mahnbescheid Amtsgericht 120,00", ""):
        monkeypatch.setattr(text, "_pdftotext", lambda d, t=teil: t)
        monat._fund_passt(datei, {"betrag": -120.0, "name": "Amtsgericht", "zweck": ""})


def test_vertrauliche_dokumente_geben_ueber_mcp_keinen_text_heraus(repo):
    from belege import dokumente

    kern_index = {"a": {"pfad": "Dokumente/Gesundheit/x.pdf", "art": "gesundheit", "gegenueber": "Praxis",
                        "titel": "Befund", "text": "Diagnose Diabetes", "vertraulich": True}}
    dokumente._speichere(kern_index)
    assert dokumente.suchen("diabetes") == [], "kein Treffer über den Text"
    treffer = dokumente.suchen("befund")
    assert treffer and "auszug" not in treffer[0] and treffer[0]["vertraulich"] is True


def test_alte_dokumente_ohne_merker_werden_nachgeprueft(repo):
    from belege import dokumente

    dokumente._speichere({
        "a": {"pfad": "Dokumente/Gesundheit/x.pdf", "art": "gesundheit", "titel": "Brief", "text": "Diagnose Diabetes"},
        "b": {"pfad": "Dokumente/Vertrag/y.pdf", "art": "vertrag", "titel": "Mietvertrag", "text": "Laufzeit bis 2027"},
    })
    assert dokumente.suchen("diabetes") == []
    assert dokumente.suchen("laufzeit")[0]["auszug"].startswith("Laufzeit")
    assert len(dokumente.suchen("", max=1)) == 1


def test_mcp_suche_und_fristen_geben_vertrauliches_nicht_heraus(repo, monkeypatch):
    from belege import dokumente, mcp_server

    class Postfach:
        def suchen(self, abfrage, max):
            return [{"von": "praxis@example.de", "betreff": "Befund", "auszug": "Diagnose Diabetes"},
                    {"von": "info@hetzner.com", "betreff": "Rechnung", "auszug": "Ihre Rechnung 4,51 EUR"}]

    monkeypatch.setattr("belege.postfach.oeffnen", lambda konto: Postfach())
    treffer = mcp_server.suchen("x")
    assert "Diabetes" not in str(treffer) and treffer[1]["auszug"].startswith("Ihre Rechnung")
    dokumente._speichere({"a": {"pfad": "p", "art": "gesundheit", "titel": "Befund Dr. X", "gegenueber": "Praxis",
                                "fristen": [{"art": "termin", "datum": None, "text": "Kontrolle Diabetes"}]}})
    frist = mcp_server.fristen()["pruefen"][0]
    assert "Diabetes" not in str(frist) and frist["titel"] == "vertraulich" and frist["art"] == "termin"
