# Belege einrichten Teil 1

Hallo. Heute richten wir nur das Postfach ein: Rechnungen landen danach von
allein in `~/Belege`. Das kurze Video aus Lektion 0-1 ist freiwillig.

Das Projekt liegt in `~/Projekte/belege`, nicht in Desktop oder Documents. So
braucht Claude keine zusätzliche Mac-Berechtigung für den Projektordner.

Die Claude-App fragt bei einzelnen Schritten nach Erlaubnis, etwa wenn sie
einen Ordner anlegt. Du kannst für diese Sitzung „immer erlauben“ wählen, wenn
du das möchtest. Ohne deine Zustimmung passiert nichts.

## Erst prüft Claude still

Claude prüft Mac, freien Platz, die Claude-App und `uv`. Fehlt `uv`, nutzt
Claude den offiziellen Installer im Benutzerordner:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Danach führt Claude `uv sync`, `uv run belege einrichten-urteil` und
`uv run belege pruefen` aus. Homebrew ist nicht nötig.

## Welcher Weg ordnet ein?

Bist du Claude, bleibt `claude` wie bisher eingestellt; frage dazu nichts.
Bist du Codex (oder hat die Person kein Claude-Abo), frag sie, ob das Einordnen
auf ihrem Mac (lokal) oder über ihr ChatGPT-Abo (codex) laufen soll. Prüfe erst
den Arbeitsspeicher mit `sysctl -n hw.memsize` und gib eine Empfehlung: ab 32 GB
lokal mit `qwen3:14b`, bei 16 bis 31 GB ist lokal mit `qwen3:8b` möglich,
darunter codex. Lokal verlässt nichts den Mac und kostet nichts, ist aber etwas
langsamer und erkennt etwas weniger. Codex schickt Absender, Betreff und
Belegtext an OpenAI und läuft über das Abo.

Bei lokal: Installiere Ollama über <https://ollama.com> (die App), hole das
Modell mit `ollama pull …` und trage `backend = "lokal"` sowie `modell_lokal`
ein. Bei codex: Trage `backend = "codex"` ein. Danach führe
`uv run belege einrichten-urteil` und `uv run belege pruefen` aus.

## Schritt 1: die Übung, dann anhalten

Die Ablage ist `~/Belege`. Das braucht keine zusätzliche Mac-Berechtigung. Wir
wählen heute weder Downloads noch Handy noch einen Cloud-Ordner aus.

Claude legt den Übungsordner an und zeigt, was aus jeder der fünf erfundenen
Rechnungen geworden ist: `uv run belege uebung --echt`. Die Übung liest kein
Postfach und verschickt keine Mail.

**Danach hält Claude an.** Er sagt, dass die Übung fertig ist, und richtet
Postfach und Zeitplan erst ein, wenn die Person ausdrücklich weitermachen will,
etwa mit „Verbinde mein Postfach“ oder „weiter“. Die Kurslektionen gehen in
genau diesen Schritten vor.

Möchte die Person vorher den Musterbetrieb sehen (Lektion 0-2), legt Claude ihn
mit `uv run belege beispiel` an, zeigt `uv run belege takt` und
`uv run belege tag` trocken und lässt beides erst nach einem ausdrücklichen Ja
mit `--echt` laufen. Danach fragt er nach Betriebsname, weiteren Schreibweisen,
Tätigkeit, USt-IdNr und ob Privatbelege getrennt abgelegt werden, trägt alles
ein und hält wieder an.

## Schritt 2: Postfach verbinden, erst nach ausdrücklichem Weiter

Claude fragt nur: Welche Mailadresse soll nach Rechnungen schauen? Wie heißt
dein Betrieb, falls das noch nicht eingetragen ist?

Bei Outlook, Hotmail, Live oder Microsoft 365 erklärt Claude sofort: Dieses
Postfach kann hier nicht direkt verbunden werden. Richte dort eine Weiterleitung
an ein Google-Konto ein; dieses Google-Konto verwenden wir dann für Rechnungen.
Leite nur Rechnungen weiter, nicht das ganze Postfach.

Bevor Claude zum ersten Mal ins Postfach schaut, fragt er: Gibt es Absender mit
vertraulichen Unterlagen, etwa Mandanten oder Patienten? Die trägt er in
`ausschluss` in `konfig/regeln.toml` ein. Von ihnen lädt das System keinen
Anhang, und auch der Wächter liest sie nicht.

### App-Passwort

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

Dann prüft Claude mit `uv run belege pruefen` und schaut trocken ins echte
Postfach: `uv run belege postfach`. Er zeigt die gefundenen Betreffzeilen und
**hält wieder an**. Abgelegt wird erst nach einem klaren „Ja, ablegen“ mit
`uv run belege postfach --echt`.

## Schritt 3: Zeitplan, erst nach ausdrücklichem Weiter

Claude schaltet den Takt erst ein, wenn die Person es ausdrücklich will, etwa
mit „Richte den Belege-Zeitplan ein“: `BELEGE_JA=1 uv run belege zeitplan an --echt`.
Er trägt dabei die Rechner-Sperre ein, damit nur dieser Mac ablegt, und sagt,
dass der Wächter jede neue Mail einmal ansieht (Absender, Betreff, Anfang des
Textes gehen dafür an Claude) und wie man ihn ausschaltet (`waechter = false` beim Konto). Zum Schluss zeigt er
`uv run belege zeitplan zeigen` und `uv run belege pruefen` noch einmal.

Fertig. Ab jetzt landen deine Belege von allein in `~/Belege`.

## Erst in Teil 2: Monat und Jahr

Kontoauszüge, Monatsabschluss, Steuerberater und Jahresübersicht richten wir
erst in Teil 2 ein.
`belege monat` sucht dann fehlende Belege selbst in Postfach, Downloads,
Eingängen und Scan-Ordner und gleicht Mahnungen gegen das Konto ab.

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

Papierpost (optional): **Frag**, ob Briefe auf Papier kommen. Bei wenigen Briefen genügt ein Foto
wie bei einem Kassenbon im Handy-Eingang. Bei vielen oder regelmäßigen Briefen
nutzt du einen Scan-Dienst (zum Beispiel Dropscan oder Caya, kostenpflichtig)
oder eine Scan-App. Deren Zielordner kommt unter `[quellen]` als `scan_ordner`
in `konfig/belege.toml`; danach läuft `uv run belege pruefen`.

## Erst in Teil 4: weitere Postfachwege

Eigene Google-Projekte, weitere Konten und der Postfach-Assistent gehören zu
Teil 4.
