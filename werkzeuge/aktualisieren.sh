#!/bin/bash
# Einheitlicher Aktualisierer fuer Vorlagen. Einstellungen stehen nebenan in
# aktualisieren.conf; eigene Dateien werden nie geloescht.

set -euo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$HIER/werkzeuge/aktualisieren.conf"
[ -f "$CONF" ] || { echo "Fehler: Einstellungsdatei fehlt: $CONF" >&2; exit 1; }
# shellcheck source=/dev/null
source "$CONF"
: "${REPO:?REPO fehlt in aktualisieren.conf}"
: "${STAND_ORDNER:?STAND_ORDNER fehlt in aktualisieren.conf}"

STAND="$HIER/$STAND_ORDNER/stand.txt"
LISTE="$HIER/$STAND_ORDNER/stand-dateien.txt"
HEUTE="$(date +%Y%m%d)"
ARCHIV=""
KENNUNG=""
PRUEFEN=0

hilfe() { echo "Aufruf: bash werkzeuge/aktualisieren.sh [--archiv URL-oder-Pfad] [--kennung KENNUNG] [--pruefen]"; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --archiv) [ "$#" -gt 1 ] || { hilfe >&2; exit 1; }; ARCHIV="$2"; shift 2 ;;
    --kennung) [ "$#" -gt 1 ] || { hilfe >&2; exit 1; }; KENNUNG="$2"; shift 2 ;;
    --pruefen) PRUEFEN=1; shift ;;
    -h|--hilfe) hilfe; exit 0 ;;
    *) echo "Fehler: unbekannter Schalter: $1" >&2; exit 1 ;;
  esac
done

ALT="unbekannt"
[ -s "$STAND" ] && ALT="$(awk 'NR == 1 { print $1 }' "$STAND")"

api_kennung() {
  local antwort
  antwort="$(curl -fsSL -m 15 "https://api.github.com/repos/$REPO/commits/main" 2>/dev/null)" || return 1
  printf '%s\n' "$antwort" | grep -Eo '"sha": *"[0-9a-f]{40}"' | head -1 | grep -Eo '[0-9a-f]{40}' | cut -c1-7
}

if [ -d "$HIER/.git" ] && command -v git >/dev/null 2>&1 && git -C "$HIER" rev-parse >/dev/null 2>&1; then
  ALT="$(git -C "$HIER" rev-parse --short HEAD)"
  if [ "$PRUEFEN" -eq 1 ]; then
    if [ -n "$KENNUNG" ]; then NEU="$KENNUNG"
    else
      NEU="$(git -C "$HIER" ls-remote origin HEAD 2>/dev/null | awk 'NR == 1 {print substr($1,1,7)}')" || true
      [ -n "$NEU" ] || { echo "Fehler: neuesten Git-Stand nicht abrufbar." >&2; exit 1; }
    fi
    echo "STAND $ALT $NEU"
    [ "$ALT" = "$NEU" ] && exit 0 || exit 10
  fi
  git -C "$HIER" pull --ff-only
  NEU="$(git -C "$HIER" rev-parse --short HEAD)"
  mkdir -p "$(dirname "$STAND")"
  echo "$NEU $(date '+%d.%m.%Y %H:%M') git" > "$STAND"
  echo "Stand vorher: $ALT"
  echo "Stand jetzt:  $NEU"
  if [ "$ALT" != "$NEU" ]; then
    echo "Geänderte Dateien:"
    git -C "$HIER" diff --name-status "$ALT" "$NEU" | sed 's/^/  /'
    [ -n "${DANACH:-}" ] && echo "Danach: $DANACH"
  else
    echo "Keine Änderungen."
  fi
  echo "STAND $ALT $NEU"
  exit 0
fi

if [ -z "$KENNUNG" ]; then
  KENNUNG="$(api_kennung)" || { echo "Fehler: neueste Kennung von GitHub nicht abrufbar; nichts wurde verändert." >&2; exit 1; }
  [ -n "$KENNUNG" ] || { echo "Fehler: GitHub lieferte keine Kennung; nichts wurde verändert." >&2; exit 1; }
fi
NEU="$KENNUNG"
if [ "$PRUEFEN" -eq 1 ]; then
  echo "STAND $ALT $NEU"
  [ "$ALT" = "$NEU" ] && exit 0 || exit 10
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PAKET="$TMP/archiv"
if [ -n "$ARCHIV" ]; then
  if [ -f "$ARCHIV" ]; then cp "$ARCHIV" "$PAKET"
  else curl -fsSL -m 60 "$ARCHIV" -o "$PAKET" || { echo "Fehler: Archiv nicht abrufbar; nichts wurde verändert." >&2; exit 1; }
  fi
else
  curl -fsSL -m 60 "https://github.com/$REPO/archive/$KENNUNG.tar.gz" -o "$PAKET" || { echo "Fehler: Archiv nicht abrufbar; nichts wurde verändert." >&2; exit 1; }
fi

ROH="$TMP/roh"
mkdir "$ROH"
if tar -tzf "$PAKET" >/dev/null 2>&1; then
  tar -xzf "$PAKET" -C "$ROH" || { echo "Fehler: tar-Archiv konnte nicht entpackt werden; nichts wurde verändert." >&2; exit 1; }
elif unzip -Z1 "$PAKET" >/dev/null 2>&1; then
  unzip -qq "$PAKET" -d "$ROH" || { echo "Fehler: ZIP-Archiv konnte nicht entpackt werden; nichts wurde verändert." >&2; exit 1; }
else
  echo "Fehler: Archiv ist weder tar.gz noch ZIP; nichts wurde verändert." >&2; exit 1
fi

QUELLE="$ROH"
erste="$(find "$ROH" -mindepth 1 -print | sed "s#^$ROH/##" | awk -F/ 'NF {a[$1]=1} END {for (x in a) print x}')"
if [ "$(printf '%s\n' "$erste" | awk 'NF {n++} END {print n+0}')" -eq 1 ] && [ -d "$ROH/$erste" ]; then QUELLE="$ROH/$erste"; fi

pruefsumme() { shasum -a 256 "$1" | awk '{print $1}'; }
gespeichert() { [ -s "$LISTE" ] && awk -v d="$1" '$2 == d {print $1; exit}' "$LISTE" || true; }
geschuetzt() {
  local p="$1" s
  for s in ${SCHUTZ:-}; do
    case "$s" in */) [[ "$p" == "$s"* ]] && return 0 ;; *) [ "$p" = "$s" ] && return 0 ;; esac
  done
  return 1
}
metadaten() { case "$1" in "$STAND_ORDNER"|"$STAND_ORDNER"/*) return 0 ;; esac; return 1; }

GEAENDERT=()
GESICHERT=()
NEUFASSUNGEN=()
while IFS= read -r -d '' datei; do
  rel="${datei#"$QUELLE"/}"
  metadaten "$rel" && continue
  ziel="$HIER/$rel"
  if geschuetzt "$rel" && [ -e "$ziel" ]; then
    # Eine neue Fassung nur, wenn sich die Vorlage seit dem letzten Update
    # geändert hat. Sonst läge nach jedem Update dieselbe .neu-Datei daneben.
    neu_summe="$(pruefsumme "$datei")"
    vorlage_vorher="$(gespeichert "$rel")"
    if [ "$(pruefsumme "$ziel")" != "$neu_summe" ] && [ "$vorlage_vorher" != "$neu_summe" ]; then
      mkdir -p "$(dirname "$ziel")"
      cp -p "$datei" "$ziel.neu-$HEUTE"
      NEUFASSUNGEN+=("$rel.neu-$HEUTE")
    fi
    continue
  fi
  if [ ! -e "$ziel" ]; then
    GEAENDERT+=("neu       $rel")
  elif [ "$(pruefsumme "$ziel")" != "$(pruefsumme "$datei")" ]; then
    GEAENDERT+=("geändert  $rel")
    vorher="$(gespeichert "$rel")"
    if [ -z "$vorher" ] || [ "$vorher" != "$(pruefsumme "$ziel")" ]; then
      cp -p "$ziel" "$ziel.vor-update-$HEUTE"
      GESICHERT+=("$rel.vor-update-$HEUTE")
    fi
  else
    continue
  fi
  mkdir -p "$(dirname "$ziel")"
  cp -p "$datei" "$ziel"
done < <(find "$QUELLE" -type f -print0)

ENTFALLEN=()
if [ -s "$LISTE" ]; then
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    metadaten "$rel" && continue
    [ -f "$QUELLE/$rel" ] || ENTFALLEN+=("$rel")
  done < <(awk '{sub(/^[^ ]+ /, ""); print}' "$LISTE")
fi
mkdir -p "$(dirname "$STAND")"
( cd "$QUELLE" && find . -type f -print0 | while IFS= read -r -d '' f; do
    rel="${f#./}"; case "$rel" in "$STAND_ORDNER"|"$STAND_ORDNER"/*) continue ;; esac
    printf '%s %s\n' "$(pruefsumme "$f")" "$rel"
  done ) > "$LISTE"
echo "$NEU $(date '+%d.%m.%Y %H:%M') archiv" > "$STAND"

echo "Stand vorher: $ALT"
echo "Stand jetzt:  $NEU"
if [ "${#GEAENDERT[@]}" -gt 0 ]; then echo "Geänderte Dateien:"; printf '  %s\n' "${GEAENDERT[@]}"; else echo "Keine Änderungen."; fi
if [ "${#GESICHERT[@]}" -gt 0 ]; then echo "Eigene Änderungen gesichert:"; printf '  %s\n' "${GESICHERT[@]}"; fi
if [ "${#NEUFASSUNGEN[@]}" -gt 0 ]; then echo "Neue Fassung neben deiner Datei, bitte zusammenführen:"; printf '  %s\n' "${NEUFASSUNGEN[@]}"; fi
if [ "${#ENTFALLEN[@]}" -gt 0 ]; then echo "Im neuen Stand entfallen (nicht gelöscht):"; printf '  %s\n' "${ENTFALLEN[@]}"; fi
if { [ "${#GEAENDERT[@]}" -gt 0 ] || [ "${#NEUFASSUNGEN[@]}" -gt 0 ]; } && [ -n "${DANACH:-}" ]; then echo "Danach: $DANACH"; fi
echo "STAND $ALT $NEU"
