"""AST function growth ratchet; baseline only records existing large functions."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'config/function_size_baseline.json'


def sizes(root=ROOT):
    result = {}
    for path in (root / 'src/app').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        def visit(node, parents=()):
            for child in ast.iter_child_nodes(node):
                named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                name = parents + (child.name,) if named else parents
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result[path.relative_to(root).as_posix() + ':' + '.'.join(name)] = child.end_lineno-child.lineno+1
                visit(child, name)
        visit(tree)
    return result


def main():
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    failures = []
    for name, count in sizes().items():
        ceiling = baseline.get(name, 200)
        if count > ceiling:
            failures.append(f'{name}: {count} > {ceiling}')
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
