from src.app.services.ollama_artifact_verification import verify_ollama_artifact


def test_exact_ollama_manifest_digest_is_required():
    digest = "a" * 64
    receipt = verify_ollama_artifact(
        base_url="http://127.0.0.1:11434", model="qwen3:14b",
        expected_digest=digest,
        fetch_tags=lambda url, timeout: {
            "models": [{"name": "qwen3:14b", "digest": f"sha256:{digest}"}],
        },
    )
    assert receipt.status == "verified"
    assert receipt.observed_digest == digest
    assert receipt.endpoint_identity == "127.0.0.1"


def test_wrong_or_missing_model_fails_closed():
    receipt = verify_ollama_artifact(
        base_url="http://127.0.0.1:11434", model="qwen3:14b",
        expected_digest="a" * 64,
        fetch_tags=lambda *_args: {
            "models": [{"name": "qwen3:14b", "digest": "b" * 64}],
        },
    )
    assert receipt.status == "mismatch"
    assert receipt.error_code == "ollama_manifest_digest_mismatch"
