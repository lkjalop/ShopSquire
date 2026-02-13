import os
import subprocess
import pytest


def test_ollama_llava_installed():
    exe = r"D:\\Ollama\\ollama.exe"
    if not os.path.exists(exe):
        pytest.skip("Ollama executable not found on expected path; skipping env check")
    proc = subprocess.run([exe, "list"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "llava" in proc.stdout.lower(), "llava model should be installed"
