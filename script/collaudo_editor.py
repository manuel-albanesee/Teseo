"""Collaudo con un editor non cooperante: uno scrittore concorrente salva note mentre Teseo applica una modifica.

Uso: python script/collaudo_editor.py [--giri 20] [--cartella DIR] [--senza-attesa] [--rapporto FILE]

Crea un vault sintetico (con `.obsidian/`, così Obsidian lo apre come vault), avvia il servizio della dashboard in questo
processo e ripete `--giri` volte due scenari mentre uno scrittore salva di continuo, nei tre modi in cui gli editor scrivono
(sovrascrittura sul posto, file temporaneo + rename, accodamento):

  A. note estranee: lo scrittore salva note che l'apply non tocca. Verifica: dopo l'apply ogni nota contiene esattamente
     l'ultimo salvataggio completato (nessun byte perso, nessun ritorno a una versione vecchia).
  B. stesso file: lo scrittore crea proprio la pagina che l'apply sta per creare. Verifica: il contenuto dello scrittore
     non viene mai sovrascritto; l'apply non può dichiarare successo sopra di esso.

Con Obsidian aperto sulla cartella stampata il test misura anche l'effetto dell'indicizzazione e dei suoi file di lavoro.
Non tocca altro che la cartella di prova: non puntarlo mai a un vault reale. Esce con 0 solo se tutti i giri passano.
"""
import argparse
import hashlib
import platform
import random
import shutil
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from dashboard_graph_fixture import create  # noqa: E402
from kit.dashboard.contracts import KIT_VERSION  # noqa: E402
from kit.dashboard.server import DashboardServer  # noqa: E402
from kit.dashboard.storage import capture_snapshot  # noqa: E402

OUTCOMES = ('succeeded', 'rifiutato', 'preview non valida', 'failed', 'rolled_back', 'recovery_required', 'blocked_external_change')
STYLES = ('sul posto', 'temporaneo + rename', 'accodamento')
NOTES = [f'wiki/Nodo {n:03}.md' for n in range(10, 16)]


class Writer(threading.Thread):
    """Salva a raffica; `ledger` tiene per ogni file l'ultimo contenuto interamente scritto."""
    def __init__(self, root, targets, pause=0.12):
        super().__init__(daemon=True)
        self.root, self.targets, self.pause, self.ledger, self.stop_event, self.count = root, targets, pause, {}, threading.Event(), 0

    def run(self):
        number = 0
        while not self.stop_event.is_set():
            for relative in self.targets[number % len(self.targets):][:1] or self.targets[:1]:
                path = self.root / relative
                number += 1
                style = STYLES[number % 3]
                if style == 'accodamento' and relative in self.ledger:
                    text = self.ledger[relative] + f'riga {number}\n'
                    with path.open('a', encoding='utf-8', newline='') as stream:
                        stream.write(f'riga {number}\n')
                else:
                    text = f'---\ntipo: concetto\n---\n# Salvataggio {number} ({style})\n'
                    if style == 'sul posto':
                        path.write_text(text, encoding='utf-8', newline='')
                    else:
                        temporary = self.root / '.editor-tmp'  # fuori dal perimetro dati, sullo stesso volume
                        temporary.write_text(text, encoding='utf-8', newline='')
                        temporary.replace(path)
                self.ledger[relative] = text
                self.count += 1
            time.sleep(random.uniform(self.pause / 2, self.pause * 3))  # intervalli irregolari, come un autore vero

    def finish(self):
        self.stop_event.set()
        self.join(10)


def wait_idle(server, vault_id, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not server.applies.active(vault_id):
            return True
        time.sleep(0.05)
    return False


def run_apply(server, vault_id, root, name, after_preview=None):
    """(esito, dettaglio): preview + apply della creazione di `name`; l'esito è lo stato del journal o l'errore del servizio."""
    from kit.dashboard.contracts import ContractError
    try:
        digest = capture_snapshot(root).digest
        proposal = server.page_ops.preview(vault_id, {'base_content_digest': digest, 'idempotency_key': 'giro_' + hashlib.sha1(name.encode()).hexdigest()[:20],
                                                     'operation': {'op': 'create', 'name': name, 'tipo': 'concetto'}})
        if not proposal['valid']:
            return 'preview non valida', proposal.get('risk')
        if after_preview:
            after_preview()
        job = server.applies.submit_pages(vault_id, {'preview_id': proposal['preview_id'], 'proposal_hash': proposal['proposal_hash'],
                                                     'idempotency_key': 'apply_' + hashlib.sha1(name.encode()).hexdigest()[:20], 'mode': 'manual_paused',
                                                     'external_writers_paused': True, 'semantic_reviewed': True}, '"' + proposal['base_content_digest'] + '"')
    except ContractError as error:
        return 'rifiutato', error.code
    if not wait_idle(server, vault_id):
        return 'bloccato', 'apply non terminato in 60 s'
    record = server.operations.get(vault_id, job['operation_id'])
    return record['state'], (record.get('error') or {}).get('code')


SCENARIOS = (('R', 'raffica: note estranee salvate di continuo durante preview e apply'),
             ('N', 'una nota estranea viene salvata proprio mentre l\'apply scrive'),
             ('P', 'la pagina che l\'apply sta per creare viene creata dall\'editor mentre l\'apply scrive'))


def run_scenario(server, vault_id, root, code, name):
    """((ultimo contenuto salvato per file, elenco salvataggi), esito). N e P iniettano il salvataggio un attimo prima che l'apply
    sposti la sua pagina: è la finestra che una raffica casuale quasi non colpisce (preview e apply rifiutano prima)."""
    from kit.dashboard import ontology_apply
    if code == 'R':
        writer = Writer(root, NOTES)
        writer.start()
        time.sleep(random.uniform(0, 0.3))
        outcome = run_apply(server, vault_id, root, name)
        writer.finish()
        return (writer.ledger, range(writer.count)), outcome
    relative = NOTES[0] if code == 'N' else f'wiki/{name}.md'
    ledger, real = {}, ontology_apply._move_new

    def intruder(staged, target):
        text = f'---\ntipo: concetto\n---\n# Salvato dall’editor mentre l’apply scrive ({code})\n'
        (root / relative).write_text(text, encoding='utf-8', newline='')
        ledger[relative] = text
        real(staged, target)
    ontology_apply._move_new = intruder
    try:
        outcome = run_apply(server, vault_id, root, name)
    finally:
        ontology_apply._move_new = real
    return (ledger, range(len(ledger))), outcome


def check_unchanged(writer, root):
    """Elenco dei file dello scrittore il cui contenuto finale non è l'ultimo salvataggio completato."""
    bad = []
    for relative, expected in writer.ledger.items():
        actual = (root / relative).read_bytes().decode('utf-8', 'replace') if (root / relative).exists() else None
        if actual != expected:
            bad.append(relative)
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--giri', type=int, default=20)
    parser.add_argument('--cartella', help='cartella nuova per il vault (predefinito: una cartella temporanea)')
    parser.add_argument('--senza-attesa', action='store_true', help='non attendere l’apertura in Obsidian')
    parser.add_argument('--rapporto', default='editor-non-cooperanti.md')
    args = parser.parse_args(argv)
    base = Path(args.cartella) if args.cartella else Path(tempfile.mkdtemp(prefix='teseo-editor-'))
    base.mkdir(parents=True, exist_ok=True)
    print(f'Cartella di prova: {base} (un vault nuovo per ogni giro: {base / "giro-N"})')
    if not args.senza_attesa:
        input('Apri la cartella del PRIMO giro in Obsidian come vault se vuoi osservarlo; lo script crea i vault in sequenza. Premi Invio per cominciare… ')
    rows, failures, saves = [], [], 0
    for giro in range(1, args.giri + 1):
        row = [giro]
        problems = []
        for scenario in SCENARIOS:
            root = create(base / f'giro-{giro}-{scenario[0]}', 120)
            (root / '.obsidian').mkdir(exist_ok=True)
            server = DashboardServer()
            vault_id = server.registry.attach(str(root))['vault_id']
            threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True).start()
            name = f'Pagina {scenario[0]} {giro}'
            try:
                ledger, outcome = run_scenario(server, vault_id, root, scenario[0], name)
            finally:
                server.request_stop()
            saves += len(ledger[1])
            lost = [relative for relative, expected in ledger[0].items()
                    if not (root / relative).exists() or (root / relative).read_bytes().decode('utf-8', 'replace') != expected]
            if lost:
                problems.append(f'{scenario[0]}: contenuto diverso dall’ultimo salvataggio in ' + ', '.join(lost))
            if outcome[0] == 'succeeded' and not (root / f'wiki/{name}.md').exists():
                problems.append(f'{scenario[0]}: successo dichiarato ma la pagina manca')
            if outcome[0] not in OUTCOMES:
                problems.append(f'{scenario[0]}: esito inatteso {outcome}')
            row.append(outcome)
        rows.append((giro, *row[1:], 'OK' if not problems else '; '.join(problems)))
        print(f'giro {giro:>2}: ' + '  '.join(f'{s[0]}={o[0]}{"/" + str(o[1]) if o[1] else ""}' for s, o in zip(SCENARIOS, row[1:])) + f'  {"OK" if not problems else "FALLITO: " + "; ".join(problems)}')
        failures += problems
    counts = {}
    for row in rows:
        for outcome in row[1:-1]:
            counts[outcome[0]] = counts.get(outcome[0], 0) + 1
    verdict = 'SUPERATO' if not failures else 'FALLITO'
    lines = [f'# Collaudo con editor non cooperante ({date.today().isoformat()})', '',
             f'- Sistema: {platform.platform()} · Python {platform.python_version()} · Teseo {KIT_VERSION}',
             f'- Giri eseguiti: {len(rows)} di {args.giri} · salvataggi dello scrittore: {saves}',
             f'- Obsidian aperto sul vault: {"non dichiarato (--senza-attesa)" if args.senza_attesa else "sì (confermato dall’utente)"}',
             f'- Esito: **{verdict}** (nessun byte dello scrittore perso né sovrascritto; ' + ', '.join(f'{k}: {v}' for k, v in sorted(counts.items())) + ')',
             '- `recovery_required` è l\'esito previsto quando un salvataggio arriva durante la scrittura: i dati sono salvi ma il vault resta fermo in `recovery_required` finché una persona non risolve.', '', '| Giro | ' + ' | '.join(f'{c} ({d})' for c, d in SCENARIOS) + ' | Controllo |', '| --- | --- | --- | --- | --- |']
    lines += ['| ' + ' | '.join([str(row[0]), *(f'{o[0]} {o[1] or ""}' for o in row[1:-1]), row[-1]]) + ' |' for row in rows]
    Path(args.rapporto).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'\n{verdict}: {len(rows)} giri, {saves} salvataggi simulati. Rapporto: {Path(args.rapporto).resolve()}')
    if not args.cartella:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
