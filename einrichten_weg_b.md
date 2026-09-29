# Weg B einrichten: eigenes Google-Projekt

**Nur abarbeiten, wenn die Person ausdrücklich Weg B verlangt hat.** Weg A
(App-Passwort) ist der Standard und reicht für das Belegsystem. Sag vorher
einmal: „Weg B dauert 20 bis 30 Minuten und hat mehrere Bestätigungen im
Browser. Dafür bekommst du getrennte Rechte (lesen, Entwürfe, senden), Gmail-
Labels und einen Zugang, den du einzeln widerrufen kannst. Sollen wir?“ Erst
bei Ja weitermachen.

Weg B geht nur mit Gmail oder Google Workspace.

## Was die Person im Browser macht, was du machst

Die Person klickt in der Google Cloud Console, du sagst ihr jeden Schritt
einzeln an und wartest, bis sie „erledigt“ sagt. Du erfindest keine
Menüpunkte: Sieht ihr Bildschirm anders aus, lass dir beschreiben, was dort
steht, und such den passenden Punkt.

1. https://console.cloud.google.com öffnen, mit dem Google-Konto des
   Postfachs anmelden. Oben „Projekt auswählen“ → „Neues Projekt“, Name
   `belege`, erstellen, dann auswählen.
2. Gmail-API einschalten: in der Suche oben „Gmail API“ → „Aktivieren“.
3. „Google Auth Platform“ (früher „OAuth-Zustimmungsbildschirm“) →
   „Jetzt starten“. App-Name `belege`, Support-Mail = eigene Adresse.
   Zielgruppe:
   - **Google Workspace mit eigener Domain und Admin-Rechten: „Intern“.**
     Dann gibt es keine 7-Tage-Grenze und keine Warnung.
   - **Privates @gmail.com: „Extern“.** Danach unter „Zielgruppe“ auf
     **„App veröffentlichen“ / „In Produktion“** stellen. Bleibt die App auf
     „Test“, läuft der Zugang nach 7 Tagen ab und der Belegabruf reißt ab.
4. „Clients“ → „Client erstellen“ → Anwendungstyp **Desktop-App**, Name
   `belege` → „JSON herunterladen“.
5. Du verschiebst die heruntergeladene Datei (`~/Downloads/client_secret_*.json`)
   nach `arbeit/geheim/google_client.json`, dann
   `chmod 700 arbeit/geheim` und `chmod 600 arbeit/geheim/google_client.json`.
   Den Inhalt liest du nicht.
6. `uv sync`
7. `uv run belege anmelden --konto geschaeft`. Der Browser öffnet sich
   **zweimal**: einmal für Lesen (samt Labels), einmal für Entwürfe und Senden. Bei „Extern“ zeigt Google „Google hat diese App nicht überprüft“.
   Das ist bei einer eigenen App für den eigenen Gebrauch normal: „Erweitert“ →
   „Weiter zu belege“. Alle Häkchen setzen.
8. In `konfig/belege.toml` beim Konto `weg = "b"` setzen. Das App-Passwort in
   `.env` kann bleiben oder von der Person gelöscht werden.
9. `uv run belege pruefen`: Die Zeile für das Konto muss GRÜN sein.
10. In Gmail ein Label `Beleg` anlegen lassen (die Person, in Gmail links
    „Neues Label“). Jede Mail mit diesem Label wird beim nächsten Lauf abgelegt,
    auch alte, und bekommt danach `Beleg/erledigt`.

## Wenn etwas nicht geht

- „Zugang abgelaufen“ nach einer Woche: Die App steht noch auf „Test“.
  Schritt 3 prüfen, dann Schritt 7 wiederholen.
- „Zugriff blockiert“ bei Workspace: Der Admin lässt keine eigenen Apps zu.
  Weg A nehmen oder den Admin fragen.
- Widerrufen: https://myaccount.google.com/permissions → `belege` →
  Zugriff entfernen. Das Postfach-Passwort bleibt unberührt.
