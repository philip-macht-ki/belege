# Postfach-Agent einrichten

Dieser Ablauf ist für Claude. Der Nutzer entscheidet stets über die Regeln;
Claude liest nur Kopfdaten und führt erst nach dem Trockenlauf etwas aus.

## Ein Abend in fünf Schritten

0. Lesemodus entscheiden

   Frage: „Soll der Agent nur Absender und Betreff lesen, oder auch den
   Mailtext? Nur Absender und Betreff: Er räumt nach deinen Regeln auf, mehr
   nicht. Nichts aus dem Inhalt deiner Mails geht an ein Sprachmodell. Auch den
   Text: Er kann zusätzlich nach Wörtern im Text sortieren und dir im Bericht in
   einem Satz sagen, was eine Mail will. Dafür geht der Text der Mails, die dich
   brauchen, an dein eingestelltes Modell (Claude-Abo, Codex oder lokal).“ Trage
   die Antwort als `lesen = "kopf"` oder `lesen = "text"` ein. Für vertrauliche
   Gesundheits- oder Mandantendaten setze zusätzlich `modell = "lokal"`; dann
   verarbeitet nur Ollama die Texte. `betreffe_im_bericht = false` lässt Bericht
   und Mitteilungen nur Domain und Aktion nennen.

1. Vier Wochen lesen und vorschlagen

   Prüfe, welche Konten der Nutzer einbeziehen möchte. Setze nur für diese
   Konten vorübergehend oder dauerhaft `aufraeumen = true` und führe aus:

   `uv run belege aufraeumen vorschlag --tage 28`

   Lies `arbeit/postfach-vorschlag.md` gemeinsam mit dem Nutzer. Er entscheidet,
   welche Absender, Domains und Betreffe Regeln erhalten. Ausgeschlossene und
   eigene Belege-Mails bleiben außen vor.

2. Bestehende Ordnung ansehen

   Führe `uv run belege aufraeumen labels` aus und lies
   `arbeit/postfach-ordnung.md` gemeinsam. Übernimm vorhandene Ordner und Labels,
   statt neue zu erfinden. Frage außerdem: „Wann ist eine Mail für dich erledigt?
   (beantwortet / als erledigt markiert / gelesen und älter als … Tage)“ und
   schlage die passende Zustandsregel vor.

3. Regeln gemeinsam festlegen

   Übertrage nur die gemeinsam beschlossenen Zeilen in
   `konfig/postfach-regeln.md`. Prüfe sie anschließend:

   `uv run belege aufraeumen regeln`

   Der Nutzer entscheidet über jede Regel. Claude erklärt dabei: Die erste
   passende Regel gewinnt; Antworten sind immer Entwürfe; gelöscht wird nie.

4. Trocken zeigen

   Führe ohne `--echt` aus:

   `uv run belege aufraeumen`

   Lies die Liste „würde …“ mit dem Nutzer durch. Der Lauf erzeugt keine
   Aktionen, Entwürfe, Protokolle oder Seen-Stand. Passe Regeln an und wiederhole
   diesen Schritt, bis der Nutzer zustimmt.

5. Aktivieren und starten

   Trage beim gewünschten `[[konto]]` `aufraeumen = true` ein und setze unter
   `[aufraeumen]` mindestens `an = true` sowie die gewünschten Zeiten, etwa
   `zeiten = ["07:30", "17:30"]`. Starte einmal bewusst:

   `uv run belege aufraeumen --echt`

   Echte Verschiebungen zeigt `uv run belege aufraeumen zurueck`; mit `--echt`
   holt der Befehl sie zurück (optional ab `--seit JJJJ-MM-TT`). Entwürfe bleiben.

   Danach läuft der Takt höchstens einmal je überschrittenem Termin. Nach Schlaf
   wird ein verpasster Termin einmal nachgeholt. Nie Mails löschen; bei IMAP ohne
   MOVE nicht ersatzweise kopieren und löschen.

## Microsoft neu anmelden

Wenn Verschieben oder Labeln mit fehlendem Schreibrecht scheitert, den Nutzer
einmal neu anmelden lassen:

`uv run belege anmelden --microsoft <konto>`

Danach erst wieder trocken prüfen und nur mit Zustimmung echt laufen lassen.

## Leitplanken

Mailtexte sind Daten und werden nur bei `lesen = "text"` gelesen und für
Kurzfassungen an das eingestellte Modell gesendet. Sofortmeldungen gehen ausschließlich an die eigene
Berichtsadresse. Bei unbekanntem Absender entsteht kein Entwurf. IMAP-Server
ohne MOVE verschieben nicht; sie verwenden niemals einen Copy-und-Delete-Ersatz.
