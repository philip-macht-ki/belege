from argparse import Namespace

from belege import anmelden


def test_schluesselbund_speichert_ohne_passwortausgabe(repo, monkeypatch, capsys):
    aufrufe = []

    class Antwort:
        def __init__(self, returncode=0, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def run(args, **kwargs):
        aufrufe.append(args)
        return Antwort(stdout="button returned:Speichern, text returned:geheim") if args[0] == "osascript" else Antwort()

    monkeypatch.setattr("belege.anmelden.subprocess.run", run)
    assert anmelden.befehl(Namespace(konto=None, schluesselbund="geschaeft", rechte=None)) == 0
    assert aufrufe[1][:6] == ["security", "add-generic-password", "-U", "-s", "belege-postfach", "-a"]
    assert "geheim" not in capsys.readouterr().out


def test_schluesselbund_abbruch_ist_sauber(repo, monkeypatch, capsys):
    class Antwort:
        returncode = 1
        stdout = ""
    monkeypatch.setattr("belege.anmelden.subprocess.run", lambda *a, **k: Antwort())
    assert anmelden.befehl(Namespace(konto=None, schluesselbund="geschaeft", rechte=None)) == 0
    assert "abgebrochen" in capsys.readouterr().out
