"""Hook PostToolUse (Read) e Stop: collega alla domanda in sospeso le pagine di wiki/ lette, e a fine turno le archivia.

La domanda la mette in sospeso recall_hook.py quando il grafo non la riconosce; il ciclo è descritto in memoria.py.
Log dei turni (memoria.py): ogni Read di una pagina di wiki/ è collegata anche all'ultimo turno della sessione
(tabella letture_turno), sempre, con o senza domanda in sospeso: `memoria.py --turni` confronta così le pagine iniettate
da recall_hook.py con quelle che il modello ha poi aperto. Un errore nel log non fa fallire l'annotazione per la memoria.
Registrato in .claude/settings.json; si prova a mano con:
  echo '{"hook_event_name": "PostToolUse", "session_id": "prova", "tool_input": {"file_path": "wiki/Rilascio in produzione.md"}}' | python .graph/learn_hook.py
  echo '{"hook_event_name": "Stop", "session_id": "prova"}' | python .graph/learn_hook.py
"""
import json
import sys
from pathlib import Path

from memoria import apri, annota, chiudi, leggi_turno


def pagina_wiki(vault, file_path):
    p = Path(file_path)
    if not p.is_absolute():
        p = vault / p
    p = p.resolve()
    if p.suffix.lower() != ".md" or p.parent != (vault / "wiki").resolve():
        return None
    return p.stem


def main():
    qui = Path(__file__).resolve().parent
    evento = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sessione = evento.get("session_id", "")
    mem = apri(qui / "memoria.sqlite")
    try:
        if evento.get("hook_event_name") == "PostToolUse":
            pagina = pagina_wiki(qui.parent, (evento.get("tool_input") or {}).get("file_path", ""))
            if pagina:
                annota(mem, sessione, pagina)
                try:  # il log dei turni è un di più: se fallisce, l'hook non deve finire in traceback
                    leggi_turno(mem, sessione, pagina)
                except Exception:
                    pass
        elif evento.get("hook_event_name") == "Stop":
            pagine = chiudi(mem, sessione)
            if pagine:
                print(json.dumps({"systemMessage": f"memoria: domanda collegata a {', '.join(pagine)}"}))
    finally:
        mem.close()


if __name__ == "__main__":
    main()
