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
    def checkpoint(self,operation_id,expected_head,files,message=''):
        if self.oid!=expected_head: raise ContractError('git_head_changed','Changed')
        self.commits+=1;self.oid='b'*40;self.dirty=False;return self.oid
    def fetch(self,remote,branch): return self.remote
    def is_ancestor(self,a,b): return a==b or a=='a'*40
    def merge_base(self,a,b): return 'a'*40
    def snapshot(self,oid): return {'oid':oid,'root':str(self.root)}
    def integrate(self,local,remote): return {'oid':local,'root':str(self.root)}
    def push(self,oid,remote,branch):
        self.pushes+=1
        if self.fail: raise ContractError(self.fail,'fixture')
        self.remote=oid
        if self.after_push:self.after_push()
    def adopt(self,local,candidate):
        if self.dirty:raise ContractError('git_dirty','Editor changed')
        self.oid=candidate['oid']


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
