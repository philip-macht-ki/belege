# Belege einrichten Teil 1

Hallo. Heute richten wir nur das Postfach ein: Rechnungen landen danach von
allein in `~/Belege`. Das kurze Video aus Lektion 0-1 ist freiwillig.

Das Projekt liegt in `~/Projekte/belege`, nicht in Desktop oder Documents. So
braucht Claude keine zusätzliche Mac-Berechtigung für den Projektordner.

Die Claude-App fragt bei einzelnen Schritten nach Erlaubnis, etwa wenn sie
einen Ordner anlegt. Du kannst für diese Sitzung „immer erlauben“ wählen, wenn
du das möchtest. Ohne deine Zustimmung passiert nichts.

Claude oder Codex: Diese Anleitung spricht von Claude. Richtest du belege mit
Codex ein, gilt alles genauso (siehe `AGENTS.md`); nur das Einordnen läuft dann
über `codex` oder `lokal` statt `claude` (Abschnitt „Welcher Weg ordnet ein?“).

## Vorab, freiwillig: ein Ort für deine Zugänge

Claude empfiehlt einmal kurz einen Passwort-Manager wie 1Password. Wer
App-Passwörter, Bank-Zugänge und Portal-Logins dort ablegt, hat sie in späteren
Schritten sofort zur Hand. Pflicht ist das nicht. belege selbst hält das
App-Passwort fürs Postfach im Schlüsselbund deines Macs, nicht in einer Datei,
und kein Agent tippt je ein Passwort: Du legst es an und fügst es selbst ein.

## Erst prüft Claude still

Claude prüft Mac, freien Platz, die Claude-App und `uv`. Fehlt `uv`, nutzt
Claude den offiziellen Installer im Benutzerordner:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Danach führt Claude `uv sync`, `uv run belege einrichten-urteil` und
`uv run belege pruefen` aus. Homebrew ist nicht nötig.

## Welcher Mac ist das?

Frag nicht, sondern sieh nach: `uv run belege rechner --echt`. Sag der Person in
einem Satz, was du gefunden hast („ein MacBook Air mit 16 GB, 120 GB frei“).
Ein MacBook ist der Normalfall und reicht: Was zugeklappt verpasst wird, holt
belege beim Aufklappen nach. Nur wenn zusätzlich ein Mac dauerhaft läuft, frag,
ob belege dorthin soll.

## Welcher Weg ordnet ein?

Bist du Claude, bleibt `claude` wie bisher eingestellt; frage dazu nichts.
Vertrauliche Briefe gehen trotzdem nie an Claude (Weiche „vertraulich“). Wer
dafür zusätzlich ein Modell auf dem Mac will, findet die freiwillige Anleitung
in `einrichten_lokal.md`; im Workshop ist das kein Schritt.
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

Bei Outlook, Hotmail, Live oder Microsoft 365 erklärt Claude sofort: Microsoft
nimmt seit 2026 kein App-Passwort mehr an, dieses Postfach wird stattdessen mit
einer Anmeldung im Browser verbunden. Eine eigene Domain erkennt Claude daran,
dass `dig +short MX <domain>` auf `mail.protection.outlook.com` zeigt. Dann gilt
der Abschnitt „Microsoft-Postfach“ unten.

Bei einer eigenen Domain (etwa `info@meinbetrieb.de`) findet belege die
Server selbst: Google Workspace, IONOS, Strato, united-domains, all-inkl und
Hetzner am MX-Eintrag, alle übrigen über die öffentliche Anbieterliste von
Thunderbird. `uv run belege pruefen` zeigt danach, ob die Anmeldung klappt.
Meldet belege, dass die Server unbekannt sind, fragt Claude nach dem Anbieter,
schlägt dessen IMAP- und SMTP-Server in der Hilfe des Anbieters nach und trägt
sie beim Postfach als `imap_server` und `smtp_server` ein (mit Port, etwa
`mail.anbieter.de:993`). Liegt die Domain bei Microsoft 365, gilt der
Abschnitt „Microsoft-Postfach“ unten. Bei Google Workspace muss der Admin App-Passwörter
erlauben.

**Frag** bei einem IMAP-Postfach, ob das Mailprogramm Rechnungen per Filter in
Unterordner verschiebt (Thunderbird, Apple Mail, Regeln beim Anbieter). belege
liest sonst nur den Posteingang. Die Ordner trägt Claude beim Postfach ein, mit
dem Namen, den der Server nennt (oft mit `INBOX/` davor):
`imap_ordner = ["INBOX/Rechnungen", "INBOX/Software, Hosting"]`.

Bevor Claude zum ersten Mal ins Postfach schaut, sagt er in einem Satz: Briefe
von Arzt, Gericht, Krankenkasse oder über Mitarbeitende erkennt belege selbst
und liest sie nur auf diesem Mac, nie mit einem Cloud-Modell. Dann fragt er:
Gibt es Absender mit vertraulichen Unterlagen, etwa Mandanten, Patienten oder
ein Labor? Die trägt er unter `[vertraulich]` als `absender` in
`konfig/regeln.toml` ein; solche Belege liest dann nur dein Mac. Absender, deren
Anhänge gar nicht geladen werden sollen, kommen stattdessen in `ausschluss`.

### Microsoft-Postfach

Ein Microsoft-Postfach wird direkt verbunden: einmal im Browser anmelden, danach
liest belege selbst. Dafür braucht es eine App-Kennung bei Microsoft. Es gibt
zwei Wege; Claude prüft zuerst, ob diese Fassung schon Philips gemeinsame App
kennt:

```
uv run python -c "from belege.microsoft import CLIENT_ID; print('gemeinsam' if CLIENT_ID else 'eigene')"
```

Steht dort `gemeinsam`, fragt Claude in einem Satz: „Willst du den einfachen
Weg mit Philips App (nur anmelden und zustimmen), oder deine eigene App (mehr
Kontrolle und Privatsphäre, nur deine Firma kann sie nutzen, etwa 15 Minuten
mehr)?“ Steht dort `eigene`, gibt es nur die eigene App oder den Rückfall
unten.

**Hilfe im Browser.** Beide Wege laufen im Browser. Bevor es losgeht, bietet
Claude einmal an: „Soll ich im Browser mitklicken? Dafür installierst du die
Erweiterung Claude in Chrome (im Chrome Web Store nach ‚Claude‘ suchen, ab
Claude Pro). Sonst sage ich dir jeden Klick einzeln an.“ Lehnt die Person ab,
fragt Claude bei einem Hänger noch einmal. Passwörter, Codes und die Zustimmung
klickt immer die Person selbst.

**Philips App (der einfache Weg).** Claude trägt nur `weg = "microsoft"` beim
Postfach ein, ohne `client_id` und `tenant_id`, und es geht weiter mit
„Anmelden“ unten. Für private Outlook.com-, Hotmail- und Live-Postfächer ist das
der einzige direkte Weg.

**Eigene App (etwa 15 Minuten, einmalig).** Nur für Firmenpostfächer bei
Microsoft 365, denn sie braucht ein Firmenverzeichnis bei Microsoft. Die eigene
App legt ein Admin der Firma an, bei kleinen Firmen meist die Geschäftsführung:

Die Bezeichnungen stammen aus dem Entra Admin Center auf Deutsch, Stand
Oktober 2026; mit Claude in Chrome klickt Claude die Felder selbst, die Person
klickt nur „Registrieren“ (damit stimmt sie Microsofts Plattformrichtlinien zu)
und die Administratorzustimmung.

1. entra.microsoft.com öffnen und mit dem Admin-Konto der Firma anmelden.
2. Links „Entra ID“, „App-Registrierungen“, oben „Neue Registrierung“.
3. Name `belege`. „Unterstützte Kontotypen“: „Nur ein Mandant – <Name des
   Verzeichnisses>“. „Umleitungs-URI“: Plattform „Öffentlicher Client/nativ
   (mobil und Desktop)“, Adresse `http://localhost`. „Registrieren“.
4. Auf der Übersicht der App stehen „Anwendungs-ID (Client)“ und
   „Verzeichnis-ID (Mandant)“. Beides sind keine Geheimnisse; Claude liest sie
   ab oder die Person kopiert sie in den Chat.
5. Links „API-Berechtigungen“, „Berechtigung hinzufügen“, „Microsoft Graph“,
   „Delegierte Berechtigungen“. Ins Suchfeld `Mail.` tippen, die Gruppe „Mail“
   aufklappen, `Mail.ReadWrite` und `Mail.Send` anhaken, „Berechtigungen
   hinzufügen“. `User.Read` ist schon da. Dann „Administratorzustimmung für
   „<Verzeichnis>“ erteilen“ und bestätigen; alle drei Zeilen zeigen danach
   einen grünen Haken.
6. Links „Authentication (Preview)“ (so heißt der Punkt auch in der deutschen
   Oberfläche; in der älteren Ansicht „Authentifizierung“), Reiter
   „Einstellungen“ (älter: „Erweiterte Einstellungen“): „Öffentliche
   Clientflows zulassen“ steht auf „Deaktiviert“ bzw. „Nein“ und bleibt so. Ein Geheimnis (Client
   Secret) wird nicht gebraucht.

Claude trägt beim Postfach in `konfig/belege.toml` ein:

```toml
[[konto]]
name = "geschaeft"
adresse = "info@firma.de"
weg = "microsoft"
client_id = "<Anwendungs-ID>"
tenant_id = "<Verzeichnis-ID>"
```

**Anmelden (beide Wege).** `uv run belege anmelden --microsoft <name>` öffnet
die Microsoft-Anmeldung im Browser:

1. Mit der Postfachadresse anmelden, wie sonst bei Outlook.
2. Bei Philips App fragt Microsoft, ob „belege“ Mails lesen, Entwürfe anlegen
   und senden darf. Wer Admin ist, setzt den Haken **„Im Namen Ihrer
   Organisation zustimmen“** und bestätigt. Bei der eigenen App ist das schon
   in Schritt 5 erledigt.
   Microsoft zeigt bei Philips App „nicht verifiziert“ beim Herausgeber; das
   ist erwartet (Deern & Jung Investment GmbH ist kein Microsoft-Partner), Claude
   sagt das vorher in einem Satz.
3. Steht dort „Administratorgenehmigung erforderlich“, ist die angemeldete
   Person kein Admin. Dann meldet sich der Admin einmal selbst an und stimmt
   zu; danach klappt es für alle Postfächer der Firma.

`uv run belege pruefen` zeigt danach „Microsoft-Zugang erneuert“. Der Zugang
erneuert sich bei jedem Lauf selbst. Nach einem Passwortwechsel oder wenn ein
Admin die Zugänge zurücksetzt, meldet `belege pruefen` und der nächste Lauf
einen Fehler mit dem Befehl zur Neuanmeldung; dann einmal neu anmelden. Die
Anmeldung läuft immer im Browser dieses Macs; eine Anmeldung per Code auf einer
fremden Seite gibt es bewusst nicht, das ist ein bekannter Phishing-Weg.

Klappt keiner der beiden Wege (etwa weil niemand Admin-Rechte hat), nimm den
Rückfall:

**Rückfall: Umleitung an ein Gmail-Konto.** Rechnungen werden aus dem Microsoft-Postfach an ein eigenes, kostenloses
Gmail-Konto umgeleitet, und belege liest dieses Konto. Claude geht die Schritte
einzeln durch und wartet nach jedem auf ein Weiter:

1. Unter accounts.google.com ein neues Gmail-Konto anlegen, etwa
   `belege.<betrieb>@gmail.com`. Nur für Belege, sonst für nichts.
2. In diesem Konto die Bestätigung in zwei Schritten einschalten und unter
   myaccount.google.com/apppasswords ein App-Passwort erzeugen.
3. In Outlook im Web (outlook.office.com): Einstellungen, E-Mail, Regeln,
   „Neue Regel hinzufügen“. Bedingung: „Betreff oder Text enthält“ mit den
   Wörtern Rechnung, Invoice, Beleg, Quittung, Receipt, Gutschrift. Aktion:
   **„Umleiten an“** das neue Gmail-Konto, nicht „Weiterleiten an“. Beim
   Umleiten bleibt der echte Absender stehen, belege braucht ihn für den
   Dateinamen.
4. Eine Testmail mit dem Wort Rechnung im Betreff an die eigene Adresse
   schicken und nachsehen, ob sie im Gmail-Konto ankommt.

Kommt nichts an, sperrt fast immer Microsoft selbst: Microsoft 365 blockiert
automatische Weiterleitungen nach außen in der Grundeinstellung. Freischalten
kann das nur ein Admin unter security.microsoft.com, „Richtlinien und Regeln“,
„Bedrohungsrichtlinien“, „Antispam“, „Antispamrichtlinie für ausgehende
Nachrichten“, Einstellung „Regeln für die automatische Weiterleitung“ auf
„Ein – Weiterleitung ist aktiviert“. Wer die Firma allein führt, ist meist
selbst Admin. Outlook.com, Hotmail und Live haben diese Sperre nicht.

Danach geht es mit dem Gmail-Konto weiter wie bei jedem Gmail-Postfach. Rechnungen,
die vor der Regel eingegangen sind, schickt man einmal von Hand weiter oder legt
sie als PDF in den Eingang.

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
Nur wenn die Person zwei Macs mit demselben Ablageordner hat, trägt er die
Rechner-Sperre ein, damit nur einer ablegt. Er sagt,
dass der Wächter jede neue Mail einmal ansieht (Absender, Betreff, Anfang des
Textes gehen dafür an Claude) und wie man ihn ausschaltet (`waechter = false` beim Konto). Zum Schluss zeigt er
`uv run belege zeitplan zeigen` und `uv run belege pruefen` noch einmal.

Lebenszeichen: Ist der Kurs-Connector „Philip macht KI“ verbunden, legt Claude
mit dessen Werkzeug `lebenszeichen` eines an (Name „Belege aus dem Postfach“,
`max_stunden` 3, auch auf einem MacBook). Aus der Zeile, die das Werkzeug
zurückgibt, trägt er nur die Adresse in Anführungszeichen als
`[takt] lebenszeichen` in `konfig/belege.toml` ein. Der Takt meldet sich dort
beim Start („Mac ist an“, mit MacBook oder Dauerrechner) und nach jedem
fehlerfreien Lauf. War ein MacBook nur zu, kommt kein Alarm, nach vier Tagen
Stille höchstens ein freundlicher Hinweis. Ist der Mac an und der Takt scheitert
zwei Stunden lang, kommt eine Mail.

Fertig. Ab jetzt landen deine Belege von allein in `~/Belege`.

## Updates

Sonntags um 6 Uhr prüft Belege automatisch auf Verbesserungen. Alles, wofür du
nichts tun musst, kommt von allein; deine Einstellungen, Zeitpläne und Schlüssel
bleiben erhalten. Braucht eine neue Version einen Schritt von dir, macht Belege
nichts und sagt dir verständlich Bescheid. Wenn du früher aktualisieren möchtest,
sag deinem Claude einfach: „Update“. Ausschalten kannst du das später in
`konfig/belege.toml` mit `[update] automatisch = false`.

## Teil 2: Monat und Jahr

Nur wenn die Person Teil 2 hat. Jeder Schritt erst trocken, dann nach einem
ausdrücklichen Ja mit `--echt`.

1. **Kontoauszüge.** Claude legt `~/Belege/Kontoauszuege` an (Einstellung
   `[monat] auszuege`). Die Person lädt im Online-Banking die Umsätze als CSV
   herunter und legt sie dort ab, je Konto eine Datei, eine Jahres-CSV geht auch.
   Claude darf sich nicht bei der Bank anmelden.
   Die Kontoauszüge lädt die Person von Hand als CSV herunter. Wer möchte, holt sie
   stattdessen automatisch aus MoneyMoney (kostenpflichtig, optional):
   `einrichten_moneymoney.md`. Claude bietet das nur an, er drängt nicht.
2. **Abgleich.** `uv run belege monat --monat JJJJ-MM` zeigt, wie viele Buchungen
   einen Beleg haben. Mit `--echt` entstehen im Monatsordner `fehlt_noch.md/.csv`
   (Zahlung ohne Beleg, mit Summe), `pruefen.md`, `klaerung.md` und
   `mahnungen.md`. Fehlende Belege sucht `monat` selbst in Postfach, Downloads,
   Eingängen und Scan-Ordner. Die Klärungsliste geht Claude Zeile für Zeile mit
   der Person durch und trägt ihre Antworten ein.
3. **Übergabeweg.** Claude fragt, wohin die Belege gehen, und trägt `[uebergabe]`
   ein: `weg = "mail"` mit `adresse` (Steuerberater, DATEV Upload Mail, Lexware
   Office, sevDesk `autobox@sevdesk.email`) oder `weg = "ordner"` mit `ordner`
   (ein freigegebener Ordner). Bei DATEV setzt er `nur_pdf_tif = true`. Die
   Adresse kommt erst nach einem ausdrücklichen Ja der Person in `[senden] erlaubt`.
4. **Probelauf.** `uv run belege monat --monat JJJJ-MM --uebergabe` zeigt Text und
   Anhänge. Erst geht eine Testübergabe an die eigene Adresse der Person, dann die
   echte. `--anfragen --echt` legt Entwürfe an Lieferanten mit fehlender Rechnung an.
5. **Offene Posten und Konten.** `belege posten --mail` zeigt die Rückfrage zuerst
   nur an; mit `--echt` geht sie ausschließlich an die eigene erlaubte Adresse.
   Antworten im Betreff `[Belege-Posten]` mit Kurz-ID und `privat`, `kein Beleg`,
   `liegt bei` oder `andere Firma` übernimmt `belege posten --antworten`. Für
   mehrere Konten füllt Claude `konfig/konten.toml` (Kürzel, Quelle, Muster,
   Startmonat) aus. Ohne diese Datei bleibt der bisherige CSV-Lauf unverändert.
6. **Automatisch.** Ab dem 3. läuft der Monatsabgleich täglich um 9 Uhr; die
   Übergabe bleibt je Monat einmalig. Fehlende Auszüge werden zuerst sofort,
   danach höchstens wöchentlich gemeldet und nach Nachlieferung entwarnt. Am 1.
   und 15. um 7 Uhr läuft die Posten-Rückfrage nach einem Zwischenstand.
7. **Jahr.** `uv run belege jahr --jahr JJJJ` rechnet alle zwölf Monate.
   `uv run belege postfach --tage 400 --echt` holt ältere Belege nach,
   `jahr --anfragen --echt` legt Entwürfe für die übrigen Lücken an,
   `jahr --paket` baut das Jahrespaket, `jahr --uebergabe` übergibt es (als Mail
   immer nur als Entwurf).

## Teil 3: Handy, Downloads, Cloud und Ablage

Nur wenn die Person Teil 3 hat.

1. **Cloud-Ordner.** Claude fragt, welchen Dienst die Person auf Handy und Mac
   nutzt (iCloud Drive, Google Drive, Dropbox, OneDrive), legt dort `Belege/Eingang`
   an und trägt den Pfad als `[quellen] handy_ordner` ein. Im selben Block setzt
   Claude `downloads_an = true`; ab Werk ist das aus, damit vor Teil 3 kein Lauf
   den echten Downloads-Ordner liest. Die Person prüft am
   Handy, dass der Ordner erscheint. Fotos landen dort über die Dateien-App
   (iPhone) oder die App des Dienstes (Android).
2. **Festplattenvollzugriff.** Der Zeitplan braucht für Cloud-Ordner und
   Downloads möglicherweise Festplattenvollzugriff. Die Vorlagen starten
   `/bin/zsh`, das wiederum `uv run belege` ausführt. Claude öffnet die
   Systemeinstellungen mit:

   ```sh
   open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
   ```

   Claude erklärt dort, welchem gestarteten Programm der Schalter gilt, du setzt
   ihn selbst, danach folgt ein harmloser Lesetest: `uv run belege handy` und
   `uv run belege downloads`, beide trocken. Das Verhalten auf einem frischen
   Mac wird vor dem Einsatz noch einmal geprüft.
3. **Downloads.** `uv run belege downloads` zeigt, was verschoben würde, erst
   nach Ja `--echt`. Danach räumt der Tagestermin um 21 Uhr von allein auf
   (`[quellen] downloads_an = true` aus Schritt 1).
4. **Papierpost (optional).** **Frag**, ob Briefe auf Papier kommen. Bei wenigen
   Briefen genügt ein Foto wie bei einem Kassenbon im Handy-Eingang. Bei vielen
   oder regelmäßigen Briefen nutzt du einen Scan-Dienst (zum Beispiel Dropscan
   oder Caya, kostenpflichtig) oder eine Scan-App.
   **Nutzt die Person Dropscan, sag es ihr so:** In Dropscan unter Einstellungen
   die automatische Weiterleitung an einen Cloud-Speicher einschalten (Google
   Drive, Dropbox oder OneDrive, derselbe Dienst wie für das Handy). Dropscan legt
   dann jeden Scan als PDF in einen Ordner, meist mit Unterordnern je Scanbox und
   Tag. Genau diesen Ordner trägt Claude als `scan_ordner` unter `[quellen]` in
   `konfig/belege.toml` ein; Unterordner liest belege mit, die Originale bleiben
   bei Dropscan. Bei Caya oder einer Scan-App gilt dasselbe mit deren Zielordner.
   Danach läuft `uv run belege pruefen`.
   Eingescannte Briefe landen danach in der Ablage wie jeder andere Beleg oder als
   Dokument. Fragt die Person später „Wo ist der Brief vom Finanzamt?“, sucht
   Claude mit `dokumente_suchen` bzw. `belege_suchen` darin.
5. **Regeln.** Wiederkehrende Lieferanten bekommen eine feste Regel in
   `konfig/regeln.toml`; die USt-IdNr. steht unter `[betrieb] ust_id`. Dateien in
   `Unsortiert` ordnet Claude nach einem Satz der Person mit
   `uv run belege ablegen <datei> --echt` ein.
6. **Ablage für Dokumente.** Verträge, Versicherungen und Briefe legt belege
   seit 1.9.0 selbst ab, wenn sie über Postfach, Handy-Ordner, Scan-Ordner oder
   Downloads kommen: sicher Erkanntes unter `Dokumente/<Art>/<Gegenüber>/`, mit
   Fristen in `belege fristen` und einer Zeile im Tagesbericht. Aus Postfach und
   Downloads nimmt belege nur klare Fälle (Vertrag, Versicherung, Behörde, Bank);
   Unsicheres bleibt wie bisher (Handy und Scan: `Unsortiert`). Vertrauliches
   wie Arztbriefe liest nur der Mac. Wer das nicht will, setzt unter
   `[dokumente]` die Zeile `automatisch = false`. Von Hand geht weiterhin
   `uv run belege dokumente` (Eingang `~/Belege/Dokumente-Eingang`), Fristen mit
   `uv run belege fristen --echt` als Kalenderdatei, Notfallordner mit
   `uv run belege notfall` aus `konfig/notfall.toml` (nie mit Passwörtern).
   Damit Claude im Chat in Dokumenten und Belegen suchen kann, bindet er den
   Postfach-Server ein: `claude mcp add belege -s user -- uv --directory
   ~/Projekte/belege run belege mcp`. Er bringt `dokumente_suchen`, `fristen`
   und `belege_suchen` mit.

## Teil 4: weitere Postfachwege

Eigene Google-Projekte, weitere Konten und der Postfach-Assistent gehören zu
Teil 4.
