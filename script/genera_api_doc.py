"""Genera doc/api.md dai docstring dei moduli Python del kit.

Uso: python script/genera_api_doc.py [--check]
Senza opzioni riscrive doc/api.md; con --check verifica che sia aggiornato
(exit 1 se diverso, senza scrivere). L'output è deterministico: niente date,
percorsi assoluti o dati dell'ambiente. Lo esegue il test tests/test_api_doc.py.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINO = ROOT / "doc" / "api.md"
SORGENTI = [ROOT / "installa.py"] + sorted((ROOT / "kit" / "graph").glob("*.py")) + \
           sorted((ROOT / "kit" / "dashboard").glob("*.py"))

INTESTAZIONE = """# Riferimento API del kit

Generato da `script/genera_api_doc.py` a partire dai docstring dei moduli: non modificare a mano.
Dopo una modifica al codice esegui `python script/genera_api_doc.py` e verifica con `--check`.
Sono elencate le funzioni e le classi pubbliche (nome senza `_` iniziale) con la prima riga del
loro docstring; il docstring del modulo è riportato per esteso perché documenta il contratto.

Per la mappa dei componenti, gli schemi SQLite e i contratti degli hook vedi
[architettura-motore.md](architettura-motore.md).
"""


def firma(nodo):
    args = ast.unparse(nodo.args)
    prefix = "async " if isinstance(nodo, ast.AsyncFunctionDef) else ""
    return f"`{prefix}{nodo.name}({args})`"


def prima_riga(nodo):
    doc = ast.get_docstring(nodo)
    return doc.strip().splitlines()[0] if doc else "—"


def membri(albero, tipo):
    return [n for n in albero.body if isinstance(n, tipo) and not n.name.startswith("_")]


def sezione(percorso):
    relativo = percorso.relative_to(ROOT).as_posix()
    albero = ast.parse(percorso.read_text(encoding="utf-8"), filename=relativo)
    doc = ast.get_docstring(albero) or ""
    parti = [f"\n## `{relativo}`\n", doc, ""]
    classi = membri(albero, ast.ClassDef)
    if classi:
        parti += ["| Classe | Descrizione |", "| --- | --- |"]
        for c in classi:
            parti.append(f"| `{c.name}` | {prima_riga(c)} |")
        parti.append("")
    funzioni = membri(albero, (ast.FunctionDef, ast.AsyncFunctionDef))
    if funzioni:
        parti += ["| Funzione | Descrizione |", "| --- | --- |"]
        for f in funzioni:
            parti.append(f"| {firma(f)} | {prima_riga(f)} |")
        parti.append("")
    return "\n".join(parti).rstrip() + "\n"


def genera():
    blocchi = [INTESTAZIONE.rstrip()]
    blocchi += [sezione(p).rstrip() for p in SORGENTI]
    return "\n".join(blocchi) + "\n"


def main():
    testo = genera()
    if "--check" in sys.argv[1:]:
        attuale = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else None
        if attuale != testo:
            print("doc/api.md non aggiornato: esegui python script/genera_api_doc.py")
            return 1
        print("doc/api.md aggiornato")
        return 0
    DESTINO.write_text(testo, encoding="utf-8", newline="\n")
    print(f"scritto {DESTINO.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
