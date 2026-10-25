"""Validate repository-owned JSON configuration before deployment or import."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    paths = sorted([*(root / 'config').rglob('*.json'),
                    *(root / 'docs/observability').rglob('*.json')])
    failures = []
    for path in paths:
        try:
            json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError) as exc:
            failures.append(f'{path.relative_to(root).as_posix()}: {exc}')
    for failure in failures:
        print(failure)
    print(f'JSON configuration: {len(paths)} files, {len(failures)} failures')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
