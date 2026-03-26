"""IT-DET-05 / IT-PREV-02 — Prompt version registry (hash-lock).

Every system prompt registered here is hash-locked.  On startup, each
prompt's current text is hashed and compared against the persisted value in
``config/ai_governance/prompt_hashes.json``.  A mismatch means the prompt
was changed without going through the approved change process (PR review +
AI governance sign-off + updated hash file).

This prevents an insider from subtly biasing model behaviour — e.g. adding
"always approve refunds from supplier X" to the fraud-scoring prompt — without
triggering a code review alert.

How to update a prompt
----------------------
1. Edit the prompt text.
2. Run ``python -m src.app.security.prompt_registry --update <prompt_id>``
   (or call ``update_hash_file(prompt_id, new_text)`` programmatically).
3. Commit the updated ``config/ai_governance/prompt_hashes.json`` in the
   SAME PR as the prompt change.
4. The PR requires review from CODEOWNERS: config/ai_governance/ → AI
   governance owner + CISO.

Framework alignment
-------------------
  ISO 42001:2023  Cl 8.5  (change management for AI systems)
  NIST AI RMF     GOVERN-1.4  (AI lifecycle governance)
  EU AI Act Art 17  (quality management — prompt as model configuration)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HASH_FILE = Path(os.getenv("PROMPT_HASH_FILE", "config/ai_governance/prompt_hashes.json"))

# In-memory registry: prompt_id → (text, expected_sha256)
_REGISTRY: Dict[str, Tuple[str, str]] = {}


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _hash_text(text: str) -> str:
    """SHA-256 of the UTF-8 encoded prompt text."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_hash_file() -> Dict[str, str]:
    """Return {prompt_id: sha256_hex} from the hash file, or {} if absent."""
    if not HASH_FILE.exists():
        return {}
    try:
        data = json.loads(HASH_FILE.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if isinstance(v, str)}
    except Exception as exc:
        logger.error("prompt_registry load_hash_file error: %s", exc)
        return {}


def _save_hash_file(hashes: Dict[str, str]) -> None:
    """Persist {prompt_id: sha256_hex} to the hash file."""
    HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PromptTamperError(Exception):
    """Raised when a registered prompt's content doesn't match its locked hash."""
    def __init__(self, prompt_id: str, expected: str, actual: str):
        self.prompt_id = prompt_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Prompt '{prompt_id}' hash mismatch — possible tampering. "
            f"Expected {expected[:12]}..., got {actual[:12]}... "
            "If intentional, run: python -m src.app.security.prompt_registry "
            f"--update {prompt_id}"
        )


def register(prompt_id: str, text: str, *, strict: bool = True) -> str:
    """Register a prompt and verify its content hash.

    Parameters
    ----------
    prompt_id:  Unique identifier (e.g. "fraud_scorer_system", "nqe_system").
    text:       The full system prompt text.
    strict:     If True and a persisted hash exists that doesn't match,
                raise PromptTamperError in non-local envs; log a warning in
                local/dev/test.

    Returns
    -------
    The SHA-256 hex of *text* (for logging / verification output).
    """
    actual_hash = _hash_text(text)
    persisted = _load_hash_file()
    expected_hash = persisted.get(prompt_id)

    if expected_hash is None:
        # First registration — persist the hash
        logger.info("prompt_registry new_prompt id=%s hash=%s...", prompt_id, actual_hash[:12])
        persisted[prompt_id] = actual_hash
        _save_hash_file(persisted)
        expected_hash = actual_hash

    if actual_hash != expected_hash:
        env = str(os.getenv("APP_ENV", "local") or "local").lower()
        is_prod = env not in ("local", "dev", "development", "test", "testing")

        # Always emit an insider threat signal
        try:
            from src.app.security.insider_threat_detector import detect_prompt_tampering
            detect_prompt_tampering(
                prompt_id=prompt_id,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
            )
        except Exception:
            pass

        if strict and is_prod:
            raise PromptTamperError(prompt_id, expected_hash, actual_hash)
        else:
            logger.warning(
                "prompt_registry hash_mismatch id=%s expected=%s... actual=%s... "
                "(non-prod: allowing but alerting)",
                prompt_id, expected_hash[:12], actual_hash[:12],
            )

    _REGISTRY[prompt_id] = (text, expected_hash)
    return actual_hash


def verify_all() -> List[dict]:
    """Re-verify all registered prompts against the persisted hash file.

    Returns a list of violation dicts (empty = all good).
    Intended for use in the Celery periodic check and the admin API.
    """
    persisted = _load_hash_file()
    violations = []

    for prompt_id, (text, _) in list(_REGISTRY.items()):
        actual_hash = _hash_text(text)
        expected_hash = persisted.get(prompt_id)

        if expected_hash and actual_hash != expected_hash:
            violations.append({
                "prompt_id": prompt_id,
                "expected_hash": expected_hash[:16] + "...",
                "actual_hash":   actual_hash[:16]   + "...",
            })

    if violations:
        logger.critical(
            "prompt_registry verify_all violations=%d ids=%s",
            len(violations),
            [v["prompt_id"] for v in violations],
        )

    return violations


def update_hash_file(prompt_id: str, new_text: str) -> str:
    """Update the persisted hash for *prompt_id* after an approved change.

    This should be called by the CLI helper below, not inline in application
    code, so that the update goes through the commit → review → deploy cycle.
    """
    new_hash = _hash_text(new_text)
    persisted = _load_hash_file()
    old_hash = persisted.get(prompt_id)
    persisted[prompt_id] = new_hash
    _save_hash_file(persisted)
    logger.info(
        "prompt_registry hash_updated id=%s old=%s new=%s",
        prompt_id,
        (old_hash or "none")[:16],
        new_hash[:16],
    )
    # Also update in-memory registry if the text was previously registered
    if prompt_id in _REGISTRY:
        _REGISTRY[prompt_id] = (new_text, new_hash)
    return new_hash


def list_registered() -> Dict[str, str]:
    """Return {prompt_id: hash_prefix} for admin inspection."""
    return {pid: h[:16] + "..." for pid, (_, h) in _REGISTRY.items()}


# ---------------------------------------------------------------------------
# CLI helper — run as: python -m src.app.security.prompt_registry --update ID
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="ShopSquire prompt hash registry tool")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="List all registered prompt hashes")

    p_update = sub.add_parser("update", help="Update hash for a prompt (reads stdin)")
    p_update.add_argument("prompt_id", help="Prompt ID to update")

    p_verify = sub.add_parser("verify", help="Verify hash file against registry")

    args = parser.parse_args()

    if args.cmd == "list":
        hashes = _load_hash_file()
        for pid, h in sorted(hashes.items()):
            print(f"{pid}: {h}")

    elif args.cmd == "update":
        print(f"Paste/pipe the prompt text for '{args.prompt_id}', then Ctrl+D:")
        text = sys.stdin.read()
        new_hash = update_hash_file(args.prompt_id, text)
        print(f"Updated {args.prompt_id} → {new_hash}")

    elif args.cmd == "verify":
        violations = verify_all()
        if violations:
            print(f"VIOLATIONS ({len(violations)}):")
            for v in violations:
                print(f"  {v}")
            sys.exit(1)
        else:
            print("All registered prompts are intact.")
    else:
        parser.print_help()
