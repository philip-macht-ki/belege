from belege import senden


def test_trocken_dann_echt_und_fremde_adresse_ist_entwurf(repo, monkeypatch):
    aufrufe = []

    class Box:
        def _senden(self, *a):
            aufrufe.append(("send", a))
            return "s"

        def entwurf(self, *a):
            aufrufe.append(("draft", a))
            return "d"

    monkeypatch.setattr("belege.postfach.oeffnen", lambda k=None: Box())
    assert (
        senden.senden("fremd@example", "T", "x", [], False).status == "nichts"
        and not aufrufe
    )
    assert (
        senden.senden("fremd@example", "T", "x", [], True).status == "befund"
        and aufrufe[-1][0] == "draft"
    )
    t = repo / "konfig/belege.toml"
    t.write_text(t.read_text().replace("erlaubt = []", "erlaubt = ['ok@example']"))
    assert (
        senden.senden("ok@example", "T", "x", [], True).status == "ok"
        and aufrufe[-1][0] == "send"
    )


def test_anhaenge_werden_aufgeteilt(repo, monkeypatch):
    t = repo / "konfig/belege.toml"
    s = t.read_text()
    s = s.replace("max_anhaenge = 50", "max_anhaenge = 1").replace(
        "erlaubt = []", "erlaubt = ['ok@example']"
    )
    t.write_text(s)
    a = []

    class Box:
        def _senden(self, *x):
            a.append(x)
            return str(len(a))

    monkeypatch.setattr("belege.postfach.oeffnen", lambda k=None: Box())
    f1 = repo / "a"
    f2 = repo / "b"
    f1.write_bytes(b"x")
    f2.write_bytes(b"y")
    senden.senden("ok@example", "T", "x", [f1, f2], True)
    assert len(a) == 2 and "Teil 1 von 2" in a[0][1]


def test_mehrere_empfaenger_sind_nie_erlaubt(repo):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(toml.read_text().replace("erlaubt = []", 'erlaubt = ["stb@kanzlei.example"]'))
    assert senden.erlaubt("stb@kanzlei.example")
    assert senden.erlaubt("Kanzlei <STB@kanzlei.example>")
    assert not senden.erlaubt("stb@kanzlei.example, fremd@boese.example")
    assert not senden.erlaubt("stb@kanzlei.example; fremd@boese.example")
    assert not senden.erlaubt("")


def test_wiederholung_sendet_nur_fehlende_teile(repo, monkeypatch):
    toml = repo / "konfig" / "belege.toml"
    toml.write_text(
        toml.read_text().replace("erlaubt = []", 'erlaubt = ["stb@kanzlei.example"]')
        .replace("max_anhaenge = 50", "max_anhaenge = 1")
    )
    dateien = []
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (repo / name).write_bytes(b"x")
        dateien.append(repo / name)
    gesendet = []

    class Postfach:
        fehler_bei = 2

        def _senden(self, an, betreff, text, anhaenge):
            if "Teil 2" in betreff and self.fehler_bei == 2:
                Postfach.fehler_bei = None
                raise RuntimeError("Verbindung weg")
            gesendet.append(betreff)
            return betreff

    monkeypatch.setattr("belege.postfach.oeffnen", lambda konto=None: Postfach())
    import pytest

    with pytest.raises(RuntimeError):
        senden.senden("stb@kanzlei.example", "Belege", "x", dateien, True, fortschritt="uebergabe:2026-08")
    senden.senden("stb@kanzlei.example", "Belege", "x", dateien, True, fortschritt="uebergabe:2026-08")
    assert gesendet == ["Belege (Teil 1 von 3)", "Belege (Teil 2 von 3)", "Belege (Teil 3 von 3)"]
