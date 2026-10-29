"""Tests für Rechnungen, die nur als Link in einer Mail stehen. Ohne echtes Netz."""
from __future__ import annotations

import json
import re
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from belege import kern, quellen, rechnungslink
from belege.rechnungslink import LinkFehler

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class _Antwort:
    def __init__(self, daten: bytes):
        self.daten = daten

    def read(self, n: int) -> bytes:
        stueck, self.daten = self.daten[:n], self.daten[n:]
        return stueck

    def close(self) -> None:
        pass


def _kopf(**felder) -> EmailMessage:
    kopf = EmailMessage()
    for name, wert in felder.items():
        kopf[name.replace("_", "-")] = wert
    return kopf


def _server(monkeypatch, antworten: dict, erlaubt=lambda host: host.endswith("example.com")):
    """Ersetzt das Netz: ``antworten`` ordnet URLs (status, kopf, inhalt) zu."""
    geladen = []

    def anfrage(url, zeitlimit, ip):
        geladen.append(url)
        status, kopf, inhalt = antworten[url]
        return status, kopf, _Antwort(inhalt)

    monkeypatch.setattr(rechnungslink, "_anfrage", anfrage)
    monkeypatch.setattr(rechnungslink, "_host_erlaubt",
                        lambda host, port: "93.184.215.14" if port in (None, 443) and erlaubt(host) else None)
    return geladen


def _pdf_antwort(inhalt: bytes = PDF):
    return 200, _kopf(Content_Type="application/pdf"), inhalt


def test_sieht_nach_rechnung():
    assert rechnungslink.sieht_nach_rechnung("Your receipt from Acme", "")
    assert rechnungslink.sieht_nach_rechnung("Hallo", "anbei Ihre Rechnung zum Download")
    assert not rechnungslink.sieht_nach_rechnung("Newsletter Oktober", "Neue Funktionen")


def test_pdf_links_nur_plausible_https():
    links = [
        "https://example.com/rechnung/4711.pdf",
        "http://example.com/rechnung/4712.pdf",
        "https://example.com/newsletter/abmelden",
        "https://example.com/unsubscribe?pdf=1",
        "https://example.com/login?next=/invoice",
        "https://user:pw@example.com/invoice.pdf",
        "https://pay.stripe.com/invoice/acct_1/test_abc/pdf",
        "https://example.com/blog/neuigkeiten",
    ]
    assert rechnungslink.pdf_links(links) == [
        "https://example.com/rechnung/4711.pdf",
        "https://pay.stripe.com/invoice/acct_1/test_abc/pdf",
    ]


def test_laden_echtes_pdf(repo, monkeypatch):
    url = "https://example.com/rechnung/4711.pdf"
    _server(monkeypatch, {url: _pdf_antwort()})
    datei = rechnungslink.laden(url, repo / "arbeit" / "tmp" / "x")
    assert datei.name == "4711.pdf" and datei.read_bytes() == PDF


def test_laden_folgt_geprueften_weiterleitungen(repo, monkeypatch):
    start = "https://klick.example.com/r/1"
    ziel = "https://dl.example.com/files/rechnung"
    geladen = _server(monkeypatch, {start: (302, _kopf(Location=ziel), b""), ziel: _pdf_antwort()})
    datei = rechnungslink.laden(start, repo / "arbeit" / "tmp" / "x")
    assert geladen == [start, ziel] and datei.name == "rechnung.pdf"


@pytest.mark.parametrize("antwort, grund", [
    ((200, _kopf(Content_Type="text/html"), b"<html>Login</html>"), "kein PDF"),
    ((200, _kopf(Content_Type="application/pdf"), b"<html>kein pdf</html>"), "Inhalt ist kein PDF"),
    ((200, _kopf(Content_Type="application/pdf"), PDF + b"x" * 2000), "zu groß"),
    ((404, _kopf(), b""), "404"),
    ((302, _kopf(Location="http://example.com/rechnung.pdf"), b""), "kein https"),
    ((302, _kopf(Location="https://intern.firma.lan/rechnung.pdf"), b""), "Host nicht erlaubt"),
    ((302, _kopf(Location="https://example.com:8443/rechnung.pdf"), b""), "Host nicht erlaubt"),
])
def test_laden_lehnt_ab(repo, monkeypatch, antwort, grund):
    url = "https://example.com/rechnung.pdf"
    _server(monkeypatch, {url: antwort})
    with pytest.raises(LinkFehler) as fehler:
        rechnungslink.laden(url, repo / "arbeit" / "tmp" / "x", max_bytes=1000)
    assert grund in fehler.value.grund and fehler.value.endgueltig
    assert not (repo / "arbeit" / "tmp" / "x").exists()


def test_serverfehler_ist_voruebergehend(repo, monkeypatch):
    url = "https://example.com/rechnung.pdf"
    _server(monkeypatch, {url: (503, _kopf(), b"")})
    with pytest.raises(LinkFehler) as fehler:
        rechnungslink.laden(url, repo / "arbeit" / "tmp" / "x")
    assert not fehler.value.endgueltig


def test_zu_viele_weiterleitungen(repo, monkeypatch):
    urls = [f"https://example.com/r/{i}" for i in range(6)]
    _server(monkeypatch, {u: (302, _kopf(Location=urls[i + 1]), b"") for i, u in enumerate(urls[:-1])})
    with pytest.raises(LinkFehler, match="zu viele Weiterleitungen"):
        rechnungslink.laden(urls[0], repo / "arbeit" / "tmp" / "x")


def test_host_erlaubt_sperrt_interne_adressen(monkeypatch):
    monkeypatch.undo()  # das echte _host_erlaubt; IP-Literale brauchen kein DNS
    from belege import rechnungslink as echt

    for host in ("127.0.0.1", "10.0.0.8", "192.168.1.1", "169.254.169.254", "::1", "localhost", "drucker.local"):
        assert not echt._host_erlaubt(host, None), host
    assert not echt._host_erlaubt("93.184.215.14", 8443)
    assert echt._host_erlaubt("93.184.215.14", None)


# --- Quelle im Postfach ---------------------------------------------------

def _mail(repo, name: str, betreff: str, html: str, anhang: bool = False) -> None:
    nachricht = EmailMessage()
    nachricht["From"] = "Acme Billing <billing@acme.example.com>"
    nachricht["To"] = "mara@studio-beispiel.example"
    nachricht["Subject"] = betreff
    nachricht["Date"] = format_datetime(kern.jetzt())
    nachricht.set_content(re.sub(r"<[^>]+>", " ", html))  # Klartextteil wie bei echten Mails
    nachricht.add_alternative(html, subtype="html")
    if anhang:
        nachricht.add_attachment(PDF, maintype="application", subtype="pdf", filename="rechnung.pdf")
    (repo / "beispiel" / "erzeugt" / "postfach" / name).write_bytes(nachricht.as_bytes())


def _gesehen(repo) -> dict:
    datei = repo / "arbeit" / "gesehen.json"
    return json.loads(datei.read_text()) if datei.exists() else {}


def test_mail_mit_genau_einem_pdf_link_wird_fund(repo, monkeypatch):
    url = "https://acme.example.com/invoices/2026-10.pdf"
    _mail(repo, "link.eml", "Ihre Rechnung Oktober",
          f'<p>Ihre Rechnung: <a href="{url}">herunterladen</a></p>'
          '<a href="https://acme.example.com/newsletter/abmelden">Abmelden</a>')
    geladen = _server(monkeypatch, {url: _pdf_antwort()})
    funde = list(quellen.postfach_funde("geschaeft", 3))
    assert geladen == [url]
    assert len(funde) == 1 and funde[0].quelle == "postfach"
    assert funde[0].mail["link"] == "acme.example.com" and funde[0].mail["id"] == "link.eml"
    assert funde[0].datei.read_bytes() == PDF
    assert "links_geprueft" not in _gesehen(repo).get("geschaeft", {})


def test_mail_mit_anhang_laedt_keinen_link(repo, monkeypatch):
    url = "https://acme.example.com/invoices/2026-10.pdf"
    _mail(repo, "anhang.eml", "Ihre Rechnung", f'<a href="{url}">PDF</a>', anhang=True)
    geladen = _server(monkeypatch, {url: _pdf_antwort()})
    funde = list(quellen.postfach_funde("geschaeft", 3))
    assert geladen == [] and [f.name for f in funde] == ["rechnung.pdf"]


def test_zwei_links_laden_nichts_und_werden_erst_echt_gemerkt(repo, monkeypatch):
    _mail(repo, "zwei.eml", "Ihre Rechnungen",
          '<a href="https://acme.example.com/a/rechnung.pdf">A</a>'
          '<a href="https://acme.example.com/b/rechnung.pdf">B</a>')
    geladen = _server(monkeypatch, {})
    assert list(quellen.postfach_funde("geschaeft", 3)) == []
    assert geladen == [] and "links_geprueft" not in _gesehen(repo).get("geschaeft", {})
    assert list(quellen.postfach_funde("geschaeft", 3, echt=True)) == []
    assert _gesehen(repo)["geschaeft"]["links_geprueft"] == ["zwei.eml"]
    log = next((repo / "arbeit" / "logs").glob("*.log")).read_text()
    assert "2 plausible PDF-Links" in log


def test_keine_rechnung_kein_download(repo, monkeypatch):
    _mail(repo, "news.eml", "Neuigkeiten mit Beleg-Funktion",
          '<a href="https://acme.example.com/download/app.pdf">App</a>')
    # "Beleg" im Betreff zählt als Rechnungsmail; die Werbemail ohne Rechnungswort nicht.
    _mail(repo, "werbung.eml", "Herbstangebot", '<a href="https://acme.example.com/flyer.pdf">Flyer</a>')
    geladen = _server(monkeypatch, {"https://acme.example.com/download/app.pdf": _pdf_antwort()})
    funde = list(quellen.postfach_funde("geschaeft", 3, echt=True))
    assert geladen == ["https://acme.example.com/download/app.pdf"]
    assert [f.mail["id"] for f in funde] == ["news.eml"]


def test_abofalle_im_mailtext_oeffnet_keinen_link(repo, monkeypatch):
    url = "https://businesseintrag.example.com/rechnung/offerte.pdf"
    _mail(repo, "falle.eml", "Rechnung Eintragung Branchenbuch",
          "<p>Ihr Eintrag im Branchenbuch. Eintragungsofferte bitte per Fax zurücksenden: "
          "+41 44 123 45 67. businesseintrag.info</p>"
          f'<a href="{url}">Rechnung</a>')
    geladen = _server(monkeypatch, {url: _pdf_antwort()}, erlaubt=lambda host: True)
    assert list(quellen.postfach_funde("geschaeft", 3, echt=True)) == []
    assert geladen == []
    ereignisse = [e for e in kern.ereignisse() if e["art"] == "zweifel"]
    assert ereignisse and "Abofalle" in ereignisse[0]["text"]
    assert _gesehen(repo)["geschaeft"]["links_geprueft"] == ["falle.eml"]


def test_voruebergehender_fehler_wird_nicht_gemerkt(repo, monkeypatch):
    url = "https://acme.example.com/invoices/1.pdf"
    _mail(repo, "netz.eml", "Ihre Rechnung", f'<a href="{url}">PDF</a>')
    _server(monkeypatch, {url: (502, _kopf(), b"")})
    assert list(quellen.postfach_funde("geschaeft", 3, echt=True)) == []
    stand = _gesehen(repo)["geschaeft"]
    assert "links_geprueft" not in stand and "netz.eml" in stand["offen"]
    # Rückblick bleibt offen, beim nächsten Lauf klappt es: Fund statt Merken.
    quellen.lauf_abschliessen("geschaeft", {}, True)
    assert "lauf" not in _gesehen(repo)["geschaeft"]
    _server(monkeypatch, {url: _pdf_antwort()})
    assert [f.mail["id"] for f in quellen.postfach_funde("geschaeft", 3, echt=True)] == ["netz.eml"]


def test_abbruch_beim_lesen_ist_voruebergehend(repo, monkeypatch):
    class Abbruch(_Antwort):
        def read(self, n):
            raise ConnectionResetError("weg")

    url = "https://example.com/rechnung.pdf"
    monkeypatch.setattr(rechnungslink, "_host_erlaubt", lambda host, port: "93.184.215.14")
    monkeypatch.setattr(rechnungslink, "_anfrage",
                        lambda u, z, ip: (200, _kopf(Content_Type="application/pdf"), Abbruch(b"")))
    with pytest.raises(LinkFehler) as fehler:
        rechnungslink.laden(url, repo / "arbeit" / "tmp" / "x")
    assert not fehler.value.endgueltig


def test_gesamtfrist_gilt_ueber_alle_weiterleitungen(repo, monkeypatch):
    uhr = iter([0, 5, 15, 25, 30, 40])
    monkeypatch.setattr(rechnungslink.time, "monotonic", lambda: next(uhr))
    urls = [f"https://example.com/r/{i}" for i in range(4)]
    _server(monkeypatch, {u: (302, _kopf(Location=urls[i + 1]), b"") for i, u in enumerate(urls[:-1])})
    with pytest.raises(LinkFehler, match="Zeitlimit") as fehler:
        rechnungslink.laden(urls[0], repo / "arbeit" / "tmp" / "x")
    assert not fehler.value.endgueltig


def test_anfrage_verbindet_mit_gepruefter_ip(monkeypatch):
    """Kein zweites DNS, kein Proxy: die Verbindung geht an die geprüfte IP."""
    gesehen = {}

    def verbinden(adresse, zeitlimit):
        gesehen["adresse"] = adresse
        raise ConnectionRefusedError("Test")

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(rechnungslink.socket, "create_connection", verbinden)
    from belege.rechnungslink import _Verbindung

    with pytest.raises(ConnectionRefusedError):
        _Verbindung("example.com", "93.184.215.14", 5).connect()
    assert gesehen["adresse"] == ("93.184.215.14", 443)


def test_schalter_aus(repo, monkeypatch):
    url = "https://acme.example.com/invoices/1.pdf"
    _mail(repo, "link.eml", "Ihre Rechnung", f'<a href="{url}">PDF</a>')
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text().replace("rechnungslinks = true", "rechnungslinks = false"), encoding="utf-8")
    geladen = _server(monkeypatch, {url: _pdf_antwort()})
    assert list(quellen.postfach_funde("geschaeft", 3)) == [] and geladen == []


def test_lesen_liefert_links(repo):
    from belege.postfach import oeffnen

    _mail(repo, "l.eml", "Rechnung", '<a href="https://acme.example.com/x.pdf?a=1&amp;b=2">x</a>')
    assert oeffnen("geschaeft").lesen("l.eml")["links"] == ["https://acme.example.com/x.pdf?a=1&b=2"]


def test_restfrist_gilt_auch_fuer_jedes_lesestueck(repo, monkeypatch):
    class Sock:
        zeiten = []

        def settimeout(self, wert):
            self.zeiten.append(wert)

    uhr = iter([0, 13])
    monkeypatch.setattr(rechnungslink.time, "monotonic", lambda: next(uhr))
    antwort = _Antwort(PDF)
    antwort.belege_sock = Sock()
    assert rechnungslink._lesen(antwort, 10_000, 20) == PDF
    assert Sock.zeiten == [20, 7]


def test_rechnung_nur_im_mailtext_wird_als_pdf_abgelegt(repo, monkeypatch):
    """Apple schickt die Rechnung als HTML-Mail ohne PDF und ohne Link (Meldung Nina, 29.10.2026)."""
    _mail(repo, "apple.eml", "Deine Rechnung von Apple",
          "<p>Rechnungsdatum: 20.10.2026</p><p>Prêt à Template, Monatsabo</p>"
          "<p>Zwischensumme 8,39 €</p><p>USt. 19 % 1,60 €</p><p>Gesamt 9,99 €</p>"
          "<p>USt-IdNr. IE9700053D</p>")
    _mail(repo, "werbung.eml", "Deine Rechnung wird bald günstiger", "<p>Jetzt 20 % sparen!</p>")
    geladen = _server(monkeypatch, {})
    funde = list(quellen.postfach_funde("geschaeft", 3))
    assert geladen == []
    assert [f.mail["id"] for f in funde] == ["apple.eml"]
    pdf = funde[0].datei
    assert pdf.suffix == ".pdf" and pdf.read_bytes().startswith(b"%PDF")
    from belege.text import auslesen

    inhalt = auslesen(pdf).text
    assert "Gesamt 9,99" in inhalt and "Deine Rechnung von Apple" in inhalt

    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text().replace("rechnung_im_mailtext = true", "rechnung_im_mailtext = false"), encoding="utf-8")
    assert list(quellen.postfach_funde("geschaeft", 3)) == []
