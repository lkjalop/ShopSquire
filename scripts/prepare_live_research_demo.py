"""Clone a disposable model fixture for consented live, read-only search checks."""
import argparse
import json
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source, target = args.source.resolve(), args.directory.resolve()
    if not all(path.is_relative_to(root / '.artifacts') for path in (source, target)):
        parser.error('Disposable artifact directories only')
    config = json.loads((source / 'runtime-private.json').read_text(encoding='utf-8'))
    target.mkdir(parents=True, exist_ok=False)
    database = target / 'shop.sqlite3'
    with sqlite3.connect(source / 'shop.sqlite3') as src, sqlite3.connect(database) as dst:
        src.backup(dst)
    config.update(DATABASE_URL='sqlite:///' + database.as_posix(), DATABASE_URL_RO='sqlite:///' + database.as_posix(),
        EXTERNAL_RESEARCH_ENABLED='1', EXTERNAL_RESEARCH_SEARCH_URL='http://127.0.0.1:8888/search?q={query}&format=json',
        EXTERNAL_RESEARCH_ALLOW_PRIVATE='1', EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED='1',
        EXTERNAL_RESEARCH_TENANT_ALLOWLIST='synthetic-electronics', RESEARCH_POLICY_PROFILE='buyer-consent-v1',
        SEMANTIC_RESEARCH_FIXTURES_ENABLED='0', SEMANTIC_SIMULATION_AUTHORITY_ENABLED='0',
        SEMANTIC_RESEARCH_FIXTURE_ID='', SEMANTIC_RESEARCH_FIXTURE_PATH='')
    from scripts.roadmap_runtime import simulation_controls
    config.update(simulation_controls())
    (target / 'runtime-private.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(target), 'live_research': True, 'commerce_effects': 'simulated'}))


if __name__ == '__main__':
    main()
