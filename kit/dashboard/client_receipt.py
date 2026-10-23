"""CLI locale esplicita: produce ricevuta, non invia rete né applica note."""
import argparse
from pathlib import Path

from .contracts import canonical_json, parse_json, ContractError
from .storage import capture_snapshot, _no_link


def create_receipt(request_path, outcome, reason='', checks=None):
    request_path=Path(request_path).resolve(strict=True)
    _no_link(request_path)
    if request_path.stat().st_size>16384:
        raise ContractError('invalid_receipt','Mandato troppo grande')
    request=parse_json(request_path.read_bytes())
    workspace=Path(request['workspace'])
    if workspace.resolve(strict=True)!=request_path.parent/'workspace':
        raise ContractError('invalid_receipt','Copia isolata non corrispondente al mandato')
    snapshot=capture_snapshot(workspace)
    return {'operation_id':request['operation_id'],'base_content_digest':request['base_content_digest'],
            'phase':request['phase'],'token':request['token'],'outcome':outcome,'files':snapshot.hashes,
            'processed_response_ids':[],'checks':checks or {},'reason':reason}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    parser.add_argument('--outcome',choices=('succeeded','failed','awaiting_user'),required=True)
    parser.add_argument('--reason',default='')
    args=parser.parse_args(argv)
    path=Path(args.request).resolve(strict=True)
    receipt=create_receipt(path,args.outcome,args.reason)
    output=path.parent/'receipt.json'
    _no_link(output)
    output.write_bytes(canonical_json(receipt))
    print('Ricevuta locale creata: '+str(output))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
