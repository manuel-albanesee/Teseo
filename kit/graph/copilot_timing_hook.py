"""Hook Copilot CLI: misura la durata dei tool e la rende visibile in timeline.

preToolUse registra l'istante di avvio di ogni chiamata; postToolUse e
postToolUseFailure calcolano i millisecondi impiegati, emettono una riga di
progresso nella timeline della CLI ({"type": "progress"}, senza toccare il
contesto del modello) e appendono il dettaglio in .graph/timing.jsonl:
istante, tool, ms, esito, argomenti e anteprima del risultato, cioè i fatti
ricavati (per sql: le righe della query). Il log resta nel vault e si può
rileggere o filtrare in seguito.

Il payload non ha un id di chiamata: la correlazione pre/post avviene per
sessionId + toolName con una pila FIFO in .graph/timing-stato/<sessione>.json.
Non blocca mai: preToolUse è fail-closed, quindi ogni errore degrada a {}
senza impedire l'esecuzione del tool.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

QUI = Path(__file__).resolve().parent
LOG = QUI / "timing.jsonl"
STATO_DIR = QUI / "timing-stato"
MAX_PILA = 20
MAX_ANTEPRIMA = 800
MAX_ARGOMENTI = 300


def stato_path(sid: object) -> Path:
    if not isinstance(sid, str) or not sid:
        raise ValueError("sessionId mancante")
    return STATO_DIR / (hashlib.sha256(sid.encode("utf-8")).hexdigest() + ".json")


def carica(path: Path) -> dict:
    try:
        stato = json.loads(path.read_text(encoding="utf-8"))
        return stato if isinstance(stato, dict) and isinstance(stato.get("pile"), dict) else {"pile": {}}
    except (OSError, ValueError):
        return {"pile": {}}


def salva(path: Path, stato: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    temporaneo = path.with_name(uuid.uuid4().hex + ".tmp")
    try:
        temporaneo.write_text(json.dumps(stato, ensure_ascii=False), encoding="utf-8")
        os.replace(temporaneo, path)
    finally:
        temporaneo.unlink(missing_ok=True)


def testo(valore: object, limite: int) -> str:
    if valore is None:
        return ""
    if not isinstance(valore, str):
        try:
            valore = json.dumps(valore, ensure_ascii=False)
        except (TypeError, ValueError):
            valore = str(valore)
    valore = " ".join(valore.split())
    return valore[:limite]


def registra_avvio(evento: dict) -> dict:
    tool = evento.get("toolName")
    if not isinstance(tool, str) or not tool:
        return {}
    path = stato_path(evento.get("sessionId"))
    stato = carica(path)
    pila = stato["pile"].setdefault(tool, [])
    if len(pila) < MAX_PILA:
        pila.append(time.time() * 1000)
    salva(path, stato)
    return {}


def registra_fine(evento: dict, ok: bool) -> dict:
    tool = evento.get("toolName")
    if not isinstance(tool, str) or not tool:
        return {}
    ms = None
    try:
        path = stato_path(evento.get("sessionId"))
        stato = carica(path)
        pila = stato["pile"].get(tool) or []
        if pila:
            ms = round(time.time() * 1000 - pila.pop(0))
        if stato["pile"].get(tool) == []:
            del stato["pile"][tool]
        if stato["pile"]:
            salva(path, stato)
        else:
            path.unlink(missing_ok=True)
    except ValueError:
        pass  # sessionId mancante: la durata resta ignota ma il log si scrive lo stesso
    risultato = evento.get("toolResult") if ok else None
    if not isinstance(risultato, dict):
        risultato = {}
    voce = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": tool, "ms": ms, "ok": ok,
            "args": testo(evento.get("toolArgs"), MAX_ARGOMENTI),
            "risultato": testo(risultato.get("textResultForLlm"), MAX_ANTEPRIMA)}
    if not ok:
        voce["errore"] = testo(evento.get("error"), MAX_ANTEPRIMA)
    try:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(voce, ensure_ascii=False) + "\n")
    except OSError:
        pass
    durata = f"{ms} ms" if ms is not None else "ms n/d"
    esito = "" if ok else " · ERRORE"
    print(json.dumps({"type": "progress",
                      "message": f"⏱ {tool} · {durata}{esito}"}, ensure_ascii=False))
    return {}


def gestisci(nome: str, evento: dict) -> dict:
    if not isinstance(evento, dict):
        raise ValueError("l'evento deve essere un oggetto JSON")
    if nome == "preToolUse":
        return registra_avvio(evento)
    if nome == "postToolUse":
        return registra_fine(evento, ok=True)
    return registra_fine(evento, ok=False)


def main() -> None:
    cast(Any, sys.stdout).reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("evento", choices=("preToolUse", "postToolUse", "postToolUseFailure"))
    nome = ap.parse_args().evento
    try:
        evento = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        risultato = gestisci(nome, evento)
    except Exception as errore:
        print("Teseo timing: " + " ".join(str(errore).split())[:200], file=sys.stderr)
        risultato = {}
    print(json.dumps(risultato, ensure_ascii=False))


if __name__ == "__main__":
    main()
