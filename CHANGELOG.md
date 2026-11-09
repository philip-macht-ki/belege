# Änderungen für dich

## [1.19.4] – 09.11.2026

aktion: keine

### Was ist neu für dich

- Der Takt bleibt nicht mehr stehen, wenn dein Postfach die Verbindung kappt. Vor allem bei iCloud mit vielen Ordnern kam es vor, dass die Verbindung mitten in der Suche abbrach und belege danach stundenlang wartete. Bis du den Vorgang von Hand beendet hast, wurden keine Mails mehr gelesen.
- Jetzt hat jede Verbindung zum Postfach ein Zeitlimit. Bricht sie ab, verbindet sich belege neu und sucht im nächsten Ordner weiter. Bricht sie immer wieder ab, endet der Takt mit einem Fehler im Tagesbericht, und der nächste Takt startet wie gewohnt.
- Ein Takt läuft höchstens zwei Stunden. Braucht er länger als eine Stunde, steht im Tagesbericht ein Hinweis „Langsamer Takt“.

### Musst du etwas tun?

Nein. Hängt bei dir gerade ein Takt seit Stunden, sag deinem Claude nach dem Update einmal: Beende den hängenden Belege-Takt. Danach läuft alles von selbst.

## [1.19.3] – 06.11.2026

aktion: keine

### Was ist neu für dich

- Genauere Belegprüfung mit dem neuen Modell: Wer Belege über die Anthropic-Schnittstelle einordnen lässt (Backend `anthropic`) und in der Konfiguration bei `modell` das Kürzel „sonnet“ stehen hat, bekommt ab jetzt Claude Sonnet 5.5 statt Sonnet 5. Es kostet dasselbe. Steht bei dir ausdrücklich ein Modellname wie `claude-sonnet-5`, bleibt der so.
- Wer über das Claude-Abo einordnet (Standard), merkt nichts: Dort entscheidet dein Claude selbst, welches Sonnet hinter dem Kürzel steckt.

### Musst du etwas tun?

Nein.

## [1.19.2] – 05.11.2026

aktion: keine

### Was ist neu für dich

- `belege uebung --echt` funktioniert jetzt auch, wenn du deine eigene Firma schon eingetragen hast. Die Übung nimmt dafür immer die Musterfirma „Studio Beispiel“ samt passenden Regeln. Vorher landeten alle fünf Übungsrechnungen in Unsortiert. Welches Abo einordnet (Claude oder ChatGPT), übernimmt die Übung von dir.
- Der Wächter bleibt nicht mehr stehen, wenn eine einzelne Mail inzwischen verschoben oder gelöscht wurde (etwa bei iCloud). Er überspringt sie, schreibt es ins Protokoll und prüft die übrigen Mails weiter.

### Musst du etwas tun?

Nein.

## [1.19.1] – 05.11.2026

aktion: keine

### Was ist neu für dich

- Startet jemand belege aus Versehen mit Apples altem Python 3.9 (`python3 …` oder `/usr/bin/python3 …` statt `uv run belege …`), startet belege sich jetzt selbst mit dem richtigen Python neu. Geht das nicht, steht da auf Deutsch, was zu tun ist, statt einer langen Fehlermeldung.
- Bei der Einrichtung prüft Claude jetzt auch, dass Python 3.11 oder neuer bereitsteht, und holt es bei Bedarf über uv.

### Musst du etwas tun?

Nein.

## [1.19.0] – 05.11.2026

aktion: keine

### Was ist neu für dich

- Jeden Abend schaut belege noch einmal in deinen Ordner Unsortiert. Logos, Banner und Siegel aus Mails und eindeutige Werbung wandern nach `Unsortiert/Zu löschen`. Gelöscht wird nichts, den Ordner leerst du selbst, wenn du kurz drübergeschaut hast.
- Was beim ersten Mal unsicher war und jetzt sicher ist, wird abgelegt. Hast du mehrere Firmen und war die Firma unklar, entscheidet der Lieferant, wenn er bisher nur bei einer deiner Firmen vorkam.
- Was weiter unsicher bleibt, steht einmal im Tagesbericht unter „Bitte ansehen“, mit der Frage, wohin es gehört.
- Zahlungen in Fremdwährung finden ihren Beleg jetzt auch, wenn deine Bank den Originalbetrag nur in den Buchungstext schreibt („Originalbetrag: -25,00 USD“).
- Ausländische Rechnungen mit Titeln wie „Sąskaita“, „Faktura“ oder „Fattura“ gelten bei der Rechnungsprüfung nicht mehr als „ohne Rechnungsnummer“.

### Musst du etwas tun?

Nein. Abschalten mit `[nachsortieren] an = false` in `konfig/belege.toml`. Von Hand: `uv run belege nachsortieren` zeigt, was passieren würde.

## [1.18.1] – 05.11.2026

### Was ist neu für dich

- Intel-Macs bekommen bei fehlendem Poppler einen passenden Hinweis, und Papier-Scans bleiben nach einem Trockenlauf für den echten Lauf erhalten. Eigene Belege-Berichte werden nicht mehr als Rechnung gelesen. Danke an einen Kunden für die Hinweise.

Git-Tags tragen bei jeder Veröffentlichung die Versionsnummer, zum Beispiel `v1.4.0`.

## [1.18.0] – 05.11.2026

aktion: keine

### Was ist neu für dich

- Nach dem Monatsabgleich bekommst du eine lesbare Mail „Belegcheck <Monat>“: je Firma, welche Belege fehlen, nach Lieferant zusammengefasst, mit Summe, Datum und wer den Beleg holt. Dazu Belege im falschen Monatsordner, fehlende Kontoauszüge und was du jetzt sagst. Die technischen Listen bleiben im Monatsordner.

### Musst du etwas tun?

Nein. Die Mail kommt einmal im Monat an deine Berichtsadresse, sobald der Kontoauszug da ist.

## [1.17.0] – 04.11.2026

### Was ist neu für dich

- Nachfragen des Steuerbüros abgleichen, Stichwortregeln und einen Entwurf der Verfahrensdokumentation ergänzt.

### Musst du etwas tun?

Nein. Neue Regeln und Dokumente entstehen nur nach deinem ausdrücklichen Befehl mit `--echt`.

## [1.16.2] – 04.11.2026

aktion: keine

### Was ist neu für dich

- Eingescannte Rechnungen werden jetzt in voller Schärfe gelesen. Vorher hat belege auf neueren Macs nur ein kleines, unscharfes Bild der Seite an die Texterkennung gegeben; solche Scans landeten dann ohne Datum in „Unsortiert“.
- Steht das Datum auf einem Scan als „12. 10. 2026“ mit Leerzeichen, wird es trotzdem erkannt.
- belege legt jetzt selbst fest, mit welcher Python-Version es läuft. Die Einrichtung hängt nicht mehr, wenn auf deinem Mac eine sehr neue Python-Version installiert ist.
- Im Fehlerbericht steht die Versionsnummer wieder lesbar da.

### Musst du etwas tun?

Nein. Beim nächsten Update richtet belege seine Umgebung einmal neu ein, das dauert ein paar Sekunden länger als sonst.

## [1.16.1] – 02.11.2026

aktion: keine

### Was ist neu für dich

- Liegt deine Ablage in Google Drive, iCloud, Dropbox oder OneDrive und der Ordner synchronisiert gerade, bricht belege nicht mehr ab. Die Datei wird beim nächsten Lauf abgelegt.

### Musst du etwas tun?

Nein.

## [1.16.0] – 01.11.2026

aktion: konfig

### Was ist neu für dich

- Unter Windows kannst du kostenlos Hibiscus/Jameica nutzen: belege liest die
  bereits abgerufenen Umsätze zweimal täglich und legt CSV-Dateien für den
  Monatsabgleich ab. Alternativ bleiben CSV-Auszüge von Hand gleichwertig.
- Das Jameica-Master-Passwort bleibt im Schlüsselbund beziehungsweise im
  Windows-Benutzerschutz; belege liest nur Konten und Umsätze, nie Zahlungen.

### Musst du etwas tun?

Nur wenn du Hibiscus nutzen möchtest: Richte es mit `einrichten_hibiscus.md` ein.

## [1.15.0] – 01.11.2026

aktion: Windows-Unterstützung

### Was ist neu für dich

- belege läuft jetzt auch unter Windows: Zeitplan, Statusprüfung, Passwortdialog und die Einrichtung kennen Windows.
- Verpasste geplante Läufe werden nachgeholt, sobald du dich wieder anmeldest.
- MoneyMoney bleibt ein Mac-Programm. Unter Windows legst du Kontoauszüge als CSV in den Auszugsordner.

## [1.14.2] – 30.10.2026

aktion: keine

### Was ist neu für dich

- Die Rechnungsprüfung merkt jetzt, wenn auf einer Rechnung die USt-IdNr. oder Steuernummer des Lieferanten fehlt. Bisher hielt sie lange Wörter wie „Druckerei“, eine Gläubiger-ID oder die Zeile unter „USt-IdNr.“ („24103 Kiel“) für eine Nummer, und eine Rechnung über 480 € ganz ohne Steuernummer ging als „OK“ durch.
- Als Nummer zählt jetzt nur, was wirklich eine ist: eine gültige EU-USt-IdNr., eine gekennzeichnete Steuernummer wie `19/295/12345` oder eine gekennzeichnete Nummer aus dem Ausland wie `GB123456789`. Deine eigene USt-IdNr. auf der Rechnung zählt nie als die des Lieferanten.

### Musst du etwas tun?

Nein.

## [1.14.1] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Der Monatsabgleich ist deutlich schneller: Die Nachsuche liest jede Datei nur noch einmal, nicht einmal je fehlender Buchung. Mit vielen Scans dauerte der erste Abgleich über eine Stunde, jetzt sind es Minuten.
- Rechnungen, die nur im Mailtext stehen (etwa von Apple, ohne PDF und ohne Link), legt belege jetzt selbst als PDF ab. Das passiert auf deinem Mac, ohne etwas aus dem Netz zu laden.
- Ein richtig erkannter Beleg landet nicht mehr unter „Unsortiert“, nur weil die Beschreibung Akzente oder ein Wort zu viel hatte („Prêt à Template“). Die Beschreibung wird jetzt bereinigt.
- Die Tests fassen deine echte Einrichtung nicht mehr an: keine echten Postfächer, keine eigenen Regeln, nichts in `arbeit/`. `uv run pytest -q` läuft in rund einer Minute, auch bei fertiger Einrichtung.
- Die Anleitung für Teil 2 erklärt jetzt, was bei Zahlungen über PayPal zu tun ist.

Danke an Nina für die genaue Meldung und den Patch zur Nachsuche.

### Musst du etwas tun?

Nein. Wer Rechnungen im Mailtext nicht als PDF haben möchte, setzt in `konfig/belege.toml` unter `[quellen]` `rechnung_im_mailtext = false`.

## [1.14.0] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Dein Posteingang kann sich zweimal am Tag nach deinen eigenen Regeln aufräumen: archivieren, in Ordner legen, Label setzen, Antwortentwurf anlegen oder dich melden. Gelöscht wird nie, verschickt wird nichts, Antworten sind nur Entwürfe.
- Erledigtes verschwindet von selbst aus dem Posteingang: Mails, auf die du geantwortet hast, die du als erledigt markiert hast oder die gelesen und älter als ein paar Tage sind.
- Deine bisherigen Ordner und Labels werden übernommen: `belege aufraeumen labels` schlägt Regeln vor, die zu deiner Ordnung passen.
- Du entscheidest, ob der Agent nur Absender und Betreff liest oder auch den Mailtext. Vertrauliches kann auf deinem Mac bleiben, und der Bericht nennt auf Wunsch keine Betreffe.
- Etwas falsch einsortiert? `belege aufraeumen zurueck` holt es in den Posteingang zurück.
- Ohne Einschalten ändert sich nichts.

### Musst du etwas tun?

Nein. Wenn du es möchtest, sag deinem Claude: „Lies mit mir die letzten vier Wochen meines Postfachs und schlag mir Regeln vor.“

## [1.13.1] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Weniger Fehlalarme in der Rechnungsprüfung: Mahnungen, Verkaufskataloge, Beiblätter, Pfandabrechnungen und Quittungen zu einer vorhandenen Rechnung gelten nicht mehr als Rechnung.
- EU-Anbieter, die Reverse Charge nur mit 0 % ausweisen, lösen keinen Alarm und keinen Entwurf mehr aus; das geht als Hinweis an deinen Steuerberater.
- Hast du die Prüfung eingeschaltet, bekommst du einmal eine Aufräumliste: eine Zeile je Anbieter, mit genau einem Weg – selbst umstellen (mit Klickweg), Lieferant anschreiben oder nur ein Hinweis. Danach meldet sie sich nur bei Neuem.
- Einen Lieferanten-Entwurf gibt es nur noch einmal je Anbieter, nicht für jede Rechnung.
- Behoben: 1.13.0 hat beim Update ein Beispiel-Stammdatenblatt („Beispiel & Partner GmbH“) in deine Einstellungen gelegt. Es wird jetzt ignoriert, deine Firmenzuordnung läuft wie vorher.

### Musst du etwas tun?

Nein. Wenn du einen Punkt erledigt hast, sag deinem Claude „Meta ist erledigt“ oder „SumUp ignorieren“. Absender, die nie Rechnungen schicken, kann er in `nie_beleg` eintragen.

## [1.13.0] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Ein Stammdatenblatt mit allen deinen Firmen; Rechnungen werden über USt-IdNr., Steuernummer und Anschrift sicherer der richtigen Firma zugeordnet.
- Belege kann jetzt auch deine Anschrift auf Rechnungen prüfen.
- Auf Wunsch fragt belege Lieferanten-USt-IdNrn. bei der EU ab; Störungen dort erzeugen keinen Fehlalarm.
- Reverse Charge und fehlende E-Rechnungen erscheinen als Hinweise für die Buchhaltung, nicht als Befund.
- Weniger Fehlalarme bei ausländischen Rechnungen, Gutschriften und langen Abrechnungen.

### Musst du etwas tun?

Nur wenn du es möchtest: Lass Claude die Anschrift im `[[firma]]`-Block eintragen oder die amtliche USt-Id-Prüfung einschalten.

## [1.12.0] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Belege kann Eingangsrechnungen vor dem Ablegen auf Pflichtangaben prüfen: Steht dein Firmenname richtig drauf, hat der Lieferant eine USt-IdNr. oder Steuernummer angegeben, gibt es Rechnungsnummer, Datum, Leistung und Steuer? Kleinbetragsrechnungen bis 250 € brauchen weniger.
- Fehlt etwas, liegt die Rechnung unter „Manuell prüfen“, mit einer kurzen Notiz, was fehlt. Auf Wunsch entsteht ein Entwurf an den Lieferanten mit der Bitte um eine korrigierte Rechnung. Abgeschickt wird nichts von allein.
- Ohne Einschalten ändert sich nichts.

### Musst du etwas tun?

Nein. Wenn du es möchtest, sag deinem Claude: „Richte mit mir die Rechnungsprüfung ein und prüfe erst fünf echte Rechnungen trocken.“

## [1.11.0] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Abgelegte Mails können auf Wunsch markiert oder aus dem Posteingang genommen werden. Gelöscht wird nie etwas. Markiert wird nur eine Mail, deren Belege alle abgelegt sind.
- Klappt die Anmeldung bei deinem Postfach nicht mehr, etwa nach einem Passwortwechsel, sagt dir der Bericht das jetzt in Klartext und wie du es behebst.
- Ein kaputtes oder unvollständig heruntergeladenes PDF landet mit genau diesem Hinweis in Unsortiert.
- Hakt etwas, schreibt `belege fehlerbericht` einen geschwärzten Text für Philip, ohne Passwörter, Mailadressen, Beträge oder Belegnamen.
- Die Übergabe an DATEV Unternehmen online kann Eingang, Ausgang und Sonstige an getrennte Upload-Adressen schicken.

### Musst du etwas tun?

Nein. Wenn du es möchtest, sag deinem Claude zum Beispiel: „Nimm abgelegte Mails aus meinem Posteingang“ oder „Schick Eingangs- und Ausgangsrechnungen an getrennte DATEV-Adressen“.

## [1.10.0] – 29.10.2026

aktion: keine

### Was ist neu für dich

- Mehrere Firmen können eigene Bereiche in einer gemeinsamen Belegablage haben. Eine Rechnung wird nach ihrem Empfängerfeld zugeordnet, nicht nach dem Postfach, aus dem sie kam.
- Ist der Empfänger nicht eindeutig, bleibt der Beleg in Unsortiert. Im Tagesbericht steht dann „Firma unklar“.
- Monatsabgleich und Übergabe laufen je Firma getrennt; jede Firma kann eine eigene Steuerberateradresse haben.
- Bestehende Betriebsbelege ohne Firmenfeld zählen zur ersten Firma. Ein schon
  übergebener Monat wird für diese Firma auch nach dem Umstieg nicht erneut gesendet.
- Firmen können ihre Konten mit `konten = ["DE…"]` im `[[firma]]`-Block
  zuordnen. Der Monatsabgleich trennt die Auszüge danach; nicht zugeordnete
  Buchungen bleiben bei der Hauptfirma. Fehlen die Zuordnungen, warnt die Prüfung
  und die übrigen Firmen bekommen einen klaren Hinweis statt falscher Fehlbelege.

### Musst du etwas tun?

Nur wenn du mehrere Firmen ablegst: Lass Claude in Teil 3 die Firmen, Schreibweisen, USt-IdNrn. und Konten eintragen und prüfe anschließend ein paar Belege je Firma im Trockenlauf.

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
