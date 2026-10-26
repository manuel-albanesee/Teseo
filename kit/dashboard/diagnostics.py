"""Diagnostica minima su stderr: tipo, codice contrattuale e posizione; mai messaggi, percorsi assoluti, contenuti o token."""
import os
import sys
import traceback


def log_unexpected(error: BaseException) -> None:
    try:
        stream = sys.stderr
        if stream is None:  # pythonw: nessuno stderr
            return
        if os.environ.get("TESEO_DASHBOARD_DEBUG") == "1":
            traceback.print_exception(error, file=stream)
            return
        frames = traceback.extract_tb(error.__traceback__)
        where = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}" if frames else "?"
        code = getattr(error, "code", None)  # ContractError.code è una costante, non dati utente
        extra = f" [{code}]" if isinstance(code, str) and code.isidentifier() else ""
        print(f"dashboard: errore inatteso {type(error).__name__}{extra} in {where}", file=stream)
    except Exception:
        pass  # il log non deve mai mascherare o sostituire l'errore originale
