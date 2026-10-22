"""Kleine Helfer, die Claude Code für launchd erreichbar machen."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "# belege-claude-starter-v1"


def starter_pfad() -> Path:
    return Path.home() / ".local" / "bin" / "claude"


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


def anlegen() -> tuple[bool, str]:
    """Legt ausschließlich unseren markierten Starter an oder aktualisiert ihn."""
    ziel = starter_pfad()
    if ziel.exists() and MARKER not in ziel.read_text(encoding="utf-8", errors="replace"):
        return False, f"{ziel} gehört nicht zu belege und wurde nicht verändert."
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(starter_text(), encoding="utf-8")
    os.chmod(ziel, 0o755)
    return True, str(ziel)


def befehl(args) -> int:
    """`belege einrichten-claude`: Starter für den Zeitplan anlegen."""
    ok, meldung = anlegen()
    print(("ok: Claude-Starter eingerichtet: " if ok else "nichts: ") + meldung)
    return 0 if ok else 1
