"""Gemeinsamer Kern: Pfade, Konfiguration, JSON, Zeit, Sperre, Protokoll, Ereignisse.

Jeder Schritt gibt ein `Ergebnis` zurück, statt still zu scheitern.
Formate der Dateien stehen in ARCHITEKTUR.md.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tomllib
import shutil
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("BELEGE_ROOT", Path(__file__).resolve().parents[1]))


def _env_laden() -> None:
    """Liest .env im Repo-Ordner (NAME=wert je Zeile). Die Umgebung hat Vorrang."""
    datei = ROOT / ".env"
    if not datei.exists():
        return
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        os.environ.setdefault(name.strip(), wert.strip().strip('"').strip("'"))


_env_laden()


@dataclass
class Ergebnis:
    """status: ok | befund | fehler | nichts. Ein Befund stoppt nichts, er wird gezeigt."""

    status: str
    meldung: str = ""
    daten: dict = field(default_factory=dict)

    @property
    def gut(self) -> bool:
        return self.status in ("ok", "befund", "nichts")


def konfig(name: str) -> dict:
    """Liest konfig/<name> (mit oder ohne .toml)."""
    datei = ROOT / "konfig" / (name if name.endswith(".toml") else f"{name}.toml")
    # Konfiguration gehört der Person und ist absichtlich nicht versioniert.
    # Beim ersten Start entsteht sie aus der mitgelieferten Vorlage, nie umgekehrt.
    if not datei.exists():
        vorlage = ROOT / "vorlagen" / "konfig" / datei.name
        if vorlage.exists():
            datei.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(vorlage, datei)
    with open(datei, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as fehler:
            # Vorlagen älterer Einrichtungen enthielten nach_ablage nicht.
            # Beim Ergänzen des Schalters wurde er daher gelegentlich noch
            # einmal im selben Kontoblock eingetragen. Die erste Angabe ist
            # die ausdrückliche Einstellung und darf die spätere Vorgabe
            # überstimmen.
            if name not in {"belege", "belege.toml"} or "Cannot overwrite a value" not in str(fehler):
                raise
    zeilen = datei.read_text(encoding="utf-8").splitlines()
    bereich = None
    aufraeumen = False
    gesehen: dict[str, int] = {}
    for nr, zeile in enumerate(zeilen):
        if zeile.strip() == "[[konto]]":
            bereich = nr
            aufraeumen = False
        elif zeile.strip() == "[aufraeumen]":
            aufraeumen = True
        elif bereich is not None and re.match(r"^\s*nach_ablage\s*=", zeile):
            vorher = gesehen.get(str(bereich))
            if vorher is None:
                gesehen[str(bereich)] = nr
            else:
                zeilen[nr] = "# durch frühere nach_ablage-Angabe ersetzt"
        elif aufraeumen and re.match(r"^\s*lesen\s*=", zeile):
            if "aufraeumen:lesen" in gesehen:
                zeilen[nr] = "# durch frühere lesen-Angabe ersetzt"
            else:
                gesehen["aufraeumen:lesen"] = nr
    return tomllib.loads("\n".join(zeilen))


def rechner() -> str:
    """Kurzname dieses Rechners, wie `hostname -s` ihn zeigt."""
    return socket.gethostname().split(".")[0]


def rechnernamen() -> set[str]:
    """Alle Namen dieses Macs. Der Hostname kann je nach WLAN wechseln, der
    lokale Name aus den Systemeinstellungen (scutil LocalHostName) nicht."""
    namen = {rechner()}
    try:
        lokal = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        if lokal:
            namen.add(lokal)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return namen


def fremder_rechner() -> str | None:
    """Der erlaubte Rechner, wenn dieser hier nicht ablegen darf, sonst None.

    Die Sperre gibt es, weil Laptops verpasste Läufe beim Aufwachen nachholen und
    eine alte Kopie dann neben dem Dauerrechner ablegt (ARCHITEKTUR.md, Rechner-Sperre).
    """
    erlaubt = str(konfig("belege").get("rechner", {}).get("erlaubt", "")).strip()
    if erlaubt and erlaubt.lower() not in {name.lower() for name in rechnernamen()}:
        return erlaubt
    return None


def pfad(*teile: str | Path) -> Path:
    return ROOT.joinpath(*[str(t) for t in teile])


def lesen(p: Path, standard=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return standard


def schreiben(p: Path, daten) -> None:
    """Schreibt JSON atomar, damit ein Abbruch keine halbe Datei hinterlässt."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def zone() -> ZoneInfo:
    return ZoneInfo(konfig("belege").get("zeitzone", "Europe/Berlin"))


def jetzt() -> datetime:
    return datetime.now(zone())


def lauf(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Führt einen Befehl aus. Wirft mit lesbarer Meldung, wenn er scheitert."""
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode != 0:
        schwanz = (r.stderr or r.stdout or "").strip().splitlines()[-8:]
        raise RuntimeError(f"{Path(str(cmd[0])).name} scheiterte ({r.returncode}): " + " | ".join(schwanz))
    return r


def log(zeile: str) -> None:
    """Eine Zeile ins Tagesprotokoll arbeit/logs/<datum>.log und auf den Bildschirm."""
    t = jetzt()
    ziel = pfad("arbeit", "logs", f"{t:%Y-%m-%d}.log")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "a", encoding="utf-8") as f:
        f.write(f"{t:%H:%M:%S} {zeile}\n")
    print(zeile, flush=True)


class Sperre:
    """Verhindert zwei gleichzeitige Läufe. Prüft die PID, nicht den Befehlstext
    (pgrep findet sonst die eigene Diagnose-Shell)."""

    def __init__(self, name: str = "lauf"):
        self.p = pfad("arbeit", f".{name}.pid")

    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        if self.p.exists():
            try:
                pid = int(self.p.read_text().strip())
                os.kill(pid, 0)
                raise RuntimeError(f"Ein Lauf ist schon aktiv (PID {pid}).")
            except (ValueError, ProcessLookupError):
                pass  # verwaiste Sperre von einem abgebrochenen Lauf
            except PermissionError:
                raise RuntimeError("Ein Lauf ist schon aktiv.")
        self.p.write_text(str(os.getpid()))
        return self

    def __exit__(self, *_):
        self.p.unlink(missing_ok=True)


class Gesamtsperre:
    """Eine Sperre für alle schreibenden Läufe (flock auf arbeit/.belege.lock).

    Anders als die PID-Datei verschwindet sie mit dem Prozess von selbst, auch
    nach Absturz oder Neustart. ``warten`` Sekunden wird gewartet, dann gibt der
    Kontext ``False`` zurück und der Aufrufer überspringt seinen Lauf.
    """

    def __init__(self, warten: float = 0):
        self.warten = warten
        self.datei = None

    def __enter__(self) -> bool:
        import fcntl
        import time

        ziel = pfad("arbeit", ".belege.lock")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        self.datei = open(ziel, "a+")
        ende = time.monotonic() + self.warten
        while True:
            try:
                fcntl.flock(self.datei, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if time.monotonic() >= ende:
                    return False
                time.sleep(5)

    def __exit__(self, *_):
        if self.datei:
            self.datei.close()  # gibt die Sperre frei


def ereignis(art: str, text: str, **daten) -> None:
    """Eine Zeile nach arbeit/ereignisse/<datum>.jsonl. Nur hier wird die Datei geschrieben;
    der Bericht liest ausschließlich dort."""
    t = jetzt()
    ziel = pfad("arbeit", "ereignisse", f"{t:%Y-%m-%d}.jsonl")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zeile = {"zeit": t.isoformat(timespec="seconds"), "art": art, "text": text, "daten": daten}
    with open(ziel, "a", encoding="utf-8") as f:
        f.write(json.dumps(zeile, ensure_ascii=False, default=str) + "\n")


def einmal_taeglich(art: str, text: str, **daten) -> bool:
    """Schreibt ein Ereignis dieser Art höchstens einmal am Tag. Gibt zurück, ob geschrieben wurde.

    Für Dinge, die alle 15 Minuten wieder auftreten würden, etwa „kein Netz“.
    """
    datei = pfad("arbeit", "ereignisse", f"{jetzt():%Y-%m-%d}.jsonl")
    if datei.exists() and f'"art": "{art}"' in datei.read_text(encoding="utf-8"):
        return False
    ereignis(art, text, **daten)
    return True


def netz_da(host: str = "api.anthropic.com", port: int = 443) -> bool:
    """Grobe Prüfung, ob dieser Mac gerade ins Netz kommt."""
    import socket

    try:
        socket.create_connection((host, port), timeout=4).close()
        return True
    except OSError:
        return False


def netzfehler(fehler: BaseException) -> bool:
    """Ist der Fehler „kein Netz/Server nicht erreichbar“ statt eines echten Fehlers?"""
    import errno
    import imaplib
    import socket

    if type(fehler).__name__ == "Unerreichbar":
        return not netz_da()
    if isinstance(fehler, (socket.gaierror, socket.timeout, TimeoutError, ConnectionError,
                           imaplib.IMAP4.abort)):
        return True
    if isinstance(fehler, OSError) and fehler.errno in {
        errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.ETIMEDOUT,
    }:
        return True
    text = str(fehler).lower()
    return any(t in text for t in ("nodename nor servname", "network is unreachable",
                                   "name or service not known", "temporary failure in name"))


def ereignisse(seit: datetime | None = None) -> list[dict]:
    """Alle Ereignisse von gestern und heute, optional erst ab `seit`."""
    from datetime import timedelta

    heute = jetzt().date()
    zeilen: list[dict] = []
    for tag in (heute - timedelta(days=1), heute):
        datei = pfad("arbeit", "ereignisse", f"{tag:%Y-%m-%d}.jsonl")
        if not datei.exists():
            continue
        for z in datei.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(z)
            except json.JSONDecodeError:
                continue
            if seit is None or datetime.fromisoformat(e["zeit"]) > seit:
                zeilen.append(e)
    return zeilen


def erweitert(p: str | Path) -> Path:
    """~ und relative Pfade (relativ zum Repo) auflösen."""
    p = Path(str(p)).expanduser()
    return p if p.is_absolute() else ROOT / p


def freier_name(ziel: Path) -> Path:
    """ziel, oder ziel_2, ziel_3 … wenn der Name schon vergeben ist. Nie überschreiben."""
    kandidat, nummer = ziel, 2
    while kandidat.exists():
        kandidat = ziel.with_name(f"{ziel.stem}_{nummer}{ziel.suffix}")
        nummer += 1
    return kandidat


def ablage_ordner() -> Path:
    return erweitert(konfig("belege")["ablage"]["ordner"])


def stammdaten_datei() -> Path:
    """Der feste, optionale Ort für die Stammdaten eigener Firmen."""
    return ROOT / "konfig" / "stammdaten.toml"


# Werte aus vorlagen/stammdaten.beispiel.toml. 1.13.0 hat die Vorlage beim Update
# als echtes Blatt nach konfig/ kopiert; ein solches Blatt gilt als nicht vorhanden.
_BEISPIEL_NAMEN = {"beispiel & partner gmbh"}
_BEISPIEL_UST = {"DE123456789"}


def _stammdaten_roh() -> list[dict]:
    datei = stammdaten_datei()
    if not datei.exists():
        return []
    with open(datei, "rb") as f:
        daten = tomllib.load(f)
    return [dict(firma) for firma in daten.get("firma", [])]


def stammdaten_beispiel() -> bool:
    """Wahr, wenn konfig/stammdaten.toml noch die unveränderte Beispielfirma enthält."""
    try:
        roh = _stammdaten_roh()
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return any(str(f.get("name", "")).strip().casefold() in _BEISPIEL_NAMEN
               or re.sub(r"\s", "", str(f.get("ust_id", ""))).upper() in _BEISPIEL_UST
               for f in roh)


def stammdaten_firmen() -> list[dict]:
    """Liest Stammdaten, ohne eine fehlende optionale Datei zu erzeugen."""
    if stammdaten_beispiel():
        return []
    return _stammdaten_roh()


def hat_stammdatenblatt() -> bool:
    return stammdaten_datei().exists() and not stammdaten_beispiel()


def _firmen_aus_belege(cfg: dict) -> list[dict]:
    """Bisherige Mehrfirmenlogik für belege.toml, unverändert kompatibel."""
    explizit = [dict(f) for f in cfg.get("firma", [])]
    betrieb = dict(cfg.get("betrieb", {}))
    if not explizit:
        # Der Einzelbetrieb hatte nie einen Firmenbereich: sein Ordner kommt
        # weiterhin ausschließlich aus [ablage].bereich_betrieb. Insbesondere
        # darf ein Betriebsname mit "/" keine neue Konfigurationsprüfung
        # auslösen.
        return [{**betrieb, "bereich": cfg.get("ablage", {}).get("bereich_betrieb", "Betrieb"),
                 "namen": list(betrieb.get("namen", []))}] if betrieb.get("name") else []
    zusaetzlicher_betrieb = False
    if betrieb.get("name"):
        alle_namen = {str(n).casefold() for f in explizit for n in [f.get("name", ""), *f.get("namen", [])] if n}
        if str(betrieb["name"]).casefold() not in alle_namen:
            explizit.insert(0, betrieb)
            zusaetzlicher_betrieb = True
    ergebnis = []
    for nummer, firma in enumerate(explizit):
        name = str(firma.get("name", "")).strip()
        if not name:
            continue
        if zusaetzlicher_betrieb and nummer == 0:
            # [betrieb] bleibt der kompatible Hauptbetrieb und erhält keinen
            # eigenen, aus seinem Namen abgeleiteten Firmenordner.
            bereich = cfg.get("ablage", {}).get("bereich_betrieb", "Betrieb")
        else:
            bereich = str(firma.get("bereich") or "").strip()
            if not bereich:
                # Aus dem Namen abgeleitet: "Muster & Co. (haftungsbeschränkt)" ist ein
                # gültiger Firmenname, also bereinigen statt abbrechen.
                bereich = re.sub(r"[^\w .-]+", " ", name, flags=re.UNICODE).replace("..", " ")
                bereich = re.sub(r"\s+", " ", bereich).strip(" .-") or "Firma"
            if (not bereich or ".." in bereich or "/" in bereich or "\\" in bereich
                    or not re.fullmatch(r"[\w .-]+", bereich, re.UNICODE)):
                raise RuntimeError(f"Ungültiger Firmenbereich {bereich!r}: nur sichere Zeichen, keine Pfadtrenner und kein '..'.")
            bereich = re.sub(r"[\\/:*?\"<>|]+", "-", bereich)
            bereich = re.sub(r"\s+", "-", bereich).strip(".-") or "Firma"
        ergebnis.append({**firma, "name": name, "bereich": bereich,
                         "namen": list(firma.get("namen", []))})
    bereiche = [f["bereich"].casefold() for f in ergebnis]
    if len(bereiche) != len(set(bereiche)):
        raise RuntimeError("Mehrere Firmen haben nach der Bereinigung denselben Bereich.")
    return ergebnis


def firmen() -> list[dict]:
    """Eigene Firmen; Stammdaten ergänzen die alten Betriebs-Schlüssel."""
    cfg = konfig("belege")
    stamm = stammdaten_firmen()
    if not hat_stammdatenblatt():
        return _firmen_aus_belege(cfg)

    explizit = [dict(f) for f in cfg.get("firma", [])]
    zusammen: list[dict] = []
    verwendet: set[int] = set()
    for eintrag in stamm:
        name = str(eintrag.get("name", "")).strip()
        passend = next((nr for nr, alt in enumerate(explizit)
                        if str(alt.get("name", "")).strip().casefold() == name.casefold()), None)
        neu = dict(eintrag)
        neu["land"] = str(neu.get("land") or "DE")
        if passend is not None:
            alt = explizit[passend]
            verwendet.add(passend)
            for schluessel in ("bereich", "konten", "uebergabe", "pruefung"):
                if schluessel in alt:
                    neu[schluessel] = alt[schluessel]
            neu["namen"] = list(dict.fromkeys([
                *neu.get("namen", []), *alt.get("namen", [])
            ]))
        if not neu.get("konten") and neu.get("ibans"):
            neu["konten"] = list(neu["ibans"])
        zusammen.append(neu)
    # Nicht übernommene alte Blöcke sind Bestandskonfiguration und bleiben aktiv.
    zusammen.extend(alt for nr, alt in enumerate(explizit) if nr not in verwendet)
    # [betrieb] verhält sich weiterhin wie bei der alten Konfiguration.
    if cfg.get("betrieb", {}).get("name"):
        namen = {str(n).casefold() for f in zusammen for n in [f.get("name", ""), *f.get("namen", [])] if n}
        if str(cfg["betrieb"]["name"]).casefold() not in namen:
            zusammen.insert(0, dict(cfg["betrieb"]))
    return _firmen_aus_belege({**cfg, "firma": zusammen})


def firma(name: str | None) -> dict | None:
    """Gibt die Firma mit diesem kanonischen Namen zurück."""
    for eintrag in firmen():
        if name and str(eintrag["name"]).casefold() == str(name).casefold():
            return eintrag
    return None


def firma_von(eintrag: dict) -> str | None:
    """Kanonische Firma eines Indexeintrags, einschließlich alter Einträge.

    Vor der Mehrfirmen-Ablage hatten Betriebsbelege kein ``firma``-Feld. Sobald
    [[firma]] konfiguriert ist, gehören diese Einträge zur Hauptfirma, also zur
    ersten von :func:`firmen` gelieferten Firma.
    """
    name = eintrag.get("firma")
    gefunden = firma(str(name)) if name else None
    if gefunden:
        return gefunden["name"]
    if not name and eintrag.get("bereich") == "betrieb" and konfig("belege").get("firma"):
        alle = firmen()
        return alle[0]["name"] if alle else None
    return str(name) if name else None


def echt(args) -> bool:
    """Trocken ist Standard. Nur --echt verschiebt, sendet oder ändert Zustand."""
    return bool(getattr(args, "echt", False))


def konten() -> list[dict]:
    """Die Postfächer aus konfig/belege.toml ([[konto]])."""
    return list(konfig("belege").get("konto", []))


def konto(name: str | None = None) -> dict:
    alle = konten()
    if not alle:
        raise RuntimeError("In konfig/belege.toml ist noch kein Postfach eingetragen ([[konto]]).")
    if name is None:
        return alle[0]
    for k in alle:
        if k.get("name") == name:
            return k
    raise RuntimeError(f"Kein Postfach mit dem Namen {name!r} in konfig/belege.toml.")
