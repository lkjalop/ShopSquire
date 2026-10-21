"""An automatic Windows checkout must preserve the exact sealed corpus bytes."""
import hashlib
import io
from pathlib import Path
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
STEMS = ('open_world_unseen_certification_v1', 'open_world_live_certification_inputs_v1')


@pytest.mark.parametrize('export', ['checkout', 'archive'])
def test_sealed_certification_bytes_survive_automatic_crlf_checkout(tmp_path, export):
    repository = tmp_path / 'owned-git'
    repository.mkdir()

    def git(*args):
        return subprocess.check_output(['git', '-C', str(repository), *args], stderr=subprocess.STDOUT)

    git('init', '-q')
    git('config', 'core.autocrlf', 'true')
    git('config', 'core.longpaths', 'true')
    (repository / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
    expected = {}
    names = ['.gitattributes']
    for stem in STEMS:
        name = 'tests/golden/' + stem + '.json'
        seal = (ROOT / ('tests/golden/' + stem + '.sha256')).read_text().strip()
        # Prepare the already-sealed index form; the exported bytes below are
        # compared raw. No corpus content or seal is rewritten by this test.
        index_bytes = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
        assert hashlib.sha256(index_bytes).hexdigest() == seal
        file = repository / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(index_bytes)
        expected[name] = seal
        names.append(name)
    git('add', '--', *names)
    if export == 'checkout':
        destination = tmp_path / 'owned-checkout'
        destination.mkdir()
        git('checkout-index', '--all', '--force', '--prefix=' + destination.as_posix() + '/')
        exported = {name: (destination / name).read_bytes() for name in expected}
    else:
        tree = git('write-tree').decode().strip()
        with zipfile.ZipFile(io.BytesIO(git('archive', '--format=zip', tree))) as archive:
            exported = {name: archive.read(name) for name in expected}
    assert {name: hashlib.sha256(raw).hexdigest() for name, raw in exported.items()} == expected
