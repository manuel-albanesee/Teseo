"""Fixture sintetica riproducibile per tests/dashboard_ui_smoke.js (ECC browser)."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.dashboard.graph_service import rebuild


def create(destination):
    root = Path(destination).resolve()
    root.mkdir()  # Fail closed: never overwrite an existing directory or vault.
    for directory in ('wiki', 'raw', '.graph', '.teseo'):
        (root / directory).mkdir()
    (root / '.teseo/project.json').write_bytes(
        (ROOT / 'tests/fixtures/dashboard/project-v1.json').read_bytes())
    (root / 'Wiki reference.md').write_text(
        '## Relazioni tipizzate\n| Nome | Da | A | Significato | Esempio |\n'
        '| --- | --- | --- | --- | --- |\n'
        '| `usa` | persona | persona | X usa Y | Anna → Bruno |\n'
        '## Fonti\n| `nota-utente` | Precisazione utente |\n', encoding='utf-8')
    for number in range(56):
        name, target = f'Persona {number:02}', f'Persona {(number + 1) % 56:02}'
        (root / f'wiki/{name}.md').write_text(
            f'---\ntipo: persona\naliases: [{name} alias]\nfonti: [nota-utente]\n'
            f'usa: "[[{target}]]"\n---\n# {name}\n'
            '<script>window.XSS_EXECUTED=true</script>\n'
            '<img src=x onerror="window.XSS_EXECUTED=true">\n'
            '[Esterno](https://example.invalid)\n'
            + 'Testo lungo accessibile con accenti è à. ' * 12, encoding='utf-8')
    rebuild(root)
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='Nuova directory sintetica, deve essere assente')
    print(create(parser.parse_args().destination))
