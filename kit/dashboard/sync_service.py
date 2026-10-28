"""Publisher esplicito: checkpoint attribuiti, candidati isolati e recovery OID.

La configurazione non autorizza l'automazione: ogni tentativo richiede conferma
di sospensione degli scrittori esterni. Credenziali gestite soltanto da Git.
"""
from datetime import date
from pathlib import Path
import hashlib
import re
import threading

from .contracts import ContractError, canonical_json, content_hash, parse_json, portable_path, stamp_schema
from .storage import VaultLock, capture_snapshot, _local_directory, _ensure_ignored, _no_link
from .shared_migration import _connection
from .shared_state import _uuid


def _fields(body,required,optional=()):
    if not isinstance(body,dict) or not set(required)<=set(body) or set(body)-set(required)-set(optional):
        raise ContractError('sync_request','Campi pubblicazione non validi')


def _key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',value):
        raise ContractError('sync_request','Chiave idempotente non valida')
    return value


def _oid(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',value):
        raise ContractError('sync_request','Revisione Git non valida')
    return value


class SyncService:
    def __init__(self,registry,*,repository_factory=None,validator=None):
        self.registry=registry;self.repository_factory=repository_factory;self.validator=validator
        self._mutex=threading.RLock()

    def _repo(self,root):
        if self.repository_factory:return self.repository_factory(root)
        from .git_sync import GitRepository
        return GitRepository(root)

    @staticmethod
    def _path(root):
        for relative in ('.teseo','.teseo/local'): _no_link(root/relative)
        path=root/'.teseo/local/sync.sqlite'
        for suffix in ('','-wal','-shm','-journal'): _no_link(Path(str(path)+suffix))
        return path

    def _db(self,root):
        local=_local_directory(root);_ensure_ignored(local)
        return _connection(self._path(root))

    @staticmethod
    def _schema(db):
        db.execute('PRAGMA synchronous=FULL')
        stamp_schema(db)
        db.execute('CREATE TABLE IF NOT EXISTS config(id INTEGER PRIMARY KEY CHECK(id=1),data BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS jobs(operation_id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,data BLOB NOT NULL)')
        db.commit()

    @staticmethod
    def _config(db):
        row=db.execute('SELECT data FROM config WHERE id=1').fetchone()
        if not row:raise ContractError('sync_unconfigured','Configurare e revisionare prima il repository dati')
        return parse_json(row[0])

    @staticmethod
    def _save(db,record):
        with db:db.execute('UPDATE jobs SET data=? WHERE operation_id=?',(canonical_json(record),record['operation_id']))

    @staticmethod
    def _public(record):
        return {k:v for k,v in record.items() if k not in {'files','config','expected_digest','request_hash'}}

    def status(self,vault_id,parameters=None):
        if parameters:raise ContractError('invalid_parameters','Parametri sync non supportati')
        try:root=self.registry.root(vault_id)
        except ContractError:
            if not hasattr(self.registry,'operation_root'):raise
            root=self.registry.operation_root(vault_id)
        path=self._path(root)
        result={'configured':False,'state':'unconfigured','head':None,'branch':None,'operations':[],
                'automatic':False,'authentication':'delegated_to_git; not_attested'}
        try:
            from .storage import assert_receiver_complete
            assert_receiver_complete(root)
            git=self._repo(root).inspect();result.update(git=git,head=git['head'],branch=git['branch'])
        except ContractError as error:result['git_error']=error.as_dict()
        if not path.exists():return result
        with _connection(path.as_uri()+'?mode=ro',uri=True) as db:
            config=self._config(db)
            jobs=[self._public(parse_json(row[0])) for row in db.execute('SELECT data FROM jobs ORDER BY rowid DESC LIMIT 30')]
        result.update(configured=True,config=config,automatic=config.get('automatic') is True,operations=jobs,
                      state=jobs[0]['state'] if jobs else 'ready',current_operation=jobs[0] if jobs else None)
        return result

    def preview(self,vault_id,body):
        _fields(body,(),('raw_paths',))
        selection=body.get('raw_paths',[])
        if not isinstance(selection,list) or len(selection)>256 or any(not isinstance(p,str) or not p.startswith('raw/') for p in selection):
            raise ContractError('sync_request','Selezione fonti non valida')
        root=self.registry.root(vault_id)
        try:
            repo=self._repo(root);preview=repo.preview(selection);git=repo.inspect()
        except ContractError as error:
            if error.code!='git_repository_required':raise
            from .git_sync import preview_data_repository
            preview=preview_data_repository(root,selection);git={'head':None,'branch':None,'remote_url':None}
        return dict(preview,git=git,automatic=False,
                    notice='Revisionare i percorsi. Visibilità dichiarata dall’utente, autenticazione e permesso push verificati da Git durante il tentativo.')

    def initialize(self,vault_id,body):
        _fields(body,('branch','remote_url','raw_paths','author','share_confirmed','expected_files'))
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root):
            from .git_sync import initialize_data_repository
            return initialize_data_repository(root,body['branch'],body['remote_url'],body['raw_paths'],
                author=body['author'],share_confirmed=body['share_confirmed'],expected_files=body['expected_files'])

    def configure(self,vault_id,body):
        _fields(body,('remote','branch','visibility','mode','raw_paths','share_confirmed','expected_head'))
        if body['share_confirmed'] is not True:raise ContractError('sync_consent','Confermare esplicitamente la selezione condivisibile')
        if body['remote']!='origin' or body['visibility'] not in ('private','public') or body['mode'] not in ('direct','pr'):
            raise ContractError('sync_config','Remote, visibilità o modalità non validi')
        branch=body['branch']
        if not isinstance(branch,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]{0,127}',branch) or any(x in branch for x in ('..','//','@{')) or branch.endswith(('/','.','.lock')):
            raise ContractError('sync_config','Branch esplicito non valido')
        raw=body['raw_paths']
        if not isinstance(raw,list) or len(raw)>256 or any(not isinstance(p,str) for p in raw) or len(set(raw))!=len(raw):
            raise ContractError('sync_config','Selezionare al massimo 256 fonti distinte')
        for p in raw:
            portable_path(p)
            if not p.startswith('raw/'):raise ContractError('sync_config','Sono ammesse solo fonti raw selezionate')
        _oid(body['expected_head'])
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root):
            repo=self._repo(root);git=repo.inspect()
            if not git.get('remote_url'):
                raise ContractError('sync_config','Configurare origin nel repository dati prima della selezione')
            if git['head']!=body['expected_head'] or git['branch']!=branch or not repo.clean():
                raise ContractError('sync_baseline','Occorre il branch scelto con index e working tree puliti')
            if git.get('tracked_violations'):raise ContractError('sync_tracked_private','File locali, binari o eseguibili già tracked: pulizia esplicita richiesta')
            preview=repo.preview(raw)
            if preview.get('tracked_violations'):raise ContractError('sync_tracked_private','File tracked fuori policy')
            snapshot=capture_snapshot(root)
            self._assert_candidate(repo,{'oid':git['head'],'root':str(root)})
            # Configuration freezes B before a root operation; it is never inferred after apply.
            config={k:body[k] for k in ('remote','branch','visibility','mode','raw_paths')}
            config.update(vault_id=vault_id,remote_url=git['remote_url'],B=git['head'],base_digest=snapshot.digest,policy_version=1,automatic=False)
            with self._db(root) as db:
                self._schema(db)
                pending=[parse_json(row[0]) for row in db.execute('SELECT data FROM jobs')]
                if any(j['state'] not in ('converged','noop') for j in pending):
                    raise ContractError('sync_pending','Conservare e risolvere il checkpoint pendente prima di riconfigurare')
                with db:db.execute('INSERT OR REPLACE INTO config VALUES (1,?)',(canonical_json(config),))
            return config

    @staticmethod
    def _event(root,operation_id):
        path=root/'.teseo/local/operations.sqlite'
        for suffix in ('','-wal','-shm','-journal'): _no_link(Path(str(path)+suffix))
        if not path.exists():raise ContractError('sync_unvalidated','Manca operation.validated')
        with _connection(path.as_uri()+'?mode=ro',uri=True) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='validated_events'").fetchone():
                raise ContractError('sync_unvalidated','Manca operation.validated')
            row=db.execute('SELECT event FROM validated_events WHERE operation_id=?',(operation_id,)).fetchone()
            if not row:raise ContractError('sync_unvalidated','Operazione non validata per la pubblicazione')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operations'").fetchone():
                for (data,) in db.execute('SELECT record FROM operations'):
                    if parse_json(data).get('state') in ('applying','recovery_required'):
                        raise ContractError('recovery_required','Completare il recovery note prima di pubblicare')
        event=parse_json(row[0])
        if event.get('type')!='operation.validated' or event.get('publication_eligible') is not True:
            raise ContractError('sync_unvalidated','Evento non autorizzato alla pubblicazione')
        return event

    def publish(self,vault_id,body):
        _fields(body,('operation_id','idempotency_key','exclusive_confirmed','expected_head'),('raw_paths','share_confirmed'))
        identifier=_uuid(body['operation_id']);key=_key(body['idempotency_key']);_oid(body['expected_head'])
        if body['exclusive_confirmed'] is not True:raise ContractError('sync_exclusion','Sospendere client, hook ed editor esterni prima di pubblicare')
        raw_selection=body.get('raw_paths',[])
        if not isinstance(raw_selection,list) or len(raw_selection)>256 or any(not isinstance(p,str) or not p.startswith('raw/') for p in raw_selection):
            raise ContractError('sync_request','Selezione esplicita fonti non valida')
        for path in raw_selection:portable_path(path)
        if raw_selection and body.get('share_confirmed') is not True:raise ContractError('sync_consent','Revisionare e autorizzare le nuove fonti prima della pubblicazione')
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root) as lock:
            with self._db(root) as db:
                self._schema(db);config=self._config(db)
                digest=content_hash(body)
                old=db.execute('SELECT request_hash,data FROM jobs WHERE operation_id=? OR request_key=?',(identifier,key)).fetchone()
                if old:
                    if old[0]!=digest:raise ContractError('idempotency_conflict','Richiesta diversa dalla pubblicazione registrata')
                    # Transport retries read the durable result; explicit resolve resumes a pause.
                    return self._public(parse_json(old[1]))
                for (data,) in db.execute('SELECT data FROM jobs'):
                    if parse_json(data)['state'] not in ('converged','noop'):
                        raise ContractError('sync_pending','Un checkpoint precedente richiede risoluzione')
                repo=self._repo(root);self._identity(repo,config)
                if repo.head()!=body['expected_head'] or repo.head()!=config['B']:
                    raise ContractError('sync_baseline','HEAD non corrisponde al checkpoint condiviso di partenza')
                event=self._event(root,identifier)
                if event.get('vault_id')!=vault_id:raise ContractError('sync_vault','Evento appartenente ad altro vault')
                snapshot=capture_snapshot(root);manifest=event['manifest']
                selected_raw=set(config['raw_paths'])|set(raw_selection)
                if manifest.get('base_digest')!=config['base_digest']:
                    # New inputs can precede the isolated root snapshot, but no
                    # unrelated note/event can be smuggled into that baseline.
                    if not hasattr(repo,'tree'):raise ContractError('sync_baseline','Baseline del ciclo diverso da B')
                    baseline={p:hashlib.sha256(data).hexdigest() for p,data in repo.tree(config['B']).items()}
                    for p,h in manifest.get('inputs',{}).items():
                        if p.startswith('raw/') and p not in baseline and p in selected_raw:
                            baseline[p]=h
                    if content_hash(baseline)!=manifest.get('base_digest'):
                        raise ContractError('sync_baseline','Modifiche preesistenti non attribuite al ciclo: revisionare il baseline')
                required_checks=('synthesis','schema_links_aliases_sources','raw_immutable','scope','shared_events_valid')
                if not all(manifest.get('checks',{}).get(check) is True for check in required_checks):
                    raise ContractError('sync_unvalidated','Mancano verifiche deterministiche obbligatorie')
                if snapshot.digest!=manifest['candidate_digest']:raise ContractError('blocked_external_change','Note cambiate dopo la validazione')
                files={item['path']:item['after'] for item in manifest['files']}
                for p,h in files.items():
                    if snapshot.hashes.get(p)!=h:raise ContractError('blocked_external_change','Hash candidato non corrispondente',p)
                # Pre-existing selected raw is already in B. New input sources must be explicit and attributed.
                for p,h in manifest.get('inputs',{}).items():
                    if p.startswith('raw/'):
                        if p not in selected_raw:raise ContractError('sync_raw_selection','Fonte non selezionata nella configurazione o nella preview autorizzata',p)
                        files[p]=h
                record=dict(operation_id=identifier,idempotency_key=key,state='ready',B=config['B'],L=None,R=None,C=None,
                            attempts=0,error=None,config=config,files=files,expected_digest=snapshot.digest,
                            manifest_digest=manifest.get('manifest_digest'),checkpoint_id=event.get('checkpoint',{}).get('checkpoint_id'))
                with db:db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(identifier,key,digest,canonical_json(record)))
                return self._public(self._advance(root,repo,db,record,lock=lock))

    @staticmethod
    def _identity(repo,config):
        git=repo.inspect()
        if git['branch']!=config['branch'] or git['remote_url']!=config['remote_url']:
            raise ContractError('sync_identity_changed','Branch o destinazione remota cambiati: nessuna pubblicazione')
        if git.get('tracked_violations'):raise ContractError('sync_tracked_private','File tracked fuori policy')

    @staticmethod
    def _pending(db):
        return [j for j in (parse_json(row[0]) for row in db.execute('SELECT data FROM jobs')) if j['state'] not in ('converged','noop')]

    def enable_automatic(self,vault_id,body):
        """Consenso una tantum dell'autosync: pull e push partono dalle skill, non da questa chiamata."""
        _fields(body,('consent','expected_head'))
        if body['consent'] is not True:raise ContractError('sync_consent','Confermare esplicitamente l’autosync di questo vault')
        _oid(body['expected_head'])
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root):
            repo=self._repo(root)
            with self._db(root) as db:
                self._schema(db);config=self._config(db)
                if config['mode']!='direct':raise ContractError('sync_config','L’autosync richiede la modalità direct')
                if repo.head()!=body['expected_head'] or repo.head()!=config['B'] or not repo.clean():
                    raise ContractError('sync_baseline','Occorre il checkpoint condiviso con index e working tree puliti')
                if self._pending(db):raise ContractError('sync_pending','Conservare e risolvere il checkpoint pendente prima di attivare l’autosync')
                config.update(automatic=True,automatic_consent_at=date.today().isoformat())
                with db:db.execute('UPDATE config SET data=? WHERE id=1',(canonical_json(config),))
            return config

    def disable_automatic(self,vault_id):
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root):
            with self._db(root) as db:
                self._schema(db);config=self._config(db)
                config.update(automatic=False)
                with db:db.execute('UPDATE config SET data=? WHERE id=1',(canonical_json(config),))
            return config

    def sync_down(self,vault_id):
        """Pull dell'autosync: solo fast-forward del branch condiviso, mai un merge nel vault vivo."""
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root) as lock:
            from .storage import assert_receiver_complete
            assert_receiver_complete(root)
            with self._db(root) as db:
                self._schema(db);config=self._config(db)
                if config.get('automatic') is not True:raise ContractError('sync_automatic_off','Autosync non attivo per questo vault')
                if self._pending(db):return dict(state='pending',received=0)
                repo=self._repo(root);self._identity(repo,config)
                if not repo.clean():raise ContractError('autosync_unpublished','Modifiche non pubblicate: eseguire teseo_git.py post --skill manuale')
                head=repo.head()
                if head!=config['B']:raise ContractError('sync_baseline','HEAD non corrisponde al checkpoint condiviso')
                try:remote=repo.fetch(config['remote_url'],config['branch'])
                except ContractError as error:
                    if error.code in ('git_network','git_timeout','git_auth'):return dict(state='offline',received=0,error=error.as_dict())
                    raise
                if remote==head or repo.is_ancestor(remote,head):return dict(state='current',received=0,head=head)
                if not repo.is_ancestor(head,remote):return dict(state='diverged',received=0,head=head,remote=remote)
                received=int(repo.run('rev-list','--count',head+'..'+remote).strip())
                candidate=repo.integrate(head,remote)
                try:
                    self._assert_candidate(repo,candidate)
                    repo.adopt(head,candidate)
                finally:
                    # Best effort: un candidato rimasto sul disco (scanner, lock) non deve far fallire un pull riuscito.
                    try:repo.cleanup_candidate(candidate)
                    except (OSError,ContractError):pass
                result=dict(state='received',received=received,head=repo.head())
                # B avanza subito: l'adozione è avvenuta. Il digest è best effort (snapshot oltre il tetto o file in uso):
                # senza di esso HEAD resterebbe fuori dal checkpoint condiviso e ogni pull successivo si fermerebbe.
                config.update(B=repo.head())
                try:config.update(base_digest=capture_snapshot(root).digest)
                except (ContractError,OSError):result['warning']={'code':'sync_digest','message':'Digest di base da ricalcolare'}
                with db:db.execute('UPDATE config SET data=? WHERE id=1',(canonical_json(config),))
                try:self._refresh_projections(root,config['vault_id'],lock)
                except Exception as error:
                    result['warning']=error.as_dict() if isinstance(error,ContractError) else {'code':'sync_projection','message':'Grafo o proiezione da ricostruire dalla dashboard'}
                return result

    def publish_session(self,vault_id,*,operation_id,files,message,trailers):
        """Pubblica una sessione skill dell'autosync: stesso motore di publish, senza evento della dashboard."""
        identifier=_uuid(operation_id)
        if not isinstance(files,dict) or not files or len(files)>10000:raise ContractError('sync_request','Elenco file della sessione non valido')
        if not isinstance(message,str) or not message or len(message)>500 or any(ord(c)<32 for c in message):
            raise ContractError('sync_request','Messaggio commit non valido')
        from .git_sync import _trailers
        _trailers(trailers)
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root) as lock:
            with self._db(root) as db:
                self._schema(db);config=self._config(db)
                if config.get('automatic') is not True:raise ContractError('sync_automatic_off','Autosync non attivo per questo vault')
                digest=content_hash(dict(files=files,message=message,trailers=trailers))
                old=db.execute('SELECT request_hash,data FROM jobs WHERE operation_id=?',(identifier,)).fetchone()
                if old:
                    if old[0]!=digest:raise ContractError('idempotency_conflict','Richiesta diversa dalla sessione registrata')
                    return self._public(parse_json(old[1]))
                if self._pending(db):raise ContractError('sync_pending','Un checkpoint precedente richiede risoluzione')
                repo=self._repo(root);self._identity(repo,config)
                if repo.head()!=config['B']:raise ContractError('sync_baseline','HEAD non corrisponde al checkpoint condiviso di partenza')
                snapshot=capture_snapshot(root)
                record=dict(operation_id=identifier,idempotency_key='auto-'+identifier,state='ready',B=config['B'],L=None,R=None,C=None,
                            attempts=0,error=None,config=config,files=files,expected_digest=snapshot.digest,
                            manifest_digest=None,checkpoint_id=None,message=message,trailers=trailers)
                with db:db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(identifier,record['idempotency_key'],digest,canonical_json(record)))
                return self._public(self._advance(root,repo,db,record,lock=lock))

    def resume_session(self,vault_id,operation_id):
        """Riprende dopo rete o autenticazione assenti; i conflitti restano alla dashboard (resolve)."""
        identifier=_uuid(operation_id)
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root) as lock:
            with self._db(root) as db:
                self._schema(db)
                row=db.execute('SELECT data FROM jobs WHERE operation_id=?',(identifier,)).fetchone()
                if not row:raise ContractError('sync_missing','Nessuna sessione con questo identificativo')
                record=parse_json(row[0])
                if record['state'] in ('converged','noop'):return self._public(record)
                if record['state'] not in ('waiting_auth','waiting_network','retry_exhausted','published_pending_local_adoption'):
                    raise ContractError('sync_resolution','Sessione non riprendibile automaticamente: usare la dashboard')
                # La ripresa è una richiesta esplicita dell'utente: il tetto di tentativi serve a non ciclare da soli.
                if record['state'] in ('waiting_auth','waiting_network','retry_exhausted'):record['attempts']=0
                return self._public(self._advance(root,self._repo(root),db,record,lock=lock))

    def _advance(self,root,repo,db,record,human_decision_key=None,*,lock=None):
        config=record['config']
        def state(value):record.update(state=value,error=None);self._save(db,record)
        try:
            self._identity(repo,config)
            if record.get('published_oid'):
                return self._adopt(root,repo,db,record,lock=lock)
            if record.get('proposal_oid'):
                state('needs_approval');return record
            if not record['L']:
                if capture_snapshot(root).digest!=record['expected_digest']:
                    raise ContractError('blocked_external_change','Snapshot modificato prima del checkpoint')
                state('checkpointing')
                # A crashed commit is recovered only through a verified operation trailer/tree.
                if repo.head()!=record['B']:
                    finder=getattr(repo,'find_checkpoint',None)
                    found=finder(record['operation_id'],record['B'],record['files']) if finder else None
                    if not found:raise ContractError('sync_head_changed','HEAD mosso fuori dal publisher')
                    record['L']=found
                else:
                    record['L']=repo.checkpoint(record['operation_id'],record['B'],record['files'],
                                                **{k:record[k] for k in ('message','trailers') if record.get(k)})
                self._save(db,record)
                if record['L']==record['B']:
                    state('noop');return record
            # Verify an uncertain acknowledgement even after the last allowed
            # attempt, and before testing whether an editor now blocks adoption.
            if record.get('push_intent_oid'):
                destination=record.get('proposal_branch') if config['mode']=='pr' else config['branch']
                try:
                    observed=repo.fetch(config['remote_url'],destination)
                except ContractError as error:
                    if config['mode']!='pr' or error.code!='git_failed':raise
                else:
                    if repo.is_ancestor(record['push_intent_oid'],observed):
                        if config['mode']=='pr':
                            record['proposal_oid']=record['push_intent_oid'];state('needs_approval');return record
                        record['published_oid']=record['push_intent_oid'];state('published')
                        return self._adopt(root,repo,db,record,lock=lock)
            if repo.head()!=record['L'] or not repo.clean():
                raise ContractError('blocked_external_change','Checkpoint conservato; working tree, index o HEAD cambiati')
            while record['attempts']<3:
                state('fetching');remote=repo.fetch(config['remote_url'],config['branch']);record['R']=remote;self._save(db,record)
                # A lost push acknowledgement is verified before building or sending another candidate.
                if record.get('push_intent_oid')==record.get('C') and record.get('C') and repo.is_ancestor(record['C'],remote) and config['mode']=='direct':
                    record['published_oid']=record['C'];state('published');return self._adopt(root,repo,db,record,lock=lock)
                if not repo.is_ancestor(record['B'],remote):
                    raise ContractError('sync_unrelated','Remote non discende dal checkpoint condiviso B')
                state('integrating')
                if record.get('resolution_digest'):
                    if remote!=record['resolution_remote']:
                        raise ContractError('sync_resolution_stale','Remote avanzato: revisionare il candidato sui nuovi input')
                    candidate=record.get('resolved_candidate')
                    if not candidate:
                        candidate=repo.resolve_candidate(record['resolution_path'],record['L'],remote,record['resolution_digest'])
                        record['resolved_candidate']=candidate;self._save(db,record)
                else:
                    candidate=repo.integrate(record['L'],remote)
                if hasattr(repo,'run'):
                    repo.run('update-ref','refs/teseo/candidates/'+record['operation_id']+'/'+candidate['oid'],candidate['oid'])
                self._assert_candidate(repo,candidate)
                record.update(C=candidate['oid'],candidate_path=str(candidate['root']));self._save(db,record)
                state('validating')
                validator=self.validator
                if validator is None:
                    from .sync_validation import validate_integration
                    validator=validate_integration
                base=repo.snapshot(record['B']);local=repo.snapshot(record['L']);other=repo.snapshot(remote)
                def attest(request):
                    return {'resolved':True,'human_decision':True,'input_key':human_decision_key,'scope':request['scope'],'candidate_digest':request['candidate_digest']}
                checked=validator(base['root'],local['root'],other['root'],candidate['root'],reconcile=attest if human_decision_key else None)
                self._assert_candidate(repo,candidate)
                record['validation']=checked;self._save(db,record)
                if checked['state']!='validated':
                    state('needs_decision');return record
                if repo.head()!=record['L'] or not repo.clean() or capture_snapshot(root).digest!=record['expected_digest']:
                    raise ContractError('blocked_external_change','Modifiche estranee rilevate prima del push')
                self._assert_candidate(repo,{'oid':record['L'],'root':str(root)})
                record['attempts']+=1
                destination=config['branch']
                if config['mode']=='pr':
                    destination='codex/teseo-'+record['operation_id'];record['proposal_branch']=destination
                    from .git_sync import github_repository_url
                    url=github_repository_url(config['remote_url'])
                    if url:record['proposal_compare_url']=url+'/compare/'+config['branch']+'...'+destination
                record['push_intent_oid']=record['C']
                state('pushing')
                try:repo.push(record['C'],config['remote_url'],destination,published=remote)
                except ContractError as error:
                    if error.code in ('git_push_rejected','git_non_fast_forward'):
                        latest=repo.fetch(config['remote_url'],config['branch'])
                        if latest!=remote:continue
                    raise
                if config['mode']=='pr':
                    record['proposal_oid']=record['C'];state('needs_approval');return record
                record['published_oid']=record['C'];state('published')
                return self._adopt(root,repo,db,record,lock=lock)
            state('retry_exhausted');return record
        except ContractError as error:
            code=error.code
            paused='waiting_auth' if code in ('git_auth','git_authentication') else 'waiting_network' if code in ('git_network','git_timeout') else 'needs_approval' if code in ('git_push_rejected','git_policy') else 'needs_resolution'
            record.update(state=paused,error=error.as_dict());self._save(db,record);return record

    @staticmethod
    def _assert_candidate(repo,candidate):
        if hasattr(repo,'tree'):
            from .git_sync import is_local_only
            expected={p:hashlib.sha256(data).hexdigest() for p,data in repo.tree(candidate['oid']).items()}
            # Le fonti binarie locali stanno sul disco del vault ma mai nell'OID: non sono byte "da pubblicare".
            actual={p:h for p,h in capture_snapshot(candidate['root']).hashes.items() if p in expected or not is_local_only(p)}
            if actual!=expected:
                raise ContractError('sync_candidate_changed','I byte del candidato non corrispondono all’OID da pubblicare')

    def _refresh_projections(self,root,vault_id,lock):
        """Dopo un'adozione locale: grafo e proiezione condivisa tornano coerenti con le note appena ricevute."""
        if self.validator is not None:return
        from .graph_service import rebuild
        from .shared_state import rebuild_projection,snapshot_events
        rebuild(root,lock=lock)
        projection=root/'.teseo/local/shared-state.sqlite'
        for suffix in ('','-journal','-wal','-shm'): _no_link(Path(str(projection)+suffix))
        rebuild_projection(projection,snapshot_events(capture_snapshot(root),vault_id),vault_id)

    def _adopt(self,root,repo,db,record,*,lock=None):
        try:
            self._identity(repo,record['config'])
            if repo.head()!=record['L'] or not repo.clean():
                # Fast-forward interrotto: completabile solo se ogni file sporco è L o C, mai con modifiche esterne.
                resumed=(record['state'] in ('adopting','published_pending_local_adoption') and repo.head()==record['L']
                         and hasattr(repo,'resume_adoption') and repo.resume_adoption(record['L'],{'oid':record['C']}))
                if not resumed and (repo.head()!=record['C'] or not repo.clean()):
                    raise ContractError('blocked_external_change','Pubblicato; adozione locale sospesa per modifiche esterne')
            else:
                record['state']='adopting';self._save(db,record)
                repo.adopt(record['L'],{'oid':record['C'],'root':record.get('candidate_path')})
            if repo.head()!=record['C'] or not repo.clean():raise ContractError('sync_adoption','Verificare HEAD e index dopo adozione')
            self._assert_candidate(repo,{'oid':record['C'],'root':str(root)})
            self._refresh_projections(root,record['config']['vault_id'],lock)
            config=self._config(db);config.update(B=record['C'],base_digest=capture_snapshot(root).digest)
            with db:db.execute('UPDATE config SET data=? WHERE id=1',(canonical_json(config),))
            record.update(state='converged',error=None);self._save(db,record)
        except Exception as error:
            record.update(state='published_pending_local_adoption',error=error.as_dict() if isinstance(error,ContractError) else {'code':'sync_adoption','message':'Pubblicazione conservata; verificare file e generazioni locali'})
            self._save(db,record)
        return record

    def resolve(self,vault_id,body):
        _fields(body,('idempotency_key','exclusive_confirmed'),('human_decision_key','resolution_digest'))
        key=_key(body['idempotency_key'])
        if body['exclusive_confirmed'] is not True:raise ContractError('sync_exclusion','Confermare la sospensione degli scrittori esterni')
        decision=body.get('human_decision_key')
        if decision is not None and (not isinstance(decision,str) or len(decision)>128):raise ContractError('sync_request','Chiave di revisione non valida')
        root=self.registry.root(vault_id)
        with self._mutex,VaultLock(root) as lock:
            with self._db(root) as db:
                self._schema(db);row=db.execute('SELECT data FROM jobs WHERE request_key=?',(key,)).fetchone()
                if not row:raise ContractError('sync_missing','Nessun checkpoint con questa chiave')
                record=parse_json(row[0])
                if record['state'] in ('converged','noop'):return self._public(record)
                if decision and decision!=(record.get('validation') or {}).get('key'):
                    raise ContractError('sync_decision_stale','La revisione non corrisponde agli input correnti')
                resolution=body.get('resolution_digest')
                if resolution is not None:
                    if not isinstance(resolution,str) or not re.fullmatch('[a-f0-9]{64}',resolution):
                        raise ContractError('sync_request','Digest della risoluzione non valido')
                    if not record.get('resolution_path'):
                        error=record.get('error') or {}
                        if error.get('code')!='git_conflict' or not error.get('path'):
                            raise ContractError('sync_resolution','Nessun candidato in conflitto da revisionare')
                        record.update(resolution_path=error['path'],resolution_remote=record['R'])
                    if record.get('resolution_digest')!=resolution:record.pop('resolved_candidate',None)
                    record['resolution_digest']=resolution;self._save(db,record)
                return self._public(self._advance(root,self._repo(root),db,record,decision,lock=lock))
