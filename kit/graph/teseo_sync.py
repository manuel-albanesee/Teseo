"""Ispezione readonly di un candidato Git conservato: nessun apply o push."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

try:
    from dashboard.contracts import ContractError
    from dashboard.storage import capture_snapshot,_no_link
except ImportError:
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from kit.dashboard.contracts import ContractError
    from kit.dashboard.storage import capture_snapshot,_no_link


def inspect_candidate(vault,candidate):
    root=Path(vault).resolve(strict=True)
    base=root/'.teseo/local/git-candidates'
    for path in (root/'.teseo',root/'.teseo/local',base):_no_link(path)
    path=Path(candidate)
    _no_link(path)
    target=path.resolve(strict=True)
    if target.parent!=base.resolve(strict=True) or str(UUID(target.name))!=target.name:
        raise ContractError('sync_candidate_path','Selezionare un candidato conservato di questo vault')
    snapshot=capture_snapshot(target)
    return {'candidate_path':str(target),'resolution_digest':snapshot.digest,'files':snapshot.hashes,
            'notice':'Revisionare note, fonti e conflitti; il digest non attesta correttezza semantica. Nessuna scrittura o pubblicazione.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault',required=True);parser.add_argument('--candidate',required=True)
    args=parser.parse_args(argv)
    try:
        print(json.dumps(inspect_candidate(args.vault,args.candidate),ensure_ascii=False,indent=2));return 0
    except (ContractError,OSError,ValueError) as error:
        print(str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
