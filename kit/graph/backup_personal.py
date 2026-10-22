"""Backup consistente dei DB personali di un vault con manifest compatibile."""
import argparse
from pathlib import Path

from dashboard.graph_service import backup_personal_databases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    print(backup_personal_databases(args.vault))


if __name__ == "__main__":
    main()
