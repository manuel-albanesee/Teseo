"""Explicit receive (Windows and POSIX): journal files, index and ref; never automatic apply."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from .contracts import ContractError,canonical_json,parse_json,resolve_path,file_hash,check_path_budget,stamp_schema
from .diagnostics import log_unexpected as _log_unexpected
from .storage import VaultLock,Journal,capture_snapshot,_local_directory,_ensure_ignored,_no_link
from .shared_migration import _connection
from .ontology_apply import _replace,_move_new,_write_stage,_local_volume,_check_live
from .sync_service import _fields,_oid


class ReceiverApplyService:
    def __init__(self,registry,sync_service,receiver):
        self.registry=registry;self.sync=sync_service;self.receiver=receiver

    def _root(self,vault):
        try:return self.registry.root(vault)
        except ContractError:
            if hasattr(self.registry,'operation_root'):return self.registry.operation_root(vault)
            raise

    @staticmethod
    def _path(root):
        for part in (root/'.teseo',root/'.teseo/local'): _no_link(part)
        path=root/'.teseo/local/receive.sqlite'
        for suffix in ('','-wal','-shm','-journal'): _no_link(Path(str(path)+suffix))
        return path

    def _load(self,root):
        path=self._path(root)
        if not path.exists():return None
        with _connection(path.as_uri()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT record FROM transactions ORDER BY rowid DESC LIMIT 1').fetchone()
        return parse_json(row[0]) if row else None

    def _save(self,root,record):
        _ensure_ignored(_local_directory(root))
        with _connection(self._path(root)) as db:
            db.execute('PRAGMA synchronous=FULL')
            stamp_schema(db)
            db.execute('CREATE TABLE IF NOT EXISTS transactions(operation_id TEXT PRIMARY KEY,record BLOB NOT NULL)')
            db.execute('INSERT OR REPLACE INTO transactions VALUES(?,?)',(record['operation_id'],canonical_json(record)))

    @staticmethod
    def _public(record):
        if not record:return None
        return {key:record.get(key) for key in ('operation_id','state','B','R','base_digest','candidate_digest','error','update_event')}

    def status(self,vault):
        root=self._root(vault);record=self._load(root)
        result=self._public(record)
        if result and record['state'] in ('current','rolled_back'):
            lock=root/'.git/index.lock';_no_link(lock)
            if lock.exists() and lock.read_bytes()==record['index_lock_marker'].encode('ascii'):
                result.update(state='recovery_required',finalized_state=record['state'])
        return result

    @staticmethod
    def _confirm(body,recovery=False):
        _fields(body,('exclusive_confirmed','expected_head','pending_oid','expected_digest')+ (('action',) if recovery else ()))
        if body['exclusive_confirmed'] is not True:
            raise ContractError('receiver_confirmation','Sospendere editor, client e hook esterni; revisionare il candidato prima dell’import manuale')
        _oid(body['expected_head']);_oid(body['pending_oid'])
        if (not isinstance(body['expected_digest'],str) or len(body['expected_digest'])!=64
            or any(char not in '0123456789abcdef' for char in body['expected_digest'])):
            raise ContractError('receiver_request','Digest candidato non valido')
        if recovery and body['action'] not in ('finish','rollback'):raise ContractError('receiver_request','Scegliere finish oppure rollback')

    @staticmethod
    def _same_request(record,body):
        return (record['B']==body['expected_head'] and record['R']==body['pending_oid'] and record['candidate_digest']==body['expected_digest'])

    @staticmethod
    def _persist(root,prefix,snapshot):
        resolve_path(root,prefix+'/wiki')
        cursor=root
        for part in Path(prefix+'/wiki').parts:
            cursor/=part;_no_link(cursor);cursor.mkdir(exist_ok=True)
        for item in snapshot.files:_write_stage(root,prefix+'/'+item.path,item.data)

    @staticmethod
    def _validate(base_root,candidate_root):
        from .sync_validation import _structural,_synthesis
        from .graph_service import rebuild
        base=capture_snapshot(base_root);candidate=capture_snapshot(candidate_root)
        _structural((base,),candidate);rebuild(candidate_root);_synthesis(candidate_root)
        base.assert_unchanged(base_root);candidate.assert_unchanged(candidate_root)

    def apply(self,vault,body):
        self._confirm(body);root=self._root(vault);check_path_budget(root)
        with self.sync._mutex,VaultLock(root,recovery=True) as lock:
            previous=self._load(root)
            if previous and self._same_request(previous,body):
                if previous['state']=='current':
                    return self._terminal(vault,root,self.sync._repo(root),previous)
                if previous['state']=='rolled_back':
                    # Un rollback scarta candidato e revisione: ripetere la richiesta non è un successo da rispondere di nuovo.
                    self._terminal(vault,root,self.sync._repo(root),previous)
                    raise ContractError('receiver_stale','Ricezione annullata con rollback: rileggere il candidato prima di importare di nuovo')
                raise ContractError('recovery_required','Ricezione già iniziata: usare finish/rollback')
            if previous and previous['state'] not in ('current','rolled_back','failed'):
                raise ContractError('recovery_required','Un’importazione precedente richiede recovery')
            with Journal(lock) as journal:journal.assert_notes_idle()
            _local_volume(root)
            pending=self.receiver._load(root)
            if (pending['state']!='pending' or not pending.get('candidate') or pending['pending_oid']!=body['pending_oid']
                or pending.get('last_seen_remote_oid')!=body['pending_oid'] or pending['candidate']['oid']!=body['pending_oid']
                or pending['base_head']!=body['expected_head'] or pending['candidate_digest']!=body['expected_digest']):
                raise ContractError('receiver_stale','Rileggere il candidato e i suoi input prima dell’import')
            review=pending.get('preview')
            if not review or review.get('truncated') is not False or review.get('complete') is not True:
                raise ContractError('receiver_preview_incomplete','Preview troncata o assente: revisionare il candidato completo con strumenti locali')
            config=self.receiver._config(root)
            if config!=pending['config'] or self.receiver._publishing(root):raise ContractError('sync_pending','Configurazione o pubblicazione pendenti')
            repo=self.sync._repo(root);self.sync._identity(repo,config)
            if repo.head()!=pending['base_head'] or not repo.clean():raise ContractError('blocked_external_change','HEAD, index o working tree cambiati')
            base=capture_snapshot(root)
            if base.digest!=pending['base_digest']:raise ContractError('blocked_external_change','Note cambiate dopo il controllo remoto')
            self.sync._assert_candidate(repo,{'oid':pending['base_head'],'root':str(root)})
            self.sync._assert_candidate(repo,pending['candidate'])
            candidate=capture_snapshot(pending['candidate']['root'])
            if candidate.digest!=body['expected_digest']:raise ContractError('receiver_stale','Candidato modificato dopo la preview')
            if not repo.is_ancestor(pending['base_head'],pending['pending_oid']):raise ContractError('receiver_diverged','Import richiede fast-forward')
            repo.audit_history(pending['pending_oid'])
            self._validate(root,pending['candidate']['root'])
            base.assert_unchanged(root);self.sync._assert_candidate(repo,pending['candidate'])
            if repo.head()!=pending['base_head'] or not repo.clean():raise ContractError('blocked_external_change','Scrittura intervenuta durante la validazione')
            identifier=pending['operation_id'];prefix='.teseo/local/receives/'+identifier+'/'+str(uuid4())
            self._persist(root,prefix+'/base',base);self._persist(root,prefix+'/candidate',candidate)
            index=root/'.git/index';_no_link(index);_no_link(root/'.git/index.lock')
            if not index.is_file() or index.stat().st_size>64*1024*1024 or (root/'.git/index.lock').exists():
                raise ContractError('receiver_index','Index o lock Git da verificare')
            before=index.read_bytes();_write_stage(root,prefix+'/index.base',before)
            target=root/(prefix+'/index.target')
            repo._bytes('read-tree',pending['pending_oid'],env={'GIT_INDEX_FILE':str(target)})
            after=target.read_bytes()
            record=dict(operation_id=identifier,state='applying',B=pending['base_head'],R=pending['pending_oid'],
                branch=config['branch'],config=config,base_digest=base.digest,candidate_digest=candidate.digest,
                snapshot_path=prefix+'/base',checkpoint={'candidate_path':prefix+'/candidate'},prefix=prefix,
                index_base=hashlib.sha256(before).hexdigest(),index_target=hashlib.sha256(after).hexdigest(),
                index_lock_marker='TESEO_RECEIVE '+identifier,attempts=[],error=None)
            self._save(root,record)
            return self._execute(vault,root,repo,lock,record,'finish')

    def _release(self,root,record):
        lock=root/'.git/index.lock';_no_link(lock)
        if lock.exists():
            if lock.read_bytes()!=record['index_lock_marker'].encode('ascii'):
                raise ContractError('receiver_index','Lock Git esterno da preservare')
            lock.unlink()

    def _check(self,root,repo,record,base,candidate):
        live=_check_live(root,record,base,candidate)
        if repo.head() not in (record['B'],record['R']):raise ContractError('recovery_conflict','HEAD mosso esternamente: nessuna sostituzione')
        if repo.branch()!=record['branch'] or repo.remote_url()!=record['config']['remote_url']:
            raise ContractError('recovery_conflict','Branch o remote cambiati')
        index=root/'.git/index';_no_link(index)
        missing=not index.exists() and bool(record.get('index_attempts'))
        if not missing and (not index.is_file() or file_hash(index) not in (record['index_base'],record['index_target'])):
            raise ContractError('recovery_conflict','Index modificato esternamente: conservarlo')
        for attempt in record.get('index_attempts',[]):
            backup=resolve_path(root,attempt['backup']);_no_link(backup)
            if backup.exists() and file_hash(backup)!=attempt['expected']:
                raise ContractError('recovery_conflict','Backup index contiene modifiche esterne')
        return live

    def _metadata(self,vault,root,record,action,desired,reference):
        desired_oid=record['R'] if action=='finish' else record['B']
        update={'type':'vault.updated','operation_id':record['operation_id'],'oid':desired_oid,'content_revision':desired.digest,'graph_generation':reference.generation}
        config=self.receiver._config(root);config.update(B=desired_oid,base_digest=desired.digest)
        with self.sync._db(root) as db:db.execute('UPDATE config SET data=? WHERE id=1',(canonical_json(config),))
        pending=self.receiver._load(root)
        fresh=pending.get('update_event')!=update
        pending.update(state='current' if action=='finish' else 'idle',last_applied_oid=desired_oid,preview=None,
            pending_oid=None if action=='finish' else record['R'],update_event=update,revision=pending.get('revision',0)+int(fresh))
        if action=='rollback':pending.update(candidate=None,candidate_digest=None,operation_id=None,base_head=None,base_digest=None)
        self.receiver._save(root,pending)
        return update

    @staticmethod
    def _final(root,repo,record,desired,desired_oid,wanted):
        if repo.head()!=desired_oid or capture_snapshot(root).digest!=desired.digest or file_hash(root/'.git/index')!=wanted:
            raise ContractError('recovery_conflict','Postcondizione ricezione diversa da note, index e ref attesi')
        if repo.branch()!=record['branch'] or repo.remote_url()!=record['config']['remote_url']:
            raise ContractError('recovery_conflict','Identità Git cambiata prima del checkpoint')

    def _terminal(self,vault,root,repo,record):
        owned=root/'.git/index.lock';_no_link(owned)
        if owned.exists():
            action='finish' if record['state']=='current' else 'rollback'
            desired=capture_snapshot(root/(record['checkpoint']['candidate_path'] if action=='finish' else record['snapshot_path']))
            self._final(root,repo,record,desired,record['R'] if action=='finish' else record['B'],record['index_target'] if action=='finish' else record['index_base'])
            self._release(root,record)
        return self._public(record)

    def _execute(self,vault,root,repo,lock,record,action):
        try:
            base=capture_snapshot(root/record['snapshot_path']);candidate=capture_snapshot(root/record['checkpoint']['candidate_path'])
            if base.digest!=record['base_digest'] or candidate.digest!=record['candidate_digest']:
                raise ContractError('snapshot_corrupt','Snapshot ricezione alterati')
            desired=candidate if action=='finish' else base
            desired_oid=record['R'] if action=='finish' else record['B']
            live=self._check(root,repo,record,base,candidate)
            git_lock=root/'.git/index.lock';_no_link(git_lock)
            if git_lock.exists():
                if git_lock.read_bytes()!=record['index_lock_marker'].encode('ascii'):raise ContractError('receiver_index','Lock Git estraneo')
            else:
                with git_lock.open('xb') as stream:stream.write(record['index_lock_marker'].encode('ascii'));stream.flush();os.fsync(stream.fileno())
            record.update(state='applying',action=action,error=None);self._save(root,record)
            values={f.path:f.data for f in desired.files}
            changes={p for p in base.hashes.keys()|candidate.hashes.keys() if base.hashes.get(p)!=candidate.hashes.get(p)}
            for path in sorted(changes,key=lambda p:(p.startswith('.teseo/shared/'),p=='Wiki reference.md',p)):
                live=self._check(root,repo,record,base,candidate)
                if live.hashes.get(path)==desired.hashes.get(path):continue
                target=resolve_path(root,path)
                for parent in (target,*target.parents):
                    if parent==root:break
                    _no_link(parent)
                token=str(uuid4());prefix=record['prefix']+'/attempts/'+token
                staged=_write_stage(root,prefix+'/staged',values.get(path,b''))
                attempt={'path':path,'backup':prefix+'/displaced','expected':live.hashes.get(path),'after':desired.hashes.get(path)}
                record['attempts'].append(attempt);self._save(root,record)
                self._check(root,repo,record,base,candidate)
                if path not in values:os.rename(target,root/attempt['backup'])
                elif target.exists():_replace(target,staged,root/attempt['backup'])
                else:target.parent.mkdir(parents=True,exist_ok=True);_move_new(staged,target)
                self._check(root,repo,record,base,candidate)
            if capture_snapshot(root).digest!=desired.digest:raise ContractError('recovery_conflict','Contenuto finale diverso dal candidato')
            wanted=record['index_target'] if action=='finish' else record['index_base']
            if not (root/'.git/index').exists() or file_hash(root/'.git/index')!=wanted:
                token=str(uuid4());prefix=record['prefix']+'/attempts/'+token
                source=root/(record['prefix']+('/index.target' if action=='finish' else '/index.base'))
                _no_link(source)
                if file_hash(source)!=wanted:raise ContractError('snapshot_corrupt','Index conservato alterato')
                staged=_write_stage(root,prefix+'/staged',source.read_bytes())
                item={'backup':prefix+'/index.displaced','expected':file_hash(root/'.git/index') if (root/'.git/index').exists() else None}
                record.setdefault('index_attempts',[]).append(item);self._save(root,record)
                self._check(root,repo,record,base,candidate)
                if (root/'.git/index').exists():_replace(root/'.git/index',staged,root/item['backup'])
                else:_move_new(staged,root/'.git/index')
                self._check(root,repo,record,base,candidate)
            current=repo.head()
            if current not in (record['B'],record['R']):raise ContractError('recovery_conflict','HEAD esterno da preservare prima del CAS')
            if current!=desired_oid:repo.run('update-ref','refs/heads/'+record['branch'],desired_oid,current)
            self._check(root,repo,record,base,candidate)
            record['state']='rebuilding';self._save(root,record)
            from .graph_service import rebuild
            from .shared_state import snapshot_events,rebuild_projection
            reference=rebuild(root,lock=lock)
            projection=root/'.teseo/local/shared-state.sqlite'
            for suffix in ('','-wal','-shm','-journal'): _no_link(Path(str(projection)+suffix))
            rebuild_projection(projection,snapshot_events(desired,lock.vault_id),lock.vault_id)
            self._check(root,repo,record,base,candidate)
            self._final(root,repo,record,desired,desired_oid,wanted)
            update=self._metadata(vault,root,record,action,desired,reference)
            self._final(root,repo,record,desired,desired_oid,wanted)
            record.update(state='current' if action=='finish' else 'rolled_back',update_event=update,error=None);self._save(root,record)
        except Exception as error:
            if not isinstance(error,ContractError):_log_unexpected(error)
            record.update(state='recovery_required',error=error.as_dict() if isinstance(error,ContractError) else {'code':'receiver_interrupted','message':'Ricezione interrotta; conservare copie e scegliere finish/rollback'})
            self._save(root,record)
            return self._public(record)
        try:self._release(root,record)
        except (ContractError,OSError) as error:
            # Checkpoint già durevole: lo stato terminale non si declassa; il lock residuo lo chiude recover/_terminal.
            _log_unexpected(error)
            return self._public(record)|{'state':'recovery_required','finalized_state':record['state'],'error':error.as_dict() if isinstance(error,ContractError) else {'code':'receiver_index','message':'Lock Git da rilasciare con il recupero'}}
        return self._public(record)

    def recover(self,vault,body):
        self._confirm(body,True);root=self._root(vault)
        with self.sync._mutex,VaultLock(root,recovery=True) as lock:
            _local_volume(root);record=self._load(root)
            if not record or not self._same_request(record,body):raise ContractError('receiver_stale','Selezionare la ricezione originale da recuperare')
            if record['state'] in ('current','rolled_back'):
                return self._terminal(vault,root,self.sync._repo(root),record)
            with Journal(lock) as journal:journal.assert_notes_idle()
            return self._execute(vault,root,self.sync._repo(root),lock,record,body['action'])
