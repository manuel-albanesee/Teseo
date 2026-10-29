"""Relazione `causa`, attributi d'arco in `relazioni_dettaglio` e catena causale in consultazione."""
import _shortpath  # noqa: F401
from urllib.parse import quote
import unittest
from unittest import mock

import test_dashboard_queries as queries
from kit.dashboard.graph_service import rebuild
from kit.graph import build_graph

SCHEMA = ("## Tipi ammessi\n| Tipo | Descrizione |\n| --- | --- |\n| `episodio` | Fatto |\n"
          "## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n| --- | --- | --- | --- | --- |\n"
          "| `causa` | qualsiasi | qualsiasi | X causa Y | A → B |\n## Fonti\n| `nota-utente` | Precisazione |\n")


def page(causa=(), extra='', tipo='episodio'):
    links = ', '.join('"[[%s]]"' % name for name in causa)
    return '---\ntipo: %s\n%s%s---\ntesto\n' % (tipo, 'causa: [%s]\n' % links if causa else '', extra)


def documents(**pages):
    return {'Wiki reference.md': SCHEMA, **{'wiki/%s.md' % name: text for name, text in pages.items()}}


class Parser(unittest.TestCase):
    def test_causal_edges_and_their_attributes_are_parsed(self):
        detail = 'relazioni_dettaglio:\n  "[[B]]": {confidenza: alta, evidenza: "lo dice la fonte"}\n'
        parsed = build_graph.parse_documents(documents(A=page(['B'], detail), B=page(), C=page()))
        self.assertEqual(parsed['problemi'], ())
        self.assertIn(('A', 'B', 'causa'), parsed['relazioni'])
        self.assertEqual(parsed['attributi'], [('A', 'B', 'causa', 'alta', 'lo dice la fonte')])

    def test_invalid_details_are_reported_with_a_stable_code(self):
        cases = {
            'target not declared as causa': 'relazioni_dettaglio:\n  "[[C]]": {confidenza: alta}\n',
            'unknown confidence': 'relazioni_dettaglio:\n  "[[B]]": {confidenza: certa}\n',
            'unknown key': 'relazioni_dettaglio:\n  "[[B]]": {peso: 3}\n',
            'empty evidence': 'relazioni_dettaglio:\n  "[[B]]": {evidenza: " "}\n',
            'long evidence': 'relazioni_dettaglio:\n  "[[B]]": {evidenza: "%s"}\n' % ('x' * 501),
            'not a map': 'relazioni_dettaglio: [1]\n',
            'key without link': 'relazioni_dettaglio:\n  B: {confidenza: alta}\n',
        }
        for name, extra in cases.items():
            with self.subTest(name):
                parsed = build_graph.parse_documents(documents(A=page(['B'], extra), B=page(), C=page()))
                self.assertEqual({item['code'] for item in parsed['problem_details']}, {'relation_detail_invalid'}, parsed['problemi'])

    def test_two_details_for_the_same_target_are_a_problem_not_a_crash(self):
        extra = 'relazioni_dettaglio:\n  "[[B]]": {confidenza: alta}\n  "[[B|bi]]": {evidenza: "x"}\n'
        parsed = build_graph.parse_documents(documents(A=page(['B'], extra), B=page()))
        self.assertEqual({item['code'] for item in parsed['problem_details']}, {'relation_detail_invalid'})
        self.assertEqual(parsed['attributi'], [('A', 'B', 'causa', 'alta', None)])

    def test_unresolved_detail_target_is_an_unresolved_link(self):
        extra = 'relazioni_dettaglio:\n  "[[Fantasma]]": {confidenza: alta}\n'
        parsed = build_graph.parse_documents(documents(A=page(['B'], extra), B=page()))
        self.assertIn('unresolved_link', {item['code'] for item in parsed['problem_details']})


class CausalAPI(unittest.TestCase):
    stop = queries.Queries.stop
    request = queries.Queries.request
    manifest = queries.Queries.manifest
    hashes = queries.Queries.hashes
    attach = queries.Queries.attach
    get = queries.Queries.get

    def setUp(self):
        queries.Queries.setUp(self)
        for path in (self.root / 'wiki').glob('*.md'):
            path.unlink()
        (self.root / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')
        detail = 'relazioni_dettaglio:\n  "[[B]]": {confidenza: media, evidenza: "dalla call"}\n'
        for name, text in dict(A=page(['B'], detail), B=page(['C']), C=page(['A']), D=page(), E=page(['D'])).items():
            (self.root / 'wiki' / (name + '.md')).write_text(text, encoding='utf-8')
        rebuild(self.root)

    def causal(self, **parameters):
        return self.get('causal', parameters)

    def test_effects_follow_the_oriented_chain_up_to_the_depth_and_flag_cycles(self):
        status, _, body = self.causal(node='A', depth='2')
        self.assertEqual(status, 200, body)
        self.assertEqual([(e['source_id'], e['target_id'], e['level']) for e in body['edges']], [('A', 'B', 1), ('B', 'C', 2)])
        self.assertEqual([n['id'] for n in body['nodes']], ['A', 'B', 'C'])
        self.assertFalse(body['cycle'])
        self.assertEqual((body['edges'][0]['confidenza'], body['edges'][0]['evidenza']), ('media', 'dalla call'))
        self.assertTrue(self.causal(node='A', depth='3')[2]['cycle'])

    def test_the_edge_cap_stops_the_whole_traversal(self):
        with mock.patch('kit.dashboard.read_api.MAX_CAUSAL_EDGES', 2):
            body = self.causal(node='A', depth='10')[2]
        self.assertEqual((len(body['edges']), body['truncated']), (2, True))

    def test_causes_walk_backwards_and_isolated_chains_stay_apart(self):
        body = self.causal(node='D', direction='causes')[2]
        self.assertEqual([(e['source_id'], e['target_id']) for e in body['edges']], [('E', 'D')])
        self.assertNotIn('A', {n['id'] for n in body['nodes']})

    def test_invalid_requests_are_rejected(self):
        for parameters, code in (({}, 'invalid_query'), ({'node': 'A', 'depth': '0'}, 'invalid_query'),
                                 ({'node': 'A', 'depth': '11'}, 'invalid_query'), ({'node': 'A', 'direction': 'x'}, 'invalid_query'),
                                 ({'node': 'Zeta'}, 'node_missing')):
            with self.subTest(parameters=parameters):
                status, _, body = self.causal(**parameters)
                self.assertEqual((status >= 400, body['error']['code']), (True, code))

    def test_node_exposes_the_attributes_of_its_arcs(self):
        status, _, body = self.get('nodes/' + quote('B', safe=''))
        self.assertEqual(status, 200, body)
        self.assertEqual(body['relation_attributes'][0]['confidenza'], 'media')


if __name__ == '__main__':
    unittest.main()


class NeighborsAPI(CausalAPI):
    """Stessa fixture: il vicinato a un passo include archi in entrata e in uscita."""
    def test_neighbors_include_both_directions_and_types(self):
        status, _, body = self.get('neighbors', {'node': 'B'})
        self.assertEqual(status, 200, body)
        self.assertEqual({(e['source_id'], e['target_id']) for e in body['edges']}, {('A', 'B'), ('B', 'C')})
        self.assertEqual({n['id'] for n in body['nodes']}, {'A', 'B', 'C'})
        self.assertTrue(all(n['tipo'] == 'episodio' for n in body['nodes']))
        self.assertFalse(body['truncated'])

    def test_neighbors_are_limited_and_validated(self):
        self.assertTrue(self.get('neighbors', {'node': 'B', 'limit': '1'})[2]['truncated'])
        for parameters in ({}, {'node': 'B', 'limit': '0'}, {'node': 'B', 'limit': '201'}, {'node': 'Zeta'}):
            with self.subTest(parameters=parameters):
                self.assertGreaterEqual(self.get('neighbors', parameters)[0], 400)
