from __future__ import annotations

import base64
import os
import sys
from typing import Optional


class LocalDPAPIKMS:
    """
    KMS provider using Windows DPAPI (CryptProtectData/CryptUnprotectData).
    This provides OS-bound encryption suitable for local at-rest protection.
    """

    def __init__(self):
        if not sys.platform.startswith("win"):
            raise RuntimeError("DPAPI KMS is only supported on Windows")
        import ctypes  # lazy import
        self._ctypes = ctypes

    def encrypt(self, plaintext: bytes, description: Optional[str] = None) -> str:
        C = self._ctypes
        class DATA_BLOB(C.Structure):
            _fields_ = [("cbData", C.wintypes.DWORD), ("pbData", C.POINTER(C.c_byte))]

        blob_in = DATA_BLOB()
        blob_in.cbData = len(plaintext)
        blob_in.pbData = (C.c_byte * len(plaintext))(*plaintext)
        blob_out = DATA_BLOB()
        p_descr = None
        if description:
            p_descr = C.c_wchar_p(description)
        if not C.windll.crypt32.CryptProtectData(C.byref(blob_in), p_descr, None, None, None, 0, C.byref(blob_out)):
            raise RuntimeError("CryptProtectData failed")
        try:
            out_bytes = C.string_at(blob_out.pbData, blob_out.cbData)
            return "kms:v1:dpapi:" + base64.b64encode(out_bytes).decode("ascii")
        finally:
            C.windll.kernel32.LocalFree(blob_out.pbData)

    def decrypt(self, token: str) -> bytes:
        if not token.startswith("kms:v1:dpapi:"):
            raise ValueError("Unsupported token")
        enc = base64.b64decode(token.split(":", 3)[-1])
        C = self._ctypes
        class DATA_BLOB(C.Structure):
            _fields_ = [("cbData", C.wintypes.DWORD), ("pbData", C.POINTER(C.c_byte))]

        blob_in = DATA_BLOB()
        blob_in.cbData = len(enc)
        blob_in.pbData = (C.c_byte * len(enc))(*enc)
        blob_out = DATA_BLOB()
        p_descr_out = C.c_wchar_p()
        if not C.windll.crypt32.CryptUnprotectData(C.byref(blob_in), C.byref(p_descr_out), None, None, None, 0, C.byref(blob_out)):
            raise RuntimeError("CryptUnprotectData failed")
        try:
            return C.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            C.windll.kernel32.LocalFree(blob_out.pbData)


def default_kms() -> Optional[LocalDPAPIKMS]:
    try:
        if os.getenv("KMS_DPAPI_ENABLED", "1").lower() in ("1", "true", "yes"):
            return LocalDPAPIKMS()
    except Exception:
        return None
    return None


def encrypt_string(value: str) -> str:
    kms = default_kms()
    if not kms:
        return value
    return kms.encrypt(value.encode("utf-8"), description="shopsquire")


def decrypt_string(token: str) -> str:
    kms = default_kms()
    if not kms:
        return token
    return kms.decrypt(token).decode("utf-8", errors="ignore")
