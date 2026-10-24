from scripts import run_roadmap_pytests as runner


def test_offline_runner_blocks_ambient_model_aliases_and_startup_warming():
    inherited = {'OLLAMA_URL': 'http://127.0.0.1:11434',
                 'OLLAMA_BASE_URL': 'http://127.0.0.1:11435',
                 'OLLAMA_HOST': 'http://127.0.0.1:11434',
                 'CUDA_VISIBLE_DEVICES': '0', 'VLM_WARMUP_ON_START': '1',
                 'CV_WARMUP_ON_START': '1'}
    actual = runner.pytest_runtime_environment(inherited, offline=True)
    for alias in ('OLLAMA_URL', 'OLLAMA_BASE_URL', 'OLLAMA_HOST'):
        assert actual[alias] == 'http://127.0.0.1:1'
    assert actual['VLM_WARMUP_ON_START'] == actual['CV_WARMUP_ON_START'] == '0'
    assert actual['CUDA_VISIBLE_DEVICES'] == '-1'
    assert inherited['CUDA_VISIBLE_DEVICES'] == '0'


def test_non_offline_runner_preserves_explicit_model_profile():
    inherited = {'OLLAMA_URL': 'http://127.0.0.1:11435', 'VLM_WARMUP_ON_START': '1'}
    actual = runner.pytest_runtime_environment(inherited, offline=False)
    assert actual['OLLAMA_URL'] == inherited['OLLAMA_URL']
    assert actual['VLM_WARMUP_ON_START'] == '1'
    assert actual['APP_ENV'] == 'test'
