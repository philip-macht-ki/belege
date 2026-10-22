# Belege einrichten – Teil 1

Hallo. Heute richten wir nur das Postfach ein: Rechnungen landen danach von
allein in `~/Belege`. Das kurze Video aus Lektion 0-1 ist freiwillig.

Die Claude-App fragt bei einzelnen Schritten nach Erlaubnis, etwa wenn sie
einen Ordner anlegt. Du kannst für diese Sitzung „immer erlauben“ wählen, wenn
du das möchtest. Ohne deine Zustimmung passiert nichts.

## Erst prüft Claude still

Claude prüft Mac, freien Platz, die Claude-App und `uv`. Fehlt `uv`, nutzt
Claude den offiziellen Installer im Benutzerordner:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Danach führt Claude `uv sync`, `uv run belege einrichten-claude` und
`uv run belege pruefen` aus. Homebrew ist nicht nötig.

## Zwei Fragen

Claude fragt nur: Welche Mailadresse soll nach Rechnungen schauen? Wie heißt
dein Betrieb?

Bei Outlook, Hotmail, Live oder Microsoft 365 erklärt Claude sofort: Dieses
Postfach kann hier nicht direkt verbunden werden. Richte dort eine Weiterleitung
an ein Google-Konto ein; dieses Google-Konto verwenden wir dann für Rechnungen.

## App-Passwort

Claude öffnet die passende Seite. Du erzeugst das Passwort selbst und fügst es
danach in das kleine Mac-Fenster ein. Es wird verdeckt eingegeben und nur im
Schlüsselbund deines Macs gespeichert, nicht in einer Datei.

- Gmail: <https://myaccount.google.com/apppasswords>. Falls die Seite es sagt,
  schaltest du zuerst die Bestätigung in zwei Schritten ein.
- GMX und web.de: In den Mail-Einstellungen zuerst IMAP einschalten, dann ein
  App-Passwort anlegen.
- T-Online: Im E-Mail-Center ein Passwort für E-Mail-Programme anlegen.
- iCloud, me.com und mac.com: <https://account.apple.com> öffnen, dann
  „Anmeldung und Sicherheit“ und „App-spezifische Passwörter“ wählen.

Claude trägt Adresse und Betriebsnamen ein und führt anschließend aus:

```sh
uv run belege anmelden --schluesselbund geschaeft
```

Der Schlüsselbunddialog zeigt die richtige Adresse. Bei Abbruch bleibt alles
unverändert. Technische Grenze: macOS nimmt das Passwort bei `security` als
kurzlebigen Programmparameter entgegen; belege schreibt oder protokolliert es
nie.

## Die erste Übung und der erste Lauf

Die Ablage ist `~/Belege`. Das braucht keine zusätzliche Mac-Berechtigung. Wir
wählen heute weder Downloads noch Handy noch einen Cloud-Ordner aus.

1. Claude legt die Übung an und zeigt sie: `uv run belege uebung --echt`.
2. Claude schaut trocken ins echte Postfach: `uv run belege postfach`.
3. Claude fragt klar „Soll ich die erkannten Belege jetzt ablegen?“ Erst nach
   deinem „Ja“ folgt `uv run belege postfach --echt`.
4. Claude schaltet den Takt erst nach deiner Zustimmung ein:
   `BELEGE_JA=1 uv run belege zeitplan an --echt`.
5. Claude prüft den Bericht und zeigt `uv run belege pruefen` noch einmal.

Fertig. Ab jetzt landen deine Belege von allein in `~/Belege`.

## Erst in Teil 2: Monat und Jahr

Kontoauszüge, Monatsabschluss, Steuerberater und Jahresübersicht richten wir
erst in Teil 2 ein.

## Erst in Teil 3: Handy, Downloads, Cloud und Ablage

Handy-Ordner, Downloads, Cloud-Ordner, Verträge und Fristen gehören zu Teil 3.
Dann braucht der tatsächlich gestartete Zeitplan möglicherweise
Festplattenvollzugriff. Die Vorlagen starten `/bin/zsh`, das wiederum `uv run
belege` ausführt. Claude öffnet die Systemeinstellungen mit:

```sh
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
```

Claude erklärt dort, welchem gestarteten Programm der Schalter gilt, du setzt
ihn selbst, danach folgt ein harmloser Lesetest. Das Verhalten auf einem frischen
Mac wird vor dem Einsatz noch einmal geprüft.

## Erst in Teil 4: weitere Postfachwege

Eigene Google-Projekte, weitere Konten und der Postfach-Assistent gehören zu
Teil 4.
