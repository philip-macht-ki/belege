"""Ausgeschriebene Monatsnamen, englisch und deutsch, unabhängig von der Spracheinstellung."""
from datetime import date

import pytest

from belege.einordnen import _datum


@pytest.mark.parametrize(("text", "erwartet"), [
    ("Date paid October 13, 2026", date(2026, 10, 13)),
    ("13 August 2026", date(2026, 8, 13)),
    ("Rechnungsdatum: 13. Oktober 2026", date(2026, 10, 13)),
    ("Date paid Oktober 13, 2026", date(2026, 10, 13)),  # %B bei LC_TIME=de_DE
    ("am 3. März 2026", date(2026, 3, 3)),
    ("1. Mai 2026", date(2026, 5, 1)),
    ("Dez. 24, 2026", date(2026, 12, 24)),
    ("Rechnungsdatum 12.10.2026", date(2026, 10, 12)),
])
def test_monatsnamen(text, erwartet):
    assert _datum(text) == erwartet


def test_musterquittung_schreibt_englisch(tmp_path):
    """Die Musterquittung darf nicht der Spracheinstellung folgen (so war test_gesamt rot)."""
    import locale
    import shutil
    import subprocess

    from belege import beispiel

    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext fehlt")
    try:
        locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
    except locale.Error:
        pytest.skip("deutsche Spracheinstellung fehlt")
    try:
        ziel = tmp_path / "q.pdf"
        beispiel._zahlfix_receipt(ziel, beispiel.SCHRIFTWERK, beispiel.STUDIO, "R-1", date(2026, 10, 13),
                                  [beispiel.Position("1", "Font license", 19.00)])
    finally:
        locale.setlocale(locale.LC_TIME, "C")
    text = subprocess.run(["pdftotext", str(ziel), "-"], capture_output=True, text=True).stdout
    assert "October 13, 2026" in text
