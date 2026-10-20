"""Legge pagine wiki da shell e registra solo letture riuscite nel turno Codex.

Uso: python .graph/leggi.py --turno <token dall'hook> "wiki/Pagina.md"
Senza --turno legge soltanto. Non esegue il testo delle pagine.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from codex_hook import QUI, VAULT, registra_letture
from learn_hook import pagina_wiki


def leggi(paths, token=None):
    sid = None
    if token:
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise ValueError("token turno non valido")
        sid = json.loads((QUI / "codex-turni" / (token + ".json")).read_text(encoding="utf-8"))["sessione"]
    for path in paths:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = VAULT / resolved
        if not pagina_wiki(VAULT, str(resolved)):
            raise ValueError("leggi.py accetta soltanto pagine .md direttamente in wiki/")
        text = resolved.read_text(encoding="utf-8-sig")
        print(f"\n--- {resolved.name} ---\n{text}", flush=True)
        if sid:
            registra_letture(sid, [str(resolved)])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pagine", nargs="+")
    ap.add_argument("--turno")
    args = ap.parse_args()
    try:
        leggi(args.pagine, args.turno)
    except (OSError, ValueError, KeyError) as error:
        ap.exit(1, f"Teseo: {error}\n")


if __name__ == "__main__":
    main()
