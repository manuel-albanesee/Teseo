"""Adozione di un vault legacy ed export diagnostico: consenso, nessuna nota toccata, nessun contenuto esportato."""
import _shortpath  # noqa: F401
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import installa
import test_dashboard_queries as queries
import test_dashboard_readonly as readonly
from kit.dashboard import adoption
from kit.dashboard.contracts import ContractError

SCHEMA = ("## Tipi ammessi\n| Tipo | Descrizione |\n| --- | --- |\n| `persona` | Persona |\n"
          "## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n| --- | --- | --- | --- | --- |\n"
          "| `usa` | persona | persona | X usa Y | A → B |\n")


def notes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(root).rglob('*')) if path.is_file() and path.relative_to(root).parts[0] not in ('.teseo', '.graph')}


class Adoption(unittest.TestCase):
    stop = readonly.ReadonlyHTTP.stop
    request = readonly.ReadonlyHTTP.request
    attach = readonly.ReadonlyHTTP.attach
    hashes = readonly.ReadonlyHTTP.hashes

    def setUp(self):
        readonly.ReadonlyHTTP.setUp(self)
        (self.root / 'wiki/Anna.md').unlink()
        (self.root / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')
        (self.root / 'wiki/Anna Rossi.md').write_text('---\ntipo: persona\nusa: "[[Bruno]]"\n---\nSEGRETO-NOTA', encoding='utf-8')
        (self.root / 'wiki/Bruno.md').write_text('---\ntipo: persona\n---\nBruno', encoding='utf-8')
        self.vault_id = self.attach()['vault_id']
        self.base = f'/api/v1/vaults/{self.vault_id}/'

    def post(self, endpoint, body):
        status, _, data = self.request('POST', self.base + endpoint, body)
        return status, json.loads(data)

    def test_preview_lists_what_would_be_created_and_writes_nothing(self):
        before = self.hashes()
        status, plan = self.post('adopt/preview', {})
        self.assertEqual(status, 200, plan)
        self.assertEqual((plan['pages'], plan['graph_buildable'], [f['path'] for f in plan['files']]),
                         (2, True, ['.teseo/project.json', '.teseo/local/']))
        self.assertEqual(self.hashes(), before)

    def test_adoption_creates_only_the_manifest_and_local_state_and_builds_the_graph(self):
        before = notes(self.root)
        plan = self.post('adopt/preview', {})[1]
        status, done = self.post('adopt/apply', {'plan_digest': plan['plan_digest'], 'confirm': True})
        self.assertEqual(status, 200, done)
        self.assertEqual(done['graph']['state'], 'built')
        self.assertEqual(notes(self.root), before)  # note, raw e schema invariati
        self.assertTrue((self.root / '.teseo/project.json').is_file())
        self.assertEqual(done['vault']['compatibility'], 'compatible')
        self.assertNotEqual(done['vault_id'], self.vault_id)
        status, _, data = self.request('GET', f"/api/v1/vaults/{done['vault_id']}/status")
        self.assertEqual((status, json.loads(data)['capabilities']['graph']), (200, True))
        self.assertEqual(self.post('adopt/preview', {})[0], 404)  # il vecchio identificatore non esiste più

    def test_consent_and_a_fresh_preview_are_required(self):
        plan = self.post('adopt/preview', {})[1]
        for body, code in (({'plan_digest': plan['plan_digest'], 'confirm': False}, 'adoption_consent'),
                           ({'plan_digest': '0' * 64, 'confirm': True}, 'preview_stale')):
            with self.subTest(code=code):
                status, data = self.post('adopt/apply', body)
                self.assertGreaterEqual(status, 400)
                self.assertEqual(data['error']['code'], code)
        self.assertFalse((self.root / '.teseo').exists())
        (self.root / 'wiki/Nuova.md').write_text('---\ntipo: persona\n---\nx', encoding='utf-8')
        self.assertEqual(self.post('adopt/apply', {'plan_digest': plan['plan_digest'], 'confirm': True})[1]['error']['code'], 'preview_stale')

    def test_a_vault_with_problems_can_be_adopted_but_the_graph_is_not_built(self):
        (self.root / 'wiki/Rotta.md').write_text('---\ntipo: persona\nusa: "[[Fantasma]]"\n---\nx', encoding='utf-8')
        plan = self.post('adopt/preview', {})[1]
        self.assertFalse(plan['graph_buildable'])
        self.assertEqual([p['code'] for p in plan['problems']], ['unresolved_link'])
        done = self.post('adopt/apply', {'plan_digest': plan['plan_digest'], 'confirm': True})[1]
        self.assertEqual(done['graph']['state'], 'not_built')

    def test_an_unparsable_vault_is_reported_and_an_existing_teseo_folder_is_never_adopted(self):
        (self.root / 'wiki/Storta.md').write_text('---\ntipo: [\n---\nx', encoding='utf-8')
        self.assertIsNotNone(self.post('adopt/preview', {})[1]['parse_error'])
        (self.root / '.teseo').mkdir()
        status, data = self.post('adopt/preview', {})
        self.assertEqual((status, data['error']['code']), (409, 'adoption_conflict'))

    def test_a_compatible_vault_is_not_adopted_twice(self):
        plan = self.post('adopt/preview', {})[1]
        done = self.post('adopt/apply', {'plan_digest': plan['plan_digest'], 'confirm': True})[1]
        status, _, data = self.request('POST', f"/api/v1/vaults/{done['vault_id']}/adopt/preview", {})
        self.assertEqual((status, json.loads(data)['error']['code']), (409, 'already_adopted'))

    def test_the_installer_adopts_with_an_explicit_flag_and_never_touches_notes(self):
        with tempfile.TemporaryDirectory(prefix='teseo adotta ') as temp:
            vault = Path(temp) / 'vault'
            (vault / 'wiki').mkdir(parents=True)
            (vault / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')
            (vault / 'wiki/Anna.md').write_text('---\ntipo: persona\n---\nSEGRETO-NOTA', encoding='utf-8')
            before = notes(vault)
            with self.assertRaises(ValueError):  # senza --adotta resta rifiutato
                installa.installa(vault, skill='no', client='codex', dashboard=True)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(installa.installa(vault, skill='no', client='codex', adotta={'si': True}), 0)
            self.assertIn('Adozione del vault', out.getvalue())
            self.assertTrue((vault / '.teseo/project.json').is_file())
            self.assertEqual({k: v for k, v in notes(vault).items() if k.startswith('wiki/') or k == 'Wiki reference.md'},
                             {k: v for k, v in before.items() if k.startswith('wiki/') or k == 'Wiki reference.md'})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installa.installa(vault, skill='no', client='codex', adotta={'si': True}), 0)  # ripetibile

    def test_the_module_refuses_non_legacy_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ContractError) as caught:
                adoption.preview(temp)
            self.assertEqual(caught.exception.code, 'adoption_unavailable')


class Export(unittest.TestCase):
    stop = queries.Queries.stop
    request = queries.Queries.request
    manifest = queries.Queries.manifest
    hashes = queries.Queries.hashes
    attach = queries.Queries.attach
    get = queries.Queries.get

    def setUp(self):
        queries.Queries.setUp(self)

    def test_the_export_has_versions_shape_and_codes_but_no_content(self):
        status, _, body = self.get('diagnostics-export')
        self.assertEqual(status, 200, body)
        self.assertEqual((body['format'], body['vault']['compatibility']), (1, 'compatible'))
        self.assertIn('python', body['environment'])
        self.assertEqual(body['shape']['pages'], 3)
        self.assertTrue(body['vault']['capabilities']['graph'])
        self.assertIn('journal', body)
        text = json.dumps(body, ensure_ascii=False)
        for secret in (str(self.root), self.root.name, 'Anna Rossi', 'Bruno', 'Équipe', 'opaque', 'nota-utente', 'Wiki reference'):
            self.assertNotIn(secret, text, secret)

    def test_the_export_rejects_parameters_and_works_for_legacy_vaults(self):
        self.assertEqual(self.get('diagnostics-export', {'x': '1'})[0], 400)
        (self.root / '.teseo/project.json').unlink()
        (self.root / '.teseo/local/graph-current.json').unlink()
        legacy = self.attach()
        status, _, data = self.request('GET', f"/api/v1/vaults/{legacy['vault_id']}/diagnostics-export")
        self.assertEqual((status, json.loads(data)['vault']['compatibility']), (200, 'legacy_readonly'))


if __name__ == '__main__':
    unittest.main()
