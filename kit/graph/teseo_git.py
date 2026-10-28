"""Autosync del vault: `pre` all'inizio di una skill (pull), `post` alla fine (commit e push).

Codici di uscita: 0 eseguito, nulla da fare o collaborazione non attiva; 2 bloccato, serve
un'azione umana (messaggio su stderr, dettagli JSON su stdout); 3 rete o autenticazione assenti,
lavoro conservato. Nei vault non collaborativi non fa nulla ed esce con 0.
"""
import argparse
import json
import os
from pathlib import Path
import sys

try:
    from dashboard.autosync import AGENTS, SKILLS, Autosync
    from dashboard.contracts import ContractError
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from kit.dashboard.autosync import AGENTS, SKILLS, Autosync
    from kit.dashboard.contracts import ContractError


def _agent(value):
    if value:
        return value
    return 'claude' if os.environ.get('CLAUDECODE') == '1' else None


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('comando', choices=('pre', 'post', 'riprendi', 'stato'))
    parser.add_argument('--vault', default=str(Path(__file__).resolve().parents[1]),
                        help='cartella del vault (predefinito: quella che contiene .graph)')
    parser.add_argument('--skill', choices=SKILLS)
    parser.add_argument('--agente', choices=AGENTS)
    args = parser.parse_args(argv)
    if args.comando in ('pre', 'post'):
        agent = _agent(args.agente)
        if not args.skill or not agent:
            parser.error('pre e post richiedono --skill e --agente (claude, codex, copilot o umano)')
    try:
        autosync = Autosync(args.vault)
        if args.comando == 'pre':
            result = autosync.pre(args.skill, agent)
        elif args.comando == 'post':
            result = autosync.post(args.skill, agent)
        elif args.comando == 'riprendi':
            result = autosync.resume()
        else:
            result = autosync.status()
    except (ContractError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['exit']:
        print(result['message'], file=sys.stderr)
    return result['exit']


if __name__ == '__main__':
    raise SystemExit(main())
