"""The real Docker context must exclude local credentials and private artifacts."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import uuid

import pytest


@pytest.mark.skipif(os.getenv('TEST_DOCKER_BUILD_CONTEXT') != '1',
    reason='Requires the explicitly selected task-owned native Docker profile')
def test_native_context_excludes_private_inputs_and_keeps_runtime_sources(tmp_path):
    root = Path(__file__).resolve().parents[2]
    context = tmp_path / 'context'
    context.mkdir()
    owner = 'shopsquire-context-' + uuid.uuid4().hex
    label = 'io.shopsquire.assessment-owner'
    tag = 'shopsquire-context-audit:' + uuid.uuid4().hex
    container = owner + '-export'
    image_id = None
    created = False

    def docker(*arguments):
        result = subprocess.run(['docker', *arguments], capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, (arguments[0], result.stdout, result.stderr)
        return result.stdout.strip()

    excluded = [
        '.env', '.env.local', 'frontend/.env.local',
        '.venv/lib/owned-private-marker.py', 'venv/lib/owned-private-marker.py',
        '.artifacts/probe/runtime-private.json', '.codex-logs/private.log',
        'frontend/playwright-report/index.html', 'frontend/test-results/trace.zip',
        'node_modules/probe/private.js',
    ]
    included = ['app/main.py', 'config/runtime_dependency_profiles.json',
        'docs/readme.md', '.env.example', 'frontend/.env.example']
    for name in [*excluded, *included]:
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Task-owned synthetic context marker; no real credential.\n', encoding='utf-8')
    (context / '.dockerignore').write_bytes((root / '.dockerignore').read_bytes())
    (context / 'Dockerfile').write_text('FROM scratch\nCOPY . /payload/\n', encoding='utf-8')
    iid = tmp_path / 'image-id'
    try:
        docker('build', '--network', 'none', '--label', label + '=' + owner,
            '--iidfile', str(iid), '--tag', tag, str(context))
        image_id = iid.read_text(encoding='utf-8').strip()
        image = json.loads(docker('image', 'inspect', image_id))[0]
        assert image['Config']['Labels'][label] == owner
        docker('create', '--name', container, '--label', label + '=' + owner, tag, '/unexecuted-audit')
        created = True
        metadata = json.loads(docker('container', 'inspect', container))[0]
        assert metadata['Config']['Labels'][label] == owner and not metadata['State']['Running']
        archive_path = tmp_path / 'context.tar'
        docker('export', '--output', str(archive_path), container)
        with tarfile.open(archive_path) as archive:
            names = {member.name.lstrip('./') for member in archive.getmembers() if member.isfile()}
        missing = [name for name in included if 'payload/' + name not in names]
        leaked = [name for name in excluded if 'payload/' + name in names]
        assert not missing, 'Required runtime/example source was excluded: ' + repr(missing)
        assert not leaked, 'Private context inputs reached the image: ' + repr(leaked)
    finally:
        if created:
            metadata = json.loads(docker('container', 'inspect', container))[0]
            assert metadata['Config']['Labels'][label] == owner and not metadata['State']['Running']
            docker('container', 'rm', container)
        if image_id is not None:
            image = json.loads(docker('image', 'inspect', image_id))[0]
            assert image['Config']['Labels'][label] == owner
            docker('image', 'rm', image_id)
