"""Publisher: consenso, attribuzione, crash e ripresa senza duplicazione."""
import _shortpath  # noqa: F401
import hashlib
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from kit.dashboard.contracts import ContractError, canonical_json
from kit.dashboard.shared_migration import _connection
from kit.dashboard.storage import capture_snapshot
from kit.dashboard.sync_service import SyncService


class Repository:
    def __init__(self,root):
        self.root=root;self.oid='a'*40;self.remote='a'*40;self.dirty=False
        self.commits=0;self.pushes=0;self.fail=None;self.after_push=None
    def head(self): return self.oid
    def branch(self): return 'team'
    def clean(self): return not self.dirty
    def inspect(self): return dict(head=self.oid,branch='team',remote_url='https://github.com/example/data.git',tracked_violations=[],author={'name':'Test','email':'test@example.invalid'})
    def preview(self,selection=None): return {'files':[],'excluded':[],'tracked_violations':[]}
    def checkpoint(self,operation_id,expected_head,files,message='',trailers=None):
        if self.oid!=expected_head: raise ContractError('git_head_changed','Changed')
        self.commits+=1;self.last_trailers=trailers;self.oid='b'*40;self.dirty=False;return self.oid
    def fetch(self,remote,branch): return self.remote
    def is_ancestor(self,a,b): return a==b or a=='a'*40
    def merge_base(self,a,b): return 'a'*40
    def snapshot(self,oid): return {'oid':oid,'root':str(self.root)}
    def integrate(self,local,remote): return {'oid':local,'root':str(self.root)}
    def push(self,oid,remote,branch,published=None):
        self.pushes+=1;self.last_published=published
        if self.fail: raise ContractError(self.fail,'fixture')
        self.remote=oid
        if self.after_push:self.after_push()
    def adopt(self,local,candidate):
        if self.dirty:raise ContractError('git_dirty','Editor changed')
        self.oid=candidate['oid']
    def run(self,*args): return '2\n'
    def cleanup_candidate(self,candidate): self.cleaned=True


class Service(unittest.TestCase):
    def test_status_remains_readable_with_missing_schema_during_receive(self):
        service=self.service
        def unavailable(_vault):
            raise ContractError('schema_missing','Schema temporarily absent')
        service.registry=type('Registry',(),{'root':staticmethod(unavailable),'operation_root':lambda _,v:self.root})()
        self.assertFalse(service.status(self.vault)['configured'])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.vault=str(uuid4());(self.root/'wiki').mkdir();(self.root/'.teseo').mkdir()
        (self.root/'Wiki reference.md').write_text('Schema',encoding='utf-8')
        (self.root/'wiki/Anna.md').write_text('Prima',encoding='utf-8')
        (self.root/'.teseo/project.json').write_bytes(canonical_json(dict(format_version=1,schema_version=1,event_version=1,vault_id=self.vault,minimum_kit_version='1.0.0',shared_paths=['wiki/','raw/','Wiki reference.md','index.md','log.md','.teseo/shared/'])))
        self.repo=Repository(self.root)
        registry=type('Registry',(),{'root':lambda _,v:self.root})()
        self.service=SyncService(registry,repository_factory=lambda root:self.repo,validator=lambda *a,**k:{'state':'validated','key':'k','scope':[]})
        self.config=dict(remote='origin',branch='team',visibility='private',mode='direct',raw_paths=[],share_confirmed=True,expected_head=self.repo.oid)
    def operation(self):
        self.service.configure(self.vault,self.config)
        before=capture_snapshot(self.root).digest
        (self.root/'wiki/Anna.md').write_text('Dopo',encoding='utf-8');self.repo.dirty=True
        operation=str(uuid4());snap=capture_snapshot(self.root)
        event=dict(type='operation.validated',operation_id=operation,vault_id=self.vault,publication_eligible=True,
                   manifest={'base_digest':before,'candidate_digest':snap.digest,'files':[{'path':'wiki/Anna.md','before':hashlib.sha256(b'Prima').hexdigest(),'after':snap.hashes['wiki/Anna.md']}],'inputs':{},'checks':{k:True for k in ('synthesis','schema_links_aliases_sources','raw_immutable','scope','shared_events_valid')}},checkpoint={'mode':'manual_paused'})
        with _connection(self.root/'.teseo/local/operations.sqlite') as db:
            db.execute('CREATE TABLE validated_events(operation_id TEXT PRIMARY KEY,event BLOB NOT NULL)')
            db.execute('INSERT INTO validated_events VALUES (?,?)',(operation,canonical_json(event)))
        return dict(operation_id=operation,idempotency_key='publish-first-001',exclusive_confirmed=True,expected_head='a'*40)
    def test_status_readonly_and_config_consent(self):
        self.assertFalse(self.service.status(self.vault)['configured'])
        self.assertFalse((self.root/'.teseo/local').exists())
        with self.assertRaises(ContractError):self.service.configure(self.vault,dict(self.config,share_confirmed=False))
        self.assertFalse((self.root/'.teseo/local/sync.sqlite').exists())
    def test_publish_consumes_validated_event_once(self):
        body=self.operation();result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'converged')
        self.assertEqual(self.service.publish(self.vault,body),result)
        self.assertEqual(self.repo.commits,1);self.assertEqual(self.repo.pushes,1)
    def test_network_failure_keeps_checkpoint_and_resumes(self):
        body=self.operation();self.repo.fail='git_network'
        result=self.service.publish(self.vault,body);self.assertEqual(result['state'],'waiting_network');self.assertEqual(result['L'],'b'*40)
        self.repo.fail=None
        result=self.service.resolve(self.vault,{'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True})
        self.assertEqual(result['state'],'converged');self.assertEqual(self.repo.commits,1)
    def test_editor_after_push_blocks_adoption_and_preserves_published_oid(self):
        body=self.operation();self.repo.after_push=lambda:setattr(self.repo,'dirty',True)
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'published_pending_local_adoption')
        self.assertEqual(result['published_oid'],'b'*40)
        self.assertEqual(self.repo.pushes,1)
    def test_unvalidated_or_external_changes_cannot_checkpoint(self):
        body=self.operation();(self.root/'wiki/Anna.md').write_text('Estraneo',encoding='utf-8')
        with self.assertRaises(ContractError):self.service.publish(self.vault,body)
        self.assertEqual(self.repo.commits,0)
    def test_pr_policy_does_not_publish_to_shared_branch(self):
        self.config['mode']='pr';body=self.operation();result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'needs_approval');self.assertTrue(result['proposal_branch'].startswith('codex/teseo-'))
        self.assertNotIn('published_oid',result)

    def test_last_attempt_lost_ack_is_verified_before_budget_and_dirty_adoption(self):
        body=self.operation();self.repo.fail='git_timeout'
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'waiting_network')
        self.repo.remote=result['C'];self.repo.dirty=True
        from kit.dashboard.contracts import parse_json
        with _connection(self.root/'.teseo/local/sync.sqlite') as db:
            record=parse_json(db.execute('SELECT data FROM jobs').fetchone()[0]);record['attempts']=3;record['state']='retry_exhausted'
            db.execute('UPDATE jobs SET data=?',(canonical_json(record),))
        result=self.service.resolve(self.vault,{'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True})
        self.assertEqual(result['state'],'published_pending_local_adoption')
        self.assertEqual(result['published_oid'],result['C']);self.assertEqual(self.repo.pushes,1)

    def test_candidate_bytes_must_match_oid_before_validation(self):
        body=self.operation()
        frozen={item.path:item.data for item in capture_snapshot(self.root).files}
        frozen['wiki/Anna.md']=b'Contenuto differente nell OID'
        self.repo.tree=lambda oid:frozen
        called=[]
        self.service.validator=lambda *args,**kwargs:called.append(True) or {'state':'validated'}
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'needs_resolution')
        self.assertEqual(result['error']['code'],'sync_candidate_changed')
        self.assertFalse(called);self.assertEqual(self.repo.pushes,0)

    def test_candidate_oid_is_checked_again_after_validator(self):
        body=self.operation()
        frozen={item.path:item.data for item in capture_snapshot(self.root).files}
        self.repo.tree=lambda oid:frozen
        def changed(*args,**kwargs):
            (self.root/'wiki/Anna.md').write_bytes(b'Byte mutati durante verifica')
            return {'state':'validated','key':'k','scope':[]}
        self.service.validator=changed
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'needs_resolution')
        self.assertEqual(result['error']['code'],'sync_candidate_changed')
        self.assertEqual(self.repo.pushes,0)

    def test_pr_lost_ack_queries_proposal_before_any_repeat_push(self):
        self.config['mode']='pr';body=self.operation();fetched=[]
        def fetch(remote,branch):
            fetched.append(branch)
            return self.repo.remote if branch.startswith('codex/teseo-') else 'a'*40
        self.repo.fetch=fetch
        def lost_ack():
            raise ContractError('git_timeout','Remote accepted, acknowledgement lost')
        self.repo.after_push=lost_ack
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'waiting_network')
        self.repo.after_push=None
        result=self.service.resolve(self.vault,{'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True})
        self.assertEqual(result['state'],'needs_approval')
        self.assertEqual(result['proposal_oid'],result['C'])
        self.assertNotIn('published_oid',result)
        self.assertEqual(fetched[-1],result['proposal_branch'])
        self.assertEqual(self.repo.pushes,1)

    def test_pending_adoption_retry_does_not_repeat_push(self):
        body=self.operation();self.repo.after_push=lambda:setattr(self.repo,'dirty',True)
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'published_pending_local_adoption')
        self.repo.dirty=False;self.repo.after_push=None
        result=self.service.resolve(self.vault,{'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True})
        self.assertEqual(result['state'],'converged');self.assertEqual(self.repo.pushes,1)

    def test_crash_after_commit_before_journal_recovers_exact_checkpoint(self):
        body=self.operation();checkpoint=self.repo.checkpoint
        def interrupted(*args,**kwargs):
            checkpoint(*args,**kwargs)
            raise OSError('process interrupted after commit')
        self.repo.checkpoint=interrupted
        with self.assertRaises(OSError):self.service.publish(self.vault,body)
        self.repo.find_checkpoint=lambda operation,base,files:self.repo.oid if operation==body['operation_id'] else None
        result=self.service.resolve(self.vault,{'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True})
        self.assertEqual(result['state'],'converged');self.assertEqual(self.repo.commits,1)

    def test_missing_deterministic_gate_cannot_create_checkpoint(self):
        body=self.operation()
        from kit.dashboard.contracts import parse_json
        with _connection(self.root/'.teseo/local/operations.sqlite') as db:
            event=parse_json(db.execute('SELECT event FROM validated_events').fetchone()[0])
            event['manifest']['checks']['synthesis']=False
            db.execute('UPDATE validated_events SET event=?',(canonical_json(event),))
        with self.assertRaises(ContractError):self.service.publish(self.vault,body)
        self.assertEqual(self.repo.commits,0)


class Autosync(unittest.TestCase):
    """Sessioni skill: consenso una tantum, pull fast-forward e push senza evento della dashboard."""
    setUp = Service.setUp  # stessa fixture, senza rieseguire i test del publisher esplicito

    def auto(self):
        self.service.configure(self.vault,self.config)
        return self.service.enable_automatic(self.vault,dict(consent=True,expected_head='a'*40))
    def edit(self):
        (self.root/'wiki/Anna.md').write_text('Sessione',encoding='utf-8');self.repo.dirty=True
        return {'wiki/Anna.md':capture_snapshot(self.root).hashes['wiki/Anna.md']}
    def session(self,files,**extra):
        return self.service.publish_session(self.vault,**dict(operation_id=str(uuid4()),files=files,message='Teseo: ingest (claude)',
                                                              trailers={'Teseo-Agent':'claude','Teseo-Skill':'ingest'},**extra))

    def test_consent_is_explicit_direct_only_and_reported(self):
        self.service.configure(self.vault,self.config)
        self.assertFalse(self.service.status(self.vault)['automatic'])
        with self.assertRaises(ContractError):self.service.enable_automatic(self.vault,dict(consent=False,expected_head='a'*40))
        config=self.service.enable_automatic(self.vault,dict(consent=True,expected_head='a'*40))
        self.assertTrue(config['automatic']);self.assertNotIn('raw_policy',config);self.assertTrue(config['automatic_consent_at'])
        self.assertTrue(self.service.status(self.vault)['automatic'])
        self.assertFalse(self.service.disable_automatic(self.vault)['automatic'])
        self.assertFalse(self.service.status(self.vault)['automatic'])

    def test_pr_mode_cannot_enable_automatic(self):
        self.config['mode']='pr';self.service.configure(self.vault,self.config)
        with self.assertRaises(ContractError) as raised:self.service.enable_automatic(self.vault,dict(consent=True,expected_head='a'*40))
        self.assertEqual(raised.exception.code,'sync_config')

    def test_session_is_refused_without_consent(self):
        self.service.configure(self.vault,self.config);files=self.edit()
        with self.assertRaises(ContractError) as raised:self.session(files)
        self.assertEqual(raised.exception.code,'sync_automatic_off');self.assertEqual(self.repo.commits,0)

    def test_session_publishes_with_trailers_incremental_audit_and_is_idempotent(self):
        self.auto();files=self.edit();operation=str(uuid4())
        body=dict(operation_id=operation,files=files,message='Teseo: ingest (claude)',trailers={'Teseo-Agent':'claude','Teseo-Skill':'ingest'})
        result=self.service.publish_session(self.vault,**body)
        self.assertEqual(result['state'],'converged')
        self.assertEqual(self.repo.last_trailers,body['trailers']);self.assertEqual(self.repo.last_published,'a'*40)
        self.assertEqual(self.service.publish_session(self.vault,**body),result)
        self.assertEqual((self.repo.commits,self.repo.pushes),(1,1))
        self.assertEqual(self.service.status(self.vault)['config']['B'],'b'*40)
        with self.assertRaises(ContractError) as raised:self.service.publish_session(self.vault,**dict(body,message='altro'))
        self.assertEqual(raised.exception.code,'idempotency_conflict')

    def test_invalid_trailers_or_message_are_rejected_before_any_record(self):
        self.auto();files=self.edit()
        for bad in (dict(trailers={'Co-Authored-By':'x'},message='m'),dict(trailers={'Teseo-Agent':'Claude'},message='m'),
                    dict(trailers={'Teseo-Agent':'claude'},message='a\nb')):
            with self.assertRaises(ContractError):self.service.publish_session(self.vault,operation_id=str(uuid4()),files=files,**bad)
        self.assertEqual(self.repo.commits,0);self.assertEqual(self.service.status(self.vault)['operations'],[])

    def test_waiting_session_blocks_the_next_one_until_resumed(self):
        self.auto();files=self.edit();self.repo.fail='git_network'
        first=self.session(files);self.assertEqual(first['state'],'waiting_network')
        with self.assertRaises(ContractError) as raised:self.session(files)
        self.assertEqual(raised.exception.code,'sync_pending')
        self.repo.fail=None
        resumed=self.service.resume_session(self.vault,first['operation_id'])
        self.assertEqual(resumed['state'],'converged');self.assertEqual(self.repo.commits,1)
        self.assertEqual(self.service.resume_session(self.vault,first['operation_id'])['state'],'converged')

    def test_blocked_session_is_not_resumable_without_the_dashboard(self):
        self.auto();files=self.edit();self.repo.fail='git_policy'
        blocked=self.session(files);self.assertEqual(blocked['state'],'needs_approval')
        with self.assertRaises(ContractError) as raised:self.service.resume_session(self.vault,blocked['operation_id'])
        self.assertEqual(raised.exception.code,'sync_resolution')

    def test_sync_down_requires_consent(self):
        self.service.configure(self.vault,self.config)
        with self.assertRaises(ContractError) as raised:self.service.sync_down(self.vault)
        self.assertEqual(raised.exception.code,'sync_automatic_off')

    def test_sync_down_current_offline_diverged_and_dirty(self):
        self.auto()
        self.assertEqual(self.service.sync_down(self.vault)['state'],'current')
        def unreachable(remote,branch):raise ContractError('git_network','fixture')
        original=self.repo.fetch;self.repo.fetch=unreachable
        self.assertEqual(self.service.sync_down(self.vault)['state'],'offline')
        self.repo.fetch=original;self.repo.remote='c'*40;self.repo.is_ancestor=lambda a,b:a==b
        self.assertEqual(self.service.sync_down(self.vault)['state'],'diverged')
        self.repo.dirty=True
        with self.assertRaises(ContractError) as raised:self.service.sync_down(self.vault)
        self.assertEqual(raised.exception.code,'autosync_unpublished')

    def test_sync_down_fast_forwards_and_moves_the_shared_baseline(self):
        self.auto();self.repo.remote='c'*40
        self.repo.integrate=lambda local,remote:{'oid':remote,'root':str(self.root)}
        result=self.service.sync_down(self.vault)
        self.assertEqual((result['state'],result['received'],result['head']),('received',2,'c'*40))
        self.assertEqual(self.repo.oid,'c'*40);self.assertTrue(self.repo.cleaned)
        self.assertEqual(self.service.status(self.vault)['config']['B'],'c'*40)
        self.assertEqual(self.service.sync_down(self.vault)['state'],'current')

    def test_exhausted_retries_are_resumable_by_an_explicit_request(self):
        from kit.dashboard.contracts import parse_json
        self.auto();files=self.edit();self.repo.fail='git_network'
        first=self.session(files);self.assertEqual(first['state'],'waiting_network')
        with _connection(self.root/'.teseo/local/sync.sqlite') as db:
            record=parse_json(db.execute('SELECT data FROM jobs').fetchone()[0]);record.update(attempts=3,state='retry_exhausted')
            db.execute('UPDATE jobs SET data=?',(canonical_json(record),))
        self.repo.fail=None
        resumed=self.service.resume_session(self.vault,first['operation_id'])
        self.assertEqual(resumed['state'],'converged');self.assertEqual(self.repo.commits,1)

    def test_sync_down_moves_the_baseline_even_when_the_digest_cannot_be_computed(self):
        self.auto();self.repo.remote='c'*40
        self.repo.integrate=lambda local,remote:{'oid':remote,'root':str(self.root)}
        import kit.dashboard.sync_service as module
        real=module.capture_snapshot;calls=[]
        def failing(root,*args,**kwargs):
            calls.append(root)
            if self.repo.oid=='c'*40:raise ContractError('snapshot_too_large','fixture')
            return real(root,*args,**kwargs)
        module.capture_snapshot=failing;self.addCleanup(setattr,module,'capture_snapshot',real)
        result=self.service.sync_down(self.vault)
        self.assertEqual(result['state'],'received');self.assertEqual(result['warning']['code'],'sync_digest')
        self.assertEqual(self.service.status(self.vault)['config']['B'],'c'*40)
        self.assertEqual(self.service.sync_down(self.vault)['state'],'current')

    def test_sync_down_leaves_a_pending_session_alone(self):
        self.auto();files=self.edit();self.repo.fail='git_network'
        self.session(files);self.repo.dirty=False
        self.assertEqual(self.service.sync_down(self.vault),dict(state='pending',received=0))
