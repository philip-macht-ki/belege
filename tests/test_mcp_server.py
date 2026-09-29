from email.message import EmailMessage
from belege import mcp_server


def test_werkzeuge_gegen_ordnerpostfach_und_fremd_ist_entwurf(repo):
    m = EmailMessage()
    m["From"] = "x@example"
    m["Subject"] = "Hallo"
    m.set_content("Text")
    (repo / "beispiel/erzeugt/postfach" / "x.eml").write_bytes(m.as_bytes())
    assert mcp_server.suchen("Hallo")[0]["id"] == "x.eml"
    assert mcp_server.lesen("x.eml")["text"] == "Text"
    r = mcp_server.senden("fremd@example", "T", "x")
    assert r["status"] == "befund"


def test_server_antwortet_ueber_stdio():
    """Der echte Weg, den Claude nimmt: Prozess starten, Werkzeuge über stdio abfragen.

    Die übrigen Tests rufen die Funktionen direkt auf und merkten deshalb nicht, dass
    mcp 2.x die Serverklasse umbenannt hatte und der Server gar nicht startete.
    """
    import json
    import subprocess
    import sys
    import time

    nachrichten = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    prozess = subprocess.Popen(
        [sys.executable, "-m", "belege.cli", "mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    for n in nachrichten:
        prozess.stdin.write(json.dumps(n) + "\n")
        prozess.stdin.flush()
    namen = []
    ende = time.time() + 20
    while time.time() < ende:
        zeile = prozess.stdout.readline()
        if not zeile:
            break
        antwort = json.loads(zeile)
        if antwort.get("id") == 2:
            namen = [w["name"] for w in antwort["result"]["tools"]]
            break
    prozess.kill()
    assert set(namen) == {"konten", "suchen", "lesen", "anhaenge_speichern", "entwurf", "senden"}
