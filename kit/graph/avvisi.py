"""Avvisi a inizio sessione per i vault collaborativi: aggiornamenti remoti non ancora ricevuti.

Solo `teseo_git.py avvisi` (un fetch): nessun pull e nessuna scrittura su note, grafo o stato dell'autosync.
Offline, tempo scaduto o qualunque guasto non disturbano l'avvio della sessione (si restituisce None).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT = 8  # secondi; gli hook SessionStart ne hanno 15
VALIDITA = 600  # secondi: sessioni ravvicinate non ripetono il fetch
CACHE = ".teseo/local/avvisi.json"  # stato locale, escluso da Git; mai note né grafo
STATI_STABILI = ("current", "behind", "diverged", "disabled")  # offline e guasti non si memorizzano: si riprova subito


def _letta(vault, adesso):
    """(True, messaggio) se c'è un esito recente in cache, altrimenti (False, None)."""
    try:
        dati = json.loads((vault / CACHE).read_text(encoding="utf-8"))
        if 0 <= adesso - float(dati["quando"]) < VALIDITA:
            messaggio = dati.get("messaggio")
            return True, messaggio if isinstance(messaggio, str) or messaggio is None else None
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return False, None


def _scritta(vault, adesso, messaggio):
    percorso = vault / CACHE
    if not percorso.parent.is_dir():
        return
    try:
        temporaneo = percorso.with_name(percorso.name + ".tmp")
        temporaneo.write_text(json.dumps({"quando": adesso, "messaggio": messaggio}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporaneo, percorso)
    except OSError:
        pass  # la cache è solo un'ottimizzazione


def remoti(vault, timeout=TIMEOUT, adesso=time.time):
    """Frase da mostrare all'utente se il remoto ha aggiornamenti (o storie divergenti), altrimenti None.
    Un esito recente (VALIDITA secondi) si riusa senza rete; `pre` e `post` lo cancellano (Autosync._forget_notice)."""
    vault = Path(vault)
    script = Path(__file__).resolve().with_name("teseo_git.py")
    if not script.is_file() or not (vault / ".teseo/project.json").is_file():
        return None
    trovata, messaggio = _letta(vault, adesso())
    if trovata:
        return messaggio
    try:
        fatto = subprocess.run([sys.executable, str(script), "avvisi", "--vault", str(vault)], capture_output=True,
                               timeout=timeout, cwd=vault)
        esito = json.loads(fatto.stdout.decode("utf-8", "replace"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if fatto.returncode or not isinstance(esito, dict):
        return None
    messaggio = "Teseo: " + str(esito.get("message", ""))[:300] if esito.get("state") in ("behind", "diverged") else None
    if esito.get("state") in STATI_STABILI:
        _scritta(vault, adesso(), messaggio)
    return messaggio
