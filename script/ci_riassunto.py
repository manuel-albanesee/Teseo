"""Riassume l'output di unittest come annotazioni GitHub Actions (una per test fallito), leggibili anche via API.

Uso: python script/ci_riassunto.py suite.log
Legge i blocchi «ERROR: test_x (modulo.Classe.test_x)» e «FAIL: ...» con la coda del traceback e stampa
`::error title=<test>::<testo>` più un conteggio finale. Non modifica nulla e non fallisce mai.
"""
import re
import sys
from pathlib import Path

BLOCCO = re.compile(r"^(ERROR|FAIL): (.+)$", re.M)
SEPARATORE = re.compile(r"^={20,}$|^-{20,}$", re.M)


def escapa(testo):
    return testo.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def riassumi(log):
    righe = []
    for trovato in BLOCCO.finditer(log):
        fine = SEPARATORE.search(log, trovato.end() + 80)
        corpo = log[trovato.end():fine.start() if fine else len(log)]
        coda = "\n".join([riga for riga in corpo.strip().splitlines() if riga.strip() and not re.fullmatch(r"[-=]{20,}", riga.strip())][-8:])
        righe.append("::error title=%s %s::%s" % (trovato.group(1), escapa(trovato.group(2)[:160]), escapa(coda[:1500])))
    esito = re.findall(r"^(Ran \d+ tests.*|OK.*|FAILED.*)$", log, re.M)
    righe.append("::notice title=Esito suite::%s" % escapa(" | ".join(esito)))
    return righe


if __name__ == "__main__":
    testo = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace") if len(sys.argv) > 1 else ""
    print("\n".join(riassumi(testo)))
