"""Kleine Helfer, die Modell-CLIs für launchd erreichbar machen."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "# belege-claude-starter-v1"
CODEX_MARKER = "# belege-codex-starter-v1"


def starter_pfad(backend: str = "claude") -> Path:
    return Path.home() / ".local" / "bin" / backend


def starter_text() -> str:
    """Shell-Starter: echte Installation vor der Claude-App, nie rekursiv sich selbst."""
    return rf'''#!/bin/zsh
{MARKER}
selbst="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
for kandidat in "$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
  if [ -x "$kandidat" ] && [ "$kandidat" != "$selbst" ]; then
    exec "$kandidat" "$@"
  fi
done
basis="$HOME/Library/Application Support/Claude/claude-code"
if [ -d "$basis" ]; then
  while IFS= read -r version; do
    kandidat="$(find "$basis/$version" -type f -path '*/claude.app/Contents/MacOS/claude' -perm -111 -print -quit 2>/dev/null)"
    if [ -n "$kandidat" ]; then
      exec "$kandidat" "$@"
    fi
  done < <(find "$basis" -mindepth 1 -maxdepth 1 -type d -exec basename {{}} \; | (sort -V -r 2>/dev/null || sort -t. -k1,1nr -k2,2nr -k3,3nr))
fi
print -u2 "Claude wurde nicht gefunden. Öffne die Claude-App einmal und versuche es erneut."
exit 127
'''


def codex_starter_text() -> str:
    """Shell-Starter für die Codex-CLI; nie rekursiv sich selbst aufrufen."""
    return rf'''#!/bin/zsh
{CODEX_MARKER}
selbst="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
for kandidat in /opt/homebrew/bin/codex /usr/local/bin/codex "$HOME/.npm-global/bin/codex" /Applications/Codex.app/Contents/Resources/codex; do
  if [ -x "$kandidat" ] && [ "$kandidat" != "$selbst" ]; then
    exec "$kandidat" "$@"
  fi
done
print -u2 "Codex wurde nicht gefunden. Codex installieren oder die Codex-App einmal öffnen."
exit 127
'''


def anlegen(backend: str = "claude") -> tuple[bool, str]:
    """Legt ausschließlich unseren markierten Starter an oder aktualisiert ihn."""
    if backend not in {"claude", "codex"}:
        return False, f"Für Urteil-Backend {backend} ist kein Starter nötig."
    ziel = starter_pfad(backend)
    marker = MARKER if backend == "claude" else CODEX_MARKER
    text = starter_text() if backend == "claude" else codex_starter_text()
    if ziel.exists() and marker not in ziel.read_text(encoding="utf-8", errors="replace"):
        return False, f"{ziel} gehört nicht zu belege und wurde nicht verändert."
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    os.chmod(ziel, 0o755)
    return True, str(ziel)


def befehl(args) -> int:
    """`belege einrichten-claude`: Starter für den Zeitplan anlegen."""
    ok, meldung = anlegen()
    print(("ok: Claude-Starter eingerichtet: " if ok else "nichts: ") + meldung)
    return 0 if ok else 1


def befehl_urteil(args) -> int:
    """`belege einrichten-urteil`: Starter für das gewählte Modell einrichten."""
    from .kern import konfig

    backend = os.environ.get(
        "URTEIL_BACKEND", konfig("belege").get("urteil", {}).get("backend", "claude")
    )
    if backend not in {"claude", "codex"}:
        print(f"nichts: Für Urteil-Backend {backend} ist kein Starter nötig.")
        return 0
    ok, meldung = anlegen(backend)
    name = "Claude" if backend == "claude" else "Codex"
    print((f"ok: {name}-Starter eingerichtet: " if ok else "nichts: ") + meldung)
    return 0 if ok else 1
