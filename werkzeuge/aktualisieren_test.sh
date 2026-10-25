#!/bin/bash
set -euo pipefail
HIER="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fehler() { echo "Test fehlgeschlagen: $1" >&2; exit 1; }
mkdir -p "$TMP/v1/keep" "$TMP/v2/keep" "$TMP/v2/neu" "$TMP/z/keep" "$TMP/z/neu"
printf 'alt\n' > "$TMP/v1/datei.txt"; printf 'mein alt\n' > "$TMP/v1/keep/einst.txt"
printf 'neu\n' > "$TMP/v2/datei.txt"; printf 'mein neu\n' > "$TMP/v2/keep/einst.txt"; printf 'neu\n' > "$TMP/v2/neu/geschuetzt.txt"; printf 'x\n' > "$TMP/v2/extra.txt"
printf 'zip\n' > "$TMP/z/datei.txt"; printf 'z\n' > "$TMP/z/keep/einst.txt"; printf 'z\n' > "$TMP/z/neu/geschuetzt.txt"
(cd "$TMP" && tar -czf eins.tar.gz v1 && tar -czf zwei.tar.gz v2 && zip -qr drei.zip z)
mkdir "$TMP/install"; mkdir -p "$TMP/install/werkzeuge"
cp "$HIER/werkzeuge/aktualisieren.sh" "$TMP/install/werkzeuge/"
printf '%s\n' 'REPO=x/y' 'STAND_ORDNER=.vorlage' 'SCHUTZ="keep/"' 'DANACH=""' > "$TMP/install/werkzeuge/aktualisieren.conf"
cd "$TMP/install"
bash werkzeuge/aktualisieren.sh --archiv "$TMP/eins.tar.gz" --kennung eins >/dev/null
[ "$(cat datei.txt)" = alt ] || fehler Erstinstallation
printf 'eigen\n' > datei.txt; printf 'mein eigen\n' > keep/einst.txt
bash werkzeuge/aktualisieren.sh --archiv "$TMP/zwei.tar.gz" --kennung zwei > "$TMP/ausgabe"
[ "$(cat datei.txt)" = neu ] || fehler Ueberschreiben
[ "$(cat datei.txt.vor-update-$(date +%Y%m%d))" = eigen ] || fehler Sicherung
[ "$(cat keep/einst.txt)" = 'mein eigen' ] || fehler Schutz
[ "$(cat keep/einst.txt.neu-$(date +%Y%m%d))" = 'mein neu' ] || fehler Schutzfassung
[ "$(cat neu/geschuetzt.txt)" = neu ] || fehler neue_Schutzdatei
[ -f extra.txt ] || fehler neue_Datei
[ -f datei.txt ] || fehler nichts_loeschen
rm -f keep/einst.txt.neu-*
bash werkzeuge/aktualisieren.sh --archiv "$TMP/zwei.tar.gz" --kennung zwei >/dev/null
ls keep/einst.txt.neu-* >/dev/null 2>&1 && fehler keine_neue_Fassung_ohne_Vorlagenaenderung
bash werkzeuge/aktualisieren.sh --pruefen --kennung zwei >/dev/null
if bash werkzeuge/aktualisieren.sh --pruefen --kennung drei >/dev/null; then fehler pruefen_alter_Stand; else [ "$?" -eq 10 ] || fehler pruefen_code; fi
bash werkzeuge/aktualisieren.sh --archiv "$TMP/drei.zip" --kennung drei >/dev/null
[ "$(cat datei.txt)" = zip ] || fehler zip_oberordner
vorher="$(shasum -a 256 datei.txt)"
if bash werkzeuge/aktualisieren.sh --archiv "$TMP/fehlt" --kennung vier >/dev/null 2>&1; then fehler fehlerarchiv; fi
[ "$(shasum -a 256 datei.txt)" = "$vorher" ] || fehler fehler_unveraendert
echo "alle Tests bestanden"
