from pathlib import Path
from types import SimpleNamespace

import pytest

from belege import urteil


def test_codex_abgeschottet_und_antwort(monkeypatch, tmp_path):
    aufrufe = []

    def lauf(cmd, **kwargs):
        aufrufe.append((cmd, kwargs))
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text('{"ok": true}')
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(urteil.shutil, "which", lambda name: "/opt/homebrew/bin/codex")
    monkeypatch.setattr(urteil.subprocess, "run", lauf)
    assert urteil._codex("Fremder Belegtext", "gpt-test") == '{"ok": true}'
    cmd, kwargs = aufrufe[0]
    for schalter in ("--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral",
                     "--ignore-user-config", "--ignore-rules"):
        assert schalter in cmd
    assert cmd[cmd.index("-C") + 1] != str(Path.cwd())
    assert cmd[cmd.index("-C") + 1] != str(tmp_path)
    assert cmd[2:4] == ["-m", "gpt-test"]
    assert kwargs["timeout"] == 600
    assert kwargs["input"].startswith(urteil.SYSTEMTEXT)


def test_codex_fehler(monkeypatch):
    monkeypatch.setattr(urteil.shutil, "which", lambda name: "/opt/homebrew/bin/codex")
    monkeypatch.setattr(urteil.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="kaputt"))
    with pytest.raises(urteil.KeinUrteil, match="codex scheiterte: kaputt"):
        urteil._codex("x", "")


def test_lokal_antwort_und_fehler(monkeypatch):
    gesehen = {}

    def post(url, **kwargs):
        gesehen.update(url=url, **kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"response": '{"ok": true}'})

    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434/")
    monkeypatch.setattr(urteil.requests, "post", post)
    assert urteil._lokal("Beleg", "qwen3:14b") == '{"ok": true}'
    assert gesehen["url"] == "http://ollama:11434/api/generate"
    assert gesehen["json"] == {"model": "qwen3:14b", "prompt": "Beleg", "system": urteil.SYSTEMTEXT,
                                "stream": False, "format": "json", "options": {"temperature": 0}}
    assert gesehen["timeout"] == 600

    monkeypatch.setattr(urteil.requests, "post", lambda *a, **k: SimpleNamespace(status_code=404, text="model not found"))
    with pytest.raises(urteil.KeinUrteil, match="Modell qwen3:14b fehlt: ollama pull qwen3:14b"):
        urteil._lokal("Beleg", "qwen3:14b")
