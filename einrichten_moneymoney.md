# Kontoauszüge automatisch mit MoneyMoney (optional)

Diese Anleitung ist für deinen Claude. Sag ihm: „Richte mir MoneyMoney nach
einrichten_moneymoney.md ein.“

`belege monat` braucht deine Kontoumsätze als CSV im Auszugsordner. Dafür gibt
es zwei gleichwertige Wege:

- **Von Hand:** Einmal im Monat im Online-Banking die Umsätze als CSV
  herunterladen und in `~/Belege/Kontoauszuege` legen. Kostet nichts, dauert je
  Konto ein paar Minuten. Dieser Weg bleibt vollwertig.
- **Mit MoneyMoney:** Das Homebanking-Programm für den Mac ruft deine Konten ab,
  belege holt sich daraus zweimal am Tag die Umsätze. Kostet einmalig 79,99 €
  inkl. MwSt. (Stand 26.10.2026, moneymoney.app), es gibt eine kostenlose
  Testversion.

## Grundsätze für Claude

- **Zugangsdaten, PIN und TAN gibt nur die Person selbst in MoneyMoney ein.**
  Claude fragt nie danach, liest sie nie und tippt sie nie.
- belege **liest** nur (`export accounts`, `export transactions`). Überweisungen,
  Lastschriften oder Änderungen in MoneyMoney löst Claude nie aus, auch nicht
  auf Bitte.
- Kontostände und Umsätze gehören nicht in den Chat. Zum Prüfen genügen
  Dateiname und Anzahl der Buchungen.
- MoneyMoney kommt auf denselben Mac wie belege, also den Dauerrechner.

## Schritt 0: fragen

Claude fragt: „Möchtest du MoneyMoney nutzen? Es kostet einmal 79,99 €, du
kannst es vorher kostenlos testen. Ohne MoneyMoney lädst du die Kontoauszüge
einmal im Monat selbst herunter, das funktioniert genauso.“

Bei Nein: hier aufhören. Es bleibt beim Herunterladen von Hand.

## Schritt 1: MoneyMoney installieren

Claude öffnet <https://moneymoney.app>. Die Person lädt die Testversion selbst
herunter und zieht MoneyMoney in den Programme-Ordner. Danach prüft Claude:

```sh
ls -d /Applications/MoneyMoney.app
```

Gekauft wird erst, wenn die Person überzeugt ist, und zwar von ihr selbst.

## Schritt 2: Konten in MoneyMoney einbinden

Das macht die Person selbst in MoneyMoney: Konto hinzufügen, Bank auswählen,
Zugangsdaten eingeben, mit TAN freigeben. Claude erklärt nur, was gleich kommt.

- **Girokonten** laufen über die Schnittstelle der Bank. Von Zeit zu Zeit
  verlangt die Bank eine neue Freigabe per TAN; dann meldet der Tagesbericht,
  dass das Konto nicht mehr abgerufen wurde.
- **American Express** bindet MoneyMoney über die Amex-Webseite an, mit den
  Zugangsdaten von amex.de. Die Banken-Schnittstelle (PSD2) bietet Amex nur in
  Frankreich an.

Danach in MoneyMoney einmal alle Konten abrufen.

## Schritt 3: Konten zuordnen

Claude führt aus:

```sh
uv run belege moneymoney konten
```

Beim ersten Mal fragt macOS, ob die Claude-App MoneyMoney steuern darf. Die
Person erlaubt das. Ist MoneyMoney gesperrt, entsperrt die Person es und Claude
versucht es noch einmal.

Die Liste zeigt Name, Kennung und Art, keine Kontostände. Claude fragt, welche
Konten für die Buchhaltung zählen (meist Geschäftskonto und Geschäfts-
Kreditkarte, nicht das Tagesgeldkonto), und trägt sie in
`konfig/moneymoney.toml` ein:

```toml
[[konto]]
kennung = "DE00 0000 0000 0000 0000 00"   # aus der Liste, die Kennung genügt
name = "Girokonto"
format = "bank"

[[konto]]
kennung = "XXX-12345"
name = "Amex"
format = "amex"                            # jede Kreditkarte: "amex" oder "kreditkarte"
```

`an` bleibt vorerst `false`. `ordner` lässt Claude weg; dann landen die Dateien
in `[monat] auszuege` aus `konfig/belege.toml`.

## Schritt 4: Testlauf in einen Testordner

```sh
uv run belege moneymoney --echt --testordner ~/Belege-Test/Kontoauszuege
```

Je Konto entstehen zwei Dateien, laufender Monat und Vormonat, etwa
`2026-10_Girokonto_MoneyMoney.csv`. Claude nennt je Datei die Anzahl der
Buchungen und bittet die Person, für einen Monat mit der Anzahl in MoneyMoney zu
vergleichen. Dann prüft er, dass der Abgleich die Dateien liest:

```sh
uv run belege monat --auszug ~/Belege-Test/Kontoauszuege/<datei>.csv
```

Die Zeile `ok: … Buchungen, … zugeordnet, …` heißt: passt. Vorgemerkte Umsätze
fehlen absichtlich, sie können sich noch ändern.

Danach **hält Claude an** und fragt, ob es scharf geschaltet werden soll.

## Schritt 5: scharf schalten, erst nach ausdrücklichem Ja

Claude setzt `an = true` in `konfig/moneymoney.toml`, führt einmal
`uv run belege moneymoney --echt` aus und richtet den Zeitplan neu ein:

```sh
BELEGE_JA=1 uv run belege zeitplan an --echt
uv run belege zeitplan zeigen
```

`de.belege.moneymoney` läuft um 7 und 19 Uhr. Fragt macOS beim ersten
geplanten Lauf noch einmal nach der Steuerung von MoneyMoney, erlaubt die
Person das. Liegen schon CSV-Dateien von Hand im Auszugsordner, stört das nicht:
`belege monat` liest alle Dateien des Monats und zählt dieselbe Buchung nur
einmal.

## Im Alltag

- MoneyMoney muss laufen und entsperrt sein, sonst steht im Tagesbericht
  „MoneyMoney nicht erreichbar“.
- Wurde ein Konto länger als drei Tage nicht abgerufen (`warnen_nach_tagen`),
  steht das im Tagesbericht. Dann MoneyMoney öffnen, Konto abrufen, ggf. TAN.
- Ausschalten: `an = false`, dann `uv run belege zeitplan aus --echt` und
  `BELEGE_JA=1 uv run belege zeitplan an --echt`. Danach lädst du die Auszüge
  wieder von Hand herunter.
