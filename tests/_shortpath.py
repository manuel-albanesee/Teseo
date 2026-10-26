"""Importare per primo: su Windows senza percorsi lunghi le temp dir dei test restano corte.

Il grafo candidato annidato in uno snapshot supera MAX_PATH (260) sotto la temp dir
predefinita dell'utente; check_path_budget rifiuterebbe l'operazione. Le variabili
d'ambiente sono impostate anche per i processi figli.
"""
import os
from pathlib import Path
import sys
import tempfile

# Anche i test rilanciati come processo figlio importano questo modulo prima di preparare sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kit.dashboard.contracts import max_vault_path_length

if max_vault_path_length() is not None:
    short = Path(tempfile.gettempdir()).resolve().anchor + "teseo-tmp"
    os.makedirs(short, exist_ok=True)
    tempfile.tempdir = short
    os.environ.update(TMPDIR=short, TEMP=short, TMP=short)
