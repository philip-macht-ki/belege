# Änderungen für dich

Git-Tags tragen bei jeder Veröffentlichung die Versionsnummer, zum Beispiel `v1.4.0`.

## [1.9.1] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Postfach über App-Passwort (IMAP, etwa mailbox.org, GMX, eigene Domain): belege findet Rechnungen im Anhang wieder. Bisher sah es dort keine Anhänge und holte deshalb nichts.
- belege sucht Rechnungen jetzt in allen Ordnern deines Postfachs, nicht mehr nur im Posteingang. Wenn deine Filter oder Outlook-Regeln Rechnungen sofort in Unterordner verschieben, findet belege sie trotzdem. Gesendet, Papierkorb, Spam und Entwürfe bleiben außen vor. Das gilt für App-Passwort-Postfächer und für Microsoft 365 und Outlook.
- Bei viel Post fielen ältere Rechnungen heraus, weil nur die 20 neuesten Mails angesehen wurden. Jetzt sind es bis zu 500, in jedem Postfach.
- ZUGFeRD-Rechnungen (PDF mit eingebetteter XML, etwa von Sage) brechen nicht mehr ab.
- Wer Claude nur über die Desktop-App hat: Der Zeitplan erreicht Claude wieder. Der Starter in `~/.local/bin` erneuert sich beim nächsten Lauf von selbst.
- Neue Einrichtungen: Downloads sind ab Werk aus und kommen erst in Teil 3 dazu. Der Musterbetrieb verkürzt den ersten echten Postfachlauf nicht mehr. Die Übung braucht kein Homebrew mehr und startet nach einem Abbruch sauber neu.

Danke an Nina Clausen für die genaue Fehlermeldung samt Korrekturen.

### Musst du etwas tun?

Nein. Der nächste Lauf schaut einmal die letzten Tage in allen Ordnern nach; was schon abgelegt ist, erkennt belege und legt es nicht doppelt ab.

## [1.9.0] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Verträge, Versicherungen und Briefe vom Amt oder von der Bank bleiben nicht mehr liegen. Kommt so ein Dokument per Mail, als Foto in deinen Handy-Ordner, über deinen Scan-Ordner (Papierpost, Dropscan) oder landet es in Downloads, legt belege es selbst in deine Dokumentenablage: `Dokumente/Vertrag/…`, `Dokumente/Versicherung/…`, `Dokumente/Behörde/…` und so weiter.
- Kündigungsfristen und Zahlungstermine aus diesen Dokumenten stehen danach in deiner Fristenliste. Im Tagesbericht siehst du unter „Dokumente abgelegt“, was neu dazugekommen ist, mit der nächsten Frist.
- belege legt nur ab, wenn es sich sicher ist. Aus Mails und Downloads nimmt es nur klare Fälle (Vertrag, Versicherung, Behörde, Bank); Werbung, Newsletter und AGB bleiben, wo sie sind. Unsicheres landet wie bisher unter „Unsortiert“ oder bleibt liegen.
- Vertrauliches, etwa ein Arztbrief, liest weiterhin nur dein Mac. Im Tagesbericht steht dann nur der Ordner, nicht der Name.

### Musst du etwas tun?

Nein. Willst du Dokumente lieber nur von Hand ablegen, schreib in `konfig/belege.toml` unter `[dokumente]` die Zeile `automatisch = false`.

## [1.8.1] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Der Rundfunkbeitrag fehlt im Monatsabgleich nicht mehr jeden Monat. Liegt der Bescheid oder die Anmeldebestätigung des Beitragsservice in deinen Dokumenten, gilt er als Dauerbeleg, solange die Beitragsnummer übereinstimmt.

### Musst du etwas tun?

Nein. Wenn du den Bescheid noch nicht abgelegt hast: Foto oder Scan in deinen Handy- oder Scan-Ordner, den Rest macht belege.

## [1.8.0] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Manche Anbieter schicken die Rechnung nicht als PDF im Anhang, sondern nur als Link („Rechnung herunterladen“), zum Beispiel über Stripe. belege holt solche Rechnungen jetzt selbst und legt sie ab wie einen Anhang.
- Das passiert nur, wenn die Mail nach Rechnung aussieht und genau einen passenden Link hat. Geladen wird nur über eine sichere Verbindung (https), nur ein echtes PDF und nur von öffentlichen Adressen. Abmelde-, Login- oder Konto-Links öffnet belege nie.
- Sieht eine Mail nach Abofalle aus (etwa ein Branchenbuch-Eintrag mit Rückfax), öffnet belege den Link nicht und warnt dich im Tagesbericht.
- Rechnungen, die nur nach Anmeldung im Kundenportal liegen, kann belege weiterhin nicht holen. Die bleiben auf deiner Liste „fehlt“.

### Musst du etwas tun?

Nein. Willst du das nicht, schreib in `konfig/belege.toml` unter `[quellen]` die Zeile `rechnungslinks = false`.

## [1.7.3] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Papierpost über Dropscan, Caya oder eine Scan-App: belege liest jetzt auch die Unterordner deines Scan-Ordners, so wie Dropscan sie je Scanbox und Tag anlegt. Die Anleitung erklärt, wie du die Weiterleitung von Dropscan an Google Drive, Dropbox oder OneDrive einschaltest. Eingescannte Briefe findet dein Claude danach wie jeden anderen Beleg.

### Musst du etwas tun?

Nein. Nutzt du Dropscan und hast den Ordner noch nicht eingetragen, sag deinem Claude: Richte meine Papierpost von Dropscan ein.

## [1.7.2] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Holst du deine Kreditkartenumsätze auf zwei Wegen, etwa als CSV von amex.de und zusätzlich über MoneyMoney, zählt der Abgleich jede Buchung nur noch einmal. Vorher konnten Belege doppelt als „fehlt“ gemeldet werden, weil beide Exporte den Händler verschieden schreiben.

### Musst du etwas tun?

Nein.

## [1.7.1] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Schickt dir dein Steuerberater eine BWA, eine Auswertung oder eine Liste mit Rückfragen, legt belege sie nicht mehr als Rechnung ab. Sie landen bei den Unterlagen zum Ansehen und gehen nicht zurück an den Steuerberater.

### Musst du etwas tun?

Nein.

## [1.7.0] – 28.10.2026

aktion: keine

### Was ist neu für dich

- Microsoft-Postfächer gehen jetzt auch ohne eigene App: Mit Philips App meldest du dich einfach einmal im Browser an und stimmst zu. Das klappt auch für private Outlook.com- und Hotmail-Postfächer. Die eigene App deiner Firma bleibt als Weg für mehr Kontrolle und Privatsphäre.

### Musst du etwas tun?

Nein. Läuft dein Microsoft-Postfach heute über eine Umleitung an Gmail, sag deinem Claude: Stell mein Postfach auf den direkten Microsoft-Weg um.

## [1.6.0] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Outlook- und Microsoft-365-Postfächer lassen sich jetzt direkt verbinden: mit einer eigenen App deiner Firma bei Microsoft (etwa 15 Minuten, Claude führt dich durch und klickt auf Wunsch im Browser mit), danach einmal im Browser anmelden. Kein App-Passwort, keine Umleitung an Gmail.
- Die Umleitung an ein Gmail-Konto bleibt als Rückfall.

### Musst du etwas tun?

Nein. Läuft dein Microsoft-Postfach heute über eine Umleitung an Gmail und willst du sie loswerden, sag deinem Claude: Stell mein Postfach auf den direkten Microsoft-Weg um.

## [1.5.4] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Liegt dein Postfach bei Microsoft (Outlook, Microsoft 365), führt dich Claude jetzt Schritt für Schritt durch die Umleitung deiner Rechnungen an ein eigenes Gmail-Konto, inklusive der Microsoft-Sperre für Weiterleitungen nach außen.

### Musst du etwas tun?

Nein.

## [1.5.3] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Das Zusatzpaket mit Monatszahlen und Fragen an deine Zahlen heißt jetzt Kassensturz. Der Hinweis bei pausierten Updates nennt den neuen Namen.

### Musst du etwas tun?

Nein.

## [1.5.2] – 27.10.2026

aktion: sicherheit

### Was ist neu für dich

- Verdächtige Branchenbuch- und Adressbuch-Angebote landen im Ordner `Vorsicht Abofalle`, nicht zwischen deinen Belegen. Im Tagesbericht steht: nicht unterschreiben, nicht zahlen.
- PDFs mit aktiven Inhalten (Skripte, eingebettete Programme) landen im Ordner `Vorsicht Datei prüfen` und werden nicht an DATEV oder den Steuerberater übergeben. E-Rechnungen mit eingebetteten Rechnungsdaten (ZUGFeRD, XRechnung) gehen wie gewohnt durch.

### Musst du etwas tun?

Nein. Sieh bei einem Hinweis kurz in den Ordner `Vorsicht Abofalle` oder `Vorsicht Datei prüfen`.

## [1.5.1] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Der Hinweis zu pausierten automatischen Updates nennt jetzt, wo es Agent Plus gibt.

### Musst du etwas tun?

Nein.

## [1.5.0] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Vertrauliche Post (Arzt, Gericht, Krankenkasse, Personal) erkennt belege selbst und liest sie nur auf deinem Mac, nie mit einem Cloud-Modell. Du findest sie im Tagesbericht unter „Bitte ansehen“.
- Dein MacBook darf zu sein: War es länger zu, holt belege alle Mails seitdem nach. Ohne Netz bleibt ein Beleg liegen, statt halb erkannt abgelegt zu werden.
- Das Lebenszeichen unterscheidet „Mac war zu“ (kein Alarm) von einem echten Fehler.
- `uv run belege rechner` zeigt, welcher Mac das ist.
- Automatische Updates laufen vier Wochen ab der Einrichtung. Danach kommen nur noch Sicherheitsupdates von allein, alles andere holst du mit `uv run belege aktualisieren --echt` oder dauerhaft automatisch mit Agent Plus.

### Musst du etwas tun?

Nein.

## [1.4.1] – 27.10.2026

aktion: keine

### Was ist neu für dich

- War dein Mac am Sonntagmorgen zugeklappt oder aus, holt er die Update-Prüfung beim nächsten Start nach.

### Musst du etwas tun?

Nein.

## [1.4.0] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Belege prüft sonntags, ob es Verbesserungen gibt, und spielt sichere Updates selbst ein.
- Deine Einstellungen, Zeitpläne und Zugangsschlüssel bleiben dabei erhalten.

### Musst du etwas tun?

Nein.

## [1.3.0] – 27.10.2026

aktion: keine

### Was ist neu für dich

- Du kannst offene Zahlungen einfach per Rückfrage klären.
- Mehrere Konten und Kreditkarten können getrennt im Monatsabgleich stehen.

### Musst du etwas tun?

Nein. Mehrere Konten richtest du nur ein, wenn du sie nutzen möchtest.

## [1.2.0] – 26.10.2026

aktion: keine

### Was ist neu für dich

- Eigene Mailadressen wie `info@meinbetrieb.de` werden beim Einrichten besser erkannt.
- Claude kann in abgelegten Belegen suchen.
- Wenn der regelmäßige Lauf ausbleibt, kann ein Lebenszeichen Bescheid geben.

### Musst du etwas tun?

Nein.

## [1.1.0] – 26.10.2026

aktion: keine

### Was ist neu für dich

- MoneyMoney kann Kontoumsätze auf Wunsch automatisch als CSV bereitstellen.
- Der Monatsabgleich liest Konto und Kreditkarte zusammen.

### Musst du etwas tun?

Nein. MoneyMoney ist freiwillig; sag deinem Claude: „MoneyMoney einrichten“.
