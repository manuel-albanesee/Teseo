"""Due clone e remoto bare: pubblicazione reale senza rete né dati personali."""
import _shortpath  # noqa: F401
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from kit.dashboard.contracts import canonical_json,DEFAULT_SHARED_PATHS
from kit.dashboard.git_sync import GitRepository
from kit.dashboard.shared_migration import _connection
from kit.dashboard.storage import capture_snapshot
from kit.dashboard.sync_service import SyncService


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='teseo-publisher-',dir=Path.cwd());self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.root=self.home/'one';self.root.mkdir();self.remote=self.home/'remote.git';self.peer=self.home/'two'
        self.git('init','--bare',str(self.remote));self.git('init','-b','team',cwd=self.root)
        self.author(self.root);self.vault=str(uuid4());(self.root/'wiki').mkdir();(self.root/'.teseo').mkdir()
        (self.root/'.teseo/project.json').write_bytes(canonical_json(dict(format_version=1,schema_version=1,event_version=1,vault_id=self.vault,minimum_kit_version='1.0.0',shared_paths=list(DEFAULT_SHARED_PATHS))))
        (self.root/'Wiki reference.md').write_text('# Schema\n',encoding='utf-8')
        for name in ('Anna','Bruno'):self.page(self.root,name,'Originale')
        self.git('add','--','.teseo/project.json','Wiki reference.md','wiki/Anna.md','wiki/Bruno.md',cwd=self.root)
        self.git('commit','-m','base',cwd=self.root);self.git('remote','add','origin',str(self.remote),cwd=self.root)
        self.git('push','-u','origin','team',cwd=self.root);self.git('clone','--branch','team',str(self.remote),str(self.peer));self.author(self.peer)
        registry=type('Registry',(),{'root':lambda _,v:self.root})()
        self.service=SyncService(registry,repository_factory=lambda r:GitRepository(r,allow_local_remote=True))
        self.base=GitRepository(self.root,allow_local_remote=True).head()
        self.service.configure(self.vault,dict(remote='origin',branch='team',visibility='private',mode='direct',raw_paths=[],share_confirmed=True,expected_head=self.base))
        self.before=capture_snapshot(self.root)
    def git(self,*args,cwd=None):
        result=subprocess.run(['git','-c','core.autocrlf=false',*args],cwd=cwd or self.home,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        return result.stdout.decode('utf-8').strip()
    def author(self,path):
        self.git('config','user.name','Fixture',cwd=path);self.git('config','user.email','fixture@example.invalid',cwd=path)
    def page(self,root,name,text):
        (root/f'wiki/{name}.md').write_text('---\ntipo: persona\n---\n'+text+'\n',encoding='utf-8')
    def validated(self):
        current=capture_snapshot(self.root);identifier=str(uuid4())
        files=[{'path':p,'before':self.before.hashes.get(p),'after':h} for p,h in current.hashes.items() if h!=self.before.hashes.get(p)]
        event=dict(type='operation.validated',operation_id=identifier,vault_id=self.vault,publication_eligible=True,
                   manifest=dict(base_digest=self.before.digest,candidate_digest=current.digest,files=files,inputs={},checks={k:True for k in ('synthesis','schema_links_aliases_sources','raw_immutable','scope','shared_events_valid')}),checkpoint={'checkpoint_id':str(uuid4())})
        with _connection(self.root/'.teseo/local/operations.sqlite') as db:
            db.execute('CREATE TABLE operations(operation_id TEXT PRIMARY KEY,record BLOB NOT NULL)')
            db.execute('CREATE TABLE validated_events(operation_id TEXT PRIMARY KEY,event BLOB NOT NULL)')
            db.execute('INSERT INTO operations VALUES (?,?)',(identifier,canonical_json({'state':'succeeded','kind':'lint'})))
            db.execute('INSERT INTO validated_events VALUES (?,?)',(identifier,canonical_json(event)))
        return dict(operation_id=identifier,idempotency_key='real-publish-'+identifier,exclusive_confirmed=True,expected_head=self.base)
    def peer_commit(self,name,text):
        self.page(self.peer,name,text);self.git('add','--','wiki/'+name+'.md',cwd=self.peer);self.git('commit','-m','peer',cwd=self.peer);self.git('push','origin','team',cwd=self.peer)
    def test_disjoint_integration_push_and_local_convergence(self):
        self.page(self.root,'Anna','Locale');body=self.validated();self.peer_commit('Bruno','Remoto')
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'converged',result)
        self.assertEqual(self.git('rev-parse','HEAD',cwd=self.root),result['published_oid'])
        self.assertEqual(self.git('rev-parse','refs/heads/team',cwd=self.remote),result['C'])
        self.assertIn('Locale',(self.root/'wiki/Anna.md').read_text());self.assertIn('Remoto',(self.root/'wiki/Bruno.md').read_text())
        self.assertEqual(self.service.publish(self.vault,body),result)
    def test_correlated_clean_merge_requires_bound_human_decision(self):
        self.page(self.root,'Anna','Locale [[Bruno]]');body=self.validated();self.peer_commit('Bruno','Remoto')
        result=self.service.publish(self.vault,body);self.assertEqual(result['state'],'needs_decision',result)
        remote_before=self.git('rev-parse','refs/heads/team',cwd=self.remote)
        self.assertNotEqual(remote_before,result['C'])
        result=self.service.resolve(self.vault,{'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True,'human_decision_key':result['validation']['key']})
        self.assertEqual(result['state'],'converged',result)
    def test_conflict_preserves_live_checkpoint_without_remote_push(self):
        self.page(self.root,'Anna','Locale');body=self.validated();self.peer_commit('Anna','Remoto')
        remote_before=self.git('rev-parse','refs/heads/team',cwd=self.remote)
        result=self.service.publish(self.vault,body);self.assertEqual(result['state'],'needs_resolution',result)
        self.assertEqual(result['error']['code'],'git_conflict');self.assertEqual(self.git('rev-parse','refs/heads/team',cwd=self.remote),remote_before)
        self.assertIn('Locale',(self.root/'wiki/Anna.md').read_text())

    def test_reviewed_isolated_conflict_resolution_is_validated_then_published(self):
        self.page(self.root,'Anna','Locale');body=self.validated();self.peer_commit('Anna','Remoto')
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'needs_resolution',result)
        candidate=Path(result['error']['path']);self.page(candidate,'Anna','Risoluzione revisionata')
        digest=capture_snapshot(candidate).digest
        resume={'idempotency_key':body['idempotency_key'],'exclusive_confirmed':True,'resolution_digest':digest}
        result=self.service.resolve(self.vault,resume)
        self.assertEqual(result['state'],'needs_decision',result)
        resume['human_decision_key']=result['validation']['key']
        result=self.service.resolve(self.vault,resume)
        self.assertEqual(result['state'],'converged',result)
        self.assertIn('Risoluzione revisionata',(self.root/'wiki/Anna.md').read_text())

    def test_new_input_raw_requires_explicit_preview_selection_and_is_attributed(self):
        (self.root/'raw').mkdir();(self.root/'raw/nuova.md').write_text('Fonte da condividere',encoding='utf-8')
        self.before=capture_snapshot(self.root)
        self.page(self.root,'Anna','Nuovo fatto');body=self.validated()
        from kit.dashboard.contracts import parse_json
        with _connection(self.root/'.teseo/local/operations.sqlite') as db:
            event=parse_json(db.execute('SELECT event FROM validated_events').fetchone()[0])
            event['manifest']['inputs']={'raw/nuova.md':self.before.hashes['raw/nuova.md']}
            db.execute('UPDATE validated_events SET event=?',(canonical_json(event),))
        body.update(raw_paths=['raw/nuova.md'],share_confirmed=True)
        result=self.service.publish(self.vault,body)
        self.assertEqual(result['state'],'converged',result)
        self.assertEqual(self.git('show',result['published_oid']+':raw/nuova.md',cwd=self.root),'Fonte da condividere')
