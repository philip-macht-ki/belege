# Freiwillig: Verarbeitung in der EU

Kein Workshop-Schritt. belege funktioniert ohne. Hier steht, wie die automatischen
Läufe (Belege einordnen, Wächter, Monatslauf) über ein Cloud-Konto in der EU
laufen statt über das Claude- oder ChatGPT-Abo. Den ganzen Ablauf mit Kosten und
Nachteilen führt das Werkzeug `datenschutz` von Philip macht KI
(„Philip macht KI, richte mit mir den Datenschutz ein.“).

Wichtig: belege startet Claude und Codex bewusst ohne die persönlichen
Einstellungen des Nutzers (`--setting-sources ""` bzw. `--ignore-user-config`).
Was nur in den Einstellungen der App steht, gilt in den Zeitplänen nicht. Deshalb
gehört der EU-Weg in die Datei `.env` im belege-Ordner (Rechte 600). Schlüssel
fügt die Person selbst ein, kein Agent tippt oder liest sie.

## Mit Claude: Amazon Bedrock

1. AWS-Konto, Region Europe (Frankfurt) `eu-central-1`, Kostenwarnung in AWS Budgets.
2. In Claude Code `/setup-bedrock` für die Arbeit am Tag
   (Anleitung: https://code.claude.com/docs/en/amazon-bedrock).
3. Für die Zeitpläne einen eigenen AWS-Benutzer nur mit Bedrock-Rechten und dessen
   Zugangsschlüssel. Die Anmeldung im Browser hält höchstens zwölf Stunden und
   reicht für nächtliche Läufe nicht.
4. In `.env`:

```
CLAUDE_CODE_USE_BEDROCK=1
AWS_REGION=eu-central-1
ANTHROPIC_DEFAULT_SONNET_MODEL=eu.anthropic.claude-sonnet-5-5
AWS_ACCESS_KEY_ID=…
AWS_SECRET_ACCESS_KEY=…
```

`[urteil] backend` bleibt `claude`, `modell` bleibt `sonnet`.

## Mit ChatGPT: Microsoft Azure

1. Azure-Konto, in Azure AI Foundry eine Ressource und ein Deployment mit dem
   Bereitstellungstyp „Data Zone Standard“ in einer EU-Region, mit einem
   allgemeinen GPT-Modell aus der EU-Liste von Microsoft (Modelle mit „codex“ im
   Namen gibt es dort derzeit nicht). Kostenwarnung in Azure Budgets.
   Anleitung: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex
2. In `.env`:

```
AZURE_OPENAI_BASE_URL=https://<ressource>.openai.azure.com/openai/v1
AZURE_OPENAI_API_KEY=…
```

3. In `konfig/belege.toml`: `[urteil] backend = "codex"` und
   `modell_codex = "<Name des Deployments>"`.

Die Codex-App bleibt beim ChatGPT-Konto; nur belege läuft über Azure. Die
Codex-App selbst unterstützt Azure laut Microsoft nicht.

## Prüfen

`uv run belege pruefen`, dann ein Trockenlauf. In `arbeit/urteile.jsonl` steht
das Backend jedes Urteils.
