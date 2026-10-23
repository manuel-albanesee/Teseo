"""Verifica sintesi da runtime fidato su copia sacrificabile, mai su DB personali."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

import build_graph
import sintesi


def main(argv=None):
    workspace=Path((argv or sys.argv[1:])[0]).resolve(strict=True)
    parsed=build_graph.parse_snapshot(workspace)
    if parsed['problemi']:
        print(json.dumps({'ok':False,'errors':list(parsed['problemi'])[:20]}))
        return 1
    with tempfile.TemporaryDirectory(prefix='teseo-synthesis-') as directory:
        root=Path(directory)
        (root/'wiki').mkdir()
        (root/'.graph').mkdir()
        for path in sorted((workspace/'wiki').glob('*.md')):
            (root/'wiki'/path.name).write_bytes(path.read_bytes())
        candidate=build_graph.build_candidate(parsed,root/'.graph/graph.sqlite')
        db=sqlite3.connect(candidate)
        try:
            problems=sintesi.verifica(db,root/'.graph')
        finally:
            db.close()
        print(json.dumps({'ok':not problems,'errors':problems[:20]},ensure_ascii=False))
        return 0 if not problems else 1


if __name__=='__main__':
    raise SystemExit(main())
