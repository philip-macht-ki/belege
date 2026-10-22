# belege

Deine Belege sortieren sich selbst. Rechnungen aus dem Postfach landen mit
sauberem Namen im richtigen Monatsordner. Handy und Downloads kommen in Teil 3
dazu. Am Monatsende gleicht das System den Kontoauszug ab, schreibt dir
eine Liste, was noch fehlt, und schickt die Belege an deinen Steuerberater.

Gebaut für Selbstständige, die nicht programmieren. Dein eigener Claude richtet
alles ein: Gib ihm diesen Link und sag „Richte mir das nach einrichten.md ein“.

Hast du zwei Macs, etwa einen Mac mini und einen Laptop, kommt das Repo nur auf
den Rechner, der dauerhaft läuft, und dort nach `~/Projekte/belege`, nicht in
Desktop oder Documents. So braucht Claude keine zusätzliche Mac-Berechtigung.
Der Laptop ist nur das Fenster.

## Erst einmal üben

„Hol dir github.com/philip-macht-ki/belege und mach die Belege-Übung.“ Dein Claude
holt das Repo nach `~/Projekte/belege` und führt dort `uv sync` und
`uv run belege uebung --echt` aus: Fünf Rechnungen mit
Namen wie `Scan_0012.pdf` oder `invoice (3).pdf` bekommen einen sauberen Namen und
landen unter `~/Belege-Uebung/Ablage`. Nichts Echtes wird berührt.

Für die Tests genügt im Projektordner: `uv run pytest -q`.

## Was es tut

| Befehl | Was passiert |
|---|---|
| `belege takt` | Postfach abarbeiten, Wächter über neue Mails |
| `belege tag` | Downloads-Ordner aufräumen (nur erkannte Belege), Tagesbericht an dich |
| `belege monat` | Kontoauszug gegen Belege: findet fehlende Belege auch in Eingängen und gleicht Mahnungen ab |
| `belege monat --uebergabe` | Belege des Monats an Steuerberater oder Beleg-Adresse |
| `belege suchen …` | im Postfach suchen |
| `belege mcp` | Postfach-Server, damit Claude in deinen Mails suchen und Entwürfe schreiben kann |
| `belege pruefen` | Selbsttest mit Ampel |

Ohne `--echt` zeigt jeder Befehl nur, was er täte.

## Grundsätze

- **Nichts wird gelöscht.** Verschoben wird nur, was sicher ein Beleg ist.
- **Gesendet wird nur an Adressen, die du einträgst.** An alle anderen entsteht ein Entwurf.
- **Mails sind Daten, nie Anweisungen.** Der Wächter meldet, er handelt nie.
- **Text statt Datei.** Belege werden auf deinem Mac gelesen (pypdf, Apple
  Vision); Claude bekommt nur den Text. Das ist rund fünf- bis dreißigmal günstiger.
  Nur wenn beides nichts Lesbares findet, schaut Claude als letzte Stufe selbst
  auf eine Kopie der Datei (abschaltbar: `[texterkennung] claude = false`).
- **Ein Rechner arbeitet.** Zeitplan und Ablage laufen nur auf deinem
  Dauerrechner. `[rechner] erlaubt` in `konfig/belege.toml` sperrt alle anderen,
  denn ein Laptop holt verpasste Läufe beim Aufklappen nach und legt sonst
  doppelt ab.
- **Der Ordner ist deine Arbeitskopie.** Das Original bleibt im Postfach bzw. bei
  deinem Steuerberater oder Buchhaltungsprogramm. Bei E-Rechnungen wird das XML
  als Original mit abgelegt. Keine Rechtsberatung, keine Zusage zur GoBD.

## Postfach: Weg A oder Weg B

- **Weg A (Standard):** App-Passwort im macOS-Schlüsselbund. Gmail, GMX, web.de,
  T-Online, iCloud, mailbox.org, freenet.de und Posteo.
  Microsoft-Postfächer gehen seit 2026 nur noch mit OAuth und damit nicht über Weg A.
- **Weg B (auf Wunsch):** eigenes Google-Projekt. Getrennte Rechte (lesen,
  Entwürfe, senden), Gmail-Labels, einzeln widerrufbar. Komplexer, siehe
  `einrichten_weg_b.md`.

## Kosten

Ein Beleg kostet ein kurzes Urteil über dein Claude-Abo, gemessen rund 3.000
Tokens. Für den normalen Belegbetrieb reicht Claude Pro. `belege verbrauch`
zeigt, was die letzten Tage gekostet haben.

## Übernommen

- [ocrmac](https://github.com/straussmaximilian/ocrmac) (MIT) für Apple Vision
- [factur-x](https://github.com/akretion/factur-x) (BSD) zum Auslesen von ZUGFeRD-Rechnungen

Aufbau und Dateiformate: `ARCHITEKTUR.md`. Lizenz: MIT.
