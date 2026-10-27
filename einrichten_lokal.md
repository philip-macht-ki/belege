# Freiwillig: ein KI-Modell auf deinem Mac

Kein Workshop-Schritt. Belege funktioniert ohne. Vertrauliche Briefe (Arzt,
Gericht, Krankenkasse, Personal, eingetragene Absender) liest belege ohnehin nie
mit einem Cloud-Modell, sondern mit festen Regeln. Ein lokales Modell macht
dieses Lesen genauer, und es prüft zusätzlich, ob ein Brief vertraulich ist.

## Passt das zu meinem Mac?

`uv run belege rechner` zeigt den Arbeitsspeicher.

| Arbeitsspeicher | Empfehlung |
|---|---|
| 8 GB | kein Modell; die Regeln genügen |
| 16–31 GB | `qwen3:8b` (rund 5 GB Download, 6 GB im Speicher) |
| ab 32 GB | `qwen3:14b` |

Gemessen am 27.10.2026 auf 40 echten Eingangsbelegen: `qwen3:8b` traf das Datum
in 82 % und den Lieferanten in 90 % der Fälle, etwa 3 Sekunden je Beleg (Mac
Studio M2 Max, auf einem MacBook Air eher 5–10 Sekunden). Große Stapel nur am
Netzteil laufen lassen.

## Einrichten

1. Ollama als App von <https://ollama.com> installieren und öffnen.
2. `ollama pull qwen3:8b`
3. Nichts weiter. Läuft Ollama mit diesem Modell, nutzt belege es automatisch für
   vertrauliche Funde. Normale Rechnungen gehen weiter an dein eingestelltes
   Backend.

Soll **alles** lokal laufen, auch normale Rechnungen: in `konfig/belege.toml`
unter `[urteil]` `backend = "lokal"` und `modell_lokal = "qwen3:8b"` eintragen,
dann `uv run belege pruefen`. Dann schreibt auch die Texterkennung nichts mehr
mit Claude ab.
