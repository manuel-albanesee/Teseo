"""Avvia il servizio locale del kit installato, senza eseguire codice dei vault collegati."""
import sys

if sys.version_info < (3, 10):
    raise SystemExit("La dashboard Teseo richiede Python 3.10 o successivo")

from dashboard.server import main


if __name__ == "__main__":
    main()
