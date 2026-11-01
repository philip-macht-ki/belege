# Kontoauszüge automatisch mit Hibiscus (optional)

Diese Anleitung ist für deinen Claude. Zuerst führt er `uv run belege rechner`
aus. Hibiscus ist kostenlos und eignet sich besonders unter Windows; auf dem Mac
bleibt MoneyMoney die bisherige Empfehlung. Sage: „Richte mir Hibiscus nach
einrichten_hibiscus.md ein.“

`belege monat` braucht Kontoauszüge als CSV. Du kannst sie weiterhin einmal im
Monat selbst bei deiner Bank herunterladen. Das ist ein vollwertiger Weg.

## Grundsätze für Claude

- PIN, TAN und Bankzugang richtet die Person **selbst** in Hibiscus ein. Claude
  fragt nie danach, liest oder tippt sie nie.
- Claude verwendet nur die XML-RPC-Lesemethoden für Konten und Umsätze. Er löst
  nie einen Abruf, keine Synchronisation, Überweisung oder Lastschrift aus.
- Kontostände und Umsätze gehören nicht in den Chat. Dateinamen und
  Buchungsanzahl genügen zum Prüfen.
- Das Jameica-Master-Passwort fragt `belege hibiscus passwort` lokal verdeckt
  ab: im macOS-Schlüsselbund beziehungsweise DPAPI-geschützt für den aktuellen
  Windows-Benutzer. Es gehört nie in eine Konfigurationsdatei oder in den Chat.

## Schritt 0: fragen

Claude fragt: „Möchtest du Hibiscus kostenlos nutzen oder die Kontoauszüge
weiter von Hand als CSV herunterladen?“ Bei „von Hand“ endet diese Anleitung.

## Schritt 1: Java, Jameica und Hibiscus installieren

Unter Windows versucht Claude zuerst in PowerShell, wenn `winget` verfügbar:

```powershell
winget install EclipseAdoptium.Temurin.21.JRE
```

Jameica und Hibiscus lädt die Person anschließend von
<https://www.willuhn.de/products/hibiscus/> herunter und installiert sie. Ist
`winget` nicht verfügbar oder fehlt ein Paket, nennt Claude diese Download-Seite
statt einen fremden Installer zu verwenden. Unter Linux/macOS folgt die Person
der jeweiligen Installationsanleitung von Willuhn.

## Schritt 2: Hibiscus selbst einrichten

Die Person startet Jameica, vergibt ihr Master-Passwort und richtet ihren
Bankzugang selbst ein. PIN und TAN bleiben dabei ausschließlich bei ihr.

N26, Wise, American Express und andere Konten ohne FinTS/HBCI kann Hibiscus
nicht automatisch abrufen. Für sie lädst du die CSV weiter von Hand herunter.

In Hibiscus stellt die Person außerdem den automatischen Abruf ein, wenn sie
ihn möchte. belege ruft selbst niemals Umsätze von der Bank ab; es liest nur
bereits vorhandene Umsätze aus Hibiscus.

## Schritt 3: XML-RPC-Plugin einschalten

Die Person installiert im Jameica-Plugin-Manager `hibiscus.xmlrpc` (einschließlich
der verlangten Jameica-XML-RPC/Webadmin-Abhängigkeiten). In
**Datei → Einstellungen → XML-RPC** aktiviert sie ausschließlich die Dienste
`hibiscus.xmlrpc.konto` und `hibiscus.xmlrpc.umsatz`; unter **HTTP** bleiben
HTTPS und Master-Passwort-Schutz an. Danach Jameica neu starten.

Jameica muss für die automatischen Läufe laufen. Die Person richtet dafür den
Autostart ihres Betriebssystems ein und lässt Jameica nach der Anmeldung laufen.

## Schritt 4: Passwort und Konten zuordnen

Claude führt aus:

```sh
uv run belege hibiscus passwort
uv run belege hibiscus konten
```

Die zweite Liste enthält nur Kontoname und Kennung, keine Salden. Claude fragt,
welche Konten zur Buchhaltung gehören, und trägt sie in `konfig/hibiscus.toml`
ein:

```toml
[[konto]]
kennung = "DE00 0000 0000 0000 0000 00"
name = "Girokonto"
format = "bank"
```

`an` bleibt zunächst `false`.

## Schritt 5: testen und erst dann einschalten

```sh
uv run belege hibiscus --echt --testordner ~/Belege-Test/Kontoauszuege
```

Je Konto entstehen zwei Dateien, etwa `2026-10_Girokonto_Hibiscus.csv`. Claude
nennt nur die Anzahl der Buchungen. Erst nach ausdrücklichem Ja setzt er
`an = true` und richtet den Zeitplan ein:

```sh
BELEGE_JA=1 uv run belege zeitplan an --echt
uv run belege zeitplan zeigen
```

Hibiscus läuft dann um 07:00 und 19:00. Zum Ausschalten setzt Claude `an = false`
und richtet den Zeitplan erneut ein; CSV-Auszüge von Hand bleiben jederzeit möglich.
