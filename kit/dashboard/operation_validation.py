"""Gate deterministici del candidato: attribuzione e confini prima dell'apply."""
import difflib
from .contracts import ContractError, content_hash, canonical_json
from .storage import validate_raw_unchanged
from .read_api import _parser


def validate_candidate(base, candidate, *, kind, inputs, scope, processed_response_ids=()):
    validate_raw_unchanged(base,candidate)
    before,after=base.hashes,candidate.hashes
    if before.get('.teseo/project.json')!=after.get('.teseo/project.json'):
        raise ContractError('manifest_changed','Identità o policy del vault non modificabili dal client')
    if processed_response_ids or any(p.startswith('.teseo/shared/') for p in set(before)|set(after)):
        raise ContractError('shared_mapping_unavailable','Record condivisi e risposte richiedono il passo 5')
    if set(before)-set(after):
        raise ContractError('page_mapping_unavailable','Eliminazioni/rinomine richiedono mapping e revisione espliciti')
    changed=sorted(p for p in after if before.get(p)!=after[p])
    if any(p.startswith('raw/') for p in changed):
        raise ContractError('input_not_selected','Le fonti vanno predisposte prima del ciclo; nessun raw prodotto dal client')
    for path in changed:
        if path not in scope and not (path.startswith('wiki/') and path.count('/')==1 and 'wiki/' in scope):
            raise ContractError('scope_violation','Modifica fuori dal perimetro dichiarato',path)
    documents={item.path:item.data.decode('utf-8') for item in candidate.files
               if item.path in ('Wiki reference.md','index.md','log.md') or item.path.startswith('wiki/')}
    parsed=_parser().parse_documents(documents)
    if parsed['problem_details']:
        raise ContractError('candidate_invalid','Schema, link, tipi, alias o fonti non validi: '+str(parsed['problem_details'][0]['code']))
    manifest={'operation_kind':kind,'base_digest':base.digest,'candidate_digest':candidate.digest,
              'files':[{'path':p,'before':before.get(p),'after':after[p]} for p in changed],
              'inputs':{p:before[p] for p in inputs},'scope':scope,
              'lint_scope':'whole_wiki' if 'wiki/' in scope else 'partial',
              'semantic_assurance':'client_declared; human review required',
              'checks':{'schema_links_aliases_sources':True,'raw_immutable':True,'scope':True,'shared_records_absent':True}}
    originals={item.path:item.data for item in base.files}
    outputs={item.path:item.data for item in candidate.files}
    manifest['diffs']=[{'path':path,'diff':''.join(difflib.unified_diff(
        originals.get(path,b'').decode('utf-8').splitlines(keepends=True),outputs[path].decode('utf-8').splitlines(keepends=True),
        fromfile=path+' (base)',tofile=path+' (candidato)'))} for path in changed]
    if len(canonical_json(manifest))>256*1024:
        raise ContractError('candidate_limit','Diff completo oltre 256 KiB: ridurre il perimetro del ciclo')
    return dict(manifest,manifest_digest=content_hash(manifest))
