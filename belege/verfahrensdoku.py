"""Erstellt einen bearbeitbaren, bewusst unverbindlichen GoBD-Entwurf."""
from __future__ import annotations
from . import __version__, kern


def entwurf() -> str:
    cfg, regeln = kern.konfig("belege"), kern.konfig("regeln")
    ablage = kern.ablage_ordner()
    konten = ", ".join(str(k.get("adresse", k.get("name", "Postfach"))) for k in cfg.get("konto", [])) or "keine eingerichtet"
    stichworte = ", ".join(f"{r.get('wort')} → {r.get('bereich', 'betrieb')}" for r in regeln.get("stichwort", [])) or "keine"
    absender = ", ".join(str(r.get("muster", "")) for r in regeln.get("absender", [])) or "keine"
    return f'''# Verfahrensdokumentation Belege

**Entwurf, keine Rechts- oder Steuerberatung. Mit deinem Steuerberater abstimmen.**

## Zweck und Software

Diese Dokumentation beschreibt die digitale Erfassung, Prüfung und Ablage von Buchhaltungsbelegen. Eingesetzt wird belege, Version {__version__}.

## Quellen und Takt

Postfächer: {konten}. Weitere Quellen sind die eingerichteten Eingangsordner für Handy und Downloads. Der regelmäßige Takt ist alle {cfg.get('takt', {}).get('minuten', 15)} Minuten; der Tageslauf erfolgt um {cfg.get('takt', {}).get('tag_uhrzeit', '21:00')}.

## Ablage und Benennung

Ablageordner: `{ablage}`. Die Struktur lautet Bereich/Jahr/Monat/Eingang, Ausgang oder Sonstige. Dateinamen folgen dem Muster `JJJJ-MM-TT_Lieferant_Beschreibung.ext`. Originale werden nicht verändert oder gelöscht.

## Privat, Firma und vertrauliche Belege

Absenderregeln: {absender}. Stichwortregeln: {stichworte}. Stichwörter haben Vorrang vor Absenderregeln. Vertrauliche Belege werden nur lokal gelesen; ihre Schutzregel bleibt von diesen Regeln unberührt.

## Rechnungsprüfung und Übergabe

Belege werden auf erkennbare Pflichtangaben geprüft. Unklare Fälle werden zur Prüfung markiert. Die Übergabe an das Steuerbüro/DATEV erfolgt als kontrolliertes Paket; Antworten auf Nachfragen werden lediglich als Entwurf vorbereitet und nie automatisch versandt.

## Kontrollen

Tagesbericht, Lebenszeichen und die Fehlt-noch-Liste zeigen offene oder unklare Vorgänge. Der Monats- und Jahresabgleich dient als zusätzliche Kontrolle.

## Aufbewahrung

Die gesetzlichen Aufbewahrungsfristen sind mit dem Steuerberater zu klären; üblicher Hinweis sind je nach Unterlage 8 oder 10 Jahre. Unveränderte Originale bleiben erhalten.

## Verantwortung und Änderungen

Verantwortlicher: _bitte ergänzen_.

Änderungsprotokoll: _Datum, Änderung, verantwortliche Person bitte ergänzen_.
'''


def befehl(args) -> int:
    text = entwurf()
    if not kern.echt(args):
        print(text, end="")
        return 0
    ziel = kern.ablage_ordner() / f"Verfahrensdokumentation_Belege_{kern.jetzt():%Y-%m-%d}.md"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    print(f"ok: Entwurf geschrieben: {ziel}")
    return 0
