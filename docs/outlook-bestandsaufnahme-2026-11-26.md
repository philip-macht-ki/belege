# Outlook und Microsoft in belege: Bestandsaufnahme und Empfehlung

Stand 26.11.2026. Nur Bestandsaufnahme, am Code ist nichts geändert.

## Das Wichtigste in fünf Sätzen

1. Outlook ist bei uns schon gelöst: Seit belege 1.7.0 (28.10.2026) verbindet sich ein Microsoft-Postfach direkt über Microsoft Graph mit deiner gemeinsamen App „belege“, der Kunde meldet sich einmal im Browser an und stimmt zu.
2. Der Weg läuft bei Martina offenbar schon im Alltag (501 Entwürfe landeten am 16.11. direkt in ihrem M365-Postfach, das geht nur über Graph mit Schreibrecht; am 19.11. schrieb sie „so schnell und unkompliziert hatte ich noch nie den Monat fertig“), protokolliert bestätigt ist er aber nirgends, und welche App sie nutzt (deine oder ihre eigene), steht nirgends.
3. Gabi kam am 25.11. nicht wegen belege nicht weiter: Ihr Postfach rechnungen@ktp.at liegt gar nicht bei Microsoft, sondern bei Kabelplus (MX `kabsi.at`), Outlook ist bei ihr nur das Programm. Sie hat versucht, Claude in Chrome im Outlook im Browser (Edge) suchen zu lassen, und dazu in der Web-Umgebung von Claude ohne Ordnerzugriff gearbeitet. Mit belege wäre das ein normales IMAP-Postfach mit Passwort gewesen.
4. Die Webrecherche bestätigt unsere Bauart: Passwort-IMAP ist bei Microsoft für Firmen- und Privatkonten tot, lokales Auslesen von Outlook ist auf Mac und Windows abgekündigt, Gerätecode-Anmeldung wird von Microsoft aktiv gesperrt. Graph mit Browser-Anmeldung ist der richtige Weg.
5. Was fehlt, ist kein neuer Weg, sondern Führung: ein Befehl, der sagt „dein Postfach liegt bei X, wir nehmen Weg Y“, ein fertiger Zustimmungslink für den Admin, die Herausgeber-Verifizierung deiner App, weniger Rechte bei der ersten Anmeldung und ein echter, protokollierter Test an Mac und Windows.

## 1. Ist-Stand im Repo

### Welche Wege es gibt

| Weg | Wofür | Seit | Wo im Code | Getestet |
|---|---|---|---|---|
| Weg A, IMAP mit (App-)Passwort | Gmail, GMX, web.de, T-Online, iCloud, eigene Domains bei IONOS, Strato, all-inkl, Hetzner, united-domains | von Anfang an | `belege/postfach.py` (ImapPostfach, Servererkennung am MX und über die Thunderbird-Liste) | im Alltag bei vielen Kunden |
| Weg Microsoft, Graph | Microsoft 365, Outlook.com, Hotmail, Live | 1.6.0 (27.10., eigene Kunden-App), 1.7.0 (28.10., deine gemeinsame App) | `belege/microsoft.py`, `belege anmelden --microsoft <konto>` | 14 Tests mit nachgebauten Antworten (`tests/test_microsoft.py`), echter Lauf nur indirekt bei Martina |
| Rückfall Umleitung an Gmail | wenn keiner der beiden Microsoft-Wege geht | 1.5.4 (27.10.) | nur Anleitung, `einrichten.md` Abschnitt Microsoft-Postfach | Anleitung, kein Test |
| Weg Ordner | `.eml`-Dateien aus einem Ordner | älter | `postfach.py` (OrdnerPostfach) | Tests |
| Kalender-Aktion (1.19.9) | Postfach-Agent schickt eine `.ics`-Datei an die eigene Adresse | 15.11. | `postfach_agent.py` | hat mit dem Postfachzugriff nichts zu tun, braucht keinen Kalenderzugriff |

Einen Weg „Outlook für Mac lokal auslesen“ gibt es nicht, und das ist richtig so (siehe Abschnitt 3).

### Wie der Microsoft-Weg genau arbeitet

- Gemeinsame App „belege“ in deinem Entra-Verzeichnis (Konto info@deern-jung.com), Client-ID `a11ea9e7-fd6a-4a41-a5bc-4192d5e3ecb2`, für alle Firmenverzeichnisse und private Microsoft-Konten, öffentlicher Client ohne Geheimnis, Rückkehr über `http://localhost`.
- Rechte (delegiert): `Mail.ReadWrite`, `Mail.Send`, `User.Read`. ReadWrite für Entwürfe und „erledigt“-Markieren, Send für den Tagesbericht.
- Anmeldung mit MSAL im Standardbrowser des Rechners (PKCE). Gerätecode ist bewusst aus.
- Zugang (MSAL-Speicher mit erneuerbarem Schlüssel) liegt in `arbeit/geheim/<konto>_microsoft.json`, chmod 600. Er erneuert sich bei jedem Lauf; Microsoft lässt ihn nach 90 Tagen ohne Nutzung verfallen, bei belege mit Takt alle 15 Minuten also praktisch nie.
- Wahlweise eigene App des Kunden: `client_id` und `tenant_id` beim Postfach, Anleitung mit echten Entra-Bezeichnungen in `einrichten.md`.
- Fehlertexte übersetzen die häufigsten Microsoft-Codes (AADSTS90094 und 65001 = Admin muss zustimmen, 50194 = tenant_id fehlt, 700016 = falsche client_id, 53003 = Firmenrichtlinie).
- `belege pruefen` meldet „Microsoft-Zugang erneuert“ oder den Befehl zur Neuanmeldung.
- Die Erkennung `ist_microsoft()` schaut auf Outlook-, Hotmail-, Live- und MSN-Adressen und auf den MX-Eintrag (`protection.outlook.com`). Weg A bricht bei einer Microsoft-Domain mit dem Hinweis auf den Microsoft-Weg ab.

### Was offen ist

- Kein protokollierter Echttest. Die MASTERLISTE (Punkt 9c) sagt seit dem 28.10. „OFFEN: noch kein Test gegen echtes M365-Postfach“. Martinas Rückmeldungen sprechen dafür, dass es läuft, aber wir wissen nicht, mit welcher App, ob sie als Admin zugestimmt hat und ob es Hänger gab.
- Kein Test unter Windows (Anmeldung im Standardbrowser, dort meist Edge, und Ablage des Zugangs).
- Kein Test mit einem privaten Outlook.com-Konto.
- Herausgeber der App nicht verifiziert (Backlog in der MASTERLISTE, „nicht heute“ am 28.10.).
- Die Servererkennung von Weg A kennt Hoster wie Kabelplus (kabsi.at) nicht; die Thunderbird-Liste auch nicht (geprüft heute, 404). belege würde bei Gabi „Server unbekannt“ melden und Claude müsste nachschlagen.

## 2. Was im Workshop am 25.11. schiefging

Quellen: `Cashflow Test/workshop-auswertung/2026-11-25/` (Auswertung, Feedback, Transkript ab 1:07 und 1:40).

- Gabi wollte ihre Hausbuchhaltung mit dem Postfach rechnungen@ktp.at nachbauen. Sie hat den Suchtext von der Folie in die Suchzeile von Outlook im Browser kopiert und Claude in Chrome suchen lassen; „da ist er jetzt immer noch am Suchen“. Danach hat sie es in Edge probiert, Claude meldete „du bist nicht angemeldet“, obwohl sie angemeldet war (die Erweiterung Claude in Chrome läuft in Chrome, nicht in Edge).
- Zusätzlich arbeitete sie in der Web-Umgebung von Claude („Server-Umgebung“), die den angegebenen Ordner nicht sehen kann; die SOP landete online statt auf ihrem Rechner.
- Deine Antwort am Abend („wo du dich nicht einloggen kannst, kann er nicht zugreifen“, Bildschirmsteuerung als Ausweg) war ehrlich, aber in ihrem Fall unnötig kompliziert: ktp.at liegt bei Kabelplus, das ist ein ganz normales Postfach mit Benutzername und Passwort, also Weg A.
- Lehre: „Ich habe Outlook“ sagt nichts darüber, wo das Postfach liegt. Die erste Frage muss immer die Mailadresse sein, dann der MX-Eintrag. Erst daraus folgt der Weg.
- Die Verkaufsseite ist seit cashflow-site#445 schon ehrlicher („gehen auch, die Verbindung ist dort etwas aufwendiger“, Desktop-App statt Browser).

Martina (ZAMCOM, M365, Outlook für Mac, selbst Admin): Rückmeldungen in Gmail lesen sich positiv (19.11.: „bin sehr happy damit“). Ihre Fehlermeldungen (ZUGFeRD, Dubletten, 501 Entwürfe) betrafen die Auswertung, nicht den Zugang. Sie hat heute, 26.11., um 15:00 einen Termin bei dir gebucht. Das ist die beste Gelegenheit, den Echttest unten mit ihrer Zustimmung zu machen.

## 3. Recherche: was heute bei welchem Postfach geht

Ausführliche Fassung mit allen Quellen: `side-session-notes/…/outlook-webrecherche.md`. Die Aussage zur Zustimmung habe ich zusätzlich direkt auf der Microsoft-Seite gegengeprüft.

### Drei Arten von „Outlook“

- **A, privat:** outlook.com, hotmail, live. Microsoft-Konto.
- **B, Firma bei Microsoft 365:** eigene Domain, MX zeigt auf `…mail.protection.outlook.com`. Bei Selbstständigen ist der Inhaber fast immer selbst Admin.
- **C, Postfach bei einem Hoster, Outlook nur als Programm:** Strato, IONOS, all-inkl, Kabelplus und so weiter. Hier ist Microsoft gar nicht beteiligt.

### Fakten, die die Wahl bestimmen

- Passwort-IMAP: bei B seit Oktober 2022 abgeschaltet, bei A seit 16.09.2024. App-Passwörter helfen bei beiden nicht mehr.
- SMTP mit Passwort bei B: ab Ende Dezember 2026 in bestehenden Firmenverzeichnissen standardmäßig aus, endgültig 2027. belege sendet bei Microsoft schon über Graph, ist also nicht betroffen.
- Zustimmung bei B: In der Microsoft-Standardrichtlinie für Nutzerzustimmung dürfen Nutzer `Mail.Read` und `Mail.ReadWrite` nicht selbst freigeben (Ausnahme nur für sechs bekannte Mail-Apps wie Apple Mail und Thunderbird). `IMAP.AccessAsUser.All` ebenso. `Mail.Send` ist nicht auf der Liste. Heißt: Bei B braucht es einmal eine Admin-Zustimmung, egal ob Graph oder IMAP mit OAuth, egal ob deine App oder eine eigene. Ist der Kunde selbst Admin, ist das ein Haken im selben Anmeldefenster.
- Unverifizierte Herausgeber: Seit 2020 können Nutzer neuen, nicht verifizierten Multi-Tenant-Apps nicht zustimmen, wenn das Verzeichnis risikobasierte Zustimmung nutzt. Die Verifizierung ist kostenlos (Partner-Konto plus Registrierung).
- Zustimmung bei A: Der Kunde stimmt selbst zu, kein Admin. (Schlussfolgerung aus den Microsoft-Seiten, nicht ausdrücklich belegt; im Test prüfen.)
- Gerätecode-Anmeldung: Microsoft empfiehlt, sie „so weit wie möglich“ zu sperren, und legt dafür eine verwaltete Sperrrichtlinie an. Kein Weg für uns.
- Erneuerbarer Zugang: 90 Tage, verlängert sich bei jeder Nutzung. Kein Wartungsthema, solange belege läuft.
- Lokales Outlook: Das neue Outlook für Mac hat kein AppleScript mehr, das alte Outlook für Mac läuft seit Oktober 2026 nicht mehr gegen Exchange Online. Das neue Outlook für Windows hat keine COM-Schnittstelle. Nur das klassische Outlook für Windows hätte noch eine, mit Ablaufdatum.
- Weiterleitung nach außen: bei B in der Grundeinstellung gesperrt, nur ein Admin schaltet sie frei. Bei A möglich, verlangt aber die Bestätigung in zwei Schritten.

### Vergleich der Möglichkeiten

| Möglichkeit | A privat | B M365 | C Hoster | Aufwand Kunde | Admin nötig | Mac/Windows | Risiko und Wartung |
|---|---|---|---|---|---|---|---|
| IMAP mit Passwort (Weg A) | nein | nein | **ja** | 2 Min., Passwort in Schlüsselbund | nein | beide | Passwortwechsel bricht ab, sonst nichts |
| **Graph, deine gemeinsame App, Browser-Anmeldung** (Weg Microsoft) | **ja** | **ja** | nein | 3 Min., anmelden, zustimmen | bei B ja, einmal (meist der Kunde selbst) | beide (Windows ungetestet) | Hinweis „nicht verifiziert“ bis zur Verifizierung; 90 Tage ohne Lauf = neu anmelden |
| Graph, eigene App des Kunden | nein | ja | nein | 15 Min. im Entra Admin Center | ja | beide | mehr Kontrolle, aber mehr Klicks und eine Stelle mehr, an der es hakt |
| IMAP mit OAuth | ja | ja | nein | wie Graph | wie Graph | beide | gleiche Zustimmung, mehr Code, kein Vorteil für uns |
| Gerätecode | ja | oft gesperrt | nein | Code auf fremder Seite eintippen | wie Graph | beide | Phishing-Muster, Microsoft sperrt ihn; bewusst nicht |
| Outlook lokal auslesen | nein | nein | nein | entfällt | entfällt | abgekündigt | nicht mehr tragfähig |
| Umleitungsregel an ein Gmail-Konto | ja | nur mit Admin-Freischaltung | geht, aber unnötig | 15 Min., neues Gmail-Konto, Regel | bei B ja | beide | zweites Postfach, Belege liegen bei Google, Regel kann still brechen |
| Weiterleitung an eine zentrale Belege-Adresse bei uns | ja | nur mit Admin | unnötig | 10 Min. | bei B ja | beide | wir würden Kundenbelege empfangen: Datenschutz, AVV, widerspricht „ich greife bei dir auf nichts zu“; nicht empfehlen |
| Claude in Chrome im Outlook im Browser | ja | ja | ja | gering, aber jedes Mal | nein | nur Chrome | kein Takt, langsam, bricht bei jeder Oberflächenänderung; nur für einmalige Einzelfälle |

## 4. Empfehlung

### Ein Weg: am MX erkennen, dann direkt verbinden

Kein neuer Weg. Der bestehende Weg Microsoft mit deiner gemeinsamen App bleibt der Hauptweg für A und B, Weg A bleibt der Weg für C. Was „oma-einfach“ macht, ist eine einzige feste Einstiegsfrage und ein Befehl, der den Rest entscheidet.

So erlebt es der Kunde, wenn Claude einrichtet:

1. Claude fragt: „An welche Adresse kommen deine Rechnungen?“ Nicht „welches Programm nutzt du“.
2. Claude führt `uv run belege postfach erkennen <adresse>` aus (neu) und sagt in einem Satz, was herauskommt: „Dein Postfach liegt bei Microsoft 365. Du meldest dich gleich einmal im Browser an und setzt einen Haken.“ oder „Dein Postfach liegt bei Kabelplus. Ich brauche nur dein Mailpasswort, das landet im Schlüsselbund.“
3. Bei Microsoft: ein Browserfenster, Adresse, Passwort, ggf. Code aufs Handy, dann bei Firmen der Haken „Im Namen Ihrer Organisation zustimmen“. Fertig. Claude prüft sofort mit `belege pruefen`, ob die neueste Rechnung gefunden wird.
4. Ist der Kunde bei B kein Admin, bekommt er einen fertigen Link, den er an seinen Admin schickt (neu). Der Admin klickt einmal, danach geht es.

### Rückfall

- **B ohne erreichbaren Admin:** Es gibt keinen sauberen Weg ohne Admin, denn auch die Umleitung nach außen braucht ihn. Dann ehrlich sagen und bis zur Freigabe Rechnungen als PDF in den Eingang ziehen (Weg Ordner bzw. Eingangsordner).
- **Wenn die Anmeldung trotz Admin scheitert** (Firmenrichtlinie blockiert fremde Apps): eigene App des Kunden, wie heute in `einrichten.md`.
- **Gmail-Umleitung** bleibt als dritter Rückfall in der Doku, wird aber nicht mehr aktiv angeboten. Sie braucht bei B ebenfalls den Admin und schafft ein zweites Postfach.

Nicht empfehlen: Gerätecode, lokales Outlook, Weiterleitung an eine Adresse bei uns, Outlook über Claude in Chrome als Dauerlösung.

### Umbauliste für das Repo (erst nach deinem OK)

Reihenfolge nach Wirkung:

1. **`belege postfach erkennen <adresse>`** (neu, `postfach.py`, CLI, MCP-Werkzeug): gibt eine Zeile zurück, Art (Microsoft privat, Microsoft 365, Hoster X, Gmail, iCloud, unbekannt), Weg und nächsten Befehl. Nutzt die vorhandene Logik (`ist_microsoft`, `_mx`, `HOSTER_NACH_MX`, `_ispdb`). Bei unbekanntem Hoster zusätzlich `imap.<domain>`, `mail.<domain>` und `imap.<mx-domain>` auf Port 993 probieren, bevor „unbekannt“ kommt. Erstes Ziel: Gabis Fall wird in einem Schritt „Kabelplus, Weg A“.
2. **Hoster-Liste ergänzen** (`HOSTER_NACH_MX`): österreichische und kleinere deutsche Anbieter (Kabelplus/kabsi, A1, Magenta AT, World4You, easyname, Netcup, Domainfactory, Mittwald). Werte je Anbieter aus deren Hilfe nachschlagen, nicht raten.
3. **Admin-Zustimmungslink** (`microsoft.py`, `belege anmelden --microsoft <konto> --admin-link`): erzeugt `https://login.microsoftonline.com/<verzeichnis oder organizations>/adminconsent?client_id=…` und einen kurzen Mailtext für den Admin (als Entwurf, nie gesendet). Bei AADSTS90094/65001 zeigt die Fehlermeldung diesen Befehl.
4. **Rechte stufen** (`microsoft.py`): erste Anmeldung nur `Mail.Read` und `User.Read`. `Mail.ReadWrite` erst, wenn der Kunde Entwürfe, Markieren oder den Postfach-Agenten einschaltet; `Mail.Send` erst für den Tagesbericht über dieses Postfach. Der Zustimmungsdialog wird kleiner und weniger beängstigend. Achtung: Bei B braucht jede Stufe wieder eine Admin-Zustimmung, also beim Einrichten gleich fragen, was der Kunde will, und dann einmal mit allem anmelden. Bestehende Zugänge (Martina) bleiben gültig.
5. **`belege pruefen` beim Microsoft-Weg vertiefen:** nicht nur „Zugang erneuert“, sondern angemeldete Adresse, Zahl der Ordner und Datum der neuesten Mail mit Anhang. Damit sieht Claude beim Kunden sofort, ob wirklich gelesen wird.
6. **Echttest-Protokoll** in `docs/` mit Datum, Postfachart, Mac oder Windows, App, Ergebnis. Erst danach Punkt 9c in der MASTERLISTE schließen.
7. **Windows:** Anmeldung im Standardbrowser (Edge) und Ablage des Zugangs auf einem Windows-Rechner prüfen; ggf. Rechte der Datei unter Windows (chmod greift dort nicht) im Code absichern.
8. **Doku und Kurs** (`einrichten.md`, cashflow-site Lektion „Postfach verbinden“, MCP-Einrichtungstext): Einstieg „An welche Adresse kommen deine Rechnungen?“ statt „Hast du Outlook?“, ein Satz „Outlook ist oft nur das Programm“. Gmail-Umleitung ans Ende rücken.
9. **Workshop-Folie:** „Outlook im Browser mit Claude in Chrome“ nicht mehr zeigen; nur Chrome, nur Desktop-App von Claude, nie die Web-Umgebung. Bei Postfachfragen auf die Einrichtung verweisen.

Für dich, ohne Code: **Herausgeber verifizieren** (Partner Center, Microsoft AI Cloud Partner Program, kostenlos; MPN-ID mit dem Entra-Konto info@deern-jung.com verknüpfen, dann bei der App „belege“ eintragen). Das nimmt den Hinweis „nicht verifiziert“ und die Sperre in Verzeichnissen mit risikobasierter Zustimmung. Steht schon im Backlog der MASTERLISTE.

### Testplan

Erst lesen, nie `--echt`, nichts senden. Echte Postfächer nur mit Zustimmung der Inhaber.

| Nr. | Postfach | Rechner | Was geprüft wird | Wer |
|---|---|---|---|---|
| T1 | Martina, M365, selbst Admin (nur mit ihrer Zustimmung, holt Philip, passt in den Termin heute 15:00) | ihr Mac | Welche App ist eingetragen (`konfig/belege.toml`, Feld client_id ja/nein)? `uv run belege pruefen` grün? `uv run belege suchen rechnung` findet die letzten drei Rechnungen? Gab es Hänger bei der Anmeldung? Kein Lauf mit `--echt`. | Martina mit ihrem Claude, Philip daneben |
| T2 | neues Testkonto outlook.com (Philip legt es an) | Philips Mac | Anmeldung mit deiner App ohne Admin, Zustimmung als Privatperson, Testrechnung mit PDF wird gefunden und im Trockenlauf abgelegt | Claude mit Philip |
| T3 | dasselbe Testkonto | Windows-Rechner oder Windows-VM | Anmeldung über Edge, Zugangsdatei entsteht, zweiter Lauf ohne Anmeldung | Claude mit Philip |
| T4 | Test-Verzeichnis M365 (kostenloses Microsoft-365-Entwicklerverzeichnis oder ein günstiges Business-Basic-Konto, entscheidet Philip) | Mac | a) Admin stimmt zu, b) normaler Nutzer ohne Admin bekommt AADSTS90094 und den Admin-Link, Admin klickt, danach geht es | Claude mit Philip |
| T5 | Hoster-Postfach (Strato oder IONOS, eigenes Testpostfach) | Mac | `postfach erkennen` sagt Weg A mit richtigen Servern, `pruefen` grün | Claude |
| T6 | nach der Verifizierung | Mac | Hinweis „nicht verifiziert“ ist weg (Screenshot) | Claude mit Philip |

Abnahme für „Outlook gelöst“: T1 bis T4 grün und protokolliert, Gabis Fall läuft in `postfach erkennen` in einem Schritt auf Weg A.

## Quellen im Repo und bei dir

- `belege/microsoft.py`, `belege/postfach.py` (Erkennung ab Zeile 1231 und 1334), `einrichten.md` Abschnitt „Microsoft-Postfach“, `ARCHITEKTUR.md` „Weg Microsoft“, `tests/test_microsoft.py`, CHANGELOG 1.5.4 bis 1.9.1.
- MASTERLISTE Punkte 9a bis 9c und Backlog „Herausgeber verifizieren“.
- Workshop 25.11.: `Cashflow Test/workshop-auswertung/2026-11-25/` (auswertung_sprache.md, feedback_workshop_25-11.md, Transkript Teil 2 ab 1:07 und 1:40).
- Gmail (gmail-dj, nur gelesen): Martina 27.10. „Workshop morgen“, 18.11. „Fehler im belege-Tool …“, 19.11. „Läuft es bei dir?“, Buchung 26.11. 15:00.
- Webrecherche mit Microsoft-Quellen: `side-session-notes/local_a42c2f58-…/outlook-webrecherche.md`.
