# Regeln für deinen Posteingang

Die erste passende Regel gewinnt. Nur Zeilen mit `- ` sind Regeln. Groß- und
Kleinschreibung spielt keine Rolle. Mehrere Bedingungen werden mit ` und `
verbunden; Anführungszeichen erlauben dieses Wort im Suchtext.

Bedingungen:

    von: name@firma.example -> genaue Absenderadresse
    von: @firma.example -> diese Domain und ihre Subdomains
    von: Rechnungshaus -> Teil des Absenders oder Anzeigenamens
    betreff: "Müller und Partner" -> Teil des Betreffs
    newsletter -> List-Unsubscribe, List-Id oder Massenmail-Kennzeichen
    anhang -> die Mail hat mindestens einen Anhang
    text: "Kündigung" -> Teil des Mailtexts (nur mit lesen = "text")
    beantwortet -> du hast auf diese Mail geantwortet
    erledigt -> als erledigt markiert
    gelesen -> als gelesen markiert
    markiert -> mit Stern/Flag markiert
    nicht markiert -> jede Bedingung kann verneint werden
    älter als 14 tage (oder aelter als 14 tage) -> mindestens volle 14 Tage alt
    sonst -> passt immer und steht sinnvollerweise zuletzt

Aktionen:

    archivieren -> nimmt die Mail aus dem Posteingang, löscht sie nie
    ordner: Belege -> verschiebt sie in den genannten Ordner
    label: Wichtig -> markiert sie und lässt sie im Posteingang
    entwurf: Danke, ich melde mich. -> legt nur einen Antwortentwurf an
    melden -> nennt sie im Tagesbericht
    melden, sofort -> meldet sie zusätzlich sofort an dich
    liegen lassen -> tut nichts und nennt sie unter „Braucht dich“

Zustandsregeln (beantwortet, erledigt, gelesen, älter als …) dürfen nur
archivieren oder in einen Ordner verschieben:

    beantwortet -> archivieren
    erledigt -> archivieren
    gelesen und älter als 14 tage -> archivieren
    gelesen und älter als 14 tage und nicht markiert -> archivieren
    text: "Kündigung" -> melden, sofort

- sonst -> liegen lassen
