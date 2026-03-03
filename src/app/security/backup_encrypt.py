"""C05 — Encrypt / decrypt database backup files at rest (AES-256-GCM).

Usage:
    python -m src.app.security.backup_encrypt encrypt  backup.sql  backup.sql.enc
    python -m src.app.security.backup_encrypt decrypt  backup.sql.enc  backup.sql

Key material is read from env var ``BACKUP_ENCRYPTION_KEY`` (hex-encoded 32-byte key)
or derived from ``BACKUP_ENCRYPTION_PASSPHRASE`` via PBKDF2 with a random salt.

Encrypted format:
    [16-byte salt][12-byte nonce][ciphertext+16-byte GCM tag]
"""
from __future__ import annotations

import hashlib
import os
import sys


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations=600_000)


def _get_key(salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Return (key, salt). Reads from env."""
    hex_key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    if hex_key:
        return bytes.fromhex(hex_key), salt or b"\x00" * 16

    passphrase = os.getenv("BACKUP_ENCRYPTION_PASSPHRASE", "").strip()
    if not passphrase:
        raise RuntimeError("Set BACKUP_ENCRYPTION_KEY (hex) or BACKUP_ENCRYPTION_PASSPHRASE")

    if salt is None:
        salt = os.urandom(16)
    return _derive_key(passphrase, salt), salt


def encrypt_file(src: str, dst: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    key, salt = _get_key(salt)
    nonce = os.urandom(12)
    plaintext = open(src, "rb").read()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)

    with open(dst, "wb") as f:
        f.write(salt)
        f.write(nonce)
        f.write(ciphertext)


def decrypt_file(src: str, dst: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    data = open(src, "rb").read()
    salt = data[:16]
    nonce = data[16:28]
    ciphertext = data[28:]
    key, _ = _get_key(salt)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)

    with open(dst, "wb") as f:
        f.write(plaintext)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python -m src.app.security.backup_encrypt <encrypt|decrypt> <input> <output>")
        sys.exit(1)
    cmd, inp, out = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "encrypt":
        encrypt_file(inp, out)
        print(f"Encrypted {inp} -> {out}")
    elif cmd == "decrypt":
        decrypt_file(inp, out)
        print(f"Decrypted {inp} -> {out}")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
