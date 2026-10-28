"""Avvisi a inizio sessione per i vault collaborativi: aggiornamenti remoti non ancora ricevuti.

Solo `teseo_git.py avvisi` (un fetch): nessun pull e nessuna scrittura su note, grafo o stato dell'autosync.
Offline, tempo scaduto o qualunque guasto non disturbano l'avvio della sessione (si restituisce None).
"""
import json
import subprocess
import sys
from pathlib import Path

TIMEOUT = 8  # secondi; gli hook SessionStart ne hanno 15


def remoti(vault, timeout=TIMEOUT):
    """Frase da mostrare all'utente se il remoto ha aggiornamenti (o storie divergenti), altrimenti None."""
    vault = Path(vault)
    script = Path(__file__).resolve().with_name("teseo_git.py")
    if not script.is_file() or not (vault / ".teseo/project.json").is_file():
        return None
    try:
        fatto = subprocess.run([sys.executable, str(script), "avvisi", "--vault", str(vault)], capture_output=True,
                               timeout=timeout, cwd=vault)
        esito = json.loads(fatto.stdout.decode("utf-8", "replace"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if fatto.returncode or not isinstance(esito, dict) or esito.get("state") not in ("behind", "diverged"):
        return None
    return "Teseo: " + str(esito.get("message", ""))[:300]
