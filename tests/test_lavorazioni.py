"""Lavorazioni (kit/graph/lavorazioni.py): pipeline ICM che leggono la wiki e producono documenti derivati."""
import _shortpath  # noqa: F401
import hashlib
import io
import json
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import build_graph
import installa
import lavorazioni
import contratti

CONTRATTO = """\
## Input
| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `Wiki reference.md` | tutto | regole |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | pagine selezionate |

## Processo
1. Lavora.

## Verifica
| Controllo | Comando | Esito atteso |
| --- | --- | --- |
| esito | rilettura | ok |

## Output
| Artefatto | Posizione | Formato |
| --- | --- | --- |
| risultato | `{esecuzione}/NN/risultato.md` | Markdown |
"""

CONFIG = """\
---
selezione:
  collegate_a: "[[Rilascio in produzione]]"
  profondita: 1
  relazioni: [usa]
  massimo: 40
parametri:
  destinatari: team operativo
---

# Configurazione

Tono sobrio.
"""

FASI = ('01-raccolta', '02-sintesi', '03-revisione')


def hash_albero(radice):
    return {p.relative_to(radice).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(radice).rglob('*')) if p.is_file() and '.graph' not in p.parts}


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', self.vault / 'wiki')
        shutil.copytree(KIT / 'esempio/raw', self.vault / 'raw')
        for nome in ('Wiki reference.md', 'index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, self.vault / nome)
        (self.vault / '.graph').mkdir()
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(self.vault, self.vault / '.graph/graph.sqlite')

    def crea(self, nome='prova', config=CONFIG, fasi=FASI, contratto=CONTRATTO):
        base = self.vault / 'lavorazioni' / nome
        (base / 'fasi').mkdir(parents=True)
        (base / 'CONTEXT.md').write_text(f'# {nome}\n\nScopo di prova.\n', encoding='utf-8')
        if config is not None:
            (base / 'config.md').write_text(config, encoding='utf-8')
        for fase in fasi:
            (base / 'fasi' / fase).mkdir()
            if contratto is not None:
                (base / 'fasi' / fase / 'CONTEXT.md').write_text(contratto, encoding='utf-8')
        return base

    def codici(self, nome='prova'):
        return [p['codice'] for p in lavorazioni.valida(self.vault, nome)]

    def pagine(self, esecuzione):
        return sorted(json.loads((Path(esecuzione['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))['pagine'])


class Valida(Base):
    def test_lavorazione_completa_e_valida(self):
        self.crea()
        self.assertEqual(lavorazioni.valida(self.vault, 'prova'), [])

    def test_lavorazione_inesistente(self):
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.valida(self.vault, 'non-c-e')
        self.assertEqual(errore.exception.codice, 'lavorazione_inesistente')

    def test_nome_non_valido_non_esce_dalla_cartella(self):
        for nome in ('../fuori', 'A B', '', '.nascosta', 'a/b'):
            with self.subTest(nome=nome), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                lavorazioni.valida(self.vault, nome)
            self.assertEqual(errore.exception.codice, 'nome_non_valido')

    def test_config_mancante(self):
        self.crea(config=None)
        self.assertIn('config_mancante', self.codici())

    def test_config_con_segnaposto(self):
        self.crea(config=CONFIG.replace('team operativo', '{{DESTINATARI}}'))
        self.assertIn('config_segnaposto', self.codici())

    def test_config_senza_frontmatter_valido(self):
        self.crea(config='nessun frontmatter\n')
        self.assertIn('config_non_valida', self.codici())

    def test_chiave_sconosciuta_nella_selezione(self):
        self.crea(config=CONFIG.replace('massimo: 40', 'massimo: 40\n  colore: blu'))
        self.assertIn('config_chiave', self.codici())

    def test_tipo_errato_nella_selezione(self):
        for sostituzione in (('profondita: 1', 'profondita: molta'), ('massimo: 40', 'massimo: 0'),
                             ('relazioni: [usa]', 'relazioni: usa'), ('profondita: 1', 'profondita: -1')):
            with self.subTest(sostituzione=sostituzione):
                self.crea(config=CONFIG.replace(*sostituzione))
                self.assertIn('config_tipo', self.codici())
                shutil.rmtree(self.vault / 'lavorazioni')

    def test_senza_fasi(self):
        self.crea(fasi=())
        self.assertIn('fasi_assenti', self.codici())

    def test_numerazione_delle_fasi_non_contigua(self):
        self.crea(fasi=('01-raccolta', '03-revisione'))
        self.assertIn('fasi_numerazione', self.codici())

    def test_nome_di_fase_non_valido(self):
        self.crea(fasi=('01-raccolta', 'sintesi'))
        self.assertIn('fasi_numerazione', self.codici())

    def test_fase_senza_contratto(self):
        self.crea(contratto=None)
        self.assertIn('fase_senza_contratto', self.codici())

    def test_errore_di_contratto_riporta_la_fase(self):
        base = self.crea()
        (base / 'fasi/02-sintesi/CONTEXT.md').write_text(CONTRATTO.replace('## Verifica', '## Altro'), encoding='utf-8')
        trovati = [p for p in lavorazioni.valida(self.vault, 'prova') if p['codice'] == 'contratto']
        self.assertEqual(len(trovati), 1)
        self.assertIn('02-sintesi', trovati[0]['messaggio'])
        self.assertIn('sezione_mancante', trovati[0]['messaggio'])

    def test_riferimento_in_avanti_tra_fasi(self):
        base = self.crea()
        avanti = CONTRATTO.replace('`{esecuzione}/01-raccolta/raccolta.md`', '`../03-revisione/x.md`')
        (base / 'fasi/02-sintesi/CONTEXT.md').write_text(avanti, encoding='utf-8')
        self.assertTrue(any('riferimento_in_avanti' in p['messaggio'] for p in lavorazioni.valida(self.vault, 'prova')))


class Elenco(Base):
    def test_elenca_le_lavorazioni_e_salta_le_cartelle_di_servizio(self):
        self.crea('alfa')
        self.crea('beta', fasi=FASI[:2])
        (self.vault / 'lavorazioni/_ingest').mkdir()
        trovate = lavorazioni.elenco(self.vault)
        self.assertEqual([(t['nome'], t['fasi'], t['esecuzione']) for t in trovate], [('alfa', 3, None), ('beta', 2, None)])

    def test_senza_cartella_lavorazioni(self):
        self.assertEqual(lavorazioni.elenco(self.vault), [])

    def test_indica_l_ultima_esecuzione(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(lavorazioni.elenco(self.vault)[0]['esecuzione'], '2026-10-30-2')


class Nuova(Base):
    def modelli(self):
        cartella = self.vault / '.graph/modelli'
        modello = cartella / 'base'
        (modello / 'fasi').mkdir(parents=True)
        (modello / 'CONTEXT.md').write_text('# base\n', encoding='utf-8')
        (modello / 'config.md').write_text(CONFIG, encoding='utf-8')
        for fase in FASI:
            (modello / 'fasi' / fase).mkdir()
            (modello / 'fasi' / fase / 'CONTEXT.md').write_text(CONTRATTO, encoding='utf-8')
        (modello / 'esecuzioni/vecchia').mkdir(parents=True)
        (modello / 'esecuzioni/vecchia/x.md').write_text('non va copiata', encoding='utf-8')
        return cartella

    def test_crea_da_un_modello_senza_le_esecuzioni(self):
        destinazione = lavorazioni.nuova(self.vault, 'mia', 'base', modelli=self.modelli())
        self.assertEqual(destinazione, self.vault / 'lavorazioni/mia')
        self.assertTrue((destinazione / 'fasi/02-sintesi/CONTEXT.md').is_file())
        self.assertFalse((destinazione / 'esecuzioni').exists())
        self.assertEqual(self.codici('mia'), [])

    def test_crea_da_una_lavorazione_esistente(self):
        self.crea('origine')
        lavorazioni.avvia(self.vault, 'origine', oggi='2026-10-30')
        destinazione = lavorazioni.nuova(self.vault, 'copia', 'origine', modelli=self.modelli())
        self.assertTrue((destinazione / 'config.md').is_file())
        self.assertFalse((destinazione / 'esecuzioni').exists())

    def test_rifiuta_destinazione_esistente_modello_ignoto_e_nome_non_valido(self):
        modelli = self.modelli()
        lavorazioni.nuova(self.vault, 'mia', 'base', modelli=modelli)
        for nome, da, codice in (('mia', 'base', 'lavorazione_esistente'), ('altra', 'ignoto', 'modello_inesistente'),
                                 ('../x', 'base', 'nome_non_valido'), ('altra', '../base', 'nome_non_valido')):
            with self.subTest(nome=nome, da=da), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                lavorazioni.nuova(self.vault, nome, da, modelli=modelli)
            self.assertEqual(errore.exception.codice, codice)

    def test_non_segue_i_collegamenti_simbolici_del_modello(self):
        modelli = self.modelli()
        fuori = self.vault / 'segreto.txt'
        fuori.write_text('riservato', encoding='utf-8')
        try:
            (modelli / 'base/leak.md').symlink_to(fuori)
        except OSError:
            self.skipTest('collegamenti simbolici non disponibili')
        destinazione = lavorazioni.nuova(self.vault, 'mia', 'base', modelli=modelli)
        self.assertFalse((destinazione / 'leak.md').exists())


class Raccolta(Base):
    def avvia(self, config=CONFIG, **opzioni):
        self.crea(config=config)
        opzioni.setdefault('oggi', '2026-10-30')
        return lavorazioni.avvia(self.vault, 'prova', **opzioni)

    def test_crea_esecuzione_e_raccolta(self):
        esecuzione = self.avvia()
        base = self.vault / 'lavorazioni/prova/esecuzioni/2026-10-30-1'
        self.assertEqual(Path(esecuzione['percorso']), base)
        self.assertTrue((base / 'esecuzione.json').is_file())
        raccolta = (base / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
        self.assertIn('## [[Rilascio in produzione]]', raccolta)
        self.assertIn('## [[Console di rilascio]]', raccolta)

    def test_ogni_esecuzione_ha_il_suo_numero(self):
        self.avvia()
        secondo = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        altro_giorno = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-31')
        self.assertEqual((secondo['id'], altro_giorno['id']), ('2026-10-30-2', '2026-10-31-1'))

    def test_pagina_nella_raccolta_ha_corpo_relazioni_e_impronta_senza_frontmatter(self):
        esecuzione = self.avvia()
        raccolta = (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
        sorgente = (self.vault / 'wiki/Console di rilascio.md').read_text(encoding='utf-8')
        impronta = hashlib.sha256(sorgente.encode('utf-8')).hexdigest()
        self.assertIn(impronta[:12], raccolta)
        self.assertIn('tipo: sistema', raccolta)
        self.assertNotIn('aggiornato: 2026-10-05\n---', raccolta)
        corpo = sorgente.split('\n---', 1)[1].strip().splitlines()[0]
        self.assertIn(corpo, raccolta)
        self.assertIn('usa', raccolta)

    def test_esecuzione_json_registra_impronte_e_parametri(self):
        esecuzione = self.avvia()
        dati = json.loads((Path(esecuzione['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(dati['lavorazione'], 'prova')
        self.assertEqual(dati['id'], '2026-10-30-1')
        self.assertEqual(sorted(dati['pagine']), ['Console di rilascio', 'Rilascio in produzione'])
        self.assertEqual(dati['pagine']['Console di rilascio'],
                         hashlib.sha256((self.vault / 'wiki/Console di rilascio.md').read_bytes()).hexdigest())
        self.assertEqual(dati['parametri'], {'destinatari': 'team operativo'})
        self.assertEqual(dati['config_sha256'], hashlib.sha256((self.vault / 'lavorazioni/prova/config.md').read_bytes()).hexdigest())
        self.assertEqual(sorted(dati['contratti']), list(FASI))
        self.assertFalse(dati['troncata'])

    def test_selezione_per_sottografo_con_profondita_e_relazioni(self):
        cfg = CONFIG.replace('profondita: 1', 'profondita: 2').replace('[usa]', '[usa, richiede, parte_di, referente]')
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Console di rilascio', 'Gestionale', 'Incident settimanale',
                                                       'Rilascio in produzione'])

    def test_profondita_zero_e_solo_la_pagina(self):
        self.assertEqual(self.pagine(self.avvia(CONFIG.replace('profondita: 1', 'profondita: 0'))), ['Rilascio in produzione'])

    def test_i_collegamenti_menziona_non_si_seguono_per_impostazione(self):
        cfg = CONFIG.replace('profondita: 1', 'profondita: 3').replace('  relazioni: [usa]\n', '')
        trovate = self.pagine(self.avvia(cfg))
        self.assertNotIn('call-2026-09-10', trovate)
        self.assertIn('Anna Rossi', trovate)

    def test_filtro_per_tipo(self):
        cfg = CONFIG.replace('profondita: 1', 'profondita: 3').replace('  relazioni: [usa]\n', '  tipi: [processo]\n')
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Incident settimanale', 'Rilascio in produzione'])

    def test_senza_punto_di_partenza_si_prendono_tutte_le_pagine_del_filtro(self):
        cfg = '---\nselezione:\n  tipi: [persona]\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Anna Rossi'])

    def test_filtro_per_data_di_aggiornamento(self):
        cfg = '---\nselezione:\n  modificate_da: 7g\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg, oggi='2026-10-23')), ['Incident settimanale', 'ServiceDesk'])
        self.assertEqual(self.pagine(lavorazioni.avvia(self.vault, 'prova', oggi='2026-11-30')), [])

    def test_massimo_taglia_e_lo_dichiara(self):
        cfg = '---\nselezione:\n  massimo: 3\n---\n'
        esecuzione = self.avvia(cfg)
        dati = json.loads((Path(esecuzione['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(len(dati['pagine']), 3)
        self.assertTrue(dati['troncata'])
        self.assertIn('troncata', (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8'))

    def test_selezione_da_domanda_usa_le_pagine_riconosciute(self):
        cfg = '---\nselezione:\n  domanda: "chi è Anna Rossi?"\n  profondita: 0\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Anna Rossi'])

    def test_selezione_vuota_produce_una_raccolta_vuota_dichiarata(self):
        esecuzione = self.avvia('---\nselezione:\n  tipi: [progetto]\n---\n')
        raccolta = (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
        self.assertIn('Nessuna pagina selezionata', raccolta)

    def test_parametro_sovrascritto_per_una_sola_esecuzione(self):
        self.crea()
        prima = lavorazioni.avvia(self.vault, 'prova', override=['destinatari=direzione', 'selezione.massimo=1'], oggi='2026-10-30')
        dopo = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        dati = json.loads((Path(prima['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(dati['parametri'], {'destinatari': 'direzione'})
        self.assertEqual(dati['override'], ['destinatari=direzione', 'selezione.massimo=1'])
        self.assertEqual(len(dati['pagine']), 1)
        self.assertEqual(len(self.pagine(dopo)), 2)
        self.assertIn('team operativo', (self.vault / 'lavorazioni/prova/config.md').read_text(encoding='utf-8'))

    def test_override_malformato_o_su_chiave_sconosciuta(self):
        self.crea()
        for override in (['senza-uguale'], ['selezione.colore=blu'], ['selezione.massimo=molti'], ['=x']):
            with self.subTest(override=override), self.assertRaises(lavorazioni.LavorazioneError):
                lavorazioni.avvia(self.vault, 'prova', override=override, oggi='2026-10-30')
        self.assertFalse((self.vault / 'lavorazioni/prova/esecuzioni').exists())

    def test_la_selezione_puo_riferirsi_a_un_parametro(self):
        cfg = '---\nselezione:\n  modificate_da: "{periodo}"\nparametri:\n  periodo: 7g\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg, oggi='2026-10-23')), ['Incident settimanale', 'ServiceDesk'])
        self.assertEqual(self.pagine(lavorazioni.avvia(self.vault, 'prova', override=['periodo=30g'], oggi='2026-10-23')),
                         ['Acronimo del progetto', 'Anna Rossi', 'Console di rilascio', 'Gestionale',
                          'Incident settimanale', 'Modulo fatture', 'Rilascio in produzione', 'ServiceDesk'])

    def test_raccolta_deterministica(self):
        self.crea()
        a = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        b = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        def leggi(esecuzione):
            testo = (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
            return testo.replace(esecuzione['id'], 'ID')
        self.assertEqual(leggi(a), leggi(b))

    def test_override_con_doppie_parentesi_quadre_resta_un_testo(self):
        # YAML leggerebbe [[Pagina]] come una lista annidata: gli override non usano YAML.
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', override=['selezione.collegate_a=[[Console di rilascio]]',
                                                              'selezione.profondita=0'], oggi='2026-10-30')
        self.assertEqual(self.pagine(e), ['Console di rilascio'])

    def test_override_di_elenchi_separati_da_virgola(self):
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', override=['selezione.profondita=3', 'selezione.tipi=processo, persona',
                                                              'selezione.relazioni=usa, richiede, parte_di, referente'],
                              oggi='2026-10-30')
        self.assertEqual(self.pagine(e), ['Anna Rossi', 'Incident settimanale', 'Rilascio in produzione'])

    def test_un_parametro_numerico_resta_numerico(self):
        cfg = '---\nselezione:\n  massimo: "{quanti}"\nparametri:\n  quanti: 2\n---\n'
        self.crea(config=cfg)
        e = lavorazioni.avvia(self.vault, 'prova', override=['quanti=3'], oggi='2026-10-30')
        self.assertEqual(len(self.pagine(e)), 3)
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.avvia(self.vault, 'prova', override=['quanti=tre'], oggi='2026-10-30')

    def test_collegate_a_vuoto_chiede_la_pagina(self):
        cfg = '---\nselezione:\n  collegate_a: "{argomento}"\nparametri:\n  argomento: ""\n---\n'
        self.crea(config=cfg)
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(errore.exception.codice, 'pagina_inesistente')
        self.assertIn('argomento', str(errore.exception))
        e = lavorazioni.avvia(self.vault, 'prova', override=['argomento=Anna Rossi'], oggi='2026-10-30')
        self.assertIn('Anna Rossi', self.pagine(e))

    def test_scrive_solo_dentro_l_esecuzione(self):
        self.crea()
        prima = hash_albero(self.vault)
        esecuzione = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        dopo = hash_albero(self.vault)
        nuovi = sorted(set(dopo) - set(prima))
        self.assertEqual(nuovi, ['lavorazioni/prova/esecuzioni/2026-10-30-1/01-raccolta/raccolta.md',
                                 'lavorazioni/prova/esecuzioni/2026-10-30-1/esecuzione.json'])
        self.assertEqual({k: v for k, v in prima.items()}, {k: dopo[k] for k in prima})
        self.assertEqual(esecuzione['id'], '2026-10-30-1')

    def test_rifiuta_una_lavorazione_non_valida(self):
        self.crea(config=None)
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(errore.exception.codice, 'lavorazione_non_valida')
        self.assertFalse((self.vault / 'lavorazioni/prova/esecuzioni').exists())

    def test_senza_grafo_chiede_di_costruirlo(self):
        self.crea()
        (self.vault / '.graph/graph.sqlite').unlink()
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(errore.exception.codice, 'grafo_assente')
        self.assertIn('build_graph.py', str(errore.exception))

    def test_data_non_valida(self):
        self.crea()
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.avvia(self.vault, 'prova', oggi='ieri')


MODELLI = KIT / 'lavorazioni'
NOMI_MODELLI = ['report-periodico', 'scheda-argomento']


class Modelli(Base):
    """I modelli inclusi nel kit: validi, brevi, configurabili e utilizzabili da riga di comando dopo l'installazione."""

    def da_modello(self, modello, nome=None):
        return lavorazioni.nuova(self.vault, nome or modello, modello, modelli=MODELLI)

    def test_ci_sono_i_due_modelli(self):
        self.assertEqual(sorted(p.name for p in MODELLI.iterdir() if p.is_dir()), NOMI_MODELLI)

    def test_ogni_modello_e_valido_appena_creato(self):
        for modello in NOMI_MODELLI:
            with self.subTest(modello=modello):
                self.da_modello(modello)
                self.assertEqual(lavorazioni.valida(self.vault, modello), [])

    def test_contratti_brevi_e_riferimenti_sotto_il_limite(self):
        for modello in NOMI_MODELLI:
            base = self.da_modello(modello)
            self.assertLessEqual(len((base / 'CONTEXT.md').read_text(encoding='utf-8').splitlines()), 80)
            for contratto in sorted((base / 'fasi').glob('*/CONTEXT.md')):
                with self.subTest(modello=modello, fase=contratto.parent.name):
                    esito = contratti.valida(contratto, radice=self.vault)
                    self.assertEqual((esito['errori'], esito['avvisi']), ([], []))
            for riferimento in sorted((base / 'riferimenti').glob('*.md')):
                self.assertLessEqual(len(riferimento.read_text(encoding='utf-8').splitlines()), 200, riferimento.name)

    def test_la_prima_fase_e_la_raccolta_e_le_creative_hanno_un_checkpoint(self):
        attese = {'report-periodico': ['02-sintesi'], 'scheda-argomento': ['02-scaletta', '03-stesura']}
        for modello in NOMI_MODELLI:
            base = self.da_modello(modello)
            fasi = sorted(p.name for p in (base / 'fasi').iterdir())
            self.assertEqual(fasi[0], '01-raccolta')
            for fase in attese[modello]:
                with self.subTest(modello=modello, fase=fase):
                    self.assertIn('\n## Checkpoint\n', (base / 'fasi' / fase / 'CONTEXT.md').read_text(encoding='utf-8'))

    def test_questionario_piatto_numerato_e_con_predefiniti(self):
        for modello in NOMI_MODELLI:
            with self.subTest(modello=modello):
                testo = (MODELLI / modello / 'setup/questionario.md').read_text(encoding='utf-8')
                domande = [r for r in testo.splitlines() if re.match(r'^\d+\. ', r)]
                self.assertGreaterEqual(len(domande), 3)
                self.assertTrue(all('predefinito' in r for r in domande), domande)

    def test_la_scheda_confronta_la_stesura_con_scaletta_e_raccolta(self):
        base = self.da_modello('scheda-argomento')
        verifica = (base / 'fasi/04-verifica/CONTEXT.md').read_text(encoding='utf-8')
        for fase in ('01-raccolta', '02-scaletta', '03-stesura'):
            self.assertIn(fase, verifica)

    def test_report_periodico_sull_esempio(self):
        self.da_modello('report-periodico')
        self.assertEqual(self.pagine(lavorazioni.avvia(self.vault, 'report-periodico', oggi='2026-10-23')),
                         ['Incident settimanale', 'ServiceDesk'])
        self.assertEqual(len(self.pagine(lavorazioni.avvia(self.vault, 'report-periodico', override=['periodo=30g'],
                                                          oggi='2026-10-23'))), 8)

    def test_scheda_argomento_chiede_la_pagina_e_poi_segue_le_relazioni(self):
        self.da_modello('scheda-argomento')
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'scheda-argomento', oggi='2026-10-23')
        self.assertEqual(errore.exception.codice, 'pagina_inesistente')
        trovate = self.pagine(lavorazioni.avvia(self.vault, 'scheda-argomento', override=['argomento=Rilascio in produzione'],
                                                oggi='2026-10-23'))
        self.assertIn('Rilascio in produzione', trovate)
        self.assertIn('Console di rilascio', trovate)

    def test_installazione_distribuisce_i_modelli_e_funziona_da_riga_di_comando(self):
        # Scenario completo senza modello AI: installa, crea da modello, valida, avvia, stato.
        destinazione = Path(tempfile.mkdtemp(prefix='teseo-lav-', dir=self.vault.parent))
        self.addCleanup(shutil.rmtree, destinazione, True)
        with redirect_stdout(io.StringIO()):
            installa.installa(destinazione, skill='no', client='claude', esempio=True)
        for modello in NOMI_MODELLI:
            self.assertTrue((destinazione / '.graph/modelli' / modello / 'config.md').is_file())

        def esegui(*argomenti):
            fatto = subprocess.run([sys.executable, *argomenti], cwd=destinazione, capture_output=True, timeout=120)
            return fatto.returncode, (fatto.stdout + fatto.stderr).decode('utf-8', 'replace')
        self.assertEqual(esegui('.graph/build_graph.py', '--check')[0], 0)
        self.assertIn('creata', esegui('.graph/lavorazioni.py', 'nuova', 'mio', '--da', 'report-periodico')[1])
        self.assertEqual(esegui('.graph/lavorazioni.py', 'valida', 'mio'), (0, 'mio: ok\n'))
        codice, uscita = esegui('.graph/lavorazioni.py', 'avvia', 'mio', '--oggi', '2026-10-23')
        self.assertEqual(codice, 0, uscita)
        self.assertIn('2 pagine', uscita)
        self.assertIn('COMPLETA', esegui('.graph/lavorazioni.py', 'stato', 'mio')[1])
        self.assertEqual(esegui('.graph/lavorazioni.py', 'avvia', 'mio', '--param', 'periodo=ieri')[0], 1)


class Stato(Base):
    def test_senza_esecuzioni_tutte_in_attesa(self):
        self.crea()
        stato = lavorazioni.stato(self.vault, 'prova')
        self.assertIsNone(stato['esecuzione'])
        self.assertEqual([f['stato'] for f in stato['fasi']], ['IN ATTESA'] * 3)

    def test_dopo_l_avvio_la_raccolta_e_completa(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        stato = lavorazioni.stato(self.vault, 'prova')
        self.assertEqual(stato['esecuzione'], '2026-10-30-1')
        self.assertEqual([(f['nome'], f['stato']) for f in stato['fasi']],
                         [('01-raccolta', 'COMPLETA'), ('02-sintesi', 'IN ATTESA'), ('03-revisione', 'IN ATTESA')])
        self.assertEqual(stato['fasi'][0]['file'], ['raccolta.md'])

    def test_una_fase_con_output_e_completa_e_gitkeep_non_conta(self):
        self.crea()
        esecuzione = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        fase = Path(esecuzione['percorso']) / '02-sintesi'
        fase.mkdir()
        (fase / '.gitkeep').write_text('', encoding='utf-8')
        self.assertEqual(lavorazioni.stato(self.vault, 'prova')['fasi'][1]['stato'], 'IN ATTESA')
        (fase / 'sintesi.md').write_text('bozza', encoding='utf-8')
        self.assertEqual(lavorazioni.stato(self.vault, 'prova')['fasi'][1]['stato'], 'COMPLETA')

    def test_stato_di_un_esecuzione_precisa(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(lavorazioni.stato(self.vault, 'prova', '2026-10-30-1')['esecuzione'], '2026-10-30-1')
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.stato(self.vault, 'prova', '2026-01-01-1')
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.stato(self.vault, 'prova', '../..')

    def test_disegno_ascii(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        disegno = lavorazioni.disegna(lavorazioni.stato(self.vault, 'prova'))
        self.assertIn('prova · esecuzione 2026-10-30-1', disegno)
        self.assertIn('[01-raccolta] --> [02-sintesi] --> [03-revisione]', disegno)
        self.assertIn('COMPLETA', disegno)
        self.assertIn('IN ATTESA', disegno)


class Riga(Base):
    def esegui(self, *argomenti):
        uscita, errori = io.StringIO(), io.StringIO()
        with redirect_stdout(uscita), redirect_stderr(errori):
            try:
                codice = lavorazioni.main(['--vault', str(self.vault), *map(str, argomenti)])
            except SystemExit as uscita_:
                codice = uscita_.code
        return codice, uscita.getvalue(), errori.getvalue()

    def test_valida_exit_zero_e_uno(self):
        self.crea()
        self.assertEqual(self.esegui('valida', 'prova')[0], 0)
        (self.vault / 'lavorazioni/prova/config.md').unlink()
        codice, testo, _ = self.esegui('valida', 'prova')
        self.assertEqual(codice, 1)
        self.assertIn('config_mancante', testo)

    def test_avvia_stampa_id_e_percorso(self):
        self.crea()
        codice, testo, _ = self.esegui('avvia', 'prova', '--oggi', '2026-10-30', '--param', 'selezione.massimo=1')
        self.assertEqual(codice, 0)
        self.assertIn('2026-10-30-1', testo)
        self.assertIn('1 pagine', testo)

    def test_errori_su_stderr_con_exit_uno(self):
        codice, testo, errori = self.esegui('avvia', 'non-c-e')
        self.assertEqual((codice, testo), (1, ''))
        self.assertIn('lavorazione_inesistente', errori)

    def test_stato_ascii_e_json(self):
        self.crea()
        self.esegui('avvia', 'prova', '--oggi', '2026-10-30')
        self.assertIn('COMPLETA', self.esegui('stato', 'prova')[1])
        dati = json.loads(self.esegui('stato', 'prova', '--json')[1])
        self.assertEqual(dati['fasi'][0]['stato'], 'COMPLETA')

    def test_elenco_json(self):
        self.crea()
        dati = json.loads(self.esegui('elenco', '--json')[1])
        self.assertEqual(dati[0]['nome'], 'prova')

    def test_senza_comando_e_un_errore_d_uso(self):
        self.assertEqual(self.esegui()[0], 2)


if __name__ == '__main__':
    unittest.main()
